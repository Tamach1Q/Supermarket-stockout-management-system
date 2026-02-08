import os
import time
import csv

# Pillowで画像生成
try:
    from PIL import Image, ImageDraw, ImageFont # type: ignore
except Exception:
    print("Pillowが必要です。pip install Pillowを実行してください")
    raise SystemExit

# フォルダ作成
os.makedirs("store_data/images", exist_ok=True)
os.makedirs("static", exist_ok=True)

# --- 設定：UIに合わせたモダンなカラーパレット ---
BG_COLOR = (248, 250, 252)       # 背景色 (Slate-50)
SHELF_FILL = (255, 255, 255)     # 棚の塗り (White)
SHELF_OUTLINE = (203, 213, 225)  # 棚の枠線 (Slate-300)
TEXT_COLOR = (71, 85, 105)       # 文字色 (Slate-600)
ACCENT_COLOR = (59, 130, 246)    # アクセント (Blue-500)

WIDTH, HEIGHT = 800, 500         # 解像度を少しアップ

def create_stylish_map():
    # 1. ベース作成
    img = Image.new("RGB", (WIDTH, HEIGHT), BG_COLOR)
    draw = ImageDraw.Draw(img)

    # --- グリッド線を描く（図面っぽさを出す） ---
    for x in range(0, WIDTH, 50):
        draw.line([(x, 0), (x, HEIGHT)], fill=(226, 232, 240), width=1)
    for y in range(0, HEIGHT, 50):
        draw.line([(0, y), (WIDTH, y)], fill=(226, 232, 240), width=1)

    # --- フォント設定 ---
    # OS標準のきれいなフォントを探す（なければデフォルト）
    font = None
    font_size = 24
    possible_fonts = [
        "arial.ttf", "Arial.ttf",              # Windows/Mac
        "NotoSansCJK-Regular.ttc",             # Linux/Google
        "/System/Library/Fonts/Helvetica.ttc", # Mac
        "C:\\Windows\\Fonts\\arial.ttf"        # Windows absolute
    ]
    
    for f in possible_fonts:
        try:
            font = ImageFont.truetype(f, font_size)
            print(f"✅ フォントロード: {f}")
            break
        except:
            continue
    
    if font is None:
        # フォントが見つからない場合はデフォルト（小さいので少し残念ですが）
        print("⚠️ 標準フォントを使用します")
        font = ImageFont.load_default()

    # --- 棚を描画する関数 ---
    def draw_shelf(x, y, w, h, label):
        # 影（フラットデザイン風のオフセット）
        draw.rectangle([x+4, y+4, x+w+4, y+h+4], fill=(226, 232, 240))
        # 本体
        draw.rectangle([x, y, x+w, y+h], fill=SHELF_FILL, outline=SHELF_OUTLINE, width=2)
        # ラベル配置（中央寄せ計算）
        bbox = draw.textbbox((0, 0), label, font=font)
        text_w = bbox[2] - bbox[0]
        text_h = bbox[3] - bbox[1]
        
        # 文字の背景に少し装飾
        cx, cy = x + w//2, y + h//2
        
        draw.text((cx - text_w//2, cy - text_h//2), label, fill=TEXT_COLOR, font=font)

    # 棚の配置
    draw_shelf(100, 80, 150, 300, "Drink Area")
    draw_shelf(350, 80, 150, 300, "Snack Area")
    draw_shelf(600, 80, 100, 120, "Register")

    # 入口などの表記
    draw.text((20, HEIGHT - 40), "Entrance ➤", fill=ACCENT_COLOR, font=font)

    # 保存
    img.save("static/map.png")
    print("✅ 地図生成: static/map.png (スタイリッシュ版)")

def create_dummy_data():
    now = time.time()
    csv_data = []
    
    # マップの座標系が変わったので、欠品位置も少し調整
    events = [
        (now - 10, 175, 200, "defect_1.jpg"), # Drink Areaの中
        (now - 5,  425, 200, "defect_2.jpg"), # Snack Areaの中
        (now - 1,  700, 400, "defect_3.jpg"), # 通路
    ]

    print("✅ テストデータ生成中...")
    for t, x, y, img_name in events:
        csv_data.append([t, x, y])
        dummy = Image.new("RGB", (100, 100), (30, 30, 30)) # 画像も少し黒っぽく
        dummy.save(f"store_data/images/defect_{t}.jpg")

    with open("store_data/tracking.csv", "w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerows(csv_data)

if __name__ == "__main__":
    create_stylish_map()
    create_dummy_data()
    print("✅ 完了！")