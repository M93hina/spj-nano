"""新旧混雑レベル閾値の比較検証スクリプト。

前処理済みB1Fデータに対し、現行固定閾値(500/700/1000)と
データ駆動閾値(分位点ベース+提案値)を適用したときのレベル分布を比較する。
"""

import sys

import pandas as pd

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, ".")

from spj_nano import db, levels, preprocess as pp  # noqa: E402

OLD = levels.Thresholds(500.0, 700.0, 1000.0)
MANUAL = levels.Thresholds(*levels.MANUAL_THRESHOLDS_2026_06)


def distribution(codes: pd.Series, daytime_only: bool) -> pd.Series:
    if daytime_only:
        mask = (
            (codes.index.hour >= 9)
            & (codes.index.hour < 18)
            & (codes.index.dayofweek < 5)
        )
        codes = codes.loc[mask]
    counts = codes.value_counts().reindex([1, 2, 3, 4], fill_value=0)
    return counts / counts.sum() * 100


def main():
    conn = db.connect()
    try:
        wide = pp.load_wide(conn)
    finally:
        conn.close()

    cleaned, _ = pp.preprocess_series(wide[pp.B1F_LABEL])

    auto = levels.compute_thresholds(cleaned)
    print("=== 算出された閾値 ===")
    print(f"現行固定(旧): {OLD.t1}/{OLD.t2}/{OLD.t3}")
    print(f"提案手動(6月): {MANUAL.t1}/{MANUAL.t2}/{MANUAL.t3}")
    print(f"データ駆動(自動): {auto.t1:.0f}/{auto.t2:.0f}/{auto.t3:.0f}")

    print("\n=== レベル分布(全データ) ===")
    print(f"{'レベル':<6}{'旧(500/700/1000)':>20}{'手動(550/650/760)':>20}{'自動':>14}")
    old_codes = levels.classify_series(cleaned, OLD)
    man_codes = levels.classify_series(cleaned, MANUAL)
    auto_codes = levels.classify_series(cleaned, auto)
    dist_old = distribution(old_codes, daytime_only=False)
    dist_man = distribution(man_codes, daytime_only=False)
    dist_auto = distribution(auto_codes, daytime_only=False)
    for lvl in range(1, 5):
        label = levels.LEVEL_META[lvl - 1][0]
        print(
            f"{label:<6}{dist_old[lvl]:>18.1f}%{dist_man[lvl]:>18.1f}%{dist_auto[lvl]:>12.1f}%"
        )

    print("\n=== レベル分布(平日日中 9-18時) ===")
    dist_old_d = distribution(old_codes, daytime_only=True)
    dist_man_d = distribution(man_codes, daytime_only=True)
    dist_auto_d = distribution(auto_codes, daytime_only=True)
    for lvl in range(1, 5):
        label = levels.LEVEL_META[lvl - 1][0]
        print(
            f"{label:<6}{dist_old_d[lvl]:>18.1f}%{dist_man_d[lvl]:>18.1f}%{dist_auto_d[lvl]:>12.1f}%"
        )

    print("\n=== 平日日中の4段階出現確認 ===")
    for name, dist in [("旧", dist_old_d), ("手動", dist_man_d), ("自動", dist_auto_d)]:
        nonzero = (dist > 0).sum()
        print(
            f"  {name}: 4段階中 {nonzero} レベルが出現(各レベル min {dist[dist > 0].min():.1f}%)"
        )


if __name__ == "__main__":
    main()
