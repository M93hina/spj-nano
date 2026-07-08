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

# fetch_latestのカバー範囲(直近15分)。これ以下のギャップは補完不要。
GAP_THRESHOLD = datetime.timedelta(minutes=15)
# 補完する期間の上限。これを超える欠損は最新側からこの期間のみ補完する。
MAX_BACKFILL = datetime.timedelta(days=30)


def log(msg: str):
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{now}] {msg}", flush=True)


def collect_once(conn):
    readings = airoco.fetch_latest()
    inserted = db.save_readings(conn, readings)
    log(f"取得{len(readings)}件 / 新規保存{inserted}件")


def backfill_missing(conn):
    """DBの最新データ時刻から現在までの欠損を、起動時に1回だけ補完する。"""
    latest_ts = db.get_latest_timestamp(conn)
    now = datetime.datetime.now()

    if latest_ts is None:
        log(
            "DBにデータがありません。scripts/backfill.py で初期データを投入してください。"
        )
        return

    latest_dt = datetime.datetime.fromtimestamp(latest_ts)
    gap = now - latest_dt

    if gap <= GAP_THRESHOLD:
        log(f"欠損なし（最終: {latest_dt:%Y-%m-%d %H:%M}, ギャップ{gap}）")
        return

    from_dt = latest_dt
    clamped = False
    if gap > MAX_BACKFILL:
        from_dt = now - MAX_BACKFILL
        clamped = True

    if clamped:
        log(
            f"欠損期間が{MAX_BACKFILL.days}日を超えているため、"
            f"最新{MAX_BACKFILL.days}日分のみ補完します（全欠損: {gap.days}日）"
        )
    log(f"欠損補完を開始: {from_dt:%Y-%m-%d %H:%M} 〜 {now:%Y-%m-%d %H:%M}")

    readings = airoco.fetch_range(int(from_dt.timestamp()), int(now.timestamp()))
    inserted = db.save_readings(conn, readings)
    log(f"補完完了: 取得{len(readings)}件 / 新規保存{inserted}件")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--interval", type=int, default=600, help="収集間隔(秒)。デフォルト600秒(10分)"
    )
    parser.add_argument(
        "--no-backfill",
        action="store_true",
        help="起動時の欠損補完をスキップする",
    )
    args = parser.parse_args()

    log(f"収集サーバーを起動しました(間隔: {args.interval}秒)")
    conn = db.connect()
    try:
        if not args.no_backfill:
            try:
                backfill_missing(conn)
            except Exception as e:
                log(f"欠損補完でエラー（ポーリングに移行）: {e}")
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
