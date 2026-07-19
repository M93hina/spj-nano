"""B1F フリースペース 混雑状況ダッシュボード FastAPI版バックエンド

Jetson Nano(Ubuntu 18.04, aarch64)でも軽量に動作させるため、Streamlit版(app.py)の
表示内容をJSON APIとして提供する。

予測機能はLightGBM(spj_nano/lgbm_forecast.py)による事前学習済みモデルを推論するのみ
(学習は行わない)。モデルファイルやカレンダーCSVが無い場合・推論が失敗した場合は
予測データをnullにして実測表示のみ返す(graceful degradation)。
"""

from __future__ import annotations

import logging
import threading
import time
from pathlib import Path
from typing import Any

import pandas as pd
from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from spj_nano import db, levels, lgbm_forecast, preprocess as pp

STATIC_DIR = Path(__file__).resolve().parent / "static"
MODEL_DIR = Path(__file__).resolve().parent.parent / "models" / "lgbm"
CALENDAR_PATH = Path(__file__).resolve().parent.parent / "data" / "calendar_tenpaku.csv"

CACHE_TTL_SECONDS = 300  # st.cache_data(ttl=300) 相当
STALE_THRESHOLD = pd.Timedelta(minutes=30)

WEEKDAY_ORDER = [
    "Monday",
    "Tuesday",
    "Wednesday",
    "Thursday",
    "Friday",
    "Saturday",
    "Sunday",
]
WEEKDAY_JA = {
    "Monday": "月",
    "Tuesday": "火",
    "Wednesday": "水",
    "Thursday": "木",
    "Friday": "金",
    "Saturday": "土",
    "Sunday": "日",
}

app = FastAPI(title="B1F 混雑状況 API")


# --- 時刻ベースの単純なTTLキャッシュ(st.cache_data(ttl=300) の代替) ---
class _TTLCache:
    def __init__(self, ttl_seconds: float):
        self._ttl = ttl_seconds
        self._lock = threading.Lock()
        self._value: Any = None
        self._computed_at: float = 0.0

    def get_or_compute(self, factory):
        with self._lock:
            now = time.monotonic()
            if self._value is None or (now - self._computed_at) > self._ttl:
                self._value = factory()
                self._computed_at = now
            return self._value


_dashboard_cache = _TTLCache(CACHE_TTL_SECONDS)


def _load_data() -> tuple[pd.Series, int]:
    """app.pyのload_data()相当。DBから読み込み前処理(スパイク除去)する。"""
    conn = db.connect()
    try:
        wide = pp.load_wide(conn)
    finally:
        conn.close()
    cleaned, is_spike = pp.preprocess_series(wide[pp.B1F_LABEL])
    return cleaned, int(is_spike.sum())


def _build_forecast_payload() -> list[dict] | None:
    """LightGBMモデル(spj_nano/lgbm_forecast.py)による予測をJSON用のリストにする。

    モデルファイル・カレンダーCSVが存在しない場合や推論中に例外が発生した場合は
    Noneを返す。呼び出し側はこれをそのまま実測データと切り離してnull扱いすれば良く、
    ダッシュボード全体を壊さない(graceful degradation)。
    """
    if not (MODEL_DIR / "metadata.json").exists() or not CALENDAR_PATH.exists():
        return None
    try:
        result, _ = lgbm_forecast.forecast_from_database(
            db.DEFAULT_DB_PATH, CALENDAR_PATH, MODEL_DIR
        )
    except Exception:
        # 予測失敗でダッシュボード全体を壊さないが、原因調査のためログには残す
        logging.getLogger(__name__).exception("LightGBM予測に失敗したためforecastをnullで返します")
        return None
    return [
        {
            "horizon_minutes": int(row.horizon_minutes),
            "time": row.time.strftime("%Y-%m-%d %H:%M"),
            "predicted_co2": round(float(row.predicted_co2), 1),
        }
        for row in result.itertuples()
    ]


def _build_dashboard_payload() -> dict:
    """app.pyの表示ロジック相当をJSONペイロードとして構築する。

    鮮度判定(staleness)はキャッシュで古くならないよう、ここでは計算せず
    ハンドラ側で毎リクエスト計算する。そのために latest_time を内部キー
    "_latest_time" として持たせる(レスポンス生成時に除去する)。

    予測(forecast)もこの関数内でまとめて計算し、TTLキャッシュ(300秒)に
    載せることでLightGBMモデルの推論をリクエスト毎に行わないようにする。
    """
    cleaned, n_spike = _load_data()

    if cleaned.empty:
        return {"empty": True}

    thresholds = levels.compute_thresholds(cleaned)

    latest_time = cleaned.index[-1]
    latest_co2 = float(cleaned.iloc[-1])
    lvl, label, icon = thresholds.level(latest_co2)

    # --- 閾値の内訳(app.pyの平日日中サンプル) ---
    quants = cleaned.loc[
        (cleaned.index.hour >= 9)
        & (cleaned.index.hour < 18)
        & (cleaned.index.dayofweek < 5)
    ]

    # --- 直近24時間の実測チャート ---
    since_24h = latest_time - pd.Timedelta(hours=24)
    df_24h = cleaned[cleaned.index >= since_24h]

    # --- 曜日×時間帯ヒートマップ(前処理済みデータ全体) ---
    heat = cleaned.to_frame("co2")
    heat["weekday"] = heat.index.day_name()
    heat["hour"] = heat.index.hour
    pivot = heat.pivot_table(
        index="weekday", columns="hour", values="co2", aggfunc="mean"
    ).reindex(WEEKDAY_ORDER, columns=range(24))

    heatmap_values = [
        [None if pd.isna(v) else round(float(v), 1) for v in row]
        for row in pivot.to_numpy()
    ]

    return {
        "empty": False,
        "_latest_time": latest_time,
        "current": {
            "co2": round(latest_co2, 1),
            "level": lvl,
            "level_label": label,
            "icon": icon,
            "last_update": latest_time.strftime("%Y-%m-%d %H:%M"),
            "spikes_removed": n_spike,
        },
        "thresholds": {
            "t1": round(thresholds.t1, 1),
            "t2": round(thresholds.t2, 1),
            "t3": round(thresholds.t3, 1),
            "weekday_daytime_samples": int(len(quants)),
            "median": None if quants.empty else round(float(quants.median()), 1),
        },
        "series_24h": {
            "timestamps": [t.strftime("%m-%d %H:%M") for t in df_24h.index],
            "co2": [round(float(v), 1) for v in df_24h.to_numpy()],
        },
        "heatmap": {
            "weekdays": [WEEKDAY_JA[w] for w in WEEKDAY_ORDER],
            "hours": list(range(24)),
            "values": heatmap_values,
        },
        # LightGBMモデルが無い/推論失敗時はnull(フロントは予測なしとして扱う)
        "forecast": _build_forecast_payload(),
    }


@app.get("/api/dashboard")
def get_dashboard() -> dict:
    cached = _dashboard_cache.get_or_compute(_build_dashboard_payload)
    if cached.get("empty"):
        return {"empty": True}

    # --- データ鮮度チェック(app.pyと同一ロジック) ---
    # キャッシュ(TTL 300秒)に閉じ込めると最大5分古い判定になるため、
    # 毎リクエストここで計算する。キャッシュ済みdictはミューテートしない。
    latest_time = cached["_latest_time"]
    now_jst = pd.Timestamp.now(tz="Asia/Tokyo").tz_localize(None)
    data_age = now_jst - latest_time
    staleness = {
        "is_stale": bool(data_age > STALE_THRESHOLD),
        "age_hours": round(data_age.total_seconds() / 3600, 2),
        "last_update": latest_time.strftime("%Y-%m-%d %H:%M"),
    }
    return {
        **{k: v for k, v in cached.items() if k != "_latest_time"},
        "staleness": staleness,
    }


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")
