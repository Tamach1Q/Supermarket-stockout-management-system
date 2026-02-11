#!/usr/bin/env bash
set -euo pipefail

# One-command demo runner for my_shop_app
# - sets up venv and deps
# - generates dummy data
# - launches app + ai_worker
# - starts detection and injects a dummy notification
#
# Usage:
#   ./run_demo.sh              # uses PORT=5000 by default
#   PORT=5001 ./run_demo.sh    # override port

PORT="${PORT:-5000}"
VENV="${VENV:-.venv}"
PYTHON="${PYTHON:-python3}"
ULTRA_CFG_DIR="${ULTRA_CFG_DIR:-$PWD/.ultralytics}"

log() { echo "[$(date +%H:%M:%S)] $*"; }

ensure_venv() {
  if [ ! -x "$VENV/bin/python" ]; then
    log "create venv: $VENV"
    $PYTHON -m venv "$VENV"
  fi
  # shellcheck disable=SC1090
  source "$VENV/bin/activate"
}

install_deps() {
  log "install deps"
  pip install -q -r requirements.txt
  pip install -q ultralytics
}

generate_dummy() {
  log "generate dummy data"
  "$VENV/bin/python" make_demo_data.py
}

start_app() {
  log "start app on :$PORT"
  APP_LOG="/tmp/my_shop_app_app.log"
  PORT="$PORT" nohup "$VENV/bin/python" app.py >"$APP_LOG" 2>&1 &
  APP_PID=$!
  echo "$APP_PID" > /tmp/my_shop_app_app.pid
  log "app pid=$APP_PID (log: $APP_LOG)"
}

start_worker() {
  log "start ai_worker"
  WORKER_LOG="/tmp/my_shop_app_worker.log"
  ULTRALYTICS_CONFIG_DIR="$ULTRA_CFG_DIR" nohup "$VENV/bin/python" -u ai_worker.py >"$WORKER_LOG" 2>&1 &
  WORKER_PID=$!
  echo "$WORKER_PID" > /tmp/my_shop_app_worker.pid
  log "worker pid=$WORKER_PID (log: $WORKER_LOG)"
}

wait_servers() {
  log "wait servers up"
  sleep 4
}

force_notification() {
  log "ensure detection started"
  curl -sS -X POST "http://127.0.0.1:${PORT}/api/detection/control" \
    -H 'Content-Type: application/json' \
    -d '{"active": true}' >/dev/null

  TS="$("$VENV/bin/python" - <<'PY'
import time
print(f"{time.time():.3f}")
PY
)"
  mkdir -p store_data/images
  echo "${TS},100,100" > store_data/tracking.csv
  SRC=$(ls test_downloads/*.jpg 2>/dev/null | head -n 1 || true)
  if [ -z "$SRC" ]; then
    log "no test_downloads/*.jpg found; skipping dummy inject"
    return
  fi
  cp "$SRC" "store_data/images/defect_${TS}.jpg"
  log "injected defect_${TS}.jpg for notification"
}

print_links() {
  log "open http://127.0.0.1:${PORT}/monitor  (manual)"
  log "stop servers: kill \$(cat /tmp/my_shop_app_app.pid /tmp/my_shop_app_worker.pid 2>/dev/null)"
}

main() {
  ensure_venv
  install_deps
  generate_dummy
  start_app
  start_worker
  wait_servers
  force_notification
  print_links
}

main "$@"
