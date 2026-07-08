"""混雑予測モデルのホールドアウト評価スクリプト。

直近1週間をホールドアウトし、ベースライン単体 vs ハイブリッド(当日残差減衰)の
MAE/残差std を比較する。目標: 残差std 45ppm 以下。
残差減衰時定数 tau の感度分析も行う。
"""

import sys

import pandas as pd

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, ".")

from spj_nano import db, forecast as fc, preprocess as pp  # noqa: E402


def main():
    conn = db.connect()
    try:
        wide = pp.load_wide(conn)
    finally:
        conn.close()

    cleaned, _ = pp.preprocess_series(wide[pp.B1F_LABEL])
    print(
        f"データ期間: {cleaned.index.min()} 〜 {cleaned.index.max()} (n={len(cleaned)})"
    )
    print(f"CO2 std(全体): {cleaned.std():.1f} ppm")

    print("\n=== 既定パラメータ(tau=2.0h)での評価 ===")
    result = fc.evaluate_holdout(cleaned, holdout_days=7, tau_hours=2.0)
    print(result.to_string())
    best_base = result.loc["baseline", "resid_std"]
    r2_like = 1 - (best_base**2) / (cleaned.std() ** 2)
    print(f"\nベースライン R²相当(全体std基準): {r2_like:.3f}")
    target = 45.0
    ok = (result["resid_std"] <= target).any()
    print(f"残差std {target}ppm 以下を達成: {'OK' if ok else 'NG'}")

    print("\n=== tau_hours の感度分析 ===")
    print(
        f"{'tau(h)':<8}{'baseline':>12}{'hybrid+1h':>12}{'hybrid+2h':>12}{'hybrid+3h':>12}"
    )
    for tau in [0.5, 1.0, 1.5, 2.0, 3.0, 4.0]:
        r = fc.evaluate_holdout(cleaned, holdout_days=7, tau_hours=tau)
        vals = [
            f"{r.loc[m, 'resid_std']:>10.1f}" if m in r.index else f"{'--':>10}"
            for m in ["baseline", "hybrid_+1h", "hybrid_+2h", "hybrid_+3h"]
        ]
        print(f"{tau:<8}" + "".join(v.rjust(12) for v in vals))

    print("\n=== 曜日別のベースライン精度 ===")
    holdout_start = cleaned.index.max() - pd.Timedelta(days=7)
    train = cleaned[cleaned.index < holdout_start]
    test = cleaned[cleaned.index >= holdout_start]
    profile = fc.BaselineProfile.fit(train)
    base_test = profile.predict(test.index)
    resid = test - base_test
    wd_names = ["月", "火", "水", "木", "金", "土", "日"]
    print(f"{'曜日':<6}{'MAE':>8}{'残差std':>10}{'n':>8}")
    for wd in range(7):
        mask = resid.index.dayofweek == wd
        sub = resid.loc[mask].dropna()
        if len(sub) == 0:
            continue
        print(
            f"{wd_names[wd]:<6}{sub.abs().mean():>8.1f}{sub.std():>10.1f}{len(sub):>8}"
        )


if __name__ == "__main__":
    main()
