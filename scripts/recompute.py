"""モデルパラメータ(閾値・無人時ベースライン・センサーオフセット)の定期再計算スクリプト。

週次程度で実行し、結果を data/model_params.json に保存する。
学期進行・季節変動で分布が変わるため、定期的に再計算してダッシュボード等に反映させる想定。

利用:
    uv run python scripts/recompute.py
"""

import datetime
import json
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, ".")

import pandas as pd  # noqa: E402

from spj_nano import db, levels, preprocess as pp  # noqa: E402

OUT_PATH = Path(__file__).resolve().parent.parent / "data" / "model_params.json"


def main():
    conn = db.connect()
    try:
        wide = pp.load_wide(conn)
    finally:
        conn.close()

    cleaned, is_spike = pp.preprocess_series(wide[pp.B1F_LABEL])
    thresholds = levels.compute_thresholds(cleaned)
    baseline = pp.estimate_baseline(cleaned)
    offsets = pp.estimate_sensor_offsets(wide)
    baseline_clean = baseline.dropna()

    params = {
        "computed_at": datetime.datetime.now().isoformat(timespec="seconds"),
        "data_until": str(cleaned.index.max()),
        "n_samples": int(len(cleaned)),
        "spike_points_removed": int(is_spike.sum()),
        "thresholds_ppm": {
            "t1_l1l2": round(thresholds.t1, 1),
            "t2_l2l3": round(thresholds.t2, 1),
            "t3_l3l4": round(thresholds.t3, 1),
        },
        "baseline_ppm": {
            "latest": round(float(baseline_clean.iloc[-1]), 1)
            if not baseline_clean.empty
            else None,
            "median": round(float(baseline_clean.median()), 1)
            if not baseline_clean.empty
            else None,
        },
        "offsets_ppm": {
            k: round(v, 1) for k, v in sorted(offsets.items(), key=lambda x: x[1])
        },
    }

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(
        json.dumps(params, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    print(json.dumps(params, ensure_ascii=False, indent=2))
    print(f"\n保存先: {OUT_PATH}")


if __name__ == "__main__":
    main()
