"""CO2時系列と大学カレンダーからLightGBM特徴量を作る。"""

from __future__ import annotations

from pathlib import Path
import re

import numpy as np
import pandas as pd

from spj_nano import forecast as fc
from spj_nano import preprocess as pp


DEFAULT_LAGS_MINUTES = (5, 10, 15, 30, 60, 120, 180)
DEFAULT_ROLLING_MINUTES = (15, 30, 60, 180)


def load_clean_co2(conn) -> tuple[pd.DataFrame, pd.Series]:
    """DBから全センサーのCO2を読み込み、既存の前処理を適用する。"""
    wide = pp.load_wide(conn)
    cleaned = pd.DataFrame(index=wide.index)
    for column in wide.columns:
        series, _ = pp.preprocess_series(wide[column])
        cleaned[column] = series
    if pp.B1F_LABEL not in cleaned:
        raise KeyError(f"対象センサー {pp.B1F_LABEL!r} がありません")
    return cleaned, cleaned[pp.B1F_LABEL].rename("target_co2")


def _safe_name(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9_]+", "_", name).strip("_").lower()


def _add_time_features(frame: pd.DataFrame) -> None:
    index = frame.index
    minute_of_day = index.hour * 60 + index.minute
    frame["hour"] = index.hour
    frame["minute"] = index.minute
    frame["dayofweek"] = index.dayofweek
    frame["month"] = index.month
    frame["dayofyear"] = index.dayofyear
    frame["is_weekend"] = (index.dayofweek >= 5).astype(int)
    frame["time_sin"] = np.sin(2 * np.pi * minute_of_day / 1440.0)
    frame["time_cos"] = np.cos(2 * np.pi * minute_of_day / 1440.0)
    frame["dow_sin"] = np.sin(2 * np.pi * index.dayofweek / 7.0)
    frame["dow_cos"] = np.cos(2 * np.pi * index.dayofweek / 7.0)


def _add_calendar_features(frame: pd.DataFrame, calendar: pd.DataFrame | None) -> None:
    if calendar is None or calendar.empty:
        frame["cal_source_present"] = 0
        frame["cal_has_schedule_marker"] = 0
        frame["cal_is_class_or_event_day"] = 0
        frame["cal_marker_count"] = 0
        return
    cal = calendar.copy()
    cal["date"] = pd.to_datetime(cal["date"]).dt.date
    cal = cal.set_index("date")
    dates = pd.Series(frame.index.date, index=frame.index)
    for source, target in (
        ("source_present", "cal_source_present"),
        ("has_schedule_marker", "cal_has_schedule_marker"),
        ("is_class_or_event_day", "cal_is_class_or_event_day"),
        ("marker_count", "cal_marker_count"),
    ):
        values = dates.map(cal[source]).fillna(0)
        frame[target] = values.astype(float).to_numpy()


def build_feature_frame(
    co2_wide: pd.DataFrame,
    target: str = pp.B1F_LABEL,
    baseline: fc.BaselineProfile | None = None,
    calendar: pd.DataFrame | None = None,
    lags_minutes: tuple[int, ...] = DEFAULT_LAGS_MINUTES,
    rolling_minutes: tuple[int, ...] = DEFAULT_ROLLING_MINUTES,
) -> pd.DataFrame:
    """予測時点tだけを使った特徴量を作る。未来値は参照しない。"""
    if target not in co2_wide:
        raise KeyError(f"対象センサー {target!r} がありません")
    frame = pd.DataFrame(index=co2_wide.index)
    target_series = co2_wide[target].astype(float)

    for sensor in co2_wide.columns:
        safe = _safe_name(sensor)
        series = co2_wide[sensor].astype(float)
        frame[f"{safe}_current"] = series.shift(1)
        for minutes in lags_minutes:
            steps = max(1, minutes // 5)
            frame[f"{safe}_lag_{minutes}m"] = series.shift(steps)

    past = target_series.shift(1)
    for minutes in rolling_minutes:
        window = max(2, minutes // 5)
        rolled = past.rolling(window=window, min_periods=max(2, window // 2))
        frame[f"target_mean_{minutes}m"] = rolled.mean()
        frame[f"target_std_{minutes}m"] = rolled.std()
        frame[f"target_min_{minutes}m"] = rolled.min()
        frame[f"target_max_{minutes}m"] = rolled.max()

    frame["target_delta_15m"] = target_series.shift(1) - target_series.shift(4)
    frame["target_delta_60m"] = target_series.shift(1) - target_series.shift(12)
    if baseline is not None:
        frame["baseline_co2"] = baseline.apply(target_series)
        frame["residual_co2"] = target_series.shift(1) - frame["baseline_co2"].shift(1)
    else:
        frame["baseline_co2"] = np.nan
        frame["residual_co2"] = np.nan

    _add_time_features(frame)
    _add_calendar_features(frame, calendar)
    return frame.replace([np.inf, -np.inf], np.nan)


def make_supervised(
    features: pd.DataFrame,
    target: pd.Series,
    horizon_minutes: int,
) -> tuple[pd.DataFrame, pd.Series]:
    if horizon_minutes <= 0 or horizon_minutes % 5 != 0:
        raise ValueError("horizon_minutesは5分の倍数で指定してください")
    steps = horizon_minutes // 5
    y = target.reindex(features.index).shift(-steps).rename("target")
    data = features.join(y).dropna()
    return data.drop(columns=["target"]), data["target"]


def load_calendar_csv(path: str | Path) -> pd.DataFrame:
    path = Path(path)
    return pd.read_csv(path, encoding="utf-8-sig")
