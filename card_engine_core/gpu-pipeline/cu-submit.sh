#!/bin/bash
CARD_ENGINE_TMP="${CARD_ENGINE_TMP:-/tmp/cu-card}"
mkdir -p "$CARD_ENGINE_TMP"
# ============================================
# cu-submit.sh — 抽卡提交脚本
# 封装提交全流程：写 meta/prompt → GPU锁 → 入队/提交
# ============================================
#
# 用法:
#   bash cu-submit.sh \
#     --prompt "英文prompt" \
#     --person "邱淑贞" \
#     --scene "公共厕所 火车站" \
#     --theme "监控偷窥" \
#     --narrative "深夜火车站..." \
#     --lighting "冷白荧光顶光" \
#     --style "CCTV监控纪实·鱼眼" \
#     [--lora girlslike_zi_qsz] \
#     [--reply-id 12345]
#
# ─── 对应 CARD_ENGINE_WORKFLOW.md STEP 5 ───
#
# 参数说明:
#   --prompt     英文 prompt（必填）
#   --person     人物名：明星中文名 / 身份职业如 OL、护士、大学生（默认模式必填）
#   --scene      场景关键词（默认模式必填）
#   --theme      主题（默认模式必填）
#   --narrative  中文场景叙事（默认模式必填）
#   --lighting   光影描述（默认模式必填）
#   --style      风格标签（默认模式必填）
#   --lora       LoRA 文件名（可选，明星卡必填）
#   --reply-id   Telegram message_id 用于回复引用（可选）
#   --width/--height  手动指定输出尺寸（可选）
#   --workflow   指定 workflow 别名（可选）
#   --raw        裸 prompt 直投模式：仅 --prompt 必填，其余元数据可选
#
# 裸 prompt 直投（卡引擎模板之外的快速通道）：
#   bash cu-submit.sh --raw --prompt "<完整英文prompt>" [--person "<人物名>"] [--scene "<场景>"] [--theme "<主题>"] [--narrative "<中文叙事>"] [--lighting "<光影>"] [--style "<风格>"]
#   只有显式传 --raw 才允许省略 person/scene/theme/narrative/lighting/style。
#
# ============================================

set -euo pipefail

show_help() {
    cat <<EOF
🚀 GPU 渲染任务提交脚本 (cu-submit.sh)
=========================================
用法:
  1. 默认卡片渲染模式（由卡引擎调用，需提供全量元数据）：
     bash cu-submit.sh \\
       --prompt "<英文prompt>" \\
       --person "<角色/演员>" \\
       --scene "<具体场景>" \\
       --theme "<主题模板>" \\
       --narrative "<中文叙事>" \\
       --lighting "<光影配方>" \\
       --style "<风格标签>" \\
       [--lora "<LoRA文件名>"] \\
       [--width <宽度>] [--height <高度>] \\
       [--workflow "<工作流别名>"] \\
       [--reply-id <Telegram消息ID>]

  2. 裸 Prompt 直投模式（快速测试或纯手工词渲染，由 AI 或主人调用）：
     bash cu-submit.sh --raw \\
       --prompt "<完整英文prompt>" \\
       [--person "<人物>"] [--scene "<场景>"] \\
       [--theme "<主题>"] [--narrative "<中文叙事>"] \\
       [--lighting "<光影>"] [--style "<风格>"]

选项说明:
  --prompt     英文提示词 (必填)
  --raw        开启直投旁路模式，允许省略元数据 (直投必填)
  --person     角色身份或演员中文名 (入队时自动绑定 LoRA)
  --scene      场景中文位置关键词
  --theme      主题分类 (如 监控偷窥, 课间, 浴室)
  --narrative  中文长标题或场景叙事 (展示于卡片正文)
  --lighting   光影描述 (如 暖黄夕阳, 冷白荧光)
  --style      画面艺术风格或胶片质感 (如 胶片纪实, 鱼眼)
  --lora       人物 LoRA 名字 (可选)
  --width      强制输出图像宽度 (可选)
  --height     强制输出图像高度 (可选)
  --workflow   强制指定 ComfyUI 工作流 (可选)
  --seed       固定渲染 Seed (可选)
  --reply-id   Telegram 引用回复消息 ID (可选)
  --card       关联卡片 ID (可选)
  --user-input 用户原始指令 (可选)
EOF
    exit 0
}

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" || "${1:-}" == "help" ]]; then
    show_help
fi

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
CONFIG_FILE="${SCRIPT_DIR}/../config.json"
WORK_DIR="${CU_WORK_DIR:-$(python3 -c "import json,os; c=json.load(open('${CONFIG_FILE}')); print(os.path.expanduser(c.get('tmp_dir') or '/tmp/cu-card'))")}"

# ── 参数解析 ───────────────────────────
PROMPT=""
PERSON=""
SCENE=""
THEME=""
NARRATIVE=""
LIGHTING=""
STYLE=""
LORA=""
REPLY_ID=""
WIDTH=""
HEIGHT=""
WORKFLOW=""
SEED=""
IDEMPOTENCY_KEY=""
USER_INPUT=""
RAW_MODE=""

CARD_ID=""

while [[ $# -gt 0 ]]; do
    case "$1" in
        --raw)       RAW_MODE="1"; shift ;;
        --prompt)    PROMPT="$2"; shift 2 ;;
        --person)    PERSON="$2"; shift 2 ;;
        --scene)     SCENE="$2"; shift 2 ;;
        --theme)     THEME="$2"; shift 2 ;;
        --narrative) NARRATIVE="$2"; shift 2 ;;
        --lighting)  LIGHTING="$2"; shift 2 ;;
        --style)     STYLE="$2"; shift 2 ;;
        --lora)      LORA="$2"; shift 2 ;;
        --reply-id)  REPLY_ID="$2"; shift 2 ;;
        --width)     WIDTH="$2"; shift 2 ;;
        --height)    HEIGHT="$2"; shift 2 ;;
        --workflow)  WORKFLOW="$2"; shift 2 ;;
        --seed)      SEED="$2"; shift 2 ;;
        --idempotency-key) IDEMPOTENCY_KEY="$2"; shift 2 ;;
        --user-input) USER_INPUT="$2"; shift 2 ;;
        --card)      CARD_ID="$2"; shift 2 ;;
        *) echo "未知参数: $1"; exit 1 ;;
    esac
done

# ── 必填校验 ───────────────────────────
if [[ -z "$PROMPT" ]]; then
    echo "❌ --prompt 是必填参数"
    echo "用法: $0 --prompt <英文prompt> --person ... --scene ... --theme ... --narrative ... --lighting ... --style ... [--lora ...] [--reply-id ...]"
    echo "或:   $0 --raw --prompt <英文prompt> [--person ...] [--scene ...] [--theme ...] [--narrative ...] [--lighting ...] [--style ...]"
    exit 1
fi

if [[ -z "$RAW_MODE" && ( -z "$PERSON" || -z "$SCENE" || -z "$THEME" || -z "$NARRATIVE" || -z "$LIGHTING" || -z "$STYLE" ) ]]; then
    echo "❌ 默认模式缺少必填参数"
    echo "用法: $0 --prompt ... --person ... --scene ... --theme ... --narrative ... --lighting ... --style ... [--lora ...] [--reply-id ...]"
    echo "若要原汁原味直投，请显式加: --raw"
    exit 1
fi

# ── 禁止「素人」 ───────────────────────
if [[ "$PROMPT" == *"素人"* || "$PERSON" == *"素人"* || "$NARRATIVE" == *"素人"* ]]; then
    echo "❌ prompt/person/narrative 中禁止出现「素人」，请替换为具体身份职业（如 OL、护士、大学生、人妻、咖啡店店员等）" >&2
    exit 1
fi

mkdir -p "$WORK_DIR"

# ── 自动清理：删除 >3天 的旧 prompt/meta/done 文件 + 同步清理队列 ──
STALE_MINUTES=4320  # 3天
find "$WORK_DIR" -maxdepth 1 -name 'card_prompt_*.txt' -mmin +$STALE_MINUTES -delete 2>/dev/null || true
find "$WORK_DIR" -maxdepth 1 -name 'card_meta_*.json' -mmin +$STALE_MINUTES -delete 2>/dev/null || true
find "$WORK_DIR" -maxdepth 1 -name 'cu-draw-card-done_*.json' -mmin +$STALE_MINUTES -delete 2>/dev/null || true
# 同步清理队列中引用已删除文件的任务
python3 "$SCRIPT_DIR/cu-queue.py" clean-stale 2>/dev/null || true

# ── 生成唯一时间戳 ─────────────────────
START_EPOCH=$(date +%s)
ts=${START_EPOCH}_$$_$RANDOM

# ── 6.1 写 meta.json ──────────────────
META_FILE="$WORK_DIR/card_meta_${ts}.json"
export CU_PROMPT="$PROMPT" CU_REPLY_ID="$REPLY_ID" CU_PERSON="$PERSON" CU_SCENE="$SCENE" CU_THEME="$THEME"
export CU_NARRATIVE="$NARRATIVE" CU_LIGHTING="$LIGHTING" CU_STYLE="$STYLE"
export CU_WIDTH="$WIDTH" CU_HEIGHT="$HEIGHT" CU_USER_INPUT="$USER_INPUT" CU_META_FILE="$META_FILE"
export CU_CARD_ID="$CARD_ID"
python3 "$SCRIPT_DIR/parse_prompt_meta.py"
echo "📝 meta.json → $META_FILE"

# ── 写 prompt 文件 ────────────────────
PROMPT_FILE="$WORK_DIR/card_prompt_${ts}.txt"
echo "$PROMPT" > "$PROMPT_FILE"
echo "📝 prompt → $PROMPT_FILE"

DONE_FILE="$WORK_DIR/cu-draw-card-done_${ts}.json"

# ── 统一入口：先持久 enqueue，再由 resume 执行 claim→spawn ──
if [ -z "$IDEMPOTENCY_KEY" ]; then
    IDEMPOTENCY_KEY=$(CU_CARD_ID="$CARD_ID" CU_PROMPT="$PROMPT" CU_WORKFLOW="$WORKFLOW" \
        CU_SEED="$SEED" CU_LORA="$LORA" CU_WIDTH="$WIDTH" CU_HEIGHT="$HEIGHT" python3 - <<'PY'
import hashlib
import json
import os

payload = {
    "card_id": os.environ.get("CU_CARD_ID", ""),
    "prompt": os.environ.get("CU_PROMPT", ""),
    "workflow": os.environ.get("CU_WORKFLOW", ""),
    "seed": os.environ.get("CU_SEED", ""),
    "lora": os.environ.get("CU_LORA", ""),
    "width": os.environ.get("CU_WIDTH", ""),
    "height": os.environ.get("CU_HEIGHT", ""),
}
raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
print(hashlib.sha256(raw.encode("utf-8")).hexdigest())
PY
)
fi

ENQUEUE_ARGS=(
    enqueue "$PROMPT_FILE" "$META_FILE" "$DONE_FILE"
    --card-id "$CARD_ID"
    --idempotency-key "$IDEMPOTENCY_KEY"
)
[ -n "$LORA" ] && ENQUEUE_ARGS+=(--lora "$LORA")
[ -n "$WIDTH" ] && ENQUEUE_ARGS+=(--width "$WIDTH")
[ -n "$HEIGHT" ] && ENQUEUE_ARGS+=(--height "$HEIGHT")
[ -n "$WORKFLOW" ] && ENQUEUE_ARGS+=(--workflow "$WORKFLOW")
[ -n "$SEED" ] && ENQUEUE_ARGS+=(--seed "$SEED")

set +e
ENQUEUE_RESULT=$(python3 "$SCRIPT_DIR/cu-queue.py" "${ENQUEUE_ARGS[@]}")
ENQUEUE_RC=$?
set -e
ENQUEUE_OK=$(ENQUEUE_JSON="$ENQUEUE_RESULT" python3 -c '
import json, os
try:
    print("1" if json.loads(os.environ.get("ENQUEUE_JSON") or "{}").get("ok") else "0")
except Exception:
    print("0")
')
if [ "$ENQUEUE_RC" -ne 0 ] || [ "$ENQUEUE_OK" != "1" ]; then
    echo "❌ 队列入队失败" >&2
    rm -f "$PROMPT_FILE" "$META_FILE" "$DONE_FILE"
    printf '%s\n' "$ENQUEUE_RESULT"
    [ "$ENQUEUE_RC" -ne 0 ] && exit "$ENQUEUE_RC"
    exit 1
fi

ENQUEUE_STATUS=$(ENQUEUE_JSON="$ENQUEUE_RESULT" python3 -c 'import json,os; print(json.loads(os.environ["ENQUEUE_JSON"]).get("status",""))')
JOB_ID=$(ENQUEUE_JSON="$ENQUEUE_RESULT" python3 -c 'import json,os; print(json.loads(os.environ["ENQUEUE_JSON"]).get("job_id",""))')
if [ "$ENQUEUE_STATUS" = "duplicate" ]; then
    echo "♻️ 任务已存在，不重复提交（job_id=${JOB_ID}）"
    rm -f "$PROMPT_FILE" "$META_FILE" "$DONE_FILE"
    DUP_ACK=$(ENQUEUE_JSON="$ENQUEUE_RESULT" python3 - <<'PY'
import json
import os
enqueue = json.loads(os.environ.get("ENQUEUE_JSON") or "{}")
job = enqueue.get("job") or {}
print(json.dumps({
    "ok": True,
    "accepted": True,
    "status": "duplicate",
    "job_id": enqueue.get("job_id"),
    "card_id": enqueue.get("card_id"),
    "state": enqueue.get("state"),
    "idempotency_key": job.get("idempotency_key"),
    "workflow": job.get("workflow"),
    "seed": job.get("seed"),
    "enqueue": enqueue,
}, ensure_ascii=False))
PY
)
    printf '%s\n' "$DUP_ACK"
    exit 0
fi

echo "📋 已持久入队（job_id=${JOB_ID}）"
set +e
RESUME_RESULT=$(python3 "$SCRIPT_DIR/cu-queue.py" resume)
RESUME_RC=$?
set -e

FINAL_ACK=$(ENQUEUE_JSON="$ENQUEUE_RESULT" RESUME_JSON="$RESUME_RESULT" python3 - <<'PY'
import json
import os

enqueue = json.loads(os.environ.get("ENQUEUE_JSON") or "{}")
try:
    resume = json.loads(os.environ.get("RESUME_JSON") or "{}")
except Exception:
    resume = {"ok": False, "status": "invalid_resume_ack", "raw": os.environ.get("RESUME_JSON", "")}
resume_status = resume.get("status")
enqueue_job_id = enqueue.get("job_id")
resume_job_id = resume.get("job_id")
job = enqueue.get("job") or {}
started_job_id = resume_job_id if resume_status == "started" else None
started_this_job = bool(
    resume_status == "started"
    and enqueue_job_id
    and resume_job_id == enqueue_job_id
)
if resume_status == "started":
    ok, status = True, ("started" if started_this_job else "queued")
elif resume_status in {"busy", "lock_busy", "empty"}:
    ok, status = True, "queued"
elif resume_status == "spawn_failed":
    if resume_job_id and resume_job_id != enqueue_job_id:
        ok, status = True, "queued"
    else:
        ok, status = False, "spawn_failed"
else:
    ok, status = False, "resume_failed"
print(json.dumps({
    "ok": ok,
    "accepted": True,
    "status": status,
    "job_id": enqueue_job_id,
    "card_id": enqueue.get("card_id"),
    "idempotency_key": enqueue.get("idempotency_key") or job.get("idempotency_key"),
    "workflow": job.get("workflow"),
    "seed": job.get("seed"),
    "state": (resume.get("state") if started_this_job else enqueue.get("state")),
    "position": enqueue.get("position"),
    "resume_status": resume_status,
    "started_job_id": started_job_id,
    "pid": resume.get("pid"),
    "log": resume.get("log"),
    "enqueue": enqueue,
    "resume": resume,
}, ensure_ascii=False))
PY
)

FINAL_OK=$(FINAL_JSON="$FINAL_ACK" python3 -c 'import json,os; print("1" if json.loads(os.environ["FINAL_JSON"]).get("ok") else "0")')
if [ "$FINAL_OK" = "1" ]; then
    ETA_JSON=$(python3 "$SCRIPT_DIR/cu-queue.py" avg-eta 2>/dev/null || echo '{}')
    EST_TIME=$(ETA_JSON="$ETA_JSON" python3 -c '
import json, os
data = json.loads(os.environ.get("ETA_JSON") or "{}")
avg = data.get("avg_min")
n = data.get("sample_count") or 0
if avg:
    print(f"（根据最近 {n} 次记录，预计约 {avg} 分钟）")
')
    [ -n "$EST_TIME" ] && echo "✅ 提交已受理 ${EST_TIME}" || echo "✅ 提交已受理"
else
    echo "⚠️ 任务已入队，但本次续跑未完成（resume_rc=${RESUME_RC}）" >&2
fi
printf '%s\n' "$FINAL_ACK"
[ "$FINAL_OK" = "1" ] && exit 0
exit 1
