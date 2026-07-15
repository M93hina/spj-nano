"""Streamlitダッシュボードのスモークテスト。"""

from pathlib import Path
import sys

from streamlit.testing.v1 import AppTest

root = Path(__file__).resolve().parents[1]
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, str(root))
test = AppTest.from_file(str(root / "app.py")).run(timeout=180)
if test.exception:
    for exception in test.exception:
        print(exception.value)
    raise SystemExit(1)
print("app smoke test: OK")
print(f"metrics: {len(test.metric)}")
