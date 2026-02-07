import paramiko
from scp import SCPClient
import os
import time
import datetime
import sys
from PIL import Image  # 画像変換用 (pip install Pillow)

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
        "remote_map_yaml": "/home/jetson/maps/map.yaml",
        "remote_map_pgm": "/home/jetson/maps/map.pgm" 
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

def download_map():
    """地図(yaml+pgm)をDLし、PNGに変換して配置する"""
    conf = ROBOT_CONFIG["xavier"]
    client = create_client(conf["host"], conf["user"], conf["pass"])
    
    if client:
        try:
            with SCPClient(client.get_transport()) as scp:
                # 1. yamlとpgmを一旦手元にDL
                local_yaml = os.path.join(LOCAL_DIR, "map.yaml")
                local_pgm = os.path.join(LOCAL_DIR, "map.pgm")
                
                scp.get(conf["remote_map_yaml"], local_yaml)
                scp.get(conf["remote_map_pgm"], local_pgm)
                
                # 2. PGM画像をPNGに変換して static/map.png に保存
                if os.path.exists(local_pgm):
                    with Image.open(local_pgm) as img:
                        # Web表示用に static/map.png として保存
                        img.save(os.path.join(STATIC_DIR, "map.png"))
                    # print("🗺️ 地図更新完了") # 頻繁に出るとうるさいのでコメントアウト

        except Exception as e:
            pass # 地図がまだ無い場合などは無視
        finally:
            client.close()

def main():
    print("=== 🤖 ロボットデータ完全同期システム 🤖 ===")
    print(f"保存先: {LOCAL_DIR}")
    
    # 1. 最初に時刻合わせ
    sync_time()
    
    print("\n📡 監視とダウンロードを開始します (Ctrl+Cで停止)")
    try:
        while True:
            download_csv()    # ログ回収
            download_images() # 画像回収
            download_map()    # 地図回収 & 変換
            
            time.sleep(1)     # 1秒待機
            
    except KeyboardInterrupt:
        print("\n🛑 停止しました")
        sys.exit(0)

if __name__ == "__main__":
    main()