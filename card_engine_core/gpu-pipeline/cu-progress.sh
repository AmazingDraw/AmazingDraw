#!/bin/bash
CARD_ENGINE_TMP="${CARD_ENGINE_TMP:-/tmp/cu-card}"
mkdir -p "$CARD_ENGINE_TMP"
# cu-progress.sh — CU 抽卡进度面板（适配新工作流）
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONFIG_FILE="${SCRIPT_DIR}/../config.json"
CU_API="http://127.0.0.1:8188"
if [ -f "$CONFIG_FILE" ]; then
  CU_API=$(python3 -c "import json; print(json.load(open('${CONFIG_FILE}')).get('comfyui_host', 'http://127.0.0.1:8188'))")
fi
WORKSPACE=$(python3 -c "import json, os; print(os.path.expanduser(json.load(open('${CONFIG_FILE}')).get('openclaw_workspace_dir') or '$HOME/.openclaw/workspace'))")

QUEUE_SCRIPT="${SCRIPT_DIR}/cu-queue.py"
CARD_DIR=$(python3 -c "import json,os; c=json.load(open('${CONFIG_FILE}')); print(os.path.expanduser(c.get('cards_dir') or '$HOME/.openclaw/draw-cards/cards'))")
TMP_DIR=$(python3 -c "import json,os; c=json.load(open('${CONFIG_FILE}')); print(os.path.expanduser(c.get('tmp_dir') or '/tmp/cu-card'))")
LOG="$TMP_DIR/cu-draw-card.log"
FAIL_DIR="$TMP_DIR/failed-delivery"
SUCCESS_DIR="$TMP_DIR/success-delivery"
GPU_LOCK="$TMP_DIR/cu-gpu.lock"

py_json_get() {
  local expr="$1"
  python3 -c "import json,sys
try:
    data=json.load(sys.stdin)
    print(${expr})
except Exception:
    print('')
" 2>/dev/null
}

echo "============================================"
echo "  🖥️  CU Progress — $(date '+%H:%M:%S')"
echo "============================================"

# ── 1. ComfyUI 状态 ──
echo ""
echo "━━ 1. ComfyUI ━━"
CU_RESP=$(curl -s --connect-timeout 3 "$CU_API/system_stats" 2>/dev/null || echo '{"error":"offline"}')
if echo "$CU_RESP" | grep -q '"os"'; then
    RAM_GB=$(echo "$CU_RESP" | py_json_get "round(data['system']['ram_free']/1073741824,1)" || echo '?')
    echo "  ✅ 在线 | 空闲内存: ${RAM_GB}GB"
else
    echo "  ❌ 离线"
fi

# ── 2. 队列 / GPU ──
echo ""
echo "━━ 2. 队列 / GPU ━━"
Q=$(curl -s "$CU_API/queue" 2>/dev/null || echo '{}')
RUNNING=$(echo "$Q" | py_json_get "len(data.get('queue_running', []))" || echo '?')
PENDING=$(echo "$Q" | py_json_get "len(data.get('queue_pending', []))" || echo '?')
echo "  ComfyUI 运行中: ${RUNNING:-?} | ComfyUI 排队: ${PENDING:-?}"

if [ -f "$GPU_LOCK" ]; then
  AGE=$(($(date +%s) - $(stat -f %m "$GPU_LOCK" 2>/dev/null || echo 0)))
  echo "  🔒 GPU 锁: active | 持续 ${AGE}s"
else
  echo "  🔓 GPU 锁: idle"
fi

if [ "${RUNNING:-0}" != "0" ]; then
  PID=$(echo "$Q" | python3 - <<'PY' 2>/dev/null
import json,sys
try:
    q=json.load(sys.stdin)
    r=q.get('queue_running',[])
    print(r[0][1][:12] if r and len(r[0])>1 else '')
except Exception:
    print('')
PY
)
  [ -n "$PID" ] && echo "  当前 PID: $PID"
fi

if [ -f "$QUEUE_SCRIPT" ]; then
  QS=$(python3 "$QUEUE_SCRIPT" status 2>/dev/null || echo '{}')
  QLEN=$(echo "$QS" | py_json_get "data.get('length', '')")
  QNEXT=$(echo "$QS" | py_json_get "data.get('next', '')")
  QLORA=$(echo "$QS" | py_json_get "data.get('next_lora', '')")
  QPROMPT=$(echo "$QS" | py_json_get "data.get('next_prompt_file', '')")
  QDONE=$(echo "$QS" | py_json_get "data.get('next_done_file', '')")
  echo "  本地队列长度: ${QLEN:-0}"
  [ -n "${QNEXT:-}" ] && echo "  下一张摘要: ${QNEXT}"
  [ -n "${QLORA:-}" ] && echo "  下一张 LoRA: ${QLORA}"
  [ -n "${QPROMPT:-}" ] && echo "  next prompt: ${QPROMPT##*/}"
  [ -n "${QDONE:-}" ] && echo "  next done: ${QDONE##*/}"
fi

# ── 3. 最新关键日志 ──
echo ""
echo "━━ 3. 最新关键日志 ━━"
if [ -f "$LOG" ]; then
  KEY_LINES=$(grep -E 'SUBMIT|WAIT_START|DONE\s\||DONE_MARKER|OUTPUTS_SEEN_WAIT_FILE|TIMEOUT|COMFYUI_DOWN|COMFYUI_START_FAILED' "$LOG" | tail -5 || true)
  if [ -n "$KEY_LINES" ]; then
    while IFS= read -r line; do
      [ -n "$line" ] && echo "  $line"
    done <<< "$KEY_LINES"
  else
    tail -5 "$LOG" | while IFS= read -r line; do
      echo "  $line"
    done
  fi
else
  echo "  无日志"
fi

# ── 4. 最近交付 / 失败现场 ──
echo ""
echo "━━ 4. 最近交付 / 失败 ━━"
LATEST_SUCCESS=$(ls -1t "$SUCCESS_DIR"/*.json 2>/dev/null | head -1 || true)
LATEST_FAIL=$(ls -1t "$FAIL_DIR"/*.json 2>/dev/null | head -1 || true)
LATEST_DONE=$(ls -1t "$TMP_DIR"/cu-draw-card-done_*.json 2>/dev/null | head -1 || true)
LATEST_META=$(ls -1t "$TMP_DIR"/card_meta_*.json 2>/dev/null | head -1 || true)

if [ -n "$LATEST_SUCCESS" ] && [ -f "$LATEST_SUCCESS" ]; then
  echo "  ✅ 最近成功交付: ${LATEST_SUCCESS##*/}"
  python3 - <<PY 2>/dev/null
import json
from pathlib import Path
p = Path('''$LATEST_SUCCESS''')
try:
    data = json.loads(p.read_text(encoding='utf-8'))
    for key in ['person','scene','theme','image_file','seed','elapsed','telegram_message_id']:
        val = data.get(key)
        if val not in (None, '', []):
            print(f"  {key}: {val}")
except Exception:
    pass
PY
elif [ -n "$LATEST_FAIL" ] && [ -f "$LATEST_FAIL" ]; then
  echo "  ⚠️ 最近失败现场: ${LATEST_FAIL##*/}"
  python3 - <<PY 2>/dev/null
import json
from pathlib import Path
p = Path('''$LATEST_FAIL''')
try:
    data = json.loads(p.read_text(encoding='utf-8'))
    for key in ['person','scene','theme','image_file','seed','elapsed']:
        val = data.get(key)
        if val not in (None, '', []):
            print(f"  {key}: {val}")
except Exception:
    pass
PY
elif [ -n "$LATEST_DONE" ] && [ -f "$LATEST_DONE" ]; then
  echo "  🧩 最近完成标记: ${LATEST_DONE##*/}"
  python3 - <<PY 2>/dev/null
import json
from pathlib import Path
p = Path('''$LATEST_DONE''')
try:
    data = json.loads(p.read_text(encoding='utf-8'))
    for key in ['file','seed','elapsed_min']:
        val = data.get(key)
        if val not in (None, '', []):
            print(f"  {key}: {val}")
except Exception:
    pass
PY
elif [ -n "$LATEST_META" ] && [ -f "$LATEST_META" ]; then
  echo "  📝 最近 meta: ${LATEST_META##*/}"
  python3 - <<PY 2>/dev/null
import json
from pathlib import Path
p = Path('''$LATEST_META''')
try:
    data = json.loads(p.read_text(encoding='utf-8'))
    for key in ['person','scene','theme','reply_id']:
        val = data.get(key)
        if val not in (None, '', []):
            print(f"  {key}: {val}")
except Exception:
    pass
PY
else
  echo "  暂无最近交付/失败记录"
fi

# ── 5. 最新卡面 ──
echo ""
echo "━━ 5. 最新卡面 ━━"
LATEST_CARD=$(ls -1t "$CARD_DIR"/*.json 2>/dev/null | head -1 || true)
if [ -n "$LATEST_CARD" ] && [ -f "$LATEST_CARD" ]; then
  python3 - <<PY 2>/dev/null
import json
from pathlib import Path
p = Path('''$LATEST_CARD''')
try:
    card = json.loads(p.read_text(encoding='utf-8'))
    scene = (card.get('scene') or {}).get('name','')
    person = (card.get('subject') or {}).get('display_name','')
    status = card.get('status','')
    version = card.get('version','')
    validation = card.get('_validation') or {}
    errs = len(validation.get('errors',[]) or [])
    warns = len(validation.get('warnings',[]) or [])
    print(f"  文件: {p.name}")
    print(f"  场景: {scene}")
    print(f"  人物: {person}")
    print(f"  状态: {status} | v{version}")
    print(f"  check: errors={errs} warnings={warns}")
except Exception as e:
    print(f"  读取失败: {e}")
PY
else
  echo "  暂无 card.json"
fi

echo ""
echo "━━ 6. 孤儿草稿 ━━"
DRAFT_COUNT=0
for f in "$CARD_DIR"/*.json; do
  if [ -f "$f" ]; then
    STATUS=$(python3 -c "import json; d=json.load(open('$f')); print(d.get('status',''))" 2>/dev/null || echo '')
    if [ "$STATUS" = "draft" ]; then
      DRAFT_COUNT=$((DRAFT_COUNT + 1))
    fi
  fi
done
if [ "$DRAFT_COUNT" -gt 0 ]; then
  echo "  ⚠️  $DRAFT_COUNT 张草稿卡未提交"
  echo "     查看: python3 gpu-pipeline/cu-queue.py drafts"
  echo "     清理: python3 gpu-pipeline/cu-queue.py drafts --clean"
else
  echo "  ✅ 无孤儿草稿"
fi

echo ""
echo "============================================"
