import paramiko
from scp import SCPClient
import os
import time
import datetime
import sys

# ================= 設定エリア =================
# ※ここを実際のロボットのIPアドレスに書き換えてください
ROBOT_CONFIG = {
    # 自動走行ロボット
    "xavier": {
        "host": "192.168.1.10",   # IPアドレス
        "user": "jetson",         # ユーザー名
        "pass": "jetson",         # パスワード
        "remote_csv": "/home/jetson/logs/tracking.csv" # 向こうのファイルの場所
    },
    # Webカメラロボット
    "tx2": {
        "host": "192.168.1.11",   # IPアドレス
        "user": "jetson",         # ユーザー名
        "pass": "jetson",         # パスワード
        "remote_img_dir": "/home/jetson/images/"       # 向こうの画像フォルダ
    }
}

# 保存先 (app.py が監視している場所と同じにする)
LOCAL_DIR = "./store_data"
LOCAL_IMG_DIR = os.path.join(LOCAL_DIR, "images")
LOCAL_CSV = os.path.join(LOCAL_DIR, "tracking.csv")

# フォルダ作成
os.makedirs(LOCAL_IMG_DIR, exist_ok=True)
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
                # パスワード入力が必要なため、標準入力(stdin)にパスワードを流し込む
                cmd = f'sudo -S date -s "{now_str}"'
                stdin, stdout, stderr = client.exec_command(cmd)
                stdin.write(conf["pass"] + '\n')
                stdin.flush()
                
                # エラーチェック
                err = stderr.read().decode()
                if err and "password" not in err: # パスワードプロンプト以外はエラー
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
            # print(f"📥 Log更新: {LOCAL_CSV}") # うるさいのでコメントアウト
        except Exception as e:
            pass # ファイルがまだ無い場合などは無視
        finally:
            client.close()

def download_images():
    """TX2から新着画像のみダウンロード"""
    conf = ROBOT_CONFIG["tx2"]
    client = create_client(conf["host"], conf["user"], conf["pass"])
    
    if client:
        try:
            # 向こうのファイルリストを取得
            stdin, stdout, stderr = client.exec_command(f"ls {conf['remote_img_dir']}")
            files = stdout.read().decode().splitlines()
            
            with SCPClient(client.get_transport()) as scp:
                for file in files:
                    # jpg かつ defect_ で始まるファイルのみ
                    if file.endswith(".jpg") and file.startswith("defect_"):
                        local_path = os.path.join(LOCAL_IMG_DIR, file)
                        
                        # まだ持っていないファイルならDL
                        if not os.path.exists(local_path):
                            remote_path = os.path.join(conf["remote_img_dir"], file)
                            scp.get(remote_path, local_path)
                            print(f"📸 新着画像GET: {file}")
        except Exception as e:
            pass
        finally:
            client.close()

def main():
    print("=== 🤖 ロボットデータ回収システム 🤖 ===")
    print(f"保存先: {LOCAL_DIR}")
    
    # 1. 最初に時刻合わせ
    sync_time()
    
    print("\n📡 監視とダウンロードを開始します (Ctrl+Cで停止)")
    try:
        while True:
            # CSV回収
            download_csv()
            # 画像回収
            download_images()
            
            # 1秒待機
            time.sleep(1)
            
    except KeyboardInterrupt:
        print("\n🛑 停止しました")
        sys.exit(0)

if __name__ == "__main__":
    main()