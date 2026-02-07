import os
import cv2
import numpy as np
import pandas as pd
import time

# フォルダ作成
os.makedirs("store_data/images", exist_ok=True)
os.makedirs("static", exist_ok=True)

# 1. ダミーの地図画像を作る (static/map.png)
map_img = np.ones((400, 600, 3), dtype=np.uint8) * 240 # グレー背景
cv2.rectangle(map_img, (50, 50), (150, 250), (200, 200, 200), -1) # 棚A
cv2.rectangle(map_img, (250, 50), (350, 250), (200, 200, 200), -1) # 棚B
cv2.putText(map_img, "Shelf A", (60, 150), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0,0,0), 2)
cv2.imwrite("static/map.png", map_img)
print("✅ 地図生成: static/map.png")

# 2. ダミーのログと画像を作る
now = time.time()
csv_data = []

# シナリオ: 3箇所で欠品発生
events = [
    (now - 10, 100, 100, "defect_1.jpg"), # 棚Aの中
    (now - 5,  300, 100, "defect_2.jpg"), # 棚Bの中
    (now - 1,  500, 300, "defect_3.jpg"), # エリア外
]

print("✅ テストデータ生成中...")
for t, x, y, img_name in events:
    # ログ追記
    csv_data.append([t, x, y])
    # 画像生成
    dummy_img = np.zeros((100, 100, 3), dtype=np.uint8)
    cv2.imwrite(f"store_data/images/defect_{t}.jpg", dummy_img)

# CSV保存
df = pd.DataFrame(csv_data, columns=['time', 'x', 'y'])
df.to_csv("store_data/tracking.csv", header=False, index=False)
print("✅ 完了！ app.py を実行してください。")