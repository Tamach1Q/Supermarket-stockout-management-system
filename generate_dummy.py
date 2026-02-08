import os
import time
import csv

# Pillowで画像生成
try:
    from PIL import Image, ImageDraw # type: ignore
except Exception:
    print("Pillowが必要です。pip install Pillowを実行してください")
    raise SystemExit

# フォルダ作成
os.makedirs("store_data/images", exist_ok=True)
os.makedirs("static", exist_ok=True)

# === 設定：LiDARスキャン風クリーンマップ ===
WIDTH, HEIGHT = 800, 600  # 少し広めの店舗

# カラーパレット
BG_COLOR = (255, 255, 255)       # 背景（通路・未検知領域）: 完全な白
OBSTACLE_COLOR = (44, 62, 80)    # 障害物（棚・壁）: 濃い紺グレー（視認性重視）
GRID_COLOR = (245, 245, 245)     # グリッド線: ごく薄いグレー

def create_realistic_map():
    img = Image.new("RGB", (WIDTH, HEIGHT), BG_COLOR)
    draw = ImageDraw.Draw(img)

    # --- 1. 薄いグリッドを描く（図面らしさ） ---
    grid_size = 50
    for x in range(0, WIDTH, grid_size):
        draw.line([(x, 0), (x, HEIGHT)], fill=GRID_COLOR, width=1)
    for y in range(0, HEIGHT, grid_size):
        draw.line([(0, y), (WIDTH, y)], fill=GRID_COLOR, width=1)

    # --- 障害物（棚・壁）を描画する関数（テキスト無し） ---
    def draw_obstacle(x, y, w, h):
        # シンプルな塗りつぶしでLiDAR検知エリアを表現
        draw.rectangle([x, y, x+w, y+h], fill=OBSTACLE_COLOR)

    # --- 2. 店舗レイアウトの構築 ---
    
    # 外壁（周囲を囲む）
    wall_thickness = 10
    draw_obstacle(0, 0, WIDTH, wall_thickness) # 上
    draw_obstacle(0, 0, wall_thickness, HEIGHT) # 左
    draw_obstacle(WIDTH-wall_thickness, 0, wall_thickness, HEIGHT) # 右
    # 下（入口部分は空ける）
    entrance_width = 200
    draw_obstacle(0, HEIGHT-wall_thickness, (WIDTH-entrance_width)//2, wall_thickness)
    draw_obstacle(WIDTH - (WIDTH-entrance_width)//2, HEIGHT-wall_thickness, (WIDTH-entrance_width)//2, wall_thickness)

    # 壁面棚（冷蔵ケースなど）
    side_shelf_depth = 60
    draw_obstacle(wall_thickness, wall_thickness, WIDTH - wall_thickness*2, side_shelf_depth) # 上側の壁面棚
    draw_obstacle(wall_thickness, wall_thickness + side_shelf_depth + 20, side_shelf_depth, HEIGHT * 0.6) # 左側の壁面棚

    # 中央のゴンドラ陳列棚（複数列配置）
    aisle_width = 70     # 通路幅
    shelf_width = 80     # 棚の幅
    shelf_height = 350   # 棚の長さ
    start_x = 180
    start_y = 120
    num_rows = 4         # 棚の列数

    for i in range(num_rows):
        x = start_x + i * (shelf_width + aisle_width)
        draw_obstacle(x, start_y, shelf_width, shelf_height)
        # 棚の端にエンドを表現（任意）
        # draw_obstacle(x, start_y - 20, shelf_width, 15)
        # draw_obstacle(x, start_y + shelf_height + 5, shelf_width, 15)

    # レジカウンターエリア（入口付近）
    register_x = WIDTH - 250
    register_y = HEIGHT - 150
    for i in range(3): # レジ3台
        draw_obstacle(register_x + i*70, register_y, 50, 80)
    
    # サービスカウンター/バックヤード壁の一部
    draw_obstacle(WIDTH - 150, HEIGHT - 250, 140, 20)

    # 保存
    img.save("static/map.png")
    print("✅ リアルなフロアマップを生成しました: static/map.png")

def create_dummy_data():
    # マップが変更されたので、ダミーの座標もそれらしい位置に調整します
    now = time.time()
    csv_data = []
    
    # 新しいレイアウトに合わせた欠品位置
    events = [
        (now - 20, 220, 250, "defect_shelf1.jpg"), # 1列目の棚
        (now - 10, 520, 300, "defect_shelf3.jpg"), # 3列目の棚
        (now - 5,  680, 500, "defect_register.jpg"), # レジ付近
        (now - 1,  50,  300, "defect_side.jpg"),     # 左側の壁面棚
    ]

    print("✅ テストデータ生成中...")
    for t, x, y, img_name in events:
        csv_data.append([t, x, y])
        # ダミー画像も少し色を変える
        dummy_color = (int(x%255), int(y%255), 150)
        dummy = Image.new("RGB", (100, 100), dummy_color)
        dummy.save(f"store_data/images/{img_name}")

    with open("store_data/tracking.csv", "w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerows(csv_data)

if __name__ == "__main__":
    create_realistic_map()
    create_dummy_data()
    print("✅ 完了！アプリをリロードして確認してください。")