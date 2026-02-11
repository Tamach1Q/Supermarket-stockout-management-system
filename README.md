# My_shop_app（欠品管理システム）

Flaskで動く簡易Webアプリです。`/` で地図上に商品エリアを設定し、`store_data/images` に増える欠品画像と `store_data/tracking.csv` の時刻・座標を突き合わせて通知します（通知一覧は `/monitor`）。

## ローカル起動（開発）

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# ダミーデータ生成（任意）
python make_demo_data.py

# 起動
python app.py
```

ブラウザで `http://localhost:5000` を開きます。

## 本番起動（Gunicorn）

```bash
pip install -r requirements.txt
export PORT=5000
gunicorn --workers 1 --bind 0.0.0.0:$PORT app:app
```

注意:
- 通知(`notifications`)はメモリ上に保持します。複数ワーカーで起動すると通知が分散するので、`--workers 1` を推奨します。
- 監視スレッドは初回リクエスト時に起動します（`DISABLE_MONITORING=1` で無効化）。

## Dockerで起動

```bash
docker build -t my-shop-app .
docker run --rm -p 5000:5000 -e PORT=5000 my-shop-app
```

## 非公開・常時稼働（おすすめ：店内PCでDocker Compose）

この構成だと「ローカルPCで常時稼働」しつつ、外部公開せずに運用できます。

```bash
docker compose up -d --build
```

- 既定では `5000` を公開するので、LAN内の別端末からもアクセスできます: `docker-compose.yml:1`
- 同じPCからだけ見たい場合は `docker-compose.yml` の `ports` を `127.0.0.1:5000:5000` に変更
- データはホスト側 `store_data/` に残ります（`store_data/areas.json` 含む）

外出先から見たい場合は、ポート公開せずにVPN（例：Tailscale等）経由にするのが安全です。

## PaaSにデプロイ（例）

GitHubにpush済みなら、多くのPaaS（Render/Railway/Fly.io等）で以下の設定だけで動きます。

- Build: `pip install -r requirements.txt`
- Start: `gunicorn --workers 1 --bind 0.0.0.0:$PORT app:app`

永続化したい場合は、`store_data/` が消えないように「永続ディスク/ボリューム」を有効化してください（通知はメモリ保持です）。

### Renderで「見る側」をクラウドに置く（ビジコン向け）

クラウド(Render)にこのWeb画面を置き、手元PCはコントロールハブWi‑Fiに繋いで `sync_robots.py` が取得したデータをクラウドへアップロードする構成です。

#### 1) Render側（Webアプリ）

- Start Command は `Procfile` の通りでOK: `Procfile:1`
- 環境変数（必須）
  - `INGEST_TOKEN`：ランダムな長い文字列（アップロード認証用）
- あると便利
  - `MAX_NOTIFICATIONS`：通知保持数（既定200）

Render起動後、ブラウザで `https://<あなたのRenderのURL>/` を開いてエリア設定を保存します（保存先は `store_data/areas.json`）。

#### 2) 手元PC側（ロボット→クラウド送信）

手元PCはコントロールハブWi‑Fiに繋いだまま、以下を設定して実行します。

```bash
export REMOTE_APP_URL="https://<あなたのRenderのURL>"
export INGEST_TOKEN="<Render側と同じ値>"
export REMOTE_RESET_ON_START=1  # 任意: デモ開始前に通知をリセット
python sync_robots.py
```

これで `tracking.csv` / `store_data/images/*.jpg` / `store_data/map.yaml` / `static/map.png` をRenderへ送ります。

注意:
- 会場でRenderにアクセスできない時に備えて、`make_demo_data.py` でローカルデモできる状態も用意しておくと安全です。

## ロボットからの同期（任意）

`sync_robots.py` はSSH/SCPでロボットから `tracking.csv` / 画像 / 地図ファイルを取得します（IPやパスは `sync_robots.py` 冒頭の設定を変更）。

## エンドポイント

- `GET /` 画面
- `GET /monitor` 通知一覧（従来UI）
- `POST /api/save_areas` エリア保存
- `GET /api/load_areas` エリア取得
- `GET /api/notifications` 通知取得
- `GET /api/detection/status` 欠品検知状態の取得
- `POST /api/detection/control` 欠品検知の開始/停止
- `GET /healthz` ヘルスチェック

### 取り込みAPI（クラウド連携用）

`INGEST_TOKEN` を設定すると、以下のエンドポイントに `X-Ingest-Token` を付けてアップロードできます。

- `POST /api/ingest/tracking`（multipart file）
- `POST /api/ingest/image`（multipart file）
- `POST /api/ingest/map_yaml`（multipart file）
- `POST /api/ingest/map_png`（multipart file）
- `POST /api/ingest/reset`（通知/処理済みリセット）

### 2DLidar地図(PNG)の見やすさ調整（任意）

`/api/ingest/map_png` にアップロードされた地図画像は、デフォルトで「線画っぽく見やすくする前処理」をかけてから `static/map.png` に保存します（Pillowが無い環境では自動的に無加工になります）。

環境変数（任意）:
- `MAP_PREPROCESS=1/0`（前処理の有効/無効）
- `MAP_OCC_THRESHOLD=0..255`（占有(黒)判定の閾値。小さいほど“黒が減る”）
- `MAP_FREE_THRESHOLD=0..255`（自由(白)判定の閾値）
- `MAP_MEDIAN_SIZE=1..9`（ノイズ低減。奇数推奨、例:3）
- `MAP_OPEN_PX=0..4`（小さいゴミを落とす強さ）
- `MAP_CLOSE_PX=0..6`（壁の切れ目を繋ぐ強さ）
- `MAP_EDGE=1/0`（輪郭線のみ描く）
- `MAP_EDGE_THICKEN_PX=0..6`（輪郭線を太くする）
- `MAP_KEEP_RAW=1/0`（`static/map.png.raw.png` にraw退避）
