# Jetson Nano セットアップ手順(FastAPI版ダッシュボード)

B1Fフリースペース混雑状況ダッシュボード(FastAPI + 静的HTML/JS版)を、実験棟のJetson Nano(Ubuntu 18.04, aarch64)上でDockerを使って稼働させるための手順。

Jetson上で**ネイティブにDockerビルドする**ため、クロスビルド環境は不要。Dockerfileはamd64/aarch64のどちらでも同じ内容でビルドできるように書かれている(アーキ固有の記述なし)。

## 1. Dockerの有無を確認する

JetPack(NVIDIAのJetson向けOSイメージ)にはDockerが同梱されている場合がある。まず確認する。

```bash
docker --version
docker compose version
```

両方ともバージョンが表示されればインストール済み。手順3に進んでよい。

## 2. Dockerが無い場合はインストールする

Ubuntu 18.04(Jetson Nano)向けに `docker.io` パッケージと Compose plugin を導入する。

```bash
sudo apt-get update
sudo apt-get install -y docker.io

# Docker Compose v2(pluginコマンド `docker compose`)を導入
# Ubuntu 18.04のaptには入っていないことが多いため、公式配布物を手動配置する
sudo mkdir -p /usr/local/lib/docker/cli-plugins
sudo curl -SL "https://github.com/docker/compose/releases/latest/download/docker-compose-linux-$(uname -m)" \
  -o /usr/local/lib/docker/cli-plugins/docker-compose
sudo chmod +x /usr/local/lib/docker/cli-plugins/docker-compose

# dockerグループに現在のユーザーを追加(sudoなしでdockerコマンドを使えるようにする)
sudo usermod -aG docker "$USER"
```

`usermod` 実行後は一度ログアウト/ログインし直す(またはJetsonを再起動する)とグループ変更が反映される。

反映後、改めて `docker --version` / `docker compose version` で確認する。

## 3. リポジトリをJetsonへ転送する

開発機からJetsonへ、`git clone` でリポジトリを取得する(学内LAN経由でSSH/HTTPSどちらでも可)。

```bash
git clone <このリポジトリのURL> spj-nano
cd spj-nano
```

社内ネットワークのみで完結させたい場合は、`git bundle` や `scp -r` で丸ごと転送してもよい。

## 4. `.env` と `data/sensor_data.db` を手動コピーする

`.env`(Airoco APIの認証情報)と既存の `data/sensor_data.db`(蓄積済みセンサーデータ)は `.gitignore` 対象のため、`git clone` には含まれない。開発機から別途コピーする。

```bash
# 開発機側で実行(例: scpでJetsonへ転送)
scp .env jetson@<JetsonのIP>:~/spj-nano/.env
scp data/sensor_data.db jetson@<JetsonのIP>:~/spj-nano/data/sensor_data.db
```

`data/` ディレクトリがJetson側に無い場合は事前に `mkdir -p data` で作成しておく。

`.env` の中身は以下の2キー(`.env.example` 参照):

```
AIROCO_SUBSCRIPTION_KEY=...
AIROCO_ID=...
```

## 5. ビルド&起動

Jetson上のリポジトリルートで実行する。

```bash
docker compose up -d --build
```

- `api` サービス: ダッシュボードを `0.0.0.0:8000` で配信
- `collector` サービス: `scripts/server.py --interval 600` を常駐実行し、10分間隔でAirocoからセンサーデータを収集して `data/sensor_data.db` に保存し続ける

初回ビルドはJetson(aarch64)上でネイティブに `python:3.12-slim` イメージから依存関係を解決するため、開発機でのビルドよりも時間がかかることがある(数分〜十数分程度を見込む)。

起動状態の確認:

```bash
docker compose ps
docker compose logs -f api
docker compose logs -f collector
```

## 6. 同一LAN内から閲覧する

JetsonのIPアドレスを確認する。

```bash
hostname -I
```

同じ学内LANに接続した端末のブラウザから以下にアクセスする。

```
http://<JetsonのIP>:8000
```

5分ごとに自動でダッシュボードのデータが更新される。

## 7. 更新時の再デプロイ

コード変更を反映する場合は、Jetson上で以下を実行する。

```bash
git pull
docker compose up -d --build
```

`data/sensor_data.db` はボリュームマウントされているため、再ビルドしてもデータは失われない。

## 補足: 開発機でのStreamlit版の起動

Streamlit版(app.py)は開発用に残してあり、依存が `streamlit` エクストラに分離されている。開発機では `uv run --extra streamlit streamlit run app.py` で起動できる(`uv sync --all-extras` 済みなら `uv run streamlit run app.py` でも可)。

## トラブルシューティング

- **`docker compose` が見つからない**: 手順2のCompose plugin導入を再確認する。`docker-compose`(ハイフン付き、v1系)しか無い場合は `docker-compose up -d --build` で代用可能(コマンド体系はほぼ同じ)。
- **ポート8000にアクセスできない**: Jetson側のファイアウォール(ufw等)で8000番ポートが塞がれていないか確認する。学内ネットワークのポリシーで到達できない場合は情報システム部門に確認する。
- **`/api/dashboard` が `"empty": true` を返す**: `data/sensor_data.db` のコピーを忘れているか、`collector` サービスがまだデータを収集できていない可能性がある。`docker compose logs -f collector` でエラーが出ていないか確認する。
