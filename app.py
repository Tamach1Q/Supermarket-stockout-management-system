import os
import json
import time
import pandas as pd
import threading
import ast
from typing import Optional, Tuple
from flask import Flask, render_template, request, jsonify

app = Flask(__name__)

# --- 設定 ---
DATA_DIR = "./store_data"
IMG_DIR = os.path.join(DATA_DIR, "images")
LOG_FILE = os.path.join(DATA_DIR, "tracking.csv")
MAP_YAML_FILE = os.path.join(DATA_DIR, "map.yaml") # 地図の設定ファイル
MAP_PNG_FILE = os.path.join("static", "map.png")   # Web表示用の地図画像
AREAS_FILE = "areas.json" # エリア設定の保存先

# 監視状態
notifications = [] # 画面に表示する通知リスト
processed_files = set()

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
    print("👀 監視システム起動中...")
    
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
                if filepath in processed_files: continue

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
                    notifications.insert(0, msg) # 最新を上に
                    print(f"🔔 通知: {area_name} で欠品！ (px: {int(pixel_x)}, {int(pixel_y)})")
                
                processed_files.add(filepath)
            
            time.sleep(1)
        except Exception as e:
            print(f"エラー: {e}")
            time.sleep(1)

def get_location_from_log(target_time):
    """ログファイルから時刻に近い座標を返す"""
    if not os.path.exists(LOG_FILE): return None, None
    try:
        df = pd.read_csv(LOG_FILE, names=['time', 'x', 'y'])
        idx = (df['time'] - target_time).abs().idxmin()
        row = df.loc[idx]
        if abs(row['time'] - target_time) > 5.0: return None, None # 5秒以上ズレたら無視
        return row['x'], row['y']
    except:
        return None, None

def check_area(x, y):
    """座標(ピクセル)がどのエリアに入っているか"""
    if not os.path.exists(AREAS_FILE): return "未設定エリア"
    
    with open(AREAS_FILE, 'r') as f:
        areas = json.load(f)
    
    for area in areas:
        # エリア定義(JSON)もピクセル座標なので、そのまま比較
        if (area['x'] <= x <= area['x'] + area['w'] and 
            area['y'] <= y <= area['y'] + area['h']):
            return area['name']
    
    return "通路・不明"

# --- Webサーバーのルート設定 ---
@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/save_areas', methods=['POST'])
def save_areas():
    """地図で描いたエリアを保存"""
    data = request.json
    with open(AREAS_FILE, 'w') as f:
        json.dump(data, f, indent=2)
    return jsonify({"status": "ok"})

@app.route('/api/load_areas')
def load_areas():
    """保存されたエリアを読み込み"""
    if os.path.exists(AREAS_FILE):
        with open(AREAS_FILE, 'r') as f:
            return jsonify(json.load(f))
    return jsonify([])

@app.route('/api/notifications')
def get_notifications():
    """フロントエンドに通知を送る"""
    return jsonify(notifications)

if __name__ == '__main__':
    # 監視スレッドを開始
    t = threading.Thread(target=monitoring_task, daemon=True)
    t.start()
    
    # Webサーバー起動
    app.run(debug=True, port=5000)
