"""Airoco latest APIを定期的にポーリングしSQLiteに保存し続ける常駐プロセス"""

import argparse
import datetime
import sys
import time

from dotenv import load_dotenv

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, ".")

load_dotenv()

from spj_nano import airoco, db  # noqa: E402


def log(msg: str):
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{now}] {msg}", flush=True)


def collect_once(conn):
    readings = airoco.fetch_latest()
    inserted = db.save_readings(conn, readings)
    log(f"取得{len(readings)}件 / 新規保存{inserted}件")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--interval", type=int, default=600, help="収集間隔(秒)。デフォルト600秒(10分)")
    args = parser.parse_args()

    log(f"収集サーバーを起動しました(間隔: {args.interval}秒)")
    conn = db.connect()
    try:
        while True:
            try:
                collect_once(conn)
            except Exception as e:
                log(f"エラー: {e}")
            time.sleep(args.interval)
    except KeyboardInterrupt:
        log("停止しました")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
