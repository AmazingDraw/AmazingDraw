#!/bin/bash
set -euo pipefail

CONFIG_FILE="$(dirname "$0")/../config.json"

# 默认值
COMFYUI_DIR="$HOME/ComfyUI"
COMFY_PORT="8188"
OUTPUT_DIR="$HOME/Downloads/draw_things"
WORKSPACE="$HOME/.openclaw/workspace"

# 如果存在 config.json，用 python 轻量提取
if [ -f "$CONFIG_FILE" ]; then
  COMFYUI_DIR=$(python3 -c "import json, os; print(os.path.expanduser(json.load(open('$CONFIG_FILE')).get('comfyui_dir', '$HOME/ComfyUI')))")
  COMFY_PORT=$(python3 -c "import json, urllib.parse; u=json.load(open('$CONFIG_FILE')).get('comfyui_host', 'http://127.0.0.1:8188'); u_parsed=urllib.parse.urlparse(u); print(u_parsed.port if u_parsed.port else 8188)")
  OUTPUT_DIR=$(python3 -c "import json, os; print(os.path.expanduser(json.load(open('$CONFIG_FILE')).get('output_dir', '~/Downloads/draw_things')))")
  WORKSPACE=$(python3 -c "import json, os; print(os.path.expanduser(json.load(open('$CONFIG_FILE')).get('openclaw_workspace_dir') or '$HOME/.openclaw/workspace'))")
fi

COMFYUI_MAIN="$COMFYUI_DIR/main.py"
COMFYUI_VENV="$COMFYUI_DIR/.venv/bin/python"
COMFY_PID_FILE="/tmp/comfyui-headless.pid"
COMFY_LOG="/tmp/comfyui-headless.log"
DETACHED_SPAWN="$(cd "$(dirname "$0")" && pwd)/detached_spawn.py"

start_comfyui() {
  if curl -fsS "http://127.0.0.1:${COMFY_PORT}/system_stats" >/dev/null 2>&1; then
    echo "✅ ComfyUI 已运行: http://127.0.0.1:${COMFY_PORT}"
    return 0
  fi

  echo "🚀 启动 ComfyUI 后端..."
  cd "$COMFYUI_DIR"
  python3 "$DETACHED_SPAWN" \
    --cwd "$COMFYUI_DIR" \
    --log "$COMFY_LOG" \
    --pid-file "$COMFY_PID_FILE" \
    -- "$COMFYUI_VENV" "$COMFYUI_MAIN" \
    --user-directory "$COMFYUI_DIR/user" \
    --input-directory "$COMFYUI_DIR/input" \
    --output-directory "$OUTPUT_DIR" \
    --base-directory "$COMFYUI_DIR" \
    --database-url "sqlite:///$COMFYUI_DIR/user/comfyui.db" \
    --log-stdout --listen 127.0.0.1 --port "$COMFY_PORT" --enable-manager >/dev/null

  for _ in $(seq 1 120); do
    if curl -fsS "http://127.0.0.1:${COMFY_PORT}/system_stats" >/dev/null 2>&1; then
      echo "✅ ComfyUI 已启动: http://127.0.0.1:${COMFY_PORT}"
      return 0
    fi
    sleep 1
  done

  echo "❌ ComfyUI 启动超时，请检查日志: $COMFY_LOG"
  stop_all
  return 1
}

stop_all() {
  COMFY_PIDS=$( {
      if [ -f "$COMFY_PID_FILE" ]; then
        cat "$COMFY_PID_FILE" 2>/dev/null || true
        printf '\n'
      fi
      pgrep -f '/Applications/ComfyUI.app/Contents/Resources/ComfyUI/main.py' || true
      pgrep -f 'ComfyUI/main.py' || true
      pgrep -f 'multiprocessing.resource_tracker' || true
    } | awk 'NF' | sort -u | tr '\n' ' ' )

  if [ -z "${COMFY_PIDS// /}" ]; then
    rm -f "$COMFY_PID_FILE"
    echo "ℹ️ ComfyUI 未运行"
    return 0
  fi

  echo "🛑 停止 ComfyUI: $COMFY_PIDS"
  # shellcheck disable=SC2086
  kill $COMFY_PIDS 2>/dev/null || true

  for _ in $(seq 1 15); do
    if ! curl -fsS "http://127.0.0.1:${COMFY_PORT}/system_stats" >/dev/null 2>&1; then
      STILL_RUNNING=0
      for pid in $COMFY_PIDS; do
        if kill -0 "$pid" 2>/dev/null; then
          STILL_RUNNING=1
          break
        fi
      done
      if [ "$STILL_RUNNING" -eq 0 ]; then
        rm -f "$COMFY_PID_FILE"
        echo "✅ 已停止 ComfyUI"
        return 0
      fi
    fi
    sleep 1
  done

  echo "⚠️ ComfyUI 未在 15s 内退出，执行强制停止"
  # shellcheck disable=SC2086
  kill -9 $COMFY_PIDS 2>/dev/null || true
  rm -f "$COMFY_PID_FILE"
  echo "✅ 已强制停止 ComfyUI"
}

status_all() {
  if curl -fsS "http://127.0.0.1:${COMFY_PORT}/system_stats" >/dev/null 2>&1; then
    echo "✅ ComfyUI: http://127.0.0.1:${COMFY_PORT}"
  else
    echo "ℹ️ ComfyUI 未运行"
  fi
}

case "${1:-start}" in
  -h|--help|help)
    echo "用法: $0 [start|stop|status]"
    echo ""
    echo "选项/指令:"
    echo "  start   启动 ComfyUI 后端并挂载 draw_things 磁盘目录"
    echo "  stop    安全停止所有 ComfyUI 主进程与子进程"
    echo "  status  查看当前服务运行状态"
    exit 0
    ;;
  start)
    start_comfyui
    ;;
  stop)
    stop_all
    ;;
  status)
    status_all
    ;;
  *)
    echo "用法: $0 [start|stop|status|help]"
    exit 1
    ;;
esac
