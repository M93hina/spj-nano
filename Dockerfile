# B1F 混雑状況ダッシュボード (FastAPI版) 用イメージ
# Jetson Nano (aarch64) / 開発機 (amd64) の両方でアーキ固有の記述なしにビルドできるようにする。
# Jetson上ではこのDockerfileをネイティブビルドする想定(クロスビルド不要)。

FROM python:3.12-slim

# LightGBMの共有ライブラリがlibgomp(GNU OpenMP)に動的リンクされているが、
# python:3.12-slimには含まれていないため明示的に導入する
# (無いと import時に "libgomp.so.1: cannot open shared object file" で失敗する)
RUN apt-get update && apt-get install -y --no-install-recommends libgomp1 \
    && rm -rf /var/lib/apt/lists/*

# uvバイナリを取り込む(マルチアーキ対応のマニフェストからそのアーキに応じたuvが選ばれる)
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

# 依存関係の解決に必要なファイルのみ先にコピーしてレイヤーキャッシュを効かせる
COPY pyproject.toml uv.lock ./

# webエクストラを本番導入(依存レイヤーをアプリコードより先にキャッシュする)
RUN uv sync --frozen --extra web --no-dev

# 本体一式をコピー
# (web側はLightGBM学習済みモデル(models/lgbm)を推論する lgbm_forecast.py のみ使用し、
#  学習用スクリプトやStreamlit専用の forecast.py には依存しない)
COPY spj_nano ./spj_nano
COPY scripts ./scripts
COPY web ./web
COPY models ./models
COPY data/calendar_tenpaku.csv ./data/calendar_tenpaku.csv

ENV PATH="/app/.venv/bin:${PATH}"

EXPOSE 8000

# uv run経由にすると起動時に暗黙のsync(ネットワークアクセス)が走り得るため、
# venvのuvicornを直接起動する(PATHに/app/.venv/binを通し済み)
CMD ["uvicorn", "web.main:app", "--host", "0.0.0.0", "--port", "8000"]
