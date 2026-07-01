"""Airoco データ API クライアント"""

import csv
import io
import os

import requests

BASE_URL = "https://airoco.necolico.jp"


def _credentials():
    return os.environ["AIROCO_ID"], os.environ["AIROCO_SUBSCRIPTION_KEY"]


def fetch_latest() -> list[dict]:
    """全センサーの最新データ(直近15分以内)を取得する"""
    hash_id, subscription_key = _credentials()
    resp = requests.get(
        f"{BASE_URL}/data-api/latest",
        params={"id": hash_id, "subscription-key": subscription_key},
        timeout=10,
    )
    resp.raise_for_status()
    return resp.json()


def fetch_day_csv(start_date: int) -> list[dict]:
    """start_date(UNIX秒)から24時間分の全センサーデータを取得し、latest APIと同じキー形式で返す"""
    hash_id, subscription_key = _credentials()
    resp = requests.get(
        f"{BASE_URL}/data-api/day-csv",
        params={"id": hash_id, "subscription-key": subscription_key, "startDate": start_date},
        timeout=30,
    )
    resp.raise_for_status()
    text = resp.content.decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(text))
    readings = []
    for row in reader:
        co2 = row.get("CO2")
        readings.append(
            {
                "sensorNumber": row["MACアドレス"],
                "sensorName": row["表示センサー名"],
                "co2": float(co2) if co2 else None,
                "temperature": float(row["温度"]) if row.get("温度") else None,
                "relativeHumidity": float(row["湿度"]) if row.get("湿度") else None,
                "timestamp": int(row["timestamp"]),
            }
        )
    return readings
