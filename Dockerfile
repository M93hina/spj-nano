# B1F 混雑状況ダッシュボード (FastAPI版) 用イメージ
# Jetson Nano (aarch64) / 開発機 (amd64) の両方でアーキ固有の記述なしにビルドできるようにする。
# Jetson上ではこのDockerfileをネイティブビルドする想定(クロスビルド不要)。

FROM python:3.12-slim

# uvバイナリを取り込む(マルチアーキ対応のマニフェストからそのアーキに応じたuvが選ばれる)
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

# 依存関係の解決に必要なファイルのみ先にコピーしてレイヤーキャッシュを効かせる
COPY pyproject.toml uv.lock ./

# webエクストラを本番導入(依存レイヤーをアプリコードより先にキャッシュする)
RUN uv sync --frozen --extra web --no-dev

# 予測機能(forecast.py)を含む本体一式をコピー
# (アプリ全体はそのままだが、web側では forecast.py を一切importしない)
COPY spj_nano ./spj_nano
COPY scripts ./scripts
COPY web ./web

ENV PATH="/app/.venv/bin:${PATH}"

EXPOSE 8000

# uv run経由にすると起動時に暗黙のsync(ネットワークアクセス)が走り得るため、
# venvのuvicornを直接起動する(PATHに/app/.venv/binを通し済み)
CMD ["uvicorn", "web.main:app", "--host", "0.0.0.0", "--port", "8000"]
