"""名城大学カレンダーPDFから天白キャンパスの予定を抽出する。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
import re
import unicodedata

import pandas as pd


DAY_RE = re.compile(r"^\d{1,2}$")


@dataclass(frozen=True)
class _Word:
    text: str
    x0: float
    top: float


def _normalise_number(text: str) -> int | None:
    value = unicodedata.normalize("NFKC", text).strip()
    if not DAY_RE.fullmatch(value):
        return None
    day = int(value)
    return day if 1 <= day <= 31 else None


def _find_target_page(pdf_path: Path) -> int:
    import pdfplumber

    with pdfplumber.open(pdf_path) as pdf:
        for number, page in enumerate(pdf.pages):
            text = page.extract_text() or ""
            if "天白キャンパス全学部" in text:
                return number
    raise ValueError("PDF内に『天白キャンパス全学部』のページが見つかりません")


def _cluster_rows(words: list[_Word]) -> list[list[_Word]]:
    rows: list[list[_Word]] = []
    for word in sorted(words, key=lambda item: item.top):
        if not rows or word.top - sum(w.top for w in rows[-1]) / len(rows[-1]) > 2.0:
            rows.append([word])
        else:
            rows[-1].append(word)
    return rows


def _column_index(x0: float, side: str) -> int | None:
    # The PDF has a narrow Sunday/Monday pair followed by five regular cells.
    if side == "left":
        boundaries = (68.0, 85.0, 105.0, 131.0, 157.0, 184.0, 211.0, 241.0)
    else:
        boundaries = (405.0, 418.0, 438.0, 464.0, 490.0, 517.0, 544.0, 580.0)
    for index in range(7):
        if boundaries[index] <= x0 < boundaries[index + 1]:
            return index
    return None


def _day_column_index(x0: float, side: str) -> int | None:
    # Narrow ranges avoid interpreting the date numbers in the right-hand
    # event-note area as calendar cells.
    if side == "left":
        ranges = ((74, 85), (88, 99), (114, 123), (140, 150), (167, 176), (194, 202), (220, 229))
    else:
        ranges = ((409, 418), (422, 432), (449, 458), (475, 485), (502, 511), (529, 538), (555, 565))
    for index, (lower, upper) in enumerate(ranges):
        if lower <= x0 <= upper:
            return index
    return None


def _extract_side(page, side: str) -> list[dict]:
    words = [
        _Word(str(word["text"]), float(word["x0"]), float(word["top"]))
        for word in page.extract_words(use_text_flow=False, keep_blank_chars=False)
    ]
    if side == "left":
        x_min, x_max = 68.0, 241.0
    else:
        x_min, x_max = 405.0, 580.0

    day_words = [
        word
        for word in words
        if x_min <= word.x0 < x_max and 95.0 <= word.top <= 480.0
        and _normalise_number(word.text) is not None
    ]
    rows = _cluster_rows(day_words)
    cells: list[dict] = []
    for row in rows:
        row_top = sum(word.top for word in row) / len(row)
        row_words = [word for word in words if abs(word.top - row_top) <= 2.0]
        by_column: dict[int, _Word] = {}
        for word in row:
            column = _day_column_index(word.x0, side)
            if column is not None:
                by_column[column] = word
        for column, word in sorted(by_column.items()):
            day = _normalise_number(word.text)
            if day is None:
                continue
            markers = []
            for candidate in row_words:
                if _column_index(candidate.x0, side) == column and _normalise_number(candidate.text) is None:
                    markers.append(candidate.text)
            cells.append(
                {
                    "row_top": row_top,
                    "column": column,
                    "day": day,
                    "marker_text": " ".join(markers),
                    "has_schedule_marker": bool(markers),
                }
            )
    return cells


def _assign_dates(cells: list[dict], year: int, month: int) -> pd.DataFrame:
    if not cells:
        return pd.DataFrame()
    rows: dict[float, list[dict]] = {}
    for cell in cells:
        rows.setdefault(cell["row_top"], []).append(cell)

    previous: date | None = None
    output: list[dict] = []
    for row_top in sorted(rows):
        for cell in sorted(rows[row_top], key=lambda value: value["column"]):
            expected_weekday = (cell["column"] + 6) % 7
            if previous is None:
                current = date(year, month, cell["day"])
            else:
                current = previous + timedelta(days=1)
                for _ in range(45):
                    if current.day == cell["day"] and current.weekday() == expected_weekday:
                        break
                    current += timedelta(days=1)
                else:
                    raise ValueError(
                        f"カレンダー日付の連続性を確認できません: {cell!r}"
                    )
            previous = current
            output.append(
                {
                    "date": current.isoformat(),
                    "weekday": current.weekday(),
                    "has_schedule_marker": bool(cell["has_schedule_marker"]),
                    "marker_count": len(cell["marker_text"].split()),
                    "calendar_page": 1,
                    "source_present": 1,
                }
            )
    return pd.DataFrame(output)


def extract_tenpaku_calendar(
    pdf_path: str | Path,
    start_year: int | None = None,
    start_month: int = 3,
) -> pd.DataFrame:
    """天白キャンパス用ページから日付単位の予定を抽出する。

    PDFのレイアウトは、左列が3月から、右列がその6か月後から始まる
    形式を前提とする。授業回数の丸数字や「遠」「補」「試」などはPDF
    フォントの都合で文字化けする場合があるため、CSVでは原文に加えて
    ``has_schedule_marker``を保存する。
    """
    import pdfplumber

    pdf_path = Path(pdf_path)
    page_number = _find_target_page(pdf_path)
    with pdfplumber.open(pdf_path) as pdf:
        page = pdf.pages[page_number]
        text = page.extract_text() or ""
        if start_year is None:
            match = re.search(r"(20\d{2})", text)
            if not match:
                raise ValueError("PDFから年度を読み取れません")
            start_year = int(match.group(1))
        left = _assign_dates(_extract_side(page, "left"), start_year, start_month)
        right_month = (start_month + 5) % 12 + 1
        right_year = start_year if right_month > start_month else start_year + 1
        right = _assign_dates(_extract_side(page, "right"), right_year, right_month)

    result = pd.concat([left, right], ignore_index=True)
    if result.empty:
        raise ValueError("カレンダーの日付セルを抽出できません")
    result = (
        result.sort_values("date")
        .groupby("date", as_index=False)
        .agg(
            weekday=("weekday", "first"),
            has_schedule_marker=("has_schedule_marker", "max"),
            marker_count=("marker_count", "max"),
            calendar_page=("calendar_page", "first"),
            source_present=("source_present", "max"),
        )
    )
    result["date"] = pd.to_datetime(result["date"]).dt.strftime("%Y-%m-%d")
    result["is_weekend"] = pd.to_datetime(result["date"]).dt.dayofweek >= 5
    result["is_class_or_event_day"] = result["has_schedule_marker"].astype(bool)
    result["marker_text"] = result["has_schedule_marker"].map(
        {True: "予定マーカーあり", False: ""}
    )
    return result[
        [
            "date",
            "weekday",
            "is_weekend",
            "has_schedule_marker",
            "is_class_or_event_day",
            "marker_text",
            "marker_count",
            "calendar_page",
            "source_present",
        ]
    ]
