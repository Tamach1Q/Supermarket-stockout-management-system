import paramiko

# 設定
TX2_CONFIG = {
    "host": "172.16.11.121",
    "user": "kauelu",
    "pass": "Kauelu203"
}

def search_folders():
    host = TX2_CONFIG["host"]
    user = TX2_CONFIG["user"]
    password = TX2_CONFIG["pass"]

    print(f"🔌 {host} に接続してフォルダを探します...")
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

    try:
        client.connect(host, username=user, password=password, timeout=5.0)
        
        # 1. ユーザーのホームディレクトリ (/home/kauelu/) の中身を見る
        print("\n🔍 1. ホームディレクトリの中身 (/home/kauelu/):")
        stdin, stdout, stderr = client.exec_command(f"ls -F /home/{user}/")
        print("--------------------------------------------------")
        print(stdout.read().decode().strip())
        print("--------------------------------------------------")

        # 2. もしデスクトップにあるなら...
        print("\n🔍 2. Desktopの中身 (念のため):")
        stdin, stdout, stderr = client.exec_command(f"ls -F /home/{user}/Desktop/")
        out = stdout.read().decode().strip()
        if out:
            print(out)
        else:
            print("(Desktopフォルダがないか、空です)")

    except Exception as e:
        print(f"❌ エラー: {e}")
    finally:
        client.close()

if __name__ == "__main__":
    search_folders()