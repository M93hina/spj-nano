"""day-csv APIで指定期間分のデータをまとめてSQLiteに取り込む"""

import argparse
import datetime
import sys
import time

from dotenv import load_dotenv

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, ".")

load_dotenv()

from spj_nano import airoco, db  # noqa: E402

MAX_RETRIES = 5


def fetch_day_csv_with_retry(start_ts: int) -> list[dict]:
    """一時的な接続エラーに対して指数バックオフでリトライする"""
    for attempt in range(MAX_RETRIES):
        try:
            return airoco.fetch_day_csv(start_ts)
        except Exception as e:
            if attempt == MAX_RETRIES - 1:
                raise
            wait = 2**attempt
            print(f"  エラー({e}) -> {wait}秒後にリトライ({attempt + 1}/{MAX_RETRIES})")
            time.sleep(wait)


def parse_date(s: str) -> datetime.datetime:
    return datetime.datetime.strptime(s, "%Y-%m-%d")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, help="今日から遡る日数(--start/--endと併用不可)")
    parser.add_argument("--start", type=str, help="取得開始日 YYYY-MM-DD(この日を含む)")
    parser.add_argument("--end", type=str, help="取得終了日 YYYY-MM-DD(この日を含む。省略時は今日)")
    args = parser.parse_args()

    today = datetime.datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)

    if args.start:
        start = parse_date(args.start)
        end = parse_date(args.end) if args.end else today
    else:
        days = args.days if args.days is not None else 30
        start = today - datetime.timedelta(days=days)
        end = today

    conn = db.connect()
    total_inserted = 0
    try:
        day = start
        while day <= end:
            start_ts = int(day.timestamp())
            readings = fetch_day_csv_with_retry(start_ts)
            inserted = db.save_readings(conn, readings)
            total_inserted += inserted
            print(f"{day.date()}: 取得{len(readings)}件 / 新規保存{inserted}件")
            day += datetime.timedelta(days=1)
            if day <= end:
                time.sleep(0.5)
    finally:
        conn.close()

    print(f"完了。合計新規保存: {total_inserted}件")


if __name__ == "__main__":
    main()
