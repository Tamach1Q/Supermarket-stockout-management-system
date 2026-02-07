import os
import time
import csv

# Pillowで簡易画像生成（未インストールならメッセージを出して終了）
try:
    from PIL import Image, ImageDraw, ImageFont  # type: ignore
except Exception:
    Image = None  # type: ignore
    ImageDraw = None  # type: ignore
    ImageFont = None  # type: ignore

# フォルダ作成
os.makedirs("store_data/images", exist_ok=True)
os.makedirs("static", exist_ok=True)

if Image is None:
    raise SystemExit("Pillow が必要です: `pip install Pillow`")

# 1. ダミーの地図画像を作る (static/map.png)
img = Image.new("RGB", (600, 400), (240, 240, 240))  # グレー背景
draw = ImageDraw.Draw(img)
draw.rectangle([50, 50, 150, 250], fill=(200, 200, 200))   # 棚A
draw.rectangle([250, 50, 350, 250], fill=(200, 200, 200))  # 棚B
font = None
try:
    font = ImageFont.load_default()
except Exception:
    font = None
draw.text((60, 150), "Shelf A", fill=(0, 0, 0), font=font)
draw.text((260, 150), "Shelf B", fill=(0, 0, 0), font=font)
img.save("static/map.png")
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
    dummy = Image.new("RGB", (100, 100), (0, 0, 0))
    dummy.save(f"store_data/images/defect_{t}.jpg")

# CSV保存
with open("store_data/tracking.csv", "w", encoding="utf-8", newline="") as f:
    writer = csv.writer(f)
    writer.writerows(csv_data)
print("✅ 完了！ app.py を実行してください。")
