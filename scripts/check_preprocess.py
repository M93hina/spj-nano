"""前処理(preprocess)モジュールの動作確認スクリプト。

処理前後の比較と、テストケース(6/29 の 2797/2443 ppm スパイク)の除去を検証する。
"""

import sys

import pandas as pd

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, ".")

from spj_nano import db, preprocess as pp  # noqa: E402


def main():
    conn = db.connect()
    try:
        wide = pp.load_wide(conn)
    finally:
        conn.close()

    b1f_raw = wide[pp.B1F_LABEL]

    print("=== データ概要 ===")
    print(f"期間: {b1f_raw.index.min()} 〜 {b1f_raw.index.max()}")
    print(f"データ点数: {len(b1f_raw)} / 欠測: {b1f_raw.isna().sum()}")

    print("\n=== スパイク除去 ===")
    cleaned, is_spike = pp.preprocess_series(b1f_raw)
    n_spike = int(is_spike.sum())
    print(f"検出スパイク点数: {n_spike}")
    print(
        f"処理前 CO2: min={b1f_raw.min():.0f} max={b1f_raw.max():.0f} mean={b1f_raw.mean():.1f}"
    )
    print(
        f"処理後 CO2: min={cleaned.min():.0f} max={cleaned.max():.0f} mean={cleaned.mean():.1f}"
    )

    print("\n--- テストケース: 6/29 のスパイク ---")
    target = pd.to_datetime(
        [
            "2026-06-29 11:55",
            "2026-06-29 12:00",
            "2026-06-29 12:05",
            "2026-06-29 15:55",
            "2026-06-29 16:00",
        ]
    )
    raw_idx = b1f_raw.index.get_indexer(target, method="nearest")
    clean_idx = cleaned.index.get_indexer(target, method="nearest")
    print("時刻                元値     処理後   スパイク?")
    for rk, ck in zip(raw_idx, clean_idx):
        ts = cleaned.index[ck]
        print(
            f"{ts}  {b1f_raw.iloc[rk]:7.0f}  {cleaned.iloc[ck]:7.1f}   {bool(is_spike[ck])}"
        )

    target_peaks_removed = (
        cleaned.loc["2026-06-29 11:55"] < 1000
        and cleaned.loc["2026-06-29 15:55"] < 1000
    )
    print(f"\n2797/2443 ppm が除去されたか: {'OK' if target_peaks_removed else 'NG'}")

    print("\n=== 無人時ベースライン(日次ローリング中央値) ===")
    baseline = pp.estimate_baseline(cleaned)
    print(f"直近7日のベースライン:")
    recent = baseline.dropna().tail(7)
    for date, val in recent.items():
        print(f"  {date.date()}: {val:.1f} ppm")
    print(f"全期間のベースライン中央値: {baseline.median():.1f} ppm")

    print("\n=== センサーオフセット(深夜1-5時 median) ===")
    offsets = pp.estimate_sensor_offsets(wide)
    for sensor, off in sorted(offsets.items(), key=lambda x: x[1]):
        print(f"  {sensor:10s}: offset = {off:+6.1f} ppm")

    corrected = pp.apply_offsets(wide, offsets)
    print("\nオフセット補正後の深夜中央値(基準=B1F EH):")
    night_mask = (corrected.index.hour >= 1) & (corrected.index.hour < 5)
    for sensor, m in corrected.loc[night_mask].median().items():
        print(f"  {sensor:10s}: {m:6.1f} ppm")


if __name__ == "__main__":
    main()
