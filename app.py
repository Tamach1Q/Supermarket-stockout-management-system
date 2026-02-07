import os
import json
import time
import pandas as pd
import threading
from flask import Flask, render_template, request, jsonify

app = Flask(__name__)

# --- 設定 ---
DATA_DIR = "./store_data"
IMG_DIR = os.path.join(DATA_DIR, "images")
LOG_FILE = os.path.join(DATA_DIR, "tracking.csv")
AREAS_FILE = "areas.json" # エリア設定の保存先

# 監視状態
notifications = [] # 画面に表示する通知リスト
processed_files = set()

# --- 監視ロジック (別スレッドで動かす) ---
def monitoring_task():
    """1秒ごとに新しい画像がないかチェックする"""
    global notifications
    print("👀 監視システム起動中...")
    
    while True:
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

                # 3. CSVから座標を探す
                x, y = get_location_from_log(photo_time)
                
                if x is not None:
                    # 4. エリア判定
                    area_name = check_area(x, y)
                    
                    # 5. 通知作成
                    msg = {
                        "time": time.strftime('%H:%M:%S', time.localtime(photo_time)),
                        "area": area_name,
                        "coords": f"({x:.1f}, {y:.1f})",
                        "img": filename
                    }
                    notifications.insert(0, msg) # 最新を上に
                    print(f"🔔 通知: {area_name} で欠品！")
                
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
    """座標がどのエリアに入っているか"""
    if not os.path.exists(AREAS_FILE): return "未設定エリア"
    
    with open(AREAS_FILE, 'r') as f:
        areas = json.load(f)
    
    for area in areas:
        # ここでは簡易的に「地図上のピクセル座標」として比較しています
        # ※実際はここでロボット座標(m)→ピクセル変換の計算が入ります
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