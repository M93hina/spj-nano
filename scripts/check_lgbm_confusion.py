"""LightGBM予測を混雑レベル4段階に変換し、ホールドアウト期間での混同行列と分類精度を評価する。

利用例:
    uv run python scripts/check_lgbm_confusion.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pandas as pd

from spj_nano import db, features, forecast as fc, levels, lgbm_forecast


def _level_label(code: int) -> str:
    label, icon = levels.LEVEL_META[code - 1]
    return f"L{code}:{label}"


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    db_path = root / "data" / "sensor_data.db"
    calendar_path = root / "data" / "calendar_tenpaku.csv"
    validation_days = 14
    horizons = (15, 30, 60, 120, 180)

    calendar = features.load_calendar_csv(calendar_path)
    with db.connect(db_path) as conn:
        co2_wide, target = features.load_clean_co2(conn)

    profile = fc.BaselineProfile.fit(target)
    frame = features.build_feature_frame(co2_wide, baseline=profile, calendar=calendar)

    cutoff = frame.index.max() - pd.Timedelta(days=validation_days)
    target_aligned = target.reindex(frame.index)
    target_train = target_aligned.loc[target_aligned.index < cutoff].dropna()
    thresholds = levels.compute_thresholds(target_train)

    print(f"CO2データ期間: {target.index.min()} 〜 {target.index.max()}")
    print(f"ホールドアウト: 直近{validation_days}日 (cutoff={cutoff})")
    print(
        f"混雑レベル閾値: t1={thresholds.t1:.1f}, t2={thresholds.t2:.1f}, t3={thresholds.t3:.1f} "
        f"(訓練データ n={len(target_train):,} から算出)"
    )
    print()

    models, _ = lgbm_forecast.train_models(
        frame,
        target,
        horizons_minutes=horizons,
        validation_days=validation_days,
    )

    labels = [_level_label(i) for i in range(1, 5)]

    for horizon in horizons:
        x, y = features.make_supervised(frame, target, horizon)
        valid_mask = x.index >= cutoff
        x_valid = x.loc[valid_mask]
        y_valid = y.loc[valid_mask]
        if len(y_valid) == 0:
            print(f"+{horizon}分: ホールドアウトデータなし\n")
            continue

        model = models[horizon]
        predicted_co2 = pd.Series(model.predict(x_valid), index=y_valid.index)

        actual_levels = levels.classify_series(y_valid, thresholds)
        predicted_levels = levels.classify_series(predicted_co2, thresholds)

        ct = pd.crosstab(
            actual_levels.rename("actual"),
            predicted_levels.rename("predicted"),
        ).reindex(index=[1, 2, 3, 4], columns=[1, 2, 3, 4], fill_value=0)
        ct.index = labels
        ct.columns = labels

        accuracy = float((actual_levels == predicted_levels).mean())
        adjacent_ok = float(((actual_levels - predicted_levels).abs() <= 1).mean())
        mae = float((predicted_co2 - y_valid).abs().mean())

        print(f"=== horizon +{horizon}分 (n={len(y_valid):,}) ===")
        print(
            f"ppm MAE: {mae:.2f} / レベル Accuracy: {accuracy:.3f} / 隣接1段許容: {adjacent_ok:.3f}"
        )
        print(ct.to_string())
        print()


if __name__ == "__main__":
    main()
