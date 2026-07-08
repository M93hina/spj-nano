"""混雑(CO2)予測モデル。

事前分析より「曜日×時刻の過去平均だけでCO2変動の8割超を説明可能(R²相当0.845)」。
これをベースラインとし、当日の実測残差を減衰させて乗せるハイブリッドモデルを実装する。

主な構成:
- BaselineProfile: 曜日×時刻ビンの加重平均(直近週ほど高重み=トレンド追従)
- forecast_horizon: 現在時刻から +1h/+2h/+3h の予測CO2を返すダッシュボード用API
- evaluate_holdout: 直近N日をホールドアウトしベースライン単体 vs ハイブリッドを比較
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

DEFAULT_BIN_MINUTES = 5
DEFAULT_HALF_LIFE_WEEKS = 2.0
DEFAULT_TAU_HOURS = 2.0
DEFAULT_HORIZONS = (1, 2, 3)


def _dayofweek(idx: pd.DatetimeIndex) -> np.ndarray:
    return pd.Series(idx).dt.dayofweek.to_numpy()


def _minute_bin(idx: pd.DatetimeIndex, bin_minutes: int) -> np.ndarray:
    return (idx.hour * 60 + idx.minute).to_numpy() // bin_minutes


@dataclass
class BaselineProfile:
    """曜日×時刻ビンの加重平均ベースライン。"""

    table: pd.Series
    bin_minutes: int

    @classmethod
    def fit(
        cls,
        series: pd.Series,
        bin_minutes: int = DEFAULT_BIN_MINUTES,
        half_life_weeks: float = DEFAULT_HALF_LIFE_WEEKS,
        until: pd.Timestamp | None = None,
    ) -> BaselineProfile:
        """学習データから曜日×時刻ビンの加重平均テーブルを構築する。

        until を指定した場合はそれ以前のデータのみ使用する(ホールドアウト時のリーク防止)。
        直近週ほど重みを大きくし(half_life_weeks で半減)、学期進行などのトレンドに追従する。
        """
        s = series.dropna().astype(float)
        if until is not None:
            s = s[s.index < until]
        if s.empty:
            raise ValueError("ベースライン学習データが空です")

        idx = s.index
        dates = idx.normalize()
        latest_date = dates.max()
        weeks_ago = (latest_date - dates).days / 7.0
        weights = np.exp(-np.log(2) * weeks_ago / half_life_weeks)

        frame = pd.DataFrame(
            {
                "co2": s.to_numpy(),
                "wd": _dayofweek(idx),
                "mb": _minute_bin(idx, bin_minutes),
                "w": weights,
            }
        )

        def _wmean(g: pd.DataFrame) -> float:
            w = g["w"].to_numpy()
            v = g["co2"].to_numpy()
            return float(np.average(v, weights=w)) if len(v) else np.nan

        table = frame.groupby(["wd", "mb"], observed=True).apply(
            _wmean, include_groups=False
        )
        table.name = "baseline"
        return cls(table=table, bin_minutes=bin_minutes)

    def predict(self, timestamps: pd.DatetimeIndex | list) -> pd.Series:
        """指定タイムスタンプ群のベースライン予測値を返す。"""
        idx = pd.DatetimeIndex(timestamps)
        keys = list(zip(_dayofweek(idx), _minute_bin(idx, self.bin_minutes)))
        values = [self.table.get(k, np.nan) for k in keys]
        return pd.Series(values, index=idx, name="baseline")

    def apply(self, series: pd.Series) -> pd.Series:
        """series と同インデックスで各点のベースライン値を返す。"""
        return self.predict(series.index).set_axis(series.index)


def forecast_horizon(
    series: pd.Series,
    profile: BaselineProfile,
    horizons_hours: tuple[int, ...] = DEFAULT_HORIZONS,
    tau_hours: float = DEFAULT_TAU_HOURS,
    base_time: pd.Timestamp | None = None,
) -> pd.DataFrame:
    """現在(既定で series の最終時刻)から horizons_hours 先の予測CO2を返す。

    予測 = baseline(t+h) + r0 * exp(-h/tau_hours)
    ただし r0 = measured(base_time) - baseline(base_time)(直近の混み具合乖離)。
    戻り値: columns=[horizon_hours, time, predicted_co2, baseline_co2, residual0]
    """
    if base_time is None:
        base_time = series.index[-1]
    measured_t0 = float(series.asof(base_time))
    baseline_t0 = float(profile.predict([base_time]).iloc[0])
    r0 = measured_t0 - baseline_t0

    future_times = [base_time + pd.Timedelta(hours=h) for h in horizons_hours]
    future_baseline = profile.predict(future_times)
    decay = np.exp(-np.array(horizons_hours, dtype=float) / tau_hours)
    predicted = future_baseline.to_numpy() + r0 * decay

    return pd.DataFrame(
        {
            "horizon_hours": list(horizons_hours),
            "time": future_times,
            "baseline_co2": future_baseline.to_numpy(),
            "predicted_co2": predicted,
            "residual0": r0,
        }
    )


def evaluate_holdout(
    series: pd.Series,
    holdout_days: int = 7,
    horizons_hours: tuple[int, ...] = DEFAULT_HORIZONS,
    bin_minutes: int = DEFAULT_BIN_MINUTES,
    half_life_weeks: float = DEFAULT_HALF_LIFE_WEEKS,
    tau_hours: float = DEFAULT_TAU_HOURS,
) -> pd.DataFrame:
    """直近 holdout_days 日をホールドアウトし、ベースライン単体 vs ハイブリッドの精度を比較する。

    ハイブリッドは各評価時刻 t について t-h 時間(過去)の実測残差を減衰させて適用する。
    戻り値: index=モデル名、columns=[mae, resid_std, n]
    """
    series = series.dropna().astype(float)
    holdout_start = series.index.max() - pd.Timedelta(days=holdout_days)
    train = series[series.index < holdout_start]
    test = series[series.index >= holdout_start]
    if len(train) < 200 or len(test) < 100:
        raise ValueError("学習/ホールドアウトデータが不足しています")

    profile = BaselineProfile.fit(
        train, bin_minutes=bin_minutes, half_life_weeks=half_life_weeks
    )
    baseline_test = profile.predict(test.index)
    common = test.index.intersection(baseline_test.dropna().index)
    test_aligned = test.loc[common]
    base_aligned = baseline_test.loc[common]

    rows = []
    resid_base = test_aligned - base_aligned
    rows.append(
        {
            "model": "baseline",
            "mae": float(resid_base.abs().mean()),
            "resid_std": float(resid_base.std()),
            "n": int(len(resid_base)),
        }
    )

    for h in horizons_hours:
        t0_times = test.index - pd.Timedelta(hours=h)
        measured_t0 = series.reindex(t0_times, method="ffill")
        baseline_t0 = profile.predict(t0_times)
        valid = measured_t0.notna() & baseline_t0.notna() & baseline_test.notna()
        if valid.sum() == 0:
            continue
        r0 = measured_t0.loc[valid] - baseline_t0.loc[valid]
        decay = np.exp(-h / tau_hours)
        pred = baseline_test.loc[valid] + r0.to_numpy() * decay
        resid = test.loc[valid] - pred
        rows.append(
            {
                "model": f"hybrid_+{h}h",
                "mae": float(resid.abs().mean()),
                "resid_std": float(resid.std()),
                "n": int(len(resid)),
            }
        )

    return pd.DataFrame(rows).set_index("model")
