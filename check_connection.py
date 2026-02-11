import paramiko
from scp import SCPClient
import os

# 確認済みの設定
TX2_CONFIG = {
    "host": "172.16.11.121",
    "user": "kauelu",
    "pass": "Kauelu203",
    "remote_img_dir": "/home/kauelu/images/"  # ★確定したパス
}

# 保存先（テスト用）
LOCAL_SAVE_DIR = "./test_downloads"

def check_and_download():
    host = TX2_CONFIG["host"]
    user = TX2_CONFIG["user"]
    password = TX2_CONFIG["pass"]
    remote_dir = TX2_CONFIG["remote_img_dir"]

    print(f"🔌 {host} ({user}) に接続中...")
    
    # 保存先フォルダ作成
    os.makedirs(LOCAL_SAVE_DIR, exist_ok=True)

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

    try:
        client.connect(host, username=user, password=password, timeout=5.0)
        print("✅ SSH接続: OK")

        # 1. ファイルリストを取得
        stdin, stdout, stderr = client.exec_command(f"ls {remote_dir}")
        file_list = stdout.read().decode().splitlines()
        
        # jpgファイルだけ抽出
        jpg_files = [f for f in file_list if f.endswith(".jpg")]
        
        print(f"📂 リモートフォルダ: {remote_dir}")
        print(f"   -> 発見した画像: {len(jpg_files)}枚 {jpg_files}")

        if not jpg_files:
            print("⚠️ ダウンロードする画像がありません。")
            return

        # 2. ダウンロード実行 (SCP)
        print(f"\n⬇️ ダウンロード開始 (保存先: {LOCAL_SAVE_DIR}) ...")
        
        # SCPクライアント作成
        with SCPClient(client.get_transport()) as scp:
            for filename in jpg_files:
                remote_path = os.path.join(remote_dir, filename)
                local_path = os.path.join(LOCAL_SAVE_DIR, filename)
                
                print(f"   - GET: {filename} ... ", end="")
                try:
                    scp.get(remote_path, local_path)
                    print("OK ✨")
                except Exception as e:
                    print(f"失敗 ❌ ({e})")

        print("\n🎉 全処理が完了しました！フォルダを確認してください。")

    except Exception as e:
        print(f"❌ エラーが発生しました: {e}")
    finally:
        client.close()

if __name__ == "__main__":
    check_and_download()