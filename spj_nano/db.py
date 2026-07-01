"""センサーデータ保存用のSQLite操作"""

import sqlite3
from pathlib import Path

import pandas as pd

DEFAULT_DB_PATH = Path(__file__).resolve().parent.parent / "data" / "sensor_data.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS sensor_readings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sensor_number TEXT NOT NULL,
    sensor_name TEXT NOT NULL,
    co2 REAL,
    temperature REAL,
    relative_humidity REAL,
    timestamp INTEGER NOT NULL,
    UNIQUE(sensor_number, timestamp)
);
CREATE INDEX IF NOT EXISTS idx_sensor_readings_name_ts
    ON sensor_readings(sensor_name, timestamp);
"""


def connect(db_path: Path = DEFAULT_DB_PATH) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.executescript(SCHEMA)
    return conn


# Airoco上のセンサー表示名 -> 分かりやすいラベル
SENSOR_LABELS = {
    "Ｒ３ーB１Ｆ_ＥＨ": "B1F EH",
    "Ｒ３ー１Ｆ_ＥＨ": "1F EH",
    "Ｒ３ー３Ｆ_ＥＨ": "3F EH",
    "Ｒ３ー４Ｆ_ＥＨ": "4F EH",
    "Ｒ３ー３０１": "301",
    "Ｒ３ー４０１": "401",
    "Ｒ３ー４０３": "403",
}


def get_readings(conn: sqlite3.Connection, sensor_name: str, since_ts: int | None = None) -> pd.DataFrame:
    """指定センサーの時系列データをDataFrameで取得する(timestamp昇順)"""
    query = "SELECT timestamp, co2, temperature, relative_humidity FROM sensor_readings WHERE sensor_name = ?"
    params: list = [sensor_name]
    if since_ts is not None:
        query += " AND timestamp >= ?"
        params.append(since_ts)
    query += " ORDER BY timestamp"
    df = pd.read_sql_query(query, conn, params=params)
    df["datetime"] = pd.to_datetime(df["timestamp"], unit="s", utc=True).dt.tz_convert("Asia/Tokyo").dt.tz_localize(None)
    return df


def save_readings(conn: sqlite3.Connection, readings: list[dict]) -> int:
    """センサーデータを保存する。CO2値が無いレコードは除外する。戻り値は新規保存件数。"""
    rows = [
        (r["sensorNumber"], r["sensorName"], r["co2"], r["temperature"], r["relativeHumidity"], r["timestamp"])
        for r in readings
        if r.get("co2") is not None
    ]
    cur = conn.executemany(
        """
        INSERT OR IGNORE INTO sensor_readings
            (sensor_number, sensor_name, co2, temperature, relative_humidity, timestamp)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        rows,
    )
    conn.commit()
    return cur.rowcount
