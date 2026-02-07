import os
import json
import time
import pandas as pd
import threading
import yaml  # 設定ファイル読み込み用 (pip install PyYAML)
from flask import Flask, render_template, request, jsonify
from PIL import Image # 画像サイズ取得用

app = Flask(__name__)

# --- 設定 ---
DATA_DIR = "./store_data"
IMG_DIR = os.path.join(DATA_DIR, "images")
LOG_FILE = os.path.join(DATA_DIR, "tracking.csv")
MAP_YAML_FILE = os.path.join(DATA_DIR, "map.yaml") # 地図の設定ファイル
AREAS_FILE = "areas.json" # エリア設定の保存先

# 監視状態
notifications = [] # 画面に表示する通知リスト
processed_files = set()

# --- 座標変換クラス ---
class MapConverter:
    def __init__(self):
        self.resolution = 0.05  # デフォルト値 (1px = 5cm)
        self.origin = [0.0, 0.0, 0.0]
        self.height = 0
        self.load_yaml()

    def load_yaml(self):
        """map.yamlを読み込んで設定を更新"""
        if os.path.exists(MAP_YAML_FILE):
            try:
                with open(MAP_YAML_FILE, 'r') as f:
                    data = yaml.safe_load(f)
                    self.resolution = data['resolution']
                    self.origin = data['origin'] # [x, y, theta]
                    
                    # 画像の高さを取得（Y軸反転のため必要）
                    # static/map.png があればそのサイズを使う
                    if os.path.exists("static/map.png"):
                        with Image.open("static/map.png") as img:
                            self.width, self.height = img.size
            except Exception as e:
                print(f"YAML読み込みエラー: {e}")

    def world_to_pixel(self, world_x, world_y):
        """
        ロボット座標(m) -> 画像ピクセル(px) 変換
        式: pixel = (world - origin) / resolution
        """
        # 1. 解像度で割る
        px = (world_x - self.origin[0]) / self.resolution
        py = (world_y - self.origin[1]) / self.resolution
        
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
        # 定期的に地図設定を再読み込み（SLAMで地図が更新される可能性があるため）
        converter.load_yaml()

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