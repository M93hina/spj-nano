"""B1F混雑状況ダッシュボード(MVP)"""

import datetime

import plotly.graph_objects as go
import streamlit as st

from spj_nano import db

st.set_page_config(page_title="B1F 混雑状況", layout="wide")

B1F_SENSOR = "Ｒ３ーB１Ｆ_ＥＨ"

# CO2濃度(ppm)ベースの混雑レベル閾値
LEVELS = [
    (500, "空いています", "🟢"),
    (700, "やや混雑", "🟡"),
    (1000, "混雑", "🟠"),
    (float("inf"), "非常に混雑", "🔴"),
]


def congestion_level(co2: float):
    for threshold, label, icon in LEVELS:
        if co2 < threshold:
            return label, icon
    return LEVELS[-1][1], LEVELS[-1][2]


conn = db.connect()
df_all = db.get_readings(conn, B1F_SENSOR)
conn.close()

st.title("B1F フリースペース 混雑状況")

if df_all.empty:
    st.warning("データがありません。先に scripts/collect.py または scripts/backfill.py を実行してください。")
    st.stop()

latest = df_all.iloc[-1]
label, icon = congestion_level(latest["co2"])

col1, col2, col3 = st.columns(3)
col1.metric("現在のCO2濃度", f"{latest['co2']:.0f} ppm")
col2.metric("混雑度", f"{icon} {label}")
col3.metric("最終更新", latest["datetime"].strftime("%Y-%m-%d %H:%M"))

st.subheader("直近24時間のCO2推移")
since_24h = int((datetime.datetime.now() - datetime.timedelta(hours=24)).timestamp())
df_24h = df_all[df_all["timestamp"] >= since_24h]

fig = go.Figure()
fig.add_trace(go.Scatter(x=df_24h["datetime"], y=df_24h["co2"], mode="lines", name="CO2"))
for threshold, lbl, _ in LEVELS[:-1]:
    fig.add_hline(y=threshold, line_dash="dot", line_color="gray", annotation_text=lbl)
fig.update_layout(yaxis_title="CO2 [ppm]", xaxis_title="時刻", height=400)
st.plotly_chart(fig, use_container_width=True)

st.subheader("曜日 × 時間帯の平均CO2濃度(過去データ全体)")
df_all["weekday"] = df_all["datetime"].dt.day_name()
df_all["hour"] = df_all["datetime"].dt.hour
weekday_order = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
weekday_ja = {"Monday": "月", "Tuesday": "火", "Wednesday": "水", "Thursday": "木", "Friday": "金", "Saturday": "土", "Sunday": "日"}
pivot = df_all.pivot_table(index="weekday", columns="hour", values="co2", aggfunc="mean").reindex(weekday_order)
pivot.index = [weekday_ja[w] for w in pivot.index]

heatmap = go.Figure(
    data=go.Heatmap(z=pivot.values, x=pivot.columns, y=pivot.index, colorscale="YlOrRd", colorbar_title="ppm")
)
heatmap.update_layout(xaxis_title="時刻(時)", yaxis_title="曜日", height=350)
st.plotly_chart(heatmap, use_container_width=True)
