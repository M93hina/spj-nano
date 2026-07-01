"""Airoco latest API を1回叩いてSQLiteに保存する。cron/タスクスケジューラから定期実行する想定。"""

import sys

from dotenv import load_dotenv

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, ".")

load_dotenv()

from spj_nano import airoco, db  # noqa: E402


def main():
    readings = airoco.fetch_latest()
    conn = db.connect()
    try:
        inserted = db.save_readings(conn, readings)
    finally:
        conn.close()
    print(f"取得: {len(readings)}件 / 新規保存: {inserted}件")


if __name__ == "__main__":
    main()
