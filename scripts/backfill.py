"""day-csv APIで過去N日分のデータをまとめてSQLiteに取り込む"""

import argparse
import datetime
import sys
import time

from dotenv import load_dotenv

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, ".")

load_dotenv()

from spj_nano import airoco, db  # noqa: E402


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=30, help="遡る日数")
    args = parser.parse_args()

    conn = db.connect()
    today = datetime.datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)

    total_inserted = 0
    try:
        for i in range(args.days, -1, -1):
            day = today - datetime.timedelta(days=i)
            start_ts = int(day.timestamp())
            readings = airoco.fetch_day_csv(start_ts)
            inserted = db.save_readings(conn, readings)
            total_inserted += inserted
            print(f"{day.date()}: 取得{len(readings)}件 / 新規保存{inserted}件")
            time.sleep(0.3)
    finally:
        conn.close()

    print(f"完了。合計新規保存: {total_inserted}件")


if __name__ == "__main__":
    main()
