# spj-nano

名城大学天白キャンパスのCO2濃度を使った混雑度・将来予測の試作システムです。

## データ収集

```powershell
uv run python scripts/server.py
```

Airoco APIを10分間隔(`--interval`秒で変更可)でポーリングし、`data/sensor_data.db`に保存し続ける常駐プロセスです。起動時にDB最新時刻から現在までの欠損を自動補完します(最大30日分。`--no-backfill`でスキップ可)。データ収集はこの収集サーバー方式に統一しています(cron想定の単発実行スクリプト`scripts/collect.py`は廃止)。Docker運用時は`compose.yml`の`collector`サービスが同じコマンドを常駐実行します。

初期データや30日を超える過去データの一括投入には`scripts/backfill.py`を使います。

## データ確認

```powershell
uv run python scripts/check_database.py
```

現在の保存済みDBは、`data/sensor_data.db`に7センサー分の約1年分のデータを保存しています。

## 天白キャンパスカレンダーCSVの生成

`calendar.pdf`内の「天白キャンパス全学部」ページを自動検出し、日付ごとの予定マーカーを抽出します。

```powershell
uv run python scripts/extract_calendar.py
```

生成先は`data/calendar_tenpaku.csv`です。PDFのフォント仕様により授業回数の丸数字などを文字列として完全復元できない場合があるため、機械学習では`has_schedule_marker`と`marker_count`を利用します。

## LightGBMの学習

```powershell
uv run python scripts/train_lgbm.py
```

15、30、60、120、180分後を別々のモデルで予測し、直近14日を時系列検証に使います。モデルは`models/lgbm/`に保存されます。

## 最新時点からの予測

```powershell
uv run python scripts/predict_lgbm.py
```

## ダッシュボード

```powershell
uv run streamlit run app.py
```

LightGBMモデルが存在する場合は、ダッシュボードでLightGBM＋カレンダー予測を使用します。モデルが存在しない場合は、既存のベースライン＋当日残差補正に自動的に戻ります。
