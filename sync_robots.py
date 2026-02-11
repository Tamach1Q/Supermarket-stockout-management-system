import paramiko
from scp import SCPClient
import os
import time
import datetime
import sys
from typing import Optional, Set
from urllib.parse import urljoin

# クラウド送信用のライブラリ
try:
    import requests  # type: ignore
except Exception:
    requests = None  # type: ignore

# Pillow はPGM→PNG変換で使用
try:
    from PIL import Image  # type: ignore
except Exception:
    Image = None  # type: ignore

# ================= 設定エリア =================
# ※ここを実際のロボットのIPアドレスに書き換えてください
ROBOT_CONFIG = {
    # 自動走行ロボット (Xavier)
    "xavier": {
        "host": "192.168.1.10",   # IPアドレス
        "user": "jetson",         # ユーザー名
        "pass": "jetson",         # パスワード
        "remote_csv": "/home/jetson/logs/tracking.csv", # ログファイルの場所
        "remote_map_yaml": "/home/jetson/maps/map.yaml",
        "remote_map_image_fallback": "/home/jetson/maps/map.pgm",
    },
    # Webカメラロボット (TX2)
    "tx2": {
        "host": "172.16.11.121",
        "user": "kauelu",
        "pass": "Kauelu203",
        "remote_img_dir": "/home/kauelu/images/"  # ← ここを修正
    }
}

# 保存先設定
LOCAL_DIR = "./store_data"
LOCAL_RAW_IMG_DIR = os.path.join(LOCAL_DIR, "raw_images") # 推論前の画像置き場
LOCAL_CSV = os.path.join(LOCAL_DIR, "tracking.csv")
STATIC_DIR = "./static"
LOCAL_MAP_YAML = os.path.join(LOCAL_DIR, "map.yaml")
LOCAL_MAP_IMAGE = os.path.join(LOCAL_DIR, "map_image")
STATIC_MAP_PNG = os.path.join(STATIC_DIR, "map.png")

# 更新間隔
MAP_SYNC_INTERVAL_SEC = 15

# クラウド設定（環境変数から読み込み）
REMOTE_APP_URL = os.environ.get("REMOTE_APP_URL")  # 例: https://xxxx.onrender.com
INGEST_TOKEN = os.environ.get("INGEST_TOKEN")

# フォルダ作成
os.makedirs(LOCAL_RAW_IMG_DIR, exist_ok=True)
os.makedirs(STATIC_DIR, exist_ok=True)
# ============================================

def create_client(host, user, password):
    """SSH接続クライアントを作成"""
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        client.connect(host, username=user, password=password, timeout=3.0)
        return client
    except Exception as e:
        print(f"⚠️ 接続エラー [{host}]: {e}")
        return None

def sync_time():
    """PCの時刻をロボットに強制同期させる"""
    now_str = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    print(f"🕒 時刻合わせを開始します... ({now_str})")
    
    for name, conf in ROBOT_CONFIG.items():
        client = create_client(conf["host"], conf["user"], conf["pass"])
        if client:
            try:
                cmd = f'sudo -S date -s "{now_str}"'
                stdin, stdout, stderr = client.exec_command(cmd)
                stdin.write(conf["pass"] + '\n')
                stdin.flush()
                err = stderr.read().decode()
                if err and "password" not in err:
                    print(f"  ❌ [{name}] 同期失敗: {err.strip()}")
                else:
                    print(f"  ✅ [{name}] 同期完了")
            except Exception as e:
                print(f"  ❌ [{name}] エラー: {e}")
            finally:
                client.close()

def download_csv():
    """XavierからCSVをダウンロード"""
    conf = ROBOT_CONFIG["xavier"]
    client = create_client(conf["host"], conf["user"], conf["pass"])
    if client:
        try:
            with SCPClient(client.get_transport()) as scp:
                scp.get(conf["remote_csv"], LOCAL_CSV)
        except Exception as e:
            pass 
        finally:
            client.close()

def download_images(downloaded_images: Set[str]):
    """TX2から全jpgをraw_imagesへダウンロード"""
    conf = ROBOT_CONFIG["tx2"]
    client = create_client(conf["host"], conf["user"], conf["pass"])
    if client:
        try:
            stdin, stdout, stderr = client.exec_command(f"ls {conf['remote_img_dir']}")
            files = stdout.read().decode().splitlines()
            
            with SCPClient(client.get_transport()) as scp:
                for file in files:
                    if not file.endswith(".jpg"): continue
                    if file in downloaded_images: continue

                    local_path = os.path.join(LOCAL_RAW_IMG_DIR, file)
                    if os.path.exists(local_path):
                        downloaded_images.add(file)
                        continue

                    remote_path = os.path.join(conf["remote_img_dir"], file)
                    scp.get(remote_path, local_path)
                    downloaded_images.add(file)
                    print(f"📸 新着画像GET(raw): {file}")
        except Exception:
            pass
        finally:
            client.close()

def _atomic_replace(tmp_path: str, final_path: str) -> None:
    os.replace(tmp_path, final_path)

def _scp_get_atomic(scp: SCPClient, remote_path: str, local_path: str) -> None:
    tmp_path = f"{local_path}.tmp"
    scp.get(remote_path, tmp_path)
    if not os.path.exists(tmp_path) or os.path.getsize(tmp_path) <= 0:
        raise RuntimeError(f"DL failed: {remote_path}")
    _atomic_replace(tmp_path, local_path)

def _parse_map_yaml_image(local_yaml_path: str) -> Optional[str]:
    try:
        with open(local_yaml_path, "r", encoding="utf-8") as f:
            for raw in f:
                line = raw.strip()
                if line.startswith("image:"):
                    value = line.split(":", 1)[1].strip()
                    if "#" in value: value = value.split("#", 1)[0].strip()
                    return value.strip("\"'") or None
    except Exception:
        return None
    return None

def _convert_to_static_png(local_image_path: str) -> bool:
    if Image is None: return False
    tmp_png = f"{STATIC_MAP_PNG}.tmp"
    try:
        with Image.open(local_image_path) as img:
            if img.mode not in ("RGB", "RGBA"):
                img = img.convert("RGB")
            img.save(tmp_png)
        _atomic_replace(tmp_png, STATIC_MAP_PNG)
        return True
    except Exception:
        return False

def download_map():
    """地図データのダウンロードと変換"""
    conf = ROBOT_CONFIG["xavier"]
    client = create_client(conf["host"], conf["user"], conf["pass"])
    if client:
        try:
            with SCPClient(client.get_transport()) as scp:
                _scp_get_atomic(scp, conf["remote_map_yaml"], LOCAL_MAP_YAML)
                
                image_from_yaml = _parse_map_yaml_image(LOCAL_MAP_YAML)
                if image_from_yaml:
                    if os.path.isabs(image_from_yaml):
                        remote_image = image_from_yaml
                    else:
                        remote_image = os.path.join(os.path.dirname(conf["remote_map_yaml"]), image_from_yaml)
                else:
                    remote_image = conf.get("remote_map_image_fallback")

                if remote_image:
                    _, ext = os.path.splitext(remote_image)
                    local_image_path = f"{LOCAL_MAP_IMAGE}{ext or '.pgm'}"
                    _scp_get_atomic(scp, remote_image, local_image_path)
                    _convert_to_static_png(local_image_path)
        except Exception as e:
            print(f"⚠️ 地図同期失敗: {e}")
        finally:
            client.close()

# --- クラウド送信ヘルパー (復活機能) ---
def _remote_enabled() -> bool:
    return bool(REMOTE_APP_URL and INGEST_TOKEN and requests)

def _remote_post_file(endpoint: str, path: str) -> bool:
    """指定したファイルをクラウドへアップロード"""
    if not _remote_enabled() or not os.path.exists(path):
        return False
    
    url = urljoin(REMOTE_APP_URL.rstrip("/") + "/", endpoint.lstrip("/"))
    headers = {"X-Ingest-Token": INGEST_TOKEN}
    
    try:
        with open(path, "rb") as f:
            files = {"file": (os.path.basename(path), f)}
            # タイムアウト短めで設定（メインループを止めないため）
            r = requests.post(url, headers=headers, files=files, timeout=5)
        return r.status_code < 300
    except Exception:
        return False

def main():
    print("=== 🤖 ロボットデータ完全同期システム (Relay Node) 🤖 ===")
    print(f"保存先: {LOCAL_DIR}")
    
    if _remote_enabled():
        print(f"🌐 クラウド連携: 有効 ({REMOTE_APP_URL})")
    else:
        print("⚠️ クラウド連携: 無効 (設定不足 または requestsなし)")

    sync_time()
    
    print("\n📡 監視・ダウンロード・クラウド同期を開始します...")
    
    last_map_sync = 0.0
    downloaded_images: Set[str] = set()
    
    # クラウド送信の重複防止用タイムスタンプ
    last_uploaded_csv_mtime: Optional[float] = None
    last_uploaded_map_yaml_mtime: Optional[float] = None
    last_uploaded_map_png_mtime: Optional[float] = None

    try:
        while True:
            # 1. ロボットからダウンロード
            download_csv()
            download_images(downloaded_images)
            
            now = time.time()
            if now - last_map_sync >= MAP_SYNC_INTERVAL_SEC:
                download_map()
                last_map_sync = now

            # 2. クラウドへアップロード (位置情報と地図のみ)
            # ※ 画像のアップロードは ai_worker.py が担当するためここでは行わない
            if _remote_enabled():
                # Tracking CSV (位置情報)
                if os.path.exists(LOCAL_CSV):
                    mtime = os.path.getmtime(LOCAL_CSV)
                    if last_uploaded_csv_mtime != mtime:
                        if _remote_post_file("api/ingest/tracking", LOCAL_CSV):
                            last_uploaded_csv_mtime = mtime
                            # print("☁️ 位置情報を送信しました")

                # Map YAML & PNG (地図更新時のみ)
                if os.path.exists(LOCAL_MAP_YAML):
                    mtime = os.path.getmtime(LOCAL_MAP_YAML)
                    if last_uploaded_map_yaml_mtime != mtime:
                        if _remote_post_file("api/ingest/map_yaml", LOCAL_MAP_YAML):
                            last_uploaded_map_yaml_mtime = mtime

                if os.path.exists(STATIC_MAP_PNG):
                    mtime = os.path.getmtime(STATIC_MAP_PNG)
                    if last_uploaded_map_png_mtime != mtime:
                        if _remote_post_file("api/ingest/map_png", STATIC_MAP_PNG):
                            last_uploaded_map_png_mtime = mtime
            
            time.sleep(1)
            
    except KeyboardInterrupt:
        print("\n🛑 停止しました")
        sys.exit(0)

if __name__ == "__main__":
    main()