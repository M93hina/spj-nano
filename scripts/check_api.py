"""Airoco data-api/latest の疎通確認とセンサー一覧の表示"""

import os
import sys

import requests
from dotenv import load_dotenv

sys.stdout.reconfigure(encoding="utf-8")

load_dotenv()

BASE_URL = "https://airoco.necolico.jp"


def main():
    subscription_key = os.environ["AIROCO_SUBSCRIPTION_KEY"]
    hash_id = os.environ["AIROCO_ID"]

    resp = requests.get(
        f"{BASE_URL}/data-api/latest",
        params={"id": hash_id, "subscription-key": subscription_key},
        timeout=10,
    )
    resp.raise_for_status()
    sensors = resp.json()

    print(f"取得センサー数: {len(sensors)}")
    for s in sensors:
        print(f"- {s['sensorName']} (co2={s['co2']}ppm, temp={s['temperature']}C, hum={s['relativeHumidity']}%)")


if __name__ == "__main__":
    main()
