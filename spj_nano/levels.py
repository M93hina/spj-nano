"""データ駆動の混雑レベル閾値モジュール。

CO2分布の分位点から4段階閾値を自動算出し、レベル分類を提供する。
固定閾値(500/700/1000)をデータ駆動閾値に置き換え、データ蓄積に応じて更新可能にする。
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

LEVEL_META = [
    ("空いています", "🟢"),
    ("やや利用あり", "🟡"),
    ("混雑", "🟠"),
    ("非常に混雑", "🔴"),
]

DEFAULT_QUANTILES = (0.30, 0.55, 0.90)
DEFAULT_DAYTIME_HOURS = (9, 18)

MANUAL_THRESHOLDS_2026_06 = (550.0, 650.0, 760.0)


@dataclass(frozen=True)
class Thresholds:
    """4段階混雑レベルの閾値セット(t1<t2<t3)。"""

    t1: float
    t2: float
    t3: float

    @property
    def bounds(self) -> tuple[float, float, float, float, float]:
        # 末尾に+infを加えて5要素にすることで、L4域(t3以上)でも
        # level()のループが範囲外アクセスせず動作するようにする。
        return (float("-inf"), self.t1, self.t2, self.t3, float("inf"))

    def level(self, co2: float) -> tuple[int, str, str]:
        """CO2値からレベル番号(1-4)・ラベル・アイコンを返す。

        classify_series(np.digitize実装、right=False)と境界挙動を一致させる。
        すなわち閾値ちょうどの値は上位レベルに分類される(例: co2==t1 は L2)。
        """
        for i, (label, icon) in enumerate(LEVEL_META):
            if co2 < self.bounds[i + 1]:
                return i + 1, label, icon
        last = LEVEL_META[-1]
        return len(LEVEL_META), last[0], last[1]


def compute_thresholds(
    series: pd.Series,
    quantiles: tuple[float, float, float] = DEFAULT_QUANTILES,
    daytime_hours: tuple[int, int] = DEFAULT_DAYTIME_HOURS,
    weekdays_only: bool = True,
) -> Thresholds:
    """CO2時系列から分位点ベースで4段階閾値を算出する。

    既定では平日日中(9-18時)の分布の Q30/Q55/Q90 を採用する。
    6月データで提案値(550/650/760ppm)前後を再現することを想定。
    """
    s = series.dropna()
    if s.empty:
        raise ValueError("閾値算出元のデータが空です")
    mask = (s.index.hour >= daytime_hours[0]) & (s.index.hour < daytime_hours[1])
    if weekdays_only:
        mask &= s.index.dayofweek < 5
    sub = s.loc[mask]
    if len(sub) < 30:
        raise ValueError("閾値算出に十分な平日日中データがありません")
    t1, t2, t3 = (float(sub.quantile(q)) for q in quantiles)
    return Thresholds(t1=t1, t2=t2, t3=t3)


def classify_series(series: pd.Series, thresholds: Thresholds) -> pd.Series:
    """CO2時系列全体に対してレベル番号(1-4)を割り当てたSeriesを返す。"""
    import numpy as np

    edges = np.array([-np.inf, thresholds.t1, thresholds.t2, thresholds.t3, np.inf])
    codes = np.digitize(series.to_numpy(dtype=float), edges[1:-1], right=False) + 1
    return pd.Series(codes, index=series.index, name="level")
