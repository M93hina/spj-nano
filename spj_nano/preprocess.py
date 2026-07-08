"""B1F混雑度システム用 前処理モジュール

事前分析(docs/B1F事前分析レポート.md)で判明したデータ品質の問題に対処する層。
以降のすべての処理は本モジュールの前処理済みデータを使う前提とする。

主な機能:
- スパイク除去: 急激なジャンプと復帰パターンからセンサーノイズを検出し線形補間
- 無人時ベースライン推定: 早朝/休日データから日次ベースラインをローリング推定
- センサーオフセット補正: 深夜中央値ベースで他階センサーを基準センサーに正規化
"""

from __future__ import annotations

import sqlite3

import numpy as np
import pandas as pd

from spj_nano import db

B1F_SENSOR_NAME = "Ｒ３ーB１Ｆ_ＥＨ"
B1F_LABEL = "B1F EH"

SPIKE_JUMP_PPM = 300.0
SPIKE_MAX_WIDTH = 4
DEEP_NIGHT_OFFSET = 30.0
RESAMPLE_FREQ = "5min"

WEEKDAY_BASELINE_HOURS = (6, 9)
WEEKEND_BASELINE_HOURS = (6, 10)
DEEP_NIGHT_HOURS = (1, 5)


def load_wide(conn: sqlite3.Connection) -> pd.DataFrame:
    """全センサーのCO2時系列を取得し、datetimeインデックス×センサーラベル列のWide形式で返す。"""
    query = "SELECT timestamp, sensor_name, co2 FROM sensor_readings ORDER BY timestamp"
    df = pd.read_sql_query(query, conn)
    df["datetime"] = (
        pd.to_datetime(df["timestamp"], unit="s", utc=True)
        .dt.tz_convert("Asia/Tokyo")
        .dt.tz_localize(None)
    )
    wide = df.pivot_table(
        index="datetime", columns="sensor_name", values="co2", aggfunc="mean"
    )
    wide = wide.rename(columns=db.SENSOR_LABELS)
    wide = wide.resample(RESAMPLE_FREQ).mean()
    return wide.sort_index()


def resample_regular(series: pd.Series, freq: str = RESAMPLE_FREQ) -> pd.Series:
    """時系列を指定ビンの等間隔に再サンプリングする(欠測は線形補間)。"""
    return (
        series.astype(float)
        .resample(freq)
        .mean()
        .interpolate(method="linear", limit_direction="both")
    )


def remove_spikes(
    series: pd.Series,
    threshold: float = SPIKE_JUMP_PPM,
    max_width: int = SPIKE_MAX_WIDTH,
) -> tuple[pd.Series, np.ndarray]:
    """急激なジャンプと復帰パターンからスパイクを検出し線形補間で除去する。

    隣接点(既定5分間隔)の差分が threshold(ppm) を超える「ジャンプ」があり、
    その後 max_width 点以内にジャンプ前のレベル(±threshold)へ戻る場合、その一連の点を
    スパイク(センサーノイズ)とみなして除去・線形補間する。両方向(上昇/下降)に対応。

    戻り値: (補間済みSeries, スパイクフラグの真偽配列)
    """
    s = series.astype(float)
    values = s.to_numpy(dtype=float)
    n = len(values)
    diff = np.diff(values, prepend=np.nan)
    is_spike = np.zeros(n, dtype=bool)

    i = 1
    while i < n - 1:
        if not np.isnan(diff[i]) and abs(diff[i]) > threshold:
            direction = 1.0 if diff[i] > 0 else -1.0
            base = values[i - 1]
            j = i
            while (
                j < n - 1
                and not np.isnan(diff[j + 1])
                and np.sign(diff[j + 1]) == direction
            ):
                j += 1
            k = j
            reverted = False
            while k < n - 1 and (k - i + 1) <= max_width:
                if abs(values[k + 1] - base) <= threshold:
                    is_spike[i : k + 2] = True
                    i = k + 2
                    reverted = True
                    break
                k += 1
            if reverted:
                continue
        i += 1

    cleaned = s.mask(is_spike).interpolate(method="linear", limit_direction="both")
    return cleaned, is_spike


def preprocess_series(
    series: pd.Series,
    freq: str = RESAMPLE_FREQ,
    threshold: float = SPIKE_JUMP_PPM,
    max_width: int = SPIKE_MAX_WIDTH,
) -> tuple[pd.Series, np.ndarray]:
    """等間隔化→スパイク除去のパイプラインを1センサーに適用する。

    戻り値: (前処理済み等間隔Series, 等間隔化後の系列に対するスパイクフラグ配列)
    """
    regular = resample_regular(series, freq=freq)
    cleaned, is_spike = remove_spikes(regular, threshold=threshold, max_width=max_width)
    return cleaned, is_spike


def estimate_baseline(series: pd.Series, window_days: int = 14) -> pd.Series:
    """無人時ベースラインを日次で算出し、直近 window_days 日の中央値でローリング平滑化する。

    平日は早朝(6-9時)、休日は早朝(6-10時)の中央値を採用。
    該当時間帯にデータが足りない場合は深夜(1-5時)中央値に +30ppm 補正した値で代用する。
    戻り値: 日付(正午タイムスタンプ)インデックス → ベースライン(ppm) のSeries。
    """
    frame = series.dropna().to_frame("co2")
    if frame.empty:
        return pd.Series(dtype=float)
    frame["hour"] = frame.index.hour
    frame["is_weekend"] = frame.index.dayofweek >= 5

    daily_values = {}
    for date, g in frame.groupby(frame.index.normalize()):
        hours = (
            WEEKEND_BASELINE_HOURS
            if g["is_weekend"].iloc[0]
            else WEEKDAY_BASELINE_HOURS
        )
        sub = g.loc[(g["hour"] >= hours[0]) & (g["hour"] < hours[1]), "co2"]
        if len(sub) >= 3:
            val = sub.median()
        else:
            sub_deep = g.loc[
                (g["hour"] >= DEEP_NIGHT_HOURS[0]) & (g["hour"] < DEEP_NIGHT_HOURS[1]),
                "co2",
            ]
            val = (
                sub_deep.median() + DEEP_NIGHT_OFFSET if len(sub_deep) >= 3 else np.nan
            )
        daily_values[date] = val

    daily = pd.Series(daily_values).sort_index()
    return daily.rolling(window=window_days, min_periods=3).median()


def estimate_sensor_offsets(
    df_wide: pd.DataFrame, reference: str = B1F_LABEL
) -> dict[str, float]:
    """各センサーの深夜(1-5時)CO2中央値と基準センサーの深夜中央値の差をオフセットとして推定する。

    補正時は co2_corrected = co2 - offset で基準センサーのスケールに揃う。
    戻り値: {センサーラベル: オフセット(ppm)}
    """
    night_mask = (df_wide.index.hour >= DEEP_NIGHT_HOURS[0]) & (
        df_wide.index.hour < DEEP_NIGHT_HOURS[1]
    )
    medians = df_wide.loc[night_mask].median()
    if reference not in medians.index:
        raise KeyError(f"基準センサー '{reference}' がDataFrameに存在しません")
    ref_median = medians[reference]
    return {sensor: float(m - ref_median) for sensor, m in medians.items()}


def apply_offsets(df_wide: pd.DataFrame, offsets: dict[str, float]) -> pd.DataFrame:
    """センサーごとのオフセットを減算して基準センサースケールに正規化したDataFrameを返す。"""
    corrected = df_wide.copy()
    for sensor, offset in offsets.items():
        if sensor in corrected.columns:
            corrected[sensor] = corrected[sensor] - offset
    return corrected
