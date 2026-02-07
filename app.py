import os
import json
import time
import threading
import ast
import csv
from pathlib import Path
from typing import Optional, Tuple
from flask import Flask, render_template, request, jsonify, send_from_directory, abort

app = Flask(__name__)

# --- 設定 ---
DATA_DIR = os.environ.get("DATA_DIR", "./store_data")
IMG_DIR = os.path.join(DATA_DIR, "images")
LOG_FILE = os.path.join(DATA_DIR, "tracking.csv")
MAP_YAML_FILE = os.path.join(DATA_DIR, "map.yaml") # 地図の設定ファイル
MAP_PNG_FILE = os.environ.get("MAP_PNG_FILE", os.path.join("static", "map.png"))   # Web表示用の地図画像
AREAS_FILE = os.environ.get("AREAS_FILE", os.path.join(DATA_DIR, "areas.json")) # エリア設定の保存先

# ディレクトリ作成（Render等の初回起動でも落ちないように）
os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(IMG_DIR, exist_ok=True)
static_dir = os.path.dirname(MAP_PNG_FILE) or "static"
os.makedirs(static_dir, exist_ok=True)

# 監視状態
notifications = [] # 画面に表示する通知リスト
processed_files = set()
notifications_lock = threading.Lock()
processed_files_lock = threading.Lock()
MAX_NOTIFICATIONS = int(os.environ.get("MAX_NOTIFICATIONS", "200"))
MAX_PROCESSED_FILES = int(os.environ.get("MAX_PROCESSED_FILES", "5000"))

# Render等で外部から取り込み（ingest）するためのトークン
INGEST_TOKEN = os.environ.get("INGEST_TOKEN")
MAX_CONTENT_LENGTH_MB = int(os.environ.get("MAX_CONTENT_LENGTH_MB", "20"))
app.config["MAX_CONTENT_LENGTH"] = MAX_CONTENT_LENGTH_MB * 1024 * 1024

# Flask
# - デプロイ環境では環境変数PORTが提供されることが多い
# - `app.run()` は開発用途。Gunicorn等では `app:app` を参照して起動する
HOST = os.environ.get("HOST", "0.0.0.0")
PORT = int(os.environ.get("PORT", "5000"))
DEBUG = os.environ.get("FLASK_DEBUG", "0") == "1"

# --- ユーティリティ ---
def _parse_map_yaml_simple(path: str) -> Tuple[Optional[float], Optional[list]]:
    """
    map.yaml から必要最小限の値だけ抜き出す簡易パーサー。
    - 依存追加なしで動かすため PyYAML は使わない
    TODO(後で修正): YAMLが複雑化するなら PyYAML に切り替え
    """
    resolution = None
    origin = None

    try:
        with open(path, "r", encoding="utf-8") as f:
            for raw in f:
                line = raw.strip()
                if not line or line.startswith("#"):
                    continue
                if line.startswith("resolution:"):
                    value = line.split(":", 1)[1].strip()
                    if "#" in value:
                        value = value.split("#", 1)[0].strip()
                    try:
                        resolution = float(value)
                    except Exception:
                        pass
                elif line.startswith("origin:"):
                    value = line.split(":", 1)[1].strip()
                    if "#" in value:
                        value = value.split("#", 1)[0].strip()
                    try:
                        parsed = ast.literal_eval(value)
                        if isinstance(parsed, (list, tuple)) and len(parsed) >= 2:
                            origin = list(parsed)
                    except Exception:
                        pass
    except Exception:
        return None, None

    return resolution, origin

def _get_png_size(path: str) -> Tuple[int, int]:
    """PNGの幅/高さを依存なしで取得（失敗時は(0,0)）"""
    try:
        with open(path, "rb") as f:
            header = f.read(24)
        if len(header) < 24:
            return 0, 0
        # PNG signature
        if header[:8] != b"\x89PNG\r\n\x1a\n":
            return 0, 0
        # IHDR chunk data begins at offset 16: width(4) height(4)
        width = int.from_bytes(header[16:20], "big")
        height = int.from_bytes(header[20:24], "big")
        return width, height
    except Exception:
        return 0, 0

# --- 座標変換クラス ---
class MapConverter:
    def __init__(self):
        # TODO(ダミー): map.yaml がまだ無い環境でも動くように仮値を入れておく
        # 後でJetson側の地図が用意できたら map.yaml を回収してこの値が自動反映されます
        self.resolution = 0.05  # 1px=5cm想定の仮値
        self.origin = [0.0, 0.0, 0.0]  # [x, y, theta] の仮値

        self.width = 0
        self.height = 0

        self._yaml_mtime: Optional[float] = None
        self._png_mtime: Optional[float] = None
        self.reload_if_needed(force=True)

    def reload_if_needed(self, force: bool = False) -> None:
        """map.yaml / map.png が更新されていたら読み直す（毎秒呼んでも軽いように）"""
        yaml_mtime = os.path.getmtime(MAP_YAML_FILE) if os.path.exists(MAP_YAML_FILE) else None
        png_mtime = os.path.getmtime(MAP_PNG_FILE) if os.path.exists(MAP_PNG_FILE) else None

        if force or yaml_mtime != self._yaml_mtime:
            if yaml_mtime is None:
                self._yaml_mtime = None
            else:
                resolution, origin = _parse_map_yaml_simple(MAP_YAML_FILE)
                if resolution is not None:
                    self.resolution = resolution
                if origin is not None:
                    # thetaは使っていないが保存しておく
                    if len(origin) == 2:
                        origin = [origin[0], origin[1], 0.0]
                    self.origin = origin[:3]
                self._yaml_mtime = yaml_mtime

        if force or png_mtime != self._png_mtime:
            if png_mtime is None:
                self._png_mtime = None
            else:
                w, h = _get_png_size(MAP_PNG_FILE)
                if w > 0 and h > 0:
                    self.width, self.height = w, h
                self._png_mtime = png_mtime

    def world_to_pixel(self, world_x, world_y):
        """
        ロボット座標(m) -> 画像ピクセル(px) 変換
        式: pixel = (world - origin) / resolution
        """
        # 1. 解像度で割る
        px = (world_x - float(self.origin[0])) / float(self.resolution)
        py = (world_y - float(self.origin[1])) / float(self.resolution)
        
        # 2. Y軸を反転させる (画像は左上が0,0、地図は左下が0,0のため)
        if self.height > 0:
            py = self.height - py
            
        return px, py

# コンバーターのインスタンス作成
converter = MapConverter()

# --- 監視ロジック (別スレッドで動かす) ---
def monitoring_task():
    """1秒ごとに新しい画像がないかチェックする"""
    global notifications
    print("👀 監視システム起動中...", flush=True)
    
    while True:
        # 地図設定を再読み込み（SLAMで地図が更新される可能性があるため）
        converter.reload_if_needed()

        try:
            # 1. 画像フォルダを見る
            if not os.path.exists(IMG_DIR):
                time.sleep(1)
                continue

            jpg_files = [f for f in os.listdir(IMG_DIR) if f.endswith(".jpg")]
            
            for filename in jpg_files:
                filepath = os.path.join(IMG_DIR, filename)
                with processed_files_lock:
                    if filepath in processed_files:
                        continue

                # 2. ファイル名から時刻取得 (defect_1707...jpg)
                try:
                    time_str = filename.replace("defect_", "").replace(".jpg", "")
                    photo_time = float(time_str)
                except:
                    continue

                # 3. CSVからロボットの座標(メートル)を探す
                world_x, world_y = get_location_from_log(photo_time)
                
                if world_x is not None:
                    # ★ 4. メートルをピクセルに変換！
                    pixel_x, pixel_y = converter.world_to_pixel(world_x, world_y)

                    # 5. エリア判定 (ピクセル座標で判定)
                    area_name = check_area(pixel_x, pixel_y)

                    # 6. 通知作成
                    msg = {
                        "time": time.strftime('%H:%M:%S', time.localtime(photo_time)),
                        "area": area_name,
                        "coords": f"({world_x:.2f}m, {world_y:.2f}m)", # 表示はメートルで
                        "img": filename
                    }
                    with notifications_lock:
                        notifications.insert(0, msg) # 最新を上に
                        if len(notifications) > MAX_NOTIFICATIONS:
                            del notifications[MAX_NOTIFICATIONS:]
                    print(f"🔔 通知: {area_name} で欠品！ (px: {int(pixel_x)}, {int(pixel_y)})", flush=True)
                
                with processed_files_lock:
                    processed_files.add(filepath)
                    if len(processed_files) > MAX_PROCESSED_FILES:
                        processed_files.clear()
            
            time.sleep(1)
        except Exception as e:
            print(f"エラー: {e}", flush=True)
            time.sleep(1)

def get_location_from_log(target_time):
    """ログファイルから時刻に近い座標を返す"""
    if not os.path.exists(LOG_FILE): return None, None
    try:
        best_diff = None
        best_x = None
        best_y = None

        with open(LOG_FILE, "r", encoding="utf-8", newline="") as f:
            reader = csv.reader(f)
            for row in reader:
                if len(row) < 3:
                    continue
                try:
                    t = float(row[0])
                    x = float(row[1])
                    y = float(row[2])
                except Exception:
                    continue

                diff = abs(t - target_time)
                if best_diff is None or diff < best_diff:
                    best_diff = diff
                    best_x = x
                    best_y = y

        if best_diff is None or best_diff > 5.0:
            return None, None  # 5秒以上ズレたら無視
        return best_x, best_y
    except:
        return None, None

def check_area(x, y):
    """座標(ピクセル)がどのエリアに入っているか"""
    if not os.path.exists(AREAS_FILE): return "未設定エリア"
    try:
        with open(AREAS_FILE, 'r', encoding="utf-8") as f:
            areas = json.load(f)
        if not isinstance(areas, list):
            return "未設定エリア"
    except Exception:
        return "未設定エリア"
    
    for area in areas:
        # エリア定義(JSON)もピクセル座標なので、そのまま比較
        try:
            if (area['x'] <= x <= area['x'] + area['w'] and 
                area['y'] <= y <= area['y'] + area['h']):
                return area.get('name', "未設定エリア")
        except Exception:
            continue
    
    return "通路・不明"

# --- Webサーバーのルート設定 ---
@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/save_areas', methods=['POST'])
def save_areas():
    """地図で描いたエリアを保存"""
    data = request.json
    if not isinstance(data, list):
        return jsonify({"status": "error", "message": "invalid payload"}), 400
    Path(os.path.dirname(AREAS_FILE) or ".").mkdir(parents=True, exist_ok=True)
    tmp_path = f"{AREAS_FILE}.tmp"
    with open(tmp_path, 'w', encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    os.replace(tmp_path, AREAS_FILE)
    return jsonify({"status": "ok"})

@app.route('/api/load_areas')
def load_areas():
    """保存されたエリアを読み込み"""
    if os.path.exists(AREAS_FILE):
        try:
            with open(AREAS_FILE, 'r', encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, list):
                return jsonify(data)
        except Exception:
            pass
    return jsonify([])

@app.route('/api/notifications')
def get_notifications():
    """フロントエンドに通知を送る"""
    with notifications_lock:
        snapshot = list(notifications)
    return jsonify(snapshot)

@app.route('/images/<path:filename>')
def get_image(filename: str):
    """欠品画像を配信（store_data/images 配下）"""
    if not filename.lower().endswith(".jpg"):
        return abort(404)
    return send_from_directory(IMG_DIR, filename)

@app.route('/healthz')
def healthz():
    return jsonify({"status": "ok"})

def _require_ingest_token() -> Optional[tuple]:
    """ingest API用の簡易認証（未設定なら503）"""
    if not INGEST_TOKEN:
        return jsonify({"status": "error", "message": "INGEST_TOKEN not set"}), 503

    json_body = request.get_json(silent=True) if request.is_json else None
    token = request.headers.get("X-Ingest-Token") or request.form.get("token") or (json_body.get("token") if isinstance(json_body, dict) else None)
    if token != INGEST_TOKEN:
        return jsonify({"status": "error", "message": "unauthorized"}), 401
    return None

def _safe_filename(name: str) -> str:
    # パス区切りを落として最低限の安全性を確保
    base = os.path.basename(name)
    return base.replace("\x00", "")

@app.route('/api/ingest/tracking', methods=['POST'])
def ingest_tracking():
    auth = _require_ingest_token()
    if auth:
        return auth
    f = request.files.get("file")
    if f is None:
        return jsonify({"status": "error", "message": "file required"}), 400

    tmp_path = f"{LOG_FILE}.tmp"
    Path(os.path.dirname(LOG_FILE) or ".").mkdir(parents=True, exist_ok=True)
    f.save(tmp_path)
    os.replace(tmp_path, LOG_FILE)
    return jsonify({"status": "ok"})

@app.route('/api/ingest/image', methods=['POST'])
def ingest_image():
    auth = _require_ingest_token()
    if auth:
        return auth
    f = request.files.get("file")
    if f is None:
        return jsonify({"status": "error", "message": "file required"}), 400

    filename = _safe_filename(f.filename or "")
    if not filename.lower().endswith(".jpg"):
        return jsonify({"status": "error", "message": "only .jpg allowed"}), 400

    Path(IMG_DIR).mkdir(parents=True, exist_ok=True)
    tmp_path = os.path.join(IMG_DIR, f"{filename}.tmp")
    final_path = os.path.join(IMG_DIR, filename)
    f.save(tmp_path)
    os.replace(tmp_path, final_path)
    return jsonify({"status": "ok", "filename": filename})

@app.route('/api/ingest/map_png', methods=['POST'])
def ingest_map_png():
    auth = _require_ingest_token()
    if auth:
        return auth
    f = request.files.get("file")
    if f is None:
        return jsonify({"status": "error", "message": "file required"}), 400
    Path(os.path.dirname(MAP_PNG_FILE) or ".").mkdir(parents=True, exist_ok=True)
    tmp_path = f"{MAP_PNG_FILE}.tmp"
    f.save(tmp_path)
    os.replace(tmp_path, MAP_PNG_FILE)
    # 次ループでサイズ反映させる
    converter.reload_if_needed(force=True)
    return jsonify({"status": "ok"})

@app.route('/api/ingest/map_yaml', methods=['POST'])
def ingest_map_yaml():
    auth = _require_ingest_token()
    if auth:
        return auth
    f = request.files.get("file")
    if f is None:
        return jsonify({"status": "error", "message": "file required"}), 400
    Path(os.path.dirname(MAP_YAML_FILE) or ".").mkdir(parents=True, exist_ok=True)
    tmp_path = f"{MAP_YAML_FILE}.tmp"
    f.save(tmp_path)
    os.replace(tmp_path, MAP_YAML_FILE)
    converter.reload_if_needed(force=True)
    return jsonify({"status": "ok"})

@app.route('/api/ingest/reset', methods=['POST'])
def ingest_reset():
    """デモ用：通知と処理済み状態をリセット"""
    auth = _require_ingest_token()
    if auth:
        return auth
    with notifications_lock:
        notifications.clear()
    with processed_files_lock:
        processed_files.clear()
    return jsonify({"status": "ok"})

_monitor_thread_started = False
_monitor_thread_lock = threading.Lock()

def start_monitoring_once() -> None:
    """WSGI(Gunicorn等)でも確実に監視スレッドを起動する"""
    global _monitor_thread_started
    with _monitor_thread_lock:
        if _monitor_thread_started:
            return
        if os.environ.get("DISABLE_MONITORING", "0") == "1":
            _monitor_thread_started = True
            return
        # Flaskのデバッグリローダは親/子の2プロセスを起動する。
        # 親プロセス側ではスレッドを起動しない（重複監視防止）。
        if DEBUG and os.environ.get("WERKZEUG_RUN_MAIN") != "true":
            return
        t = threading.Thread(target=monitoring_task, daemon=True)
        t.start()
        _monitor_thread_started = True

# 起動時に監視スレッドを開始（誰も見ていない間の通知も溜める）
start_monitoring_once()

if __name__ == '__main__':
    # Webサーバー起動（開発用途）
    # 監視は起動済み。リローダは二重起動の原因になるため無効化しておく
    app.run(debug=DEBUG, host=HOST, port=PORT, use_reloader=False)
