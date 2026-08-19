#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
CONFIG_FILE="$SCRIPT_DIR/../config.json"
WEBUI_DIR="$SCRIPT_DIR"
WEBUI_PORT="8318"
WEBUI_PID_FILE="/tmp/amazing-draw-webui.pid"
WEBUI_LOG="/tmp/amazing-draw-webui.log"
DETACHED_SPAWN="$(cd "$SCRIPT_DIR/../gpu-pipeline" && pwd)/detached_spawn.py"

if [ -f "$CONFIG_FILE" ]; then
  WEBUI_PORT=$(python3 -c "import json; print(json.load(open('$CONFIG_FILE')).get('webui_port', 8318))")
fi

health_ok() {
  curl -fsS "http://127.0.0.1:${WEBUI_PORT}/" >/dev/null 2>&1
}

collect_pids() {
  {
    if [ -f "$WEBUI_PID_FILE" ]; then
      cat "$WEBUI_PID_FILE" 2>/dev/null || true
      printf '\n'
    fi
    pgrep -f 'scripts/webui/web_server.py' || true
    pgrep -f '[w]eb_server.py' || true
  } | awk 'NF' | sort -u | tr '\n' ' '
}

start_webui() {
  if health_ok; then
    echo "✅ WebUI 已运行: http://127.0.0.1:${WEBUI_PORT}"
    return 0
  fi

  if [ ! -f "$WEBUI_DIR/web_server.py" ]; then
    echo "❌ 找不到 web_server.py: $WEBUI_DIR"
    return 1
  fi
  if [ ! -f "$DETACHED_SPAWN" ]; then
    echo "❌ 找不到 detached_spawn.py: $DETACHED_SPAWN"
    return 1
  fi

  echo "🚀 启动 WebUI..."
  python3 "$DETACHED_SPAWN" \
    --cwd "$WEBUI_DIR" \
    --log "$WEBUI_LOG" \
    --pid-file "$WEBUI_PID_FILE" \
    -- python3 "$WEBUI_DIR/web_server.py" >/dev/null

  for _ in $(seq 1 30); do
    if health_ok; then
      echo "✅ WebUI 已启动: http://127.0.0.1:${WEBUI_PORT}"
      echo "   日志: $WEBUI_LOG"
      return 0
    fi
    sleep 1
  done

  echo "❌ WebUI 启动超时，请检查日志: $WEBUI_LOG"
  stop_webui
  return 1
}

stop_webui() {
  WEBUI_PIDS=$(collect_pids)

  if [ -z "${WEBUI_PIDS// /}" ]; then
    rm -f "$WEBUI_PID_FILE"
    if health_ok; then
      echo "⚠️ 端口 ${WEBUI_PORT} 仍在响应，但未找到 web_server.py 进程"
      return 1
    fi
    echo "ℹ️ WebUI 未运行"
    return 0
  fi

  echo "🛑 停止 WebUI: $WEBUI_PIDS"
  # shellcheck disable=SC2086
  kill $WEBUI_PIDS 2>/dev/null || true

  for _ in $(seq 1 15); do
    if ! health_ok; then
      STILL_RUNNING=0
      for pid in $WEBUI_PIDS; do
        if kill -0 "$pid" 2>/dev/null; then
          STILL_RUNNING=1
          break
        fi
      done
      if [ "$STILL_RUNNING" -eq 0 ]; then
        rm -f "$WEBUI_PID_FILE"
        echo "✅ 已停止 WebUI"
        return 0
      fi
    fi
    sleep 1
  done

  echo "⚠️ WebUI 未在 15s 内退出，执行强制停止"
  # shellcheck disable=SC2086
  kill -9 $WEBUI_PIDS 2>/dev/null || true
  rm -f "$WEBUI_PID_FILE"
  echo "✅ 已强制停止 WebUI"
}

status_webui() {
  PIDS=$(collect_pids)
  if health_ok; then
    echo "✅ WebUI: http://127.0.0.1:${WEBUI_PORT}"
    if [ -n "${PIDS// /}" ]; then
      echo "   pid: $PIDS"
    fi
    if [ -f "$WEBUI_PID_FILE" ]; then
      echo "   pid-file: $(cat "$WEBUI_PID_FILE" 2>/dev/null || true)"
    fi
    echo "   日志: $WEBUI_LOG"
  else
    echo "ℹ️ WebUI 未运行 (port ${WEBUI_PORT})"
    if [ -n "${PIDS// /}" ]; then
      echo "   残留进程: $PIDS"
    fi
  fi
}

restart_webui() {
  stop_webui || true
  start_webui
}

case "${1:-start}" in
  -h|--help|help)
    echo "用法: $0 [start|stop|status|restart|help]"
    echo ""
    echo "选项/指令:"
    echo "  start    后台启动 WebUI（已运行则直接返回）"
    echo "  stop     停止 WebUI"
    echo "  status   查看运行状态"
    echo "  restart  先 stop 再 start"
    echo ""
    echo "端口: config.json webui_port（默认 ${WEBUI_PORT}）"
    echo "日志: $WEBUI_LOG"
    echo "pid:  $WEBUI_PID_FILE"
    exit 0
    ;;
  start)
    start_webui
    ;;
  stop)
    stop_webui
    ;;
  status)
    status_webui
    ;;
  restart)
    restart_webui
    ;;
  *)
    echo "用法: $0 [start|stop|status|restart|help]"
    exit 1
    ;;
esac
