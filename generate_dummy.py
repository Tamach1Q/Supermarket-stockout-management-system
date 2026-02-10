import os
import time
import csv
import math

# Pillowで画像生成
try:
    from PIL import Image, ImageDraw # type: ignore
except Exception:
    print("Pillowが必要です。pip install Pillowを実行してください")
    raise SystemExit

# 2DLidar/SLAM地図と同じ見やすさ前処理（Pillowが無い環境ではgenerate_dummy自体が動かないので基本は有効）
try:
    from map_preprocess import MapPreprocessConfig, load_config_from_env, preprocess_map_png  # type: ignore
except Exception:
    preprocess_map_png = None  # type: ignore

# フォルダ作成
os.makedirs("store_data/images", exist_ok=True)
os.makedirs("static", exist_ok=True)

# === 設定：線画フロアプラン風スタイル ===
WIDTH, HEIGHT = 900, 650

# カラーパレット（2枚目のスクショ参考）
BG_COLOR = (255, 255, 255)       # 背景：白
LINE_COLOR = (0, 0, 0)           # 線：黒
SHELF_BG = (255, 255, 255)       # 棚の中：白
WALL_WIDTH = 3                   # 壁の線の太さ
SHELF_WIDTH = 2                  # 棚の線の太さ

def create_floor_plan_map():
    img = Image.new("RGB", (WIDTH, HEIGHT), BG_COLOR)
    draw = ImageDraw.Draw(img)

    # --- 0. 背景グリッド（エリア矩形を書きやすくするため） ---
    # 生成ダミー専用。薄いグリッドなので棚/壁の線が主役になる。
    grid_spacing = 25
    major_every = 5
    minor = (235, 235, 235)
    major = (220, 220, 220)
    for x in range(0, WIDTH + 1, grid_spacing):
        color = major if (x // grid_spacing) % major_every == 0 else minor
        draw.line([(x, 0), (x, HEIGHT)], fill=color, width=1)
    for y in range(0, HEIGHT + 1, grid_spacing):
        color = major if (y // grid_spacing) % major_every == 0 else minor
        draw.line([(0, y), (WIDTH, y)], fill=color, width=1)

    # --- 1. 外壁を描く ---
    # 画面縁から少し余白を取って枠線を描く
    margin = 20
    draw.rectangle(
        [margin, margin, WIDTH - margin, HEIGHT - margin],
        outline=LINE_COLOR, width=WALL_WIDTH
    )

    # --- 2. 什器（棚）を描画する関数 ---
    def draw_shelf_rect(x, y, w, h):
        draw.rectangle(
            [x, y, x + w, y + h],
            fill=SHELF_BG, outline=LINE_COLOR, width=SHELF_WIDTH
        )

    # --- レイアウト配置（2枚目のスクショを模倣） ---

    # A. 上部の壁面棚 (Meat, Poultry...)
    # x: 左の余白〜右の余白, y: 上の余白から少し下
    draw_shelf_rect(150, margin + 20, 600, 50)

    # B. 左側の壁面棚 (Milk, Yogurt...)
    # 縦長
    draw_shelf_rect(margin + 20, 150, 50, 350)

    # C. 中央のゴンドラ棚列 (Aisle shelves)
    # 縦長の棚を等間隔に並べる
    shelf_w = 40
    shelf_h = 350
    start_x = 150
    gap_x = 30  # 通路幅
    
    # 7列ほど配置
    for i in range(7):
        sx = start_x + i * (shelf_w + gap_x)
        sy = 150
        draw_shelf_rect(sx, sy, shelf_w, shelf_h)

    # D. 右側の広いエリア (Fresh Produce)
    # 中央棚の右隣に大きな矩形
    produce_x = start_x + 7 * (shelf_w + gap_x) + 20
    produce_w = 120
    produce_h = 350
    draw_shelf_rect(produce_x, 150, produce_w, produce_h)

    # E. 下部のレジエリア (Checkout)
    # 縦長の小さい矩形を並べる
    # 重ならないように Y座標を 550付近に設定
    checkout_y = 550
    checkout_w = 30
    checkout_h = 60
    checkout_start_x = 300
    
    for i in range(4):
        cx = checkout_start_x + i * 80
        draw_shelf_rect(cx, checkout_y, checkout_w, checkout_h)

    # F. 入口 (Entrance) - 右下にドア記号を描く
    door_x = WIDTH - margin
    door_y = HEIGHT - margin - 80
    door_size = 60
    
    # 壁を白で上書きして「開口部」を作る
    draw.line([(WIDTH - margin, door_y), (WIDTH - margin, door_y + door_size)], fill=BG_COLOR, width=WALL_WIDTH)
    
    # ドアの軌跡（扇形）を描くと図面っぽくなる
    # arcのbboxは(left, top, right, bottom)
    draw.arc(
        [door_x - door_size, door_y, door_x + door_size, door_y + door_size*2],
        start=180, end=270, fill=LINE_COLOR, width=1
    )
    # ドアパネル（斜めの線）
    draw.line([(door_x, door_y + door_size), (door_x - door_size, door_y + door_size)], fill=LINE_COLOR, width=2)

    # 保存
    out_path = "static/map.png"
    img.save(out_path)

    # ingest_map_png と同じ前処理を適用（MAP_PREPROCESS=0 で無効化可能）
    preprocessed = False
    if preprocess_map_png is not None:
        try:
            # generate_dummy は元が線画なので、ノイズ除去(open/close)を強くかけると細い棚線が消えることがある。
            # 見やすさ（線画化）だけ維持しつつ、棚線は残す安全側プリセットにする。
            base = load_config_from_env()
            safe_cfg = MapPreprocessConfig(
                enabled=base.enabled,
                occ_threshold=base.occ_threshold,
                free_threshold=base.free_threshold,
                median_size=1,
                open_px=0,
                close_px=0,
                edge=False,
                edge_thicken_px=base.edge_thicken_px,
                keep_raw=base.keep_raw,
            )
            preprocessed = bool(preprocess_map_png(out_path, out_path, config=safe_cfg))
        except Exception:
            preprocessed = False

    if preprocessed:
        print("✅ 線画スタイルのフロアマップを生成＆前処理しました: static/map.png")
    else:
        print("✅ 線画スタイルのフロアマップを生成しました: static/map.png")

def create_dummy_data():
    now = time.time()
    csv_data = []
    
    # レイアウト変更に合わせて欠品位置座標を更新
    events = [
        # (時刻, x, y, 画像ファイル名)
        (now - 20, 240, 300, "defect_aisle2.jpg"),    # 2列目の通路
        (now - 10, 520, 300, "defect_aisle6.jpg"),    # 6列目の通路
        (now - 5,  750, 300, "defect_produce.jpg"),   # 青果エリア
        (now - 2,  400, 580, "defect_checkout.jpg"),  # レジ付近
    ]

    print("✅ テストデータ生成中...")
    for t, x, y, img_name in events:
        csv_data.append([t, x, y])
        # ダミー画像生成（ノイズっぽい画像にしておく）
        dummy = Image.new("RGB", (100, 100), (200, 200, 200))
        d_draw = ImageDraw.Draw(dummy)
        d_draw.rectangle([20,20,80,80], fill=(50,50,50))
        dummy.save(f"store_data/images/{img_name}")

    with open("store_data/tracking.csv", "w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerows(csv_data)

if __name__ == "__main__":
    create_floor_plan_map()
    create_dummy_data()
    print("✅ 完了！")
