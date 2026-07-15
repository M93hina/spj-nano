"""保存済みSQLiteデータベースの期間・件数・欠測を確認する。"""

from __future__ import annotations

import argparse
from pathlib import Path
import sqlite3
import sys

import pandas as pd

sys.stdout.reconfigure(encoding="utf-8")


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", type=Path, default=root / "data" / "sensor_data.db")
    args = parser.parse_args()

    with sqlite3.connect(args.db) as conn:
        summary = pd.read_sql_query(
            """
            SELECT COUNT(*) AS rows,
                   COUNT(DISTINCT sensor_name) AS sensors,
                   MIN(timestamp) AS min_timestamp,
                   MAX(timestamp) AS max_timestamp
            FROM sensor_readings
            """,
            conn,
        ).iloc[0]
        by_sensor = pd.read_sql_query(
            """
            SELECT sensor_name, COUNT(*) AS rows,
                   MIN(timestamp) AS min_timestamp,
                   MAX(timestamp) AS max_timestamp,
                   SUM(co2 IS NULL) AS co2_missing
            FROM sensor_readings
            GROUP BY sensor_name
            ORDER BY sensor_name
            """,
            conn,
        )

    def jst(timestamp: int) -> str:
        return pd.Timestamp.fromtimestamp(int(timestamp), tz="Asia/Tokyo").strftime(
            "%Y-%m-%d %H:%M:%S %Z"
        )

    print(f"DB: {args.db}")
    print(f"総レコード数: {int(summary['rows']):,}")
    print(f"センサー数: {int(summary['sensors'])}")
    print(f"期間: {jst(summary['min_timestamp'])} 〜 {jst(summary['max_timestamp'])}")
    print("センサー別:")
    for row in by_sensor.itertuples(index=False):
        print(
            f"  {row.sensor_name}: {int(row.rows):,}件, "
            f"{jst(row.min_timestamp)} 〜 {jst(row.max_timestamp)}, "
            f"CO2欠測={int(row.co2_missing)}"
        )


if __name__ == "__main__":
    main()
