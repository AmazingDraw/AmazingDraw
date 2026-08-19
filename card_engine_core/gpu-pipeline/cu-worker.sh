#!/bin/bash
CARD_ENGINE_TMP="${CARD_ENGINE_TMP:-/tmp/cu-card}"
mkdir -p "$CARD_ENGINE_TMP"
# cu-worker.sh — 单张渲染+交付 worker（前台运行，由 detached_spawn.py 拉到后台）
set -euo pipefail

show_help() {
    cat <<EOF
🛠️ GPU 渲染与分发 Worker 脚本 (cu-worker.sh)
=========================================
用法:
  bash cu-worker.sh \\
    --job-id <队列任务ID> \\
    --card-id <卡片ID> \\
    --lease-token <租约令牌> \\
    --prompt-file <提示词文件路径> \\
    --meta-file <元数据JSON文件路径> \\
    --done-file <渲染结果标记JSON路径> \\
    [--lora "<LoRA文件名>"] \\
    [--width <宽度>] [--height <高度>] \\
    [--workflow "<工作流名称>"] \\
    [--seed <固定Seed>] \\
    [--bg-log "<后台日志路径>"]

选项说明:
  --prompt-file  存储 Stable Diffusion 完整英文提示词的纯文本文件 (必填)
  --meta-file    存储卡片渲染元数据、人物、场景、Caption 信息的 JSON 文件 (必填)
  --done-file    渲染成功后写入结果文件物理路径、Seed和耗时的标记 JSON 文件 (必填)
  --job-id       QueueStore v2 任务 ID (必填)
  --card-id      关联卡片 ID，可为空字符串
  --lease-token  claim 后持久化的条件 ACK 令牌 (必填)
  --lora         强制指定 LoRA 名字 (可选)
  --width        渲染宽度 (可选)
  --height       渲染高度 (可选)
  --workflow     工作流别名/文件名 (可选)
  --seed         固定渲染 Seed (可选)
  --bg-log       后台日志落地路径 (可选)
EOF
    exit 0
}

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" || "${1:-}" == "help" ]]; then
    show_help
fi

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
CONFIG_FILE="${SCRIPT_DIR}/../config.json"
WORKSPACE="${CU_WORKSPACE:-$(python3 -c "import json, os; print(os.path.expanduser(json.load(open('${CONFIG_FILE}')).get('openclaw_workspace_dir') or '~/.openclaw/workspace'))")}"
START_EPOCH="$(date +%s)"
WORK_DIR="${CU_WORK_DIR:-$(python3 -c "import json, os; print(os.path.expanduser(json.load(open('${CONFIG_FILE}')).get('tmp_dir') or '/tmp/cu-card'))")}"
RUNTIME_FILE="$WORK_DIR/cu-runtime.json"
QUEUE_SCRIPT="$SCRIPT_DIR/cu-queue.py"

JOB_ID="${CU_JOB_ID:-}"
CARD_ID="${CU_CARD_ID:-}"
LEASE_TOKEN="${CU_LEASE_TOKEN:-}"
PROMPT_FILE=""
META_FILE=""
DONE_FILE=""
LORA=""
WIDTH=""
HEIGHT=""
WORKFLOW="${CU_WORKFLOW:-}"
SEED="${CU_SEED:-}"
BG_LOG="${CU_BG_LOG:-}"

while [[ $# -gt 0 ]]; do
    case "$1" in
        --job-id) JOB_ID="$2"; shift 2 ;;
        --card-id) CARD_ID="$2"; shift 2 ;;
        --lease-token) LEASE_TOKEN="$2"; shift 2 ;;
        --prompt-file) PROMPT_FILE="$2"; shift 2 ;;
        --meta-file) META_FILE="$2"; shift 2 ;;
        --done-file) DONE_FILE="$2"; shift 2 ;;
        --lora) LORA="$2"; shift 2 ;;
        --width) WIDTH="$2"; shift 2 ;;
        --height) HEIGHT="$2"; shift 2 ;;
        --workflow) WORKFLOW="$2"; shift 2 ;;
        --seed) SEED="$2"; shift 2 ;;
        --bg-log) BG_LOG="$2"; shift 2 ;;
        *) echo "未知参数: $1"; exit 1 ;;
    esac
done

if [[ -z "$JOB_ID" || -z "$LEASE_TOKEN" || -z "$PROMPT_FILE" || -z "$META_FILE" || -z "$DONE_FILE" ]]; then
    echo "❌ 缺少必填参数: --job-id --lease-token --prompt-file --meta-file --done-file"
    exit 1
fi

write_runtime() {
    local STAGE="$1"
    python3 - <<PY
import json, os, time
from pathlib import Path
runtime = {
    'pid': int(os.environ.get('CU_WORKER_PID') or os.getpid()),
    'job_id': os.environ.get('JOB_ID', ''),
    'card_id': os.environ.get('CARD_ID', ''),
    'lease_token': os.environ.get('LEASE_TOKEN', ''),
    'stage': '$STAGE',
    'start_epoch': int(os.environ.get('CU_START_EPOCH', '0') or 0),
    'prompt_file': os.environ.get('PROMPT_FILE', ''),
    'meta_file': os.environ.get('META_FILE', ''),
    'done_file': os.environ.get('DONE_FILE', ''),
    'lora': os.environ.get('LORA', ''),
    'width': int(os.environ.get('WIDTH', '0') or 0),
    'height': int(os.environ.get('HEIGHT', '0') or 0),
    'workflow': os.environ.get('WORKFLOW', ''),
    'seed': int(os.environ['SEED']) if os.environ.get('SEED', '').strip() else None,
    'updated_at': int(time.time()),
}
meta_path = runtime['meta_file']
if meta_path and Path(meta_path).exists():
    try:
        meta = json.loads(Path(meta_path).read_text(encoding='utf-8'))
    except Exception:
        meta = {}
    runtime['summary'] = {
        'person': meta.get('person', ''),
        'scene': meta.get('scene', ''),
        'theme': meta.get('theme', ''),
    }
Path('$RUNTIME_FILE').write_text(json.dumps(runtime, ensure_ascii=False, indent=2), encoding='utf-8')
PY
}

DELIVER_ATTEMPTED=0
NACKED=0
HEARTBEAT_PID=""

cleanup_runtime() {
    if [ -n "${HEARTBEAT_PID:-}" ]; then
        kill "$HEARTBEAT_PID" 2>/dev/null || true
        wait "$HEARTBEAT_PID" 2>/dev/null || true
        HEARTBEAT_PID=""
    fi
    rm -f "$RUNTIME_FILE"
}

recover_after_exit() {
    local RC=$?
    trap - EXIT
    if [[ "$RC" -ne 0 && -f "$DONE_FILE" && "$DELIVER_ATTEMPTED" != "1" ]]; then
        echo "♻️ Worker 异常退出，但 DONE marker 已存在 → 尝试自动恢复交付"
        write_runtime "delivering"
        set +e
        env DONE_FILE="$DONE_FILE" META_FILE="$META_FILE" \
            JOB_ID="$JOB_ID" CARD_ID="$CARD_ID" LEASE_TOKEN="$LEASE_TOKEN" \
            WORKFLOW="$WORKFLOW" REQUESTED_SEED="$SEED" \
            bash "$SCRIPT_DIR/cu-deliver.sh"
        local RECOVER_RC=$?
        set -e
        echo "RECOVER_RC=$RECOVER_RC"
        if [[ "$RECOVER_RC" -eq 0 ]]; then
            RC=0
        else
            notify_gpu_lock_issue "⚠️ 自动恢复交付失败" "worker 退出后检测到 DONE marker，但自动补交付失败" "$RECOVER_RC"
        fi
    fi
    if [[ "$RC" -ne 0 && "$NACKED" != "1" && -n "${JOB_ID:-}" && -n "${LEASE_TOKEN:-}" ]]; then
        set +e
        NACK_ACK=$(python3 "$QUEUE_SCRIPT" nack \
            --job-id "$JOB_ID" \
            --lease-token "$LEASE_TOKEN" \
            --error "worker_exit_${RC}" \
            --no-retry)
        NACK_RC=$?
        set -e
        echo "NACK_RC=$NACK_RC NACK_ACK=$NACK_ACK"
    fi
    if [[ "$RC" -ne 0 ]]; then
        rm -f "$WORK_DIR/cu-gpu.lock"
    fi
    cleanup_runtime
    exit "$RC"
}

trap recover_after_exit EXIT
export CU_START_EPOCH="$START_EPOCH" CU_WORKER_PID="$$" JOB_ID CARD_ID LEASE_TOKEN
export PROMPT_FILE META_FILE DONE_FILE LORA WIDTH HEIGHT WORKFLOW SEED
write_runtime "boot"

notify_gpu_lock_issue() {
    local TITLE="$1"
    local DETAIL="$2"
    local EXIT_CODE="$3"
    local ELAPSED_MIN="$(( ($(date +%s) - START_EPOCH) / 60 ))"
    local OPTIONS=()

    if [[ "$DETAIL" == *"保存图片到输出目录时被系统中断"* ]]; then
        OPTIONS+=(
            "差一点点卡在保存那步了 🫠\n我继续盯着，别管它～"
            "图快好了，保存时绊了一下 😵‍💫\n我来收尾，等我发你。"
        )
    elif [[ "$TITLE" == *"自动恢复交付失败"* ]]; then
        OPTIONS+=(
            "图应该出来了，发送卡了一下 📮\n我补发，别急。"
            "像是出图了但没送到你手上 🤏\n我继续补一下。"
        )
    else
        OPTIONS+=(
            "这张有点磨蹭 😵‍💫\n我继续盯着，出了就发你。"
            "还在跑，慢吞吞的 🐢\n你先别管，我看着呢。"
            "它今天有点慢 🫠\n我守着，别急。"
            "这张比平时久一点 ⏳\n我继续等它出来。"
            "还活着，只是慢 😶‍🌫️\n我盯着，出了马上发。"
            "它在憋大招吧 🫣\n我继续看着。"
        )
    fi

    local IDX=$(( RANDOM % ${#OPTIONS[@]} ))
    local NOTIFY_MSG="${OPTIONS[$IDX]}\n\n已跑约 ${ELAPSED_MIN} 分钟。"
    local CHAT_ID
    CHAT_ID=$(python3 -c "import json; print(json.load(open('${CONFIG_FILE}')).get('telegram_chat_id', ''))" 2>/dev/null || echo "")
    openclaw message send --channel telegram -t "$CHAT_ID" -m "$NOTIFY_MSG" 2>/dev/null || true
    echo "📢 已通知用户，等待确认"
}

echo "=== cu-worker $(date '+%Y-%m-%d %H:%M:%S') ==="
echo "PROMPT_FILE=$PROMPT_FILE"
echo "META_FILE=$META_FILE"
echo "DONE_FILE=$DONE_FILE"
echo "JOB_ID=$JOB_ID"
echo "CARD_ID=$CARD_ID"

# claim 已在 spawn 前持久化；worker 必须以同一 token 确认 ready。
READY_OK=0
for READY_ATTEMPT in 1 2 3; do
    set +e
    READY_ACK=$(python3 "$QUEUE_SCRIPT" ready --job-id "$JOB_ID" --lease-token "$LEASE_TOKEN")
    READY_RC=$?
    set -e
    READY_OK=$(READY_JSON="$READY_ACK" python3 -c '
import json, os
try:
    data = json.loads(os.environ.get("READY_JSON") or "{}")
    print("1" if data.get("ok") and data.get("status") == "running" else "0")
except Exception:
    print("0")
')
    [ "$READY_RC" -eq 0 ] && [ "$READY_OK" = "1" ] && break
    echo "⚠️ ready ACK 失败 (${READY_ATTEMPT}/3): ${READY_ACK}" >&2
    [ "$READY_ATTEMPT" -lt 3 ] && sleep 0.2
done
if [ "$READY_OK" != "1" ]; then
    echo "❌ worker ready 未获 QueueStore 确认，拒绝启动 GPU" >&2
    rm -f "$WORK_DIR/cu-gpu.lock"
    exit 1
fi

HEARTBEAT_INTERVAL="${CU_HEARTBEAT_INTERVAL:-30}"
(
    while sleep "$HEARTBEAT_INTERVAL"; do
        set +e
        HEARTBEAT_ACK=$(python3 "$QUEUE_SCRIPT" heartbeat --job-id "$JOB_ID" --lease-token "$LEASE_TOKEN")
        HEARTBEAT_RC=$?
        set -e
        HEARTBEAT_OK=$(HEARTBEAT_JSON="$HEARTBEAT_ACK" python3 -c '
import json, os
try:
    print("1" if json.loads(os.environ.get("HEARTBEAT_JSON") or "{}").get("ok") else "0")
except Exception:
    print("0")
')
        if [ "$HEARTBEAT_RC" -ne 0 ] || [ "$HEARTBEAT_OK" != "1" ]; then
            echo "⚠️ heartbeat 停止: ${HEARTBEAT_ACK}" >&2
            break
        fi
    done
) &
HEARTBEAT_PID=$!

write_runtime "startup"

bash "$SCRIPT_DIR/comfyui-start.sh" start
write_runtime "rendering"

DRAW_SIZE_ARGS=()
if [[ -n "$WIDTH" && -n "$HEIGHT" ]]; then
    DRAW_SIZE_ARGS=(--width "$WIDTH" --height "$HEIGHT")
fi
LORA_ARGS=()
if [[ -n "$LORA" ]]; then
    LORA_ARGS=(--lora "$LORA")
fi
CMD=(python3 "$SCRIPT_DIR/cu-draw-card.py" --prompt-file "$PROMPT_FILE")
if [[ ${#LORA_ARGS[@]} -gt 0 ]]; then
    CMD+=("${LORA_ARGS[@]}")
fi
if [[ ${#DRAW_SIZE_ARGS[@]} -gt 0 ]]; then
    CMD+=("${DRAW_SIZE_ARGS[@]}")
fi
if [[ -n "$WORKFLOW" ]]; then
    CMD+=(--mode "$WORKFLOW")
fi
if [[ -n "$SEED" ]]; then
    CMD+=(--seed "$SEED")
fi

set +e
env DONE_FILE="$DONE_FILE" META_FILE="$META_FILE" "${CMD[@]}"
DRAW_RC=$?
set -e

echo "DRAW_RC=$DRAW_RC"

if [[ -f "$DONE_FILE" ]]; then
    echo "✅ DONE marker found → start deliver"
    DELIVER_ATTEMPTED=1
    write_runtime "delivering"
    set +e
    env DONE_FILE="$DONE_FILE" META_FILE="$META_FILE" \
        JOB_ID="$JOB_ID" CARD_ID="$CARD_ID" LEASE_TOKEN="$LEASE_TOKEN" \
        WORKFLOW="$WORKFLOW" REQUESTED_SEED="$SEED" \
        bash "$SCRIPT_DIR/cu-deliver.sh"
    DELIVER_RC=$?
    set -e
    echo "DELIVER_RC=$DELIVER_RC"
    if [[ "$DELIVER_RC" -ne 0 ]]; then
        echo "⚠️ Deliver failed after DONE marker"
        notify_gpu_lock_issue "⚠️ 图片已生成，但交付失败" "Telegram 交付阶段异常退出（DONE marker 已生成）" "$DELIVER_RC"
    fi
    exit "$DELIVER_RC"
fi

echo "⚠️ DONE marker missing → skip deliver"
if [[ "$DRAW_RC" -eq 42 ]]; then
    notify_gpu_lock_issue "⚠️ 输出目录保存失败" "ComfyUI 已完成采样，但在保存图片到输出目录时被系统中断（已自动重试 1 次仍失败）" "$DRAW_RC"
else
    notify_gpu_lock_issue "⚠️ GPU 渲染超时/失败" "DONE marker 缺失，渲染结果未进入交付阶段" "$DRAW_RC"
fi

# ── 渲染失败：以 lease token 条件 nack，禁止无条件改写他人任务 ──
if [ -n "${HEARTBEAT_PID:-}" ]; then
    kill "$HEARTBEAT_PID" 2>/dev/null || true
    wait "$HEARTBEAT_PID" 2>/dev/null || true
    HEARTBEAT_PID=""
fi
set +e
NACK_ACK=$(python3 "$QUEUE_SCRIPT" nack \
    --job-id "$JOB_ID" \
    --lease-token "$LEASE_TOKEN" \
    --error "render_failed_rc_${DRAW_RC}" \
    --no-retry)
NACK_RC=$?
set -e
NACK_OK=$(NACK_JSON="$NACK_ACK" python3 -c '
import json, os
try:
    print("1" if json.loads(os.environ.get("NACK_JSON") or "{}").get("ok") else "0")
except Exception:
    print("0")
')
if [ "$NACK_RC" -eq 0 ] && [ "$NACK_OK" = "1" ]; then
    NACKED=1
    echo "🧾 QueueStore 已标记失败: $NACK_ACK"
else
    echo "⚠️ QueueStore nack 未确认: $NACK_ACK" >&2
fi

# ── 渲染失败：把卡状态标记为 failed，避免「看似已提交实际未渲染」──
if [ -n "${META_FILE:-}" ] && [ -f "$META_FILE" ]; then
    python3 -c "
import json, os
from pathlib import Path
meta_path = '$META_FILE'
try:
    meta = json.load(open(meta_path, encoding='utf-8'))
    card_id = meta.get('card_id')
    if card_id:
        card_file = Path.home() / '.openclaw' / 'draw-cards' / 'cards' / f'{card_id}.json'
        if card_file.exists():
            card = json.load(open(card_file, encoding='utf-8'))
            card['status'] = 'failed'
            card['render_error'] = 'incomplete metadata / render failure (DONE marker missing)'
            card.setdefault('history', []).append({
                'timestamp': __import__('datetime').datetime.now().isoformat(),
                'action': 'render_failed',
                'changes': {'status': 'submitted → failed', 'reason': 'DONE marker missing after render'}
            })
            with open(card_file, 'w', encoding='utf-8') as f:
                json.dump(card, f, ensure_ascii=False, indent=2)
            print(f'✅ 卡片 {card_id} 状态已标记为 failed')
except Exception as e:
    print(f'❌ 标记卡状态失败: {e}')
" || true
fi

# ── 自愈：释放锁 + 重启 ComfyUI + 续跑队列 ──
echo "🩹 启动自愈流程..."
rm -f "$WORK_DIR/cu-gpu.lock"
echo "🔓 GPU 锁已释放"
# 清理当前失败 worker 自己的 PID 文件，避免 resume 误判 worker_running 而不续跑队列
for pf in "$WORK_DIR"/cu-submit-bg_*.pid; do
    [ -f "$pf" ] || continue
    if [ "$(cat "$pf" 2>/dev/null)" = "$$" ]; then
        rm -f "$pf" && echo "🧹 已清理自身 PID 文件: $pf"
    fi
done
bash "$SCRIPT_DIR/comfyui-start.sh" stop 2>/dev/null || true
sleep 3
bash "$SCRIPT_DIR/comfyui-start.sh" start
python3 "$SCRIPT_DIR/cu-queue.py" resume 2>/dev/null || echo "⚠️ 队列续跑未成功（可能队列为空）"
echo "✅ 自愈完成"
exit "$DRAW_RC"
