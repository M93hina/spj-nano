"""生成済み天白キャンパスカレンダーCSVの整合性を確認する。"""

from pathlib import Path
import sys

import pandas as pd

root = Path(__file__).resolve().parents[1]
path = root / "data" / "calendar_tenpaku.csv"
df = pd.read_csv(path, encoding="utf-8-sig")
dates = pd.to_datetime(df["date"])
if not dates.is_unique:
    raise SystemExit("dateが重複しています")
if not (dates.dt.dayofweek == df["weekday"]).all():
    raise SystemExit("weekday列とdate列が一致しません")
if not (dates.diff().dropna() == pd.Timedelta(days=1)).all():
    raise SystemExit("日付が連続していません")
print(f"calendar check: OK ({len(df)}日, {df['date'].min()} 〜 {df['date'].max()})")
