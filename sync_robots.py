import paramiko
from scp import SCPClient
import os
import time
import datetime
import sys
from typing import Optional

# Pillow はPGM→PNG変換で使用（未インストールでも他の同期は動かす）
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
        
        # ★追加: SLAMが出力した地図ファイルの場所
        # TODO(後で修正): チームメイト実装が確定したら、実際の出力先に合わせて修正してください
        # - 基本は map.yaml をDLし、yaml内の image: で指定された画像（pgm/png）もDLします
        # - yamlのパースに失敗した場合のみ remote_map_image_fallback を使います
        "remote_map_yaml": "/home/jetson/maps/map.yaml",
        "remote_map_image_fallback": "/home/jetson/maps/map.pgm",
    },
    # Webカメラロボット (TX2)
    "tx2": {
        "host": "192.168.1.11",   # IPアドレス
        "user": "jetson",         # ユーザー名
        "pass": "jetson",         # パスワード
        "remote_img_dir": "/home/jetson/images/"       # 画像フォルダ
    }
}

# 保存先 (app.py が監視している場所と同じにする)
LOCAL_DIR = "./store_data"
LOCAL_IMG_DIR = os.path.join(LOCAL_DIR, "images")
LOCAL_CSV = os.path.join(LOCAL_DIR, "tracking.csv")
STATIC_DIR = "./static"  # Web表示用画像の保存先
LOCAL_MAP_YAML = os.path.join(LOCAL_DIR, "map.yaml")
LOCAL_MAP_IMAGE = os.path.join(LOCAL_DIR, "map_image")  # 拡張子はDL時に付ける
STATIC_MAP_PNG = os.path.join(STATIC_DIR, "map.png")

# 地図は頻繁に更新されない想定なので低頻度でOK（負荷軽減）
MAP_SYNC_INTERVAL_SEC = 15

# フォルダ作成
os.makedirs(LOCAL_IMG_DIR, exist_ok=True)
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
    """PCの時刻をロボットに強制同期させる (sudo使用)"""
    now_str = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    print(f"🕒 時刻合わせを開始します... ({now_str})")
    
    for name, conf in ROBOT_CONFIG.items():
        client = create_client(conf["host"], conf["user"], conf["pass"])
        if client:
            try:
                # sudo date -s "..." コマンドを実行
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
    """XavierからCSVをダウンロード（上書き）"""
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

def download_images():
    """TX2から新着画像のみダウンロード"""
    conf = ROBOT_CONFIG["tx2"]
    client = create_client(conf["host"], conf["user"], conf["pass"])
    
    if client:
        try:
            stdin, stdout, stderr = client.exec_command(f"ls {conf['remote_img_dir']}")
            files = stdout.read().decode().splitlines()
            
            with SCPClient(client.get_transport()) as scp:
                for file in files:
                    if file.endswith(".jpg") and file.startswith("defect_"):
                        local_path = os.path.join(LOCAL_IMG_DIR, file)
                        if not os.path.exists(local_path):
                            remote_path = os.path.join(conf['remote_img_dir'], file)
                            scp.get(remote_path, local_path)
                            print(f"📸 新着画像GET: {file}")
        except Exception as e:
            pass
        finally:
            client.close()

def _atomic_replace(tmp_path: str, final_path: str) -> None:
    """テンポラリ→本番へ原子的に差し替える"""
    os.replace(tmp_path, final_path)

def _scp_get_atomic(scp: SCPClient, remote_path: str, local_path: str) -> None:
    """SCPでDL→サイズ検証→原子的に配置"""
    tmp_path = f"{local_path}.tmp"
    scp.get(remote_path, tmp_path)
    if not os.path.exists(tmp_path) or os.path.getsize(tmp_path) <= 0:
        raise RuntimeError(f"download failed or empty: {remote_path}")
    _atomic_replace(tmp_path, local_path)

def _parse_map_yaml_image(local_yaml_path: str) -> Optional[str]:
    """
    map.yaml から image: をざっくり抜き出す（ダミー運用でも動く簡易パーサー）
    TODO(後で修正): YAML仕様に厳密にするなら PyYAML を使う
    """
    try:
        with open(local_yaml_path, "r", encoding="utf-8") as f:
            for raw in f:
                line = raw.strip()
                if not line or line.startswith("#"):
                    continue
                if line.startswith("image:"):
                    value = line.split(":", 1)[1].strip()
                    if "#" in value:
                        value = value.split("#", 1)[0].strip()
                    if (value.startswith('"') and value.endswith('"')) or (value.startswith("'") and value.endswith("'")):
                        value = value[1:-1]
                    return value or None
    except Exception:
        return None
    return None

def _convert_to_static_png(local_image_path: str) -> bool:
    """地図画像(pgm/png等)を static/map.png に変換して配置"""
    if Image is None:
        print("⚠️ Pillow 未導入のため、地図画像変換をスキップします（`pip install Pillow`）")
        return False

    tmp_png = f"{STATIC_MAP_PNG}.tmp"
    try:
        with Image.open(local_image_path) as img:
            # PGMはL(8bit)のことが多い。Web表示用にRGBへ。
            if img.mode not in ("RGB", "RGBA"):
                img = img.convert("RGB")
            img.save(tmp_png)
        if os.path.getsize(tmp_png) <= 0:
            raise RuntimeError("converted png is empty")
        _atomic_replace(tmp_png, STATIC_MAP_PNG)
        return True
    except Exception as e:
        try:
            if os.path.exists(tmp_png):
                os.remove(tmp_png)
        except Exception:
            pass
        print(f"⚠️ 地図画像の変換に失敗: {e}")
        return False

def download_map():
    """地図(yaml+画像)をDLし、PNGに変換して配置する"""
    conf = ROBOT_CONFIG["xavier"]
    client = create_client(conf["host"], conf["user"], conf["pass"])
    
    if client:
        try:
            with SCPClient(client.get_transport()) as scp:
                # 1) まず map.yaml をDL（原子的に配置）
                _scp_get_atomic(scp, conf["remote_map_yaml"], LOCAL_MAP_YAML)

                # 2) yaml内の image: を見て地図画像のリモートパスを決める
                image_from_yaml = _parse_map_yaml_image(LOCAL_MAP_YAML)
                if image_from_yaml:
                    if os.path.isabs(image_from_yaml):
                        remote_image = image_from_yaml
                    else:
                        remote_yaml_dir = os.path.dirname(conf["remote_map_yaml"])
                        remote_image = os.path.join(remote_yaml_dir, image_from_yaml)
                else:
                    # TODO(後で修正): Jetson側の地図出力が確定したら、fallbackの必要性を再検討
                    remote_image = conf.get("remote_map_image_fallback")

                if not remote_image:
                    return

                # 3) 画像もDL（拡張子を保持）
                _, ext = os.path.splitext(remote_image)
                local_image_path = f"{LOCAL_MAP_IMAGE}{ext or '.pgm'}"
                _scp_get_atomic(scp, remote_image, local_image_path)

                # 4) Web表示用に static/map.png を作成
                if _convert_to_static_png(local_image_path):
                    # print("🗺️ 地図更新完了") # 頻繁に出るとうるさい場合はコメントアウト
                    pass
        except Exception as e:
            # 地図がまだ無い/権限不足など。無視しつつ、原因が追える程度には出す。
            print(f"⚠️ 地図同期に失敗: {e}")
        finally:
            client.close()

def main():
    print("=== 🤖 ロボットデータ完全同期システム 🤖 ===")
    print(f"保存先: {LOCAL_DIR}")
    
    # 1. 最初に時刻合わせ
    sync_time()
    
    print("\n📡 監視とダウンロードを開始します (Ctrl+Cで停止)")
    last_map_sync = 0.0
    try:
        while True:
            download_csv()    # ログ回収
            download_images() # 画像回収
            # 地図は低頻度で回収（毎秒だと無駄が多い）
            now = time.time()
            if now - last_map_sync >= MAP_SYNC_INTERVAL_SEC:
                download_map()    # 地図回収 & 変換
                last_map_sync = now
            
            time.sleep(1)     # 1秒待機
            
    except KeyboardInterrupt:
        print("\n🛑 停止しました")
        sys.exit(0)

if __name__ == "__main__":
    main()
