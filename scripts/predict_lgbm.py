"""保存済みLightGBMモデルで最新時点からCO2を予測する。"""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from spj_nano import lgbm_forecast


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=root / "data" / "sensor_data.db")
    parser.add_argument("--calendar", type=Path, default=root / "data" / "calendar_tenpaku.csv")
    parser.add_argument("--model-dir", type=Path, default=root / "models" / "lgbm")
    args = parser.parse_args()
    result, metadata = lgbm_forecast.forecast_from_database(
        args.db, args.calendar, args.model_dir
    )
    print(f"データ時点: {result['data_time'].iloc[0]}")
    print(result[["horizon_minutes", "time", "predicted_co2", "baseline_co2"]].to_string(index=False))
    print(f"検証結果: {metadata['metrics']}")


if __name__ == "__main__":
    main()
