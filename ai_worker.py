import os
import re
import shutil
import time
from pathlib import Path
from urllib.parse import urljoin

try:
    import requests  # type: ignore
except Exception:
    requests = None  # type: ignore

from ultralytics import YOLO

# ===== 設定値（要件）=====
MODEL_PATH = "Best Model.pt"
STOCKOUT_CLASS = "empty"
CONF_THRESHOLD = 0.5
RAW_DIR = "./store_data/raw_images"
TARGET_DIR = "./store_data/images"
ARCHIVE_DIR = "./store_data/archive"

# Apple Silicon MPS
DEVICE = "mps"

# 追加設定
POLL_INTERVAL_SEC = 0.5
ARCHIVE_RETENTION_DAYS = 3
ARCHIVE_CLEANUP_INTERVAL_SEC = 60

# 任意: クラウド送信（sync_robots.py から移譲）
REMOTE_APP_URL = os.environ.get("REMOTE_APP_URL")
INGEST_TOKEN = os.environ.get("INGEST_TOKEN")


def ensure_dirs() -> None:
    os.makedirs(RAW_DIR, exist_ok=True)
    os.makedirs(TARGET_DIR, exist_ok=True)
    os.makedirs(ARCHIVE_DIR, exist_ok=True)


def remote_enabled() -> bool:
    return bool(REMOTE_APP_URL and INGEST_TOKEN and requests is not None)


def remote_headers() -> dict:
    return {"X-Ingest-Token": INGEST_TOKEN} if INGEST_TOKEN else {}


def upload_defect_image(path: str) -> bool:
    if not remote_enabled():
        return False
    if not os.path.exists(path):
        return False

    base = REMOTE_APP_URL.rstrip("/") + "/"
    url = urljoin(base, "api/ingest/image")
    try:
        with open(path, "rb") as f:
            files = {"file": (os.path.basename(path), f)}
            r = requests.post(url, headers=remote_headers(), files=files, timeout=10)
        if r.status_code >= 300:
            print(f"⚠️ 画像アップロード失敗: {os.path.basename(path)} ({r.status_code})")
            return False
        return True
    except Exception as e:
        print(f"⚠️ 画像アップロード例外: {e}")
        return False


def extract_timestamp_str(filename: str) -> str:
    stem = Path(filename).stem
    candidate = stem

    if candidate.startswith("image_"):
        candidate = candidate[len("image_") :]
    elif candidate.startswith("defect_"):
        candidate = candidate[len("defect_") :]

    if re.fullmatch(r"\d+(?:\.\d+)?", candidate):
        return candidate

    match = re.search(r"\d{9,}(?:\.\d+)?", stem)
    if match:
        return match.group(0)

    return f"{time.time():.6f}"


def build_defect_filename(src_name: str) -> str:
    ts = extract_timestamp_str(src_name)
    dst_name = f"defect_{ts}.jpg"
    dst_path = os.path.join(TARGET_DIR, dst_name)

    # 既存衝突時は現在時刻で作り直す（app.py が float で読める命名を維持）
    while os.path.exists(dst_path):
        ts = f"{time.time():.6f}"
        dst_name = f"defect_{ts}.jpg"
        dst_path = os.path.join(TARGET_DIR, dst_name)

    return dst_name


def detect_stockout(model: YOLO, img_path: str) -> bool:
    results = model.predict(img_path, conf=CONF_THRESHOLD, device=DEVICE, verbose=False)

    for result in results:
        names = result.names if hasattr(result, "names") else model.names
        if result.boxes is None:
            continue
        for box in result.boxes:
            cls_id = int(box.cls[0])
            conf = float(box.conf[0])
            class_name = str(names.get(cls_id, cls_id)) if isinstance(names, dict) else str(names[cls_id])
            if class_name == STOCKOUT_CLASS and conf >= CONF_THRESHOLD:
                return True
    return False


def cleanup_archive() -> None:
    now = time.time()
    expire_sec = ARCHIVE_RETENTION_DAYS * 24 * 60 * 60

    try:
        for name in os.listdir(ARCHIVE_DIR):
            path = os.path.join(ARCHIVE_DIR, name)
            if not os.path.isfile(path):
                continue
            if now - os.path.getmtime(path) >= expire_sec:
                os.remove(path)
                print(f"🧹 古いアーカイブ削除: {name}")
    except Exception as e:
        print(f"⚠️ アーカイブ削除エラー: {e}")


def upload_pending_defect_images(uploaded_images: set) -> None:
    if not remote_enabled():
        return

    try:
        for name in os.listdir(TARGET_DIR):
            if not (name.endswith(".jpg") and name.startswith("defect_")):
                continue
            if name in uploaded_images:
                continue
            path = os.path.join(TARGET_DIR, name)
            if upload_defect_image(path):
                uploaded_images.add(name)
    except Exception as e:
        print(f"⚠️ 送信ループエラー: {e}")


def main() -> None:
    ensure_dirs()

    print(f"🚀 モデルロード開始: {MODEL_PATH} (device={DEVICE})")
    model = YOLO(MODEL_PATH)
    print(f"ℹ️ クラス一覧: {model.names}")
    print("👀 raw_images監視を開始します (Ctrl+Cで停止)")

    if requests is None and REMOTE_APP_URL:
        print("⚠️ requests が無いためクラウド送信を無効化します")
    elif remote_enabled():
        print(f"🌐 クラウド送信有効: {REMOTE_APP_URL}")

    uploaded_images: set = set()
    last_archive_cleanup = 0.0

    try:
        while True:
            files = sorted(f for f in os.listdir(RAW_DIR) if f.lower().endswith(".jpg"))

            for file_name in files:
                raw_path = os.path.join(RAW_DIR, file_name)
                if not os.path.isfile(raw_path):
                    continue

                try:
                    is_stockout = detect_stockout(model, raw_path)

                    if is_stockout:
                        dst_name = build_defect_filename(file_name)
                        dst_path = os.path.join(TARGET_DIR, dst_name)
                        shutil.move(raw_path, dst_path)
                        print(f"✅ 欠品検知: {dst_name}")
                        if remote_enabled() and upload_defect_image(dst_path):
                            uploaded_images.add(dst_name)
                    else:
                        archive_path = os.path.join(ARCHIVE_DIR, file_name)
                        if os.path.exists(archive_path):
                            archive_path = os.path.join(ARCHIVE_DIR, f"{time.time():.6f}_{file_name}")
                        shutil.move(raw_path, archive_path)
                        print(f"アーカイブ: {file_name}")
                except Exception as e:
                    print(f"⚠️ 推論/移動エラー ({file_name}): {e}")
                    # 同じファイルで無限リトライしないため、エラー時もアーカイブへ退避
                    try:
                        if os.path.exists(raw_path):
                            fallback_path = os.path.join(ARCHIVE_DIR, f"error_{time.time():.6f}_{file_name}")
                            shutil.move(raw_path, fallback_path)
                    except Exception:
                        pass

            upload_pending_defect_images(uploaded_images)

            now = time.time()
            if now - last_archive_cleanup >= ARCHIVE_CLEANUP_INTERVAL_SEC:
                cleanup_archive()
                last_archive_cleanup = now

            time.sleep(POLL_INTERVAL_SEC)
    except KeyboardInterrupt:
        print("\n🛑 ai_worker を停止しました")


if __name__ == "__main__":
    main()
