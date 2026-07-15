"""calendar.pdfから天白キャンパス用CSVを生成する。

利用例:
    uv run python scripts/extract_calendar.py
    uv run python scripts/extract_calendar.py --pdf calendar.pdf --output data/calendar_tenpaku.csv
"""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from spj_nano.calendar import extract_tenpaku_calendar


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pdf", type=Path, default=root / "calendar.pdf")
    parser.add_argument("--output", type=Path, default=root / "data" / "calendar_tenpaku.csv")
    parser.add_argument("--start-year", type=int, default=None)
    args = parser.parse_args()

    calendar = extract_tenpaku_calendar(args.pdf, start_year=args.start_year)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    calendar.to_csv(args.output, index=False, encoding="utf-8-sig")
    print(f"抽出ページ: 天白キャンパス全学部")
    print(f"抽出日数: {len(calendar)}")
    print(f"期間: {calendar['date'].min()} 〜 {calendar['date'].max()}")
    print(f"マーカー付き日数: {int(calendar['has_schedule_marker'].sum())}")
    print(f"保存先: {args.output}")


if __name__ == "__main__":
    main()
