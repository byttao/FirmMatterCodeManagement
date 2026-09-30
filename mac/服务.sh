#!/bin/bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
RUN="$ROOT/data"
PID="$RUN/server.pid"
mkdir -p "$RUN"

read_config() {
  local config
  config="$("$ROOT/.venv/bin/python" "$ROOT/backend/server_config.py" --data-dir "$RUN" --package-root "$ROOT" --ensure)"
  IFS=$'\t' read -r HOST PORT <<< "$config"
}

running() {
  [ -f "$PID" ] || return 1
  local id
  id="$(cat "$PID")"
  [[ "$id" =~ ^[0-9]+$ ]] || return 1
  kill -0 "$id" 2>/dev/null || return 1
  [[ "$(ps -p "$id" -o command= 2>/dev/null || true)" == *"$ROOT/.venv/bin/python"* ]]
}

case "${1:-}" in
  start)
    if [ ! -x "$ROOT/.venv/bin/python" ]; then
      command -v python3 >/dev/null || { echo "请先安装 Python 3.11+" >&2; exit 1; }
      python3 -c 'import sys; sys.exit(sys.version_info < (3, 11))' || { echo "需要 Python 3.11+" >&2; exit 1; }
      python3 -m venv "$ROOT/.venv"
    fi
    read_config
    if running; then echo "服务已运行：http://127.0.0.1:${PORT}（监听 ${HOST}）"; exit 0; fi
    if [ ! -f "$ROOT/.venv/.requirements-installed" ]; then
      "$ROOT/.venv/bin/python" -m pip install -r "$ROOT/backend/requirements.txt"
      touch "$ROOT/.venv/.requirements-installed"
    fi
    (cd "$ROOT/backend"; FIRM_MANAGER_DATA_DIR="$RUN" FIRM_MANAGER_STATIC_DIR="$ROOT/static" FIRM_MANAGER_TRIAL_MODE="${FIRM_MANAGER_TRIAL_MODE:-1}" nohup "$ROOT/.venv/bin/python" -m uvicorn main:app --host "$HOST" --port "$PORT" </dev/null >"$RUN/server.log" 2>&1 & echo $! >"$PID")
    for _ in {1..30}; do
      if running && curl -fsS "http://127.0.0.1:$PORT/api/setup/status" >/dev/null 2>&1; then
        echo "服务已启动：http://127.0.0.1:${PORT}（监听 ${HOST}）"
        exit 0
      fi
      sleep 1
    done
    echo "启动失败，查看 data/server.log" >&2
    exit 1 ;;
  stop)
    if running; then kill "$(cat "$PID")"; echo "服务已停止"; fi
    rm -f "$PID" ;;
  status)
    if [ ! -x "$ROOT/.venv/bin/python" ]; then echo "已停止"; exit 0; fi
    read_config
    if running; then echo "运行中：http://127.0.0.1:${PORT}（监听 ${HOST}）"; else echo "已停止"; fi ;;
  check)
    "$0" start
    "$0" status
    "$0" stop ;;
  *) echo "用法：$0 {start|stop|status|check}" >&2; exit 2 ;;
esac
