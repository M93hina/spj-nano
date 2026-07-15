"""過去1年分のCO2と天白キャンパスカレンダーでLightGBMを学習する。

利用例:
    uv run python scripts/extract_calendar.py
    uv run python scripts/train_lgbm.py
"""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pandas as pd

from spj_nano import db, features, lgbm_forecast
from spj_nano import forecast as fc


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=root / "data" / "sensor_data.db")
    parser.add_argument("--calendar", type=Path, default=root / "data" / "calendar_tenpaku.csv")
    parser.add_argument("--output-dir", type=Path, default=root / "models" / "lgbm")
    parser.add_argument("--validation-days", type=int, default=14)
    parser.add_argument("--horizons", type=int, nargs="+", default=[15, 30, 60, 120, 180])
    args = parser.parse_args()

    calendar = features.load_calendar_csv(args.calendar)
    with db.connect(args.db) as conn:
        co2_wide, target = features.load_clean_co2(conn)
    profile = fc.BaselineProfile.fit(target)
    frame = features.build_feature_frame(co2_wide, baseline=profile, calendar=calendar)
    models, metrics = lgbm_forecast.train_models(
        frame,
        target,
        horizons_minutes=tuple(args.horizons),
        validation_days=args.validation_days,
    )
    lgbm_forecast.save_models(
        models,
        metrics,
        args.output_dir,
        feature_names=list(frame.columns),
    )
    print(f"データ期間: {target.index.min()} 〜 {target.index.max()}")
    print(f"学習サンプル数: {len(frame):,}")
    print(metrics.to_string(index=False))
    print(f"モデル保存先: {args.output_dir}")


if __name__ == "__main__":
    main()
