"""B1Fフリースペース 混雑状況・予測ダッシュボード

前処理済みデータ(スパイク除去)・データ駆動閾値・曜日×時刻ベースライン+当日残差
ハイブリッド予測を統合したダッシュボード。
"""

import datetime

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from spj_nano import db, forecast as fc, levels, preprocess as pp

st.set_page_config(page_title="B1F 混雑状況", layout="wide")

PRED_HORIZONS = (1, 2, 3)
PRED_BAND_PPM = 45.0  # 予測信頼帯の半値(分析目標水準)


@st.cache_data(ttl=300)
def load_data():
    conn = db.connect()
    try:
        wide = pp.load_wide(conn)
    finally:
        conn.close()
    cleaned, is_spike = pp.preprocess_series(wide[pp.B1F_LABEL])
    return cleaned, int(is_spike.sum())


@st.cache_data(ttl=300)
def compute_model(cleaned: pd.Series):
    thresholds = levels.compute_thresholds(cleaned)
    profile = fc.BaselineProfile.fit(cleaned)
    horizon_df = fc.forecast_horizon(cleaned, profile, horizons_hours=PRED_HORIZONS)
    return thresholds, profile, horizon_df


cleaned, n_spike = load_data()

st.title("B1F フリースペース 混雑状況・予測")

if cleaned.empty:
    st.warning(
        "データがありません。先に scripts/collect.py または scripts/backfill.py を実行してください。"
    )
    st.stop()

thresholds, profile, horizon_df = compute_model(cleaned)

latest_time = cleaned.index[-1]
latest_co2 = float(cleaned.iloc[-1])
lvl, label, icon = thresholds.level(latest_co2)

# --- データ鮮度チェック ---
# DBの最終データが現在時刻から一定以上古い場合、収集が止まっている可能性がある。
# 「現在のCO2濃度」等の表示は最終データ時点のものであり「今」ではないことを明示する。
STALE_THRESHOLD = pd.Timedelta(minutes=30)
now_jst = pd.Timestamp.now(tz="Asia/Tokyo").tz_localize(None)
data_age = now_jst - latest_time
is_stale = data_age > STALE_THRESHOLD
if is_stale:
    age_hours = data_age.total_seconds() / 3600
    if age_hours >= 24:
        age_str = f"約{age_hours / 24:.1f}日"
    else:
        age_str = f"約{age_hours:.1f}時間"
    st.warning(
        f"⚠ データが{age_str}前（{latest_time.strftime('%Y-%m-%d %H:%M')}時点）を最後に更新が止まっています。"
        "以下の「現在」「この先」の表示はすべて最終データ時点を起点にした情報であり、"
        "リアルタイムの状況ではない点にご注意ください。"
    )

col1, col2, col3, col4 = st.columns(4)
col1.metric("現在のCO2濃度", f"{latest_co2:.0f} ppm")
col2.metric("混雑度", f"{icon} {label}（L{lvl}）")
col3.metric("最終更新", latest_time.strftime("%Y-%m-%d %H:%M"))
col4.metric("前処理で除去したスパイク", f"{n_spike} 点")

with st.expander("閾値（平日日中のCO2分布から自動算出）"):
    quants = cleaned.loc[
        (cleaned.index.hour >= 9)
        & (cleaned.index.hour < 18)
        & (cleaned.index.dayofweek < 5)
    ]
    st.write(
        f"L1 〜{thresholds.t1:.0f}ppm「空いています」 / "
        f"L2 {thresholds.t1:.0f}〜{thresholds.t2:.0f}「やや利用あり」 / "
        f"L3 {thresholds.t2:.0f}〜{thresholds.t3:.0f}「混雑」 / "
        f"L4 {thresholds.t3:.0f}〜「非常に混雑」"
    )
    st.caption(
        f"平日日中サンプル数 {len(quants)}、分布 median={quants.median():.0f}ppm"
    )


# --- ひと言コメント（この先3時間の見込み） ---
def _one_liner(horizon_df: pd.DataFrame, current_lvl: int) -> str:
    future_lvls = [thresholds.level(v)[0] for v in horizon_df["predicted_co2"]]
    if max(future_lvls) > current_lvl:
        t = horizon_df.loc[horizon_df["predicted_co2"].idxmax(), "time"]
        return f"⤴ {t.strftime('%H:%M')} 頃から混雑の見込み"
    if min(future_lvls) < current_lvl:
        t = horizon_df.loc[horizon_df["predicted_co2"].idxmin(), "time"]
        return f"⤵ {t.strftime('%H:%M')} 頃から空く見込み"
    return "→ この先3時間は現在の混雑が続く見込み"


st.subheader("この先3時間の見込み" + ("（最終データ時点を起点とした予測）" if is_stale else ""))
st.info(_one_liner(horizon_df, lvl))
if is_stale:
    st.caption(
        f"※ 最終データ時刻（{latest_time.strftime('%Y-%m-%d %H:%M')}）を起点とした予測です。"
        "現在のリアルタイムな見込みではありません。"
    )

# --- 直近24時間チャート + 予測線 ---
st.subheader("直近24時間のCO2推移と予測")
since_24h = latest_time - pd.Timedelta(hours=24)
df_24h = cleaned[cleaned.index >= since_24h]

fig = go.Figure()
fig.add_trace(
    go.Scatter(
        x=df_24h.index,
        y=df_24h.values,
        mode="lines",
        name="CO2（実測・前処理済み）",
        line=dict(color="#1f77b4"),
    )
)
upper = horizon_df["predicted_co2"] + PRED_BAND_PPM
lower = (horizon_df["predicted_co2"] - PRED_BAND_PPM).clip(lower=0)
fig.add_trace(
    go.Scatter(
        x=list(horizon_df["time"]) + list(horizon_df["time"][::-1]),
        y=list(upper) + list(lower[::-1]),
        fill="toself",
        fillcolor="rgba(255,127,14,0.15)",
        line=dict(width=0),
        hoverinfo="skip",
        name="予測の幅（±{:.0f}ppm）".format(PRED_BAND_PPM),
    )
)
fig.add_trace(
    go.Scatter(
        x=horizon_df["time"],
        y=horizon_df["predicted_co2"],
        mode="lines+markers",
        name="予測（ハイブリッド）",
        line=dict(color="#ff7f0e", dash="dash"),
    )
)
for bound, txt in [
    (thresholds.t1, "L1/L2"),
    (thresholds.t2, "L2/L3"),
    (thresholds.t3, "L3/L4"),
]:
    fig.add_hline(
        y=bound,
        line_dash="dot",
        line_color="gray",
        annotation_text=f"{bound:.0f} ({txt})",
    )
fig.update_layout(yaxis_title="CO2 [ppm]", xaxis_title="時刻", height=420)
st.plotly_chart(fig, width="stretch")

# --- 予測サマリ表 ---
st.caption("予測サマリ（ベースライン+当日残差ハイブリッド）")
summary = horizon_df.copy()
summary["予測レベル"] = [thresholds.level(v)[1] for v in summary["predicted_co2"]]
summary["時刻"] = summary["time"].dt.strftime("%H:%M")
st.dataframe(
    summary[["時刻", "predicted_co2", "baseline_co2", "予測レベル"]]
    .rename(
        columns={"predicted_co2": "予測CO2(ppm)", "baseline_co2": "ベースライン(ppm)"}
    )
    .round(0),
    width="stretch",
    hide_index=True,
)

# --- 曜日×時間帯ヒートマップ（前処理済み） ---
st.subheader("曜日 × 時間帯の平均CO2濃度（前処理済みデータ全体）")
heat = cleaned.to_frame("co2")
heat["weekday"] = heat.index.day_name()
heat["hour"] = heat.index.hour
weekday_order = [
    "Monday",
    "Tuesday",
    "Wednesday",
    "Thursday",
    "Friday",
    "Saturday",
    "Sunday",
]
weekday_ja = {
    "Monday": "月",
    "Tuesday": "火",
    "Wednesday": "水",
    "Thursday": "木",
    "Friday": "金",
    "Saturday": "土",
    "Sunday": "日",
}
pivot = heat.pivot_table(
    index="weekday", columns="hour", values="co2", aggfunc="mean"
).reindex(weekday_order)
pivot.index = [weekday_ja[w] for w in pivot.index]

heatmap = go.Figure(
    data=go.Heatmap(
        z=pivot.values,
        x=pivot.columns,
        y=pivot.index,
        colorscale="YlOrRd",
        colorbar_title="ppm",
        zmin=thresholds.t1,
        zmax=thresholds.t3,
    )
)
heatmap.update_layout(xaxis_title="時刻(時)", yaxis_title="曜日", height=350)
st.plotly_chart(heatmap, width="stretch")
