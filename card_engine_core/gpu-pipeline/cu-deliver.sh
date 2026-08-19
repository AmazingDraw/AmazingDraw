#!/bin/bash
CARD_ENGINE_TMP="${CARD_ENGINE_TMP:-/tmp/cu-card}"
mkdir -p "$CARD_ENGINE_TMP"
# cu-deliver.sh — 自动交付：读 done.json + meta.json → 发 Telegram
# 由 cu-draw-card.py && cu-deliver.sh 链式调用，画完自动发图
# 环境变量：META_FILE / DONE_FILE / JOB_ID / LEASE_TOKEN（必传）
#             CARD_ID / WORKFLOW / REQUESTED_SEED（worker 透传上下文）
set -euo pipefail

show_help() {
    cat <<EOF
📤 GPU 渲染自动交付与 Telegram 发图脚本 (cu-deliver.sh)
=========================================
本脚本读取渲染完成后的标记文件与元数据，执行自动重命名、归档，并推送发图至 Telegram 频道。

用法:
  环境变量参数控制模式 (常规调用)：
    export META_FILE="/tmp/cu-card/card_meta_xxx.json"
    export DONE_FILE="/tmp/cu-card/cu-draw-card-done_xxx.json"
    export JOB_ID="job-..."
    export LEASE_TOKEN="..."
    [export CARD_ID="card-..."]
    [export WORKFLOW="portrait-v2"]
    [export REQUESTED_SEED="123456"]
    [export GPU_LOCK="/tmp/cu-card/cu-gpu.lock"]
    bash cu-deliver.sh

环境变量说明:
  META_FILE  存储卡片渲染元数据、人物、场景、Caption 信息的 JSON 文件路径 (必填)
  DONE_FILE  ComfyUI 渲染成功后落盘的标记 JSON 文件路径 (必填)
  JOB_ID     QueueStore v2 任务 ID (必填)
  LEASE_TOKEN  worker claim 的条件 ACK 令牌 (必填)
  CARD_ID    关联卡片 ID (可选，通常由 worker 透传)
  WORKFLOW   本任务工作流别名 (可选，通常由 worker 透传)
  REQUESTED_SEED  提交时指定的 Seed；实际 Seed 仍以 DONE_FILE 为准 (可选)
  GPU_LOCK   GPU 排队排他锁路径，交付完成后脚本会自动释放此锁 (可选，默认 $CARD_ENGINE_TMP/cu-gpu.lock)
  CU_BETWEEN_CARDS  连抽卡间策略（仅队列非空时生效；单张跳过）:
                    restart（默认）| free | off
  CU_FREE_BETWEEN   仅当 CU_BETWEEN_CARDS=free 时生效；=0 可关 /free
  CU_FREE_TIMEOUT   /free 等待显存回升超时秒数（默认 90）
  CU_AUTO_STOP_DELAY 队列空后延迟停 Comfy 秒数（默认 60）
EOF
    exit 0
}

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" || "${1:-}" == "help" ]]; then
    show_help
fi

# ═══ 日志落地(调试用,自动轮转保留最近 5 次) ═══
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONFIG_FILE="${SCRIPT_DIR}/../config.json"
TMP_DIR="${CU_WORK_DIR:-$(python3 -c "import json,os; c=json.load(open('${CONFIG_FILE}')); print(os.path.expanduser(c.get('tmp_dir') or '/tmp/cu-card'))")}"
WORKSPACE="${CU_WORKSPACE:-$(python3 -c "import json, os; print(os.path.expanduser(json.load(open('${CONFIG_FILE}')).get('openclaw_workspace_dir') or '$HOME/.openclaw/workspace'))")}"
QUEUE_SCRIPT="${SCRIPT_DIR}/cu-queue.py"
LOG_DIR="$TMP_DIR"
LOG_FILE="$LOG_DIR/cu-deliver.log"
for i in 4 3 2 1; do
    [ -f "$LOG_FILE.$i" ] && mv "$LOG_FILE.$i" "$LOG_FILE.$((i+1))" 2>/dev/null
true
done
[ -f "$LOG_FILE" ] && mv "$LOG_FILE" "$LOG_FILE.1" 2>/dev/null
true
exec 2> >(tee -a "$LOG_FILE" >&2)
echo "=== cu-deliver $(date '+%Y-%m-%d %H:%M:%S') ===" >&2
echo "META_FILE=$META_FILE" >&2

DONE_FILE="${DONE_FILE:-$TMP_DIR/cu-draw-card-done.json}"
JOB_ID="${JOB_ID:-${CU_JOB_ID:-}}"
CARD_ID="${CARD_ID:-${CU_CARD_ID:-}}"
LEASE_TOKEN="${LEASE_TOKEN:-${CU_LEASE_TOKEN:-}}"
WORKFLOW="${WORKFLOW:-${CU_WORKFLOW:-}}"
REQUESTED_SEED="${REQUESTED_SEED:-${CU_SEED:-}}"
TOKEN_FILE="$WORKSPACE/.bot_tokens"
CHAT_ID=$(python3 -c "import json; print(json.load(open('${CONFIG_FILE}')).get('telegram_chat_id', ''))")
GPU_LOCK="${GPU_LOCK:-$TMP_DIR/cu-gpu.lock}"
FAILED_DIR="$TMP_DIR/failed-delivery"
SUCCESS_DIR="$TMP_DIR/success-delivery"
mkdir -p "$FAILED_DIR" "$SUCCESS_DIR"

LOCK_RELEASED=0
release_gpu_lock() {
    if [ "${LOCK_RELEASED:-0}" -eq 0 ]; then
        rm -f "$GPU_LOCK"
        LOCK_RELEASED=1
        echo "🔓 GPU 锁已释放"
    fi
}
trap release_gpu_lock EXIT

# ── 0. 检查 meta 文件 ──
if [ -z "$META_FILE" ]; then
    echo "❌ META_FILE env not set" >&2
    exit 1
fi
if [ -z "$JOB_ID" ] || [ -z "$LEASE_TOKEN" ]; then
    echo "❌ JOB_ID / LEASE_TOKEN env not set" >&2
    exit 1
fi

# ── 0.5 读取投递位置选项配置 ──
DELIVERY_TELEGRAM=$(python3 -c "import json; print('1' if json.load(open('${CONFIG_FILE}')).get('delivery_telegram', True) else '0')")
DELIVERY_WEBUI=$(python3 -c "import json; print('1' if json.load(open('${CONFIG_FILE}')).get('delivery_webui', True) else '0')")
echo "📤 Delivery Options: Telegram=$DELIVERY_TELEGRAM, WebUI=$DELIVERY_WEBUI"

# ── 1. 读 done.json ──
if [ ! -f "$DONE_FILE" ]; then
    echo "❌ $DONE_FILE not found" >&2
    exit 1
fi

FILE=$(python3 -c "import json,sys; print(json.load(open('$DONE_FILE'))['file'])")
SEED=$(python3 -c "import json,sys; print(json.load(open('$DONE_FILE'))['seed'])")
ELAPSED=$(python3 -c "import json,sys; print(json.load(open('$DONE_FILE'))['elapsed_min'])")

echo "📦 File: $FILE"
echo "🎲 Seed: $SEED"
echo "⏱️  Elapsed: ${ELAPSED}分钟"

# ── 1.5 重命名为中文标题 + 搬运到归档目录（本地盘 → 外置卷） ──
# Comfy 输出在本地盘；优先拷到 output_dir_archive。外置盘超时/失败时：
# 在本地 output 完成同规则中文命名，继续 Telegram/WebUI 投递（绝不阻塞放锁）。
ARCHIVE_DIR=$(python3 -c "import json, os; print(os.path.expanduser(json.load(open('${CONFIG_FILE}')).get('output_dir_archive', '')))" 2>/dev/null || echo "")
ARCHIVE_CP_TIMEOUT="${ARCHIVE_CP_TIMEOUT:-90}"
if [ -f "$META_FILE" ]; then
    export FILE META_FILE ARCHIVE_DIR DONE_FILE ARCHIVE_CP_TIMEOUT
    RENAME_RESULT=$(python3 - <<'PY'
import json, os, re, shutil, signal
from pathlib import Path

src = Path(os.environ.get("FILE") or "")
meta_path = Path(os.environ.get("META_FILE") or "")
archive_dir = (os.environ.get("ARCHIVE_DIR") or "").strip()
done_path = Path(os.environ.get("DONE_FILE") or "")
timeout_s = int(os.environ.get("ARCHIVE_CP_TIMEOUT") or "90")

def unique(path: Path) -> Path:
    if not path.exists():
        return path
    base = path.with_suffix("")
    i = 1
    while True:
        cand = Path(f"{base}_{i}.png")
        if not cand.exists():
            return cand
        i += 1

def chinese_name(meta: dict) -> str:
    person = (meta.get("person") or "").strip()
    scene = (meta.get("scene") or "").strip()
    theme = (meta.get("theme") or "").strip()
    if not (person and scene):
        return ""
    name = f"{person}-{scene}-{theme}" if theme else f"{person}-{scene}"
    name = re.sub(r"[^\u4e00-\u9fff\w.-]", "-", name)
    name = re.sub(r"-+", "-", name).strip("-")
    return f"{name}.png"

def update_done(final: Path) -> None:
    if not done_path.exists():
        return
    try:
        data = json.loads(done_path.read_text(encoding="utf-8"))
        data["file"] = str(final)
        data["filename"] = final.name
        done_path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass

out = {"ok": False, "file": str(src), "mode": "skip", "msg": ""}
if not (src.is_file() and meta_path.is_file()):
    print(json.dumps(out, ensure_ascii=False))
    raise SystemExit(0)

try:
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
except Exception:
    print(json.dumps(out, ensure_ascii=False))
    raise SystemExit(0)

fname = chinese_name(meta)
if not fname:
    print(json.dumps(out, ensure_ascii=False))
    raise SystemExit(0)

local_path = unique(src.parent / fname)
archive_path = None
if archive_dir and Path(archive_dir).is_dir():
    archive_path = unique(Path(archive_dir) / fname)

final = None
mode = "local_rename"
msg = ""

class _Timeout(Exception):
    pass

def _on_alarm(signum, frame):
    raise _Timeout("archive_cp_timeout")

if archive_path is not None and archive_path.parent.resolve() != src.parent.resolve():
    signal.signal(signal.SIGALRM, _on_alarm)
    signal.alarm(max(5, timeout_s))
    try:
        shutil.copy2(src, archive_path)
        signal.alarm(0)
        if archive_path.is_file() and archive_path.stat().st_size == src.stat().st_size:
            src.unlink(missing_ok=True)
            final = archive_path
            mode = "archive"
            msg = f"Moved to archive: {archive_path.name} (源已删, {archive_path.stat().st_size}B)"
        else:
            archive_path.unlink(missing_ok=True)
            msg = "archive copy size mismatch, fallback local rename"
    except _Timeout:
        signal.alarm(0)
        try:
            archive_path.unlink(missing_ok=True)
        except Exception:
            pass
        msg = f"archive copy timeout ({timeout_s}s), fallback local rename"
    except Exception as e:
        signal.alarm(0)
        try:
            archive_path.unlink(missing_ok=True)
        except Exception:
            pass
        msg = f"archive copy failed ({type(e).__name__}), fallback local rename"

if final is None:
    try:
        if src.resolve() != local_path.resolve():
            src.rename(local_path)
        final = local_path
        mode = "local_rename" if mode != "archive" else mode
        if not msg:
            msg = f"Renamed: {final.name}"
        elif "fallback" in msg:
            msg = f"{msg} → {final.name}"
    except Exception as e:
        final = src if src.is_file() else None
        mode = "keep_src"
        msg = f"local rename failed ({type(e).__name__}), keep source"

if final is not None:
    update_done(final)
    out = {"ok": True, "file": str(final), "mode": mode, "msg": msg}
else:
    out = {"ok": False, "file": str(src), "mode": mode, "msg": msg or "rename skipped"}
print(json.dumps(out, ensure_ascii=False))
PY
)
    if [ -n "$RENAME_RESULT" ]; then
        NEW_FILE=$(RENAME_RESULT="$RENAME_RESULT" python3 -c 'import json,os; print(json.loads(os.environ["RENAME_RESULT"]).get("file") or "")')
        RENAME_MSG=$(RENAME_RESULT="$RENAME_RESULT" python3 -c 'import json,os; print(json.loads(os.environ["RENAME_RESULT"]).get("msg") or "")')
        RENAME_MODE=$(RENAME_RESULT="$RENAME_RESULT" python3 -c 'import json,os; print(json.loads(os.environ["RENAME_RESULT"]).get("mode") or "")')
        if [ -n "$RENAME_MSG" ]; then
            case "$RENAME_MODE" in
                archive) echo "📦 $RENAME_MSG" ;;
                local_rename)
                    if echo "$RENAME_MSG" | grep -q 'fallback'; then
                        echo "⚠️ archive fallback → local rename: $RENAME_MSG" >&2
                    else
                        echo "📛 $RENAME_MSG"
                    fi
                    ;;
                *) echo "⚠️ $RENAME_MSG" >&2 ;;
            esac
        fi
        if [ -n "$NEW_FILE" ] && [ -f "$NEW_FILE" ]; then
            FILE="$NEW_FILE"
        fi
    fi
fi

# ── 2. 获取 Bot Token ──
BOT_TOKEN=$(python3 -c "import json; print(json.load(open('${CONFIG_FILE}')).get('telegram_bot_token', ''))" 2>/dev/null || echo "")
if [ -z "$BOT_TOKEN" ]; then
    BOT_TOKEN=$(grep "^default=" "$TOKEN_FILE" 2>/dev/null | cut -d= -f2-)
fi
if [ -z "$BOT_TOKEN" ]; then
    echo "❌ Bot token not found in config.json or $TOKEN_FILE" >&2
    exit 1
fi
if ! printf '%s' "$BOT_TOKEN" | grep -Eq '^[0-9]+:[A-Za-z0-9_-]{20,}$'; then
    echo "❌ Invalid Telegram bot token (looks like placeholder/test value)" >&2
    exit 1
fi

# ── 3. 组装 Caption(保留标题 + 引用 + Seed) ──
if [ -f "$META_FILE" ]; then
    CAPTION=$(python3 -c "
import json, re

def convert_markdown_tables_to_lists(text):
    lines = (text or '').splitlines()
    out = []

    def split_row(line):
        return [c.strip() for c in line.strip().strip('|').split('|')]

    def is_table_separator(line):
        s = line.strip()
        if not (s.startswith('|') and s.endswith('|')):
            return False
        cells = [c.strip() for c in s.strip('|').split('|')]
        return bool(cells) and all(re.fullmatch(r':?-{3,}:?', c) for c in cells)

    i = 0
    while i < len(lines):
        line = lines[i]
        s = line.strip()
        if s.startswith('|') and s.endswith('|') and i + 1 < len(lines) and is_table_separator(lines[i + 1]):
            headers = split_row(line)
            i += 2
            row_index = 0
            while i < len(lines):
                row = lines[i].strip()
                if not (row.startswith('|') and row.endswith('|')):
                    break
                cells = split_row(row)
                if len(cells) != len(headers):
                    break
                row_index += 1
                row_title = cells[0] or f'第{row_index}项'
                out.append(row_title)
                for header, cell in zip(headers[1:], cells[1:]):
                    if cell:
                        out.append(f'• {header}：{cell}')
                out.append('')
                i += 1
            while out and out[-1] == '' and (i >= len(lines) or not lines[i].strip()):
                out.pop()
            continue
        out.append(line)
        i += 1

    return '\n'.join(out).strip()


def normalize_caption(raw_caption, seed, elapsed):
    text = (raw_caption or '').replace('{SEED}', str(seed)).replace('{ELAPSED}', str(elapsed)).strip()
    text = re.sub(r'\n\s*Seed:\s*.*$', '', text, flags=re.S).strip()
    text = convert_markdown_tables_to_lists(text)

    title = ''
    quote = ''

    m_title = re.match(r'^(.*?)(?:\n\s*\n|\n<blockquote>)', text, re.S)
    if m_title:
        title = m_title.group(1).strip()
    elif text and '<blockquote>' not in text:
        title = text.strip()

    m_quote = re.search(r'<blockquote>(.*?)</blockquote>', text, re.S)
    if m_quote:
        quote = ' '.join(m_quote.group(1).split())

    body = text
    if title:
        body = re.sub(r'^' + re.escape(title) + r'\s*', '', body, count=1).strip()
    body = re.sub(r'<blockquote>.*?</blockquote>', '', body, flags=re.S).strip()

    parts = []
    if title:
        parts.append(title)
    if quote:
        parts.append(f'<blockquote>{quote}</blockquote>')
    if body:
        parts.append(body)
    if not parts:
        parts.append('🎬 图片已生成 主人请检阅')
    parts.append(f'Seed: {seed} | {elapsed}分钟')
    return '\n\n'.join(parts)

with open('$META_FILE') as f:
    meta = json.load(f)
print(normalize_caption(meta.get('caption', ''), $SEED, $ELAPSED))
")
    REPLY_ID=$(python3 -c "
import json,sys
try:
    meta = json.load(open('$META_FILE'))
    rid = meta.get('reply_id', '')
    rid = '' if rid is None else str(rid).strip()
    print('' if rid.lower() in ('', 'none', 'null') else rid)
except:
    print('')
" 2>/dev/null)
else
    CAPTION=$(printf "🎬 图片已生成 主人请检阅\n\nSeed: %s | %s分钟" "$SEED" "${ELAPSED}")
    REPLY_ID=""
fi

# ── 4. 发送 Telegram（最多重试 3 次，成功才继续队列） ──
RESP=''
SEND_OK='0'
CURL_MAX_TIME="${CURL_MAX_TIME:-120}"
CURL_CONNECT_TIMEOUT="${CURL_CONNECT_TIMEOUT:-15}"

if [ "${DELIVERY_TELEGRAM:-1}" = "1" ]; then
    for ATTEMPT in 1 2 3; do
        if [ -n "$REPLY_ID" ]; then
            echo "↩️  Reply to: $REPLY_ID (attempt $ATTEMPT/3)"
            RESP=$(curl -sS --connect-timeout "$CURL_CONNECT_TIMEOUT" --max-time "$CURL_MAX_TIME" -X POST "https://api.telegram.org/bot${BOT_TOKEN}/sendPhoto" \
              -F "chat_id=${CHAT_ID}" \
              -F "photo=@${FILE}" \
              -F "has_spoiler=true" \
              -F "parse_mode=HTML" \
              -F "caption=${CAPTION}" \
              -F "reply_to_message_id=${REPLY_ID}" ) || RESP=''
        else
            echo "📤 Sending (no reply) attempt $ATTEMPT/3"
            RESP=$(curl -sS --connect-timeout "$CURL_CONNECT_TIMEOUT" --max-time "$CURL_MAX_TIME" -X POST "https://api.telegram.org/bot${BOT_TOKEN}/sendPhoto" \
              -F "chat_id=${CHAT_ID}" \
              -F "photo=@${FILE}" \
              -F "has_spoiler=true" \
              -F "parse_mode=HTML" \
              -F "caption=${CAPTION}" ) || RESP=''
        fi

        SEND_OK=$(echo "$RESP" | python3 -c "
import json,sys
try:
    d=json.load(sys.stdin)
    print('1' if d.get('ok') else '0')
except Exception:
    print('0')
")

        [ "$SEND_OK" = "1" ] && break
        [ "$ATTEMPT" -lt 3 ] && sleep 10
    done

    # ── 5. 解析发送结果 ──
    echo "$RESP" | python3 -c "
import json,sys
try:
    d=json.load(sys.stdin)
    if d.get('ok'):
        print(f\"✅ 已发送 (msg_id={d['result']['message_id']})\")
    else:
        print(f\"❌ 发送失败: {d.get('description','unknown')}\")
except Exception:
    print('❌ 发送失败: invalid telegram response')
"
else
    echo "ℹ️  Telegram 投递已被配置关闭，跳过 Telegram 发送流程"
    SEND_OK="1"
fi

# ── 6. 生成交付摘要工具 ──
write_delivery_summary() {
    local OUT_FILE="$1"
    local MODE="$2"
    OUT_FILE="$OUT_FILE" MODE="$MODE" META_FILE="$META_FILE" DONE_FILE="$DONE_FILE" FILE="$FILE" REPLY_ID="$REPLY_ID" SEED="$SEED" ELAPSED="$ELAPSED" CAPTION="$CAPTION" RESP="$RESP" JOB_ID="$JOB_ID" CARD_ID="$CARD_ID" WORKFLOW="$WORKFLOW" REQUESTED_SEED="$REQUESTED_SEED" \
    python3 - <<'PY'
import json, os, re

def parse_caption_parts(text: str):
    text = (text or '').strip()
    title = ''
    quote = ''
    m_title = re.match(r'^(.*?)(?:\n\s*\n|\n<blockquote>)', text, re.S)
    if m_title:
        title = m_title.group(1).strip()
    elif text and '<blockquote>' not in text:
        title = text.strip().splitlines()[0].strip()
    m_quote = re.search(r'<blockquote>(.*?)</blockquote>', text, re.S)
    if m_quote:
        quote = ' '.join(m_quote.group(1).split())

    person = scene = theme = narrative = lighting = style = ''
    clean_title = title.replace('🎬', '').strip()
    title_parts = [p.strip() for p in clean_title.split('·') if p.strip()]
    if len(title_parts) >= 1: person = title_parts[0]
    if len(title_parts) >= 2: scene = title_parts[1]
    if len(title_parts) >= 3: theme = title_parts[2]
    quote_parts = [p.strip() for p in quote.split('|') if p.strip()]
    if len(quote_parts) >= 1: narrative = quote_parts[0]
    if len(quote_parts) >= 2: lighting = quote_parts[1]
    if len(quote_parts) >= 3: style = quote_parts[2]
    return {
        'title': title,
        'quote': quote,
        'person': person,
        'scene': scene,
        'theme': theme,
        'narrative': narrative,
        'lighting': lighting,
        'style': style,
    }

meta_path = os.environ.get('META_FILE')
meta = {}
if meta_path and os.path.exists(meta_path):
    try:
        meta = json.load(open(meta_path, encoding='utf-8'))
    except Exception:
        meta = {}
caption = os.environ.get('CAPTION', '')
parsed = parse_caption_parts(meta.get('caption') or caption)
telegram_raw = os.environ.get('RESP') or '{}'
try:
    telegram = json.loads(telegram_raw)
except Exception:
    telegram = telegram_raw
payload = {
    'mode': os.environ.get('MODE'),
    'job_id': os.environ.get('JOB_ID'),
    'card_id': os.environ.get('CARD_ID') or meta.get('card_id'),
    'workflow': os.environ.get('WORKFLOW'),
    'requested_seed': os.environ.get('REQUESTED_SEED') or None,
    'meta_file': meta_path,
    'done_file': os.environ.get('DONE_FILE'),
    'image_file': os.environ.get('FILE'),
    'reply_id': os.environ.get('REPLY_ID'),
    'seed': os.environ.get('SEED'),
    'elapsed': os.environ.get('ELAPSED'),
    'caption': caption,
    'telegram_response': telegram,
    'telegram_message_id': ((telegram.get('result') or {}).get('message_id')) if isinstance(telegram, dict) else None,
    'person': meta.get('person') or parsed['person'],
    'scene': meta.get('scene') or parsed['scene'],
    'theme': meta.get('theme') or parsed['theme'],
    'narrative': meta.get('narrative') or meta.get('intent') or parsed['narrative'],
    'lighting': meta.get('lighting') or parsed['lighting'],
    'style': meta.get('style') or parsed['style'],
    'user_input': meta.get('user_input', ''),
    'meta_caption': meta.get('caption', ''),
}
with open(os.environ['OUT_FILE'], 'w', encoding='utf-8') as f:
    json.dump(payload, f, ensure_ascii=False, indent=2)
PY
}

# ── 7. 发送成功/失败后的处理（默认失败不中断批量连抽） ──
DELIVERY_STATUS="success"
if [ "$SEND_OK" = "1" ]; then
    SUCCESS_STAMP=$(date +%s)
    SUCCESS_FILE="$SUCCESS_DIR/delivery_success_${SUCCESS_STAMP}.json"
    write_delivery_summary "$SUCCESS_FILE" "success"
    echo "✅ 交付摘要已保存: $SUCCESS_FILE"
else
    DELIVERY_STATUS="failed"
    FAIL_STAMP=$(date +%s)
    FAIL_FILE="$FAILED_DIR/delivery_failed_${FAIL_STAMP}.json"
    write_delivery_summary "$FAIL_FILE" "failed"
    echo "⚠️ 发送失败，但不中断批量连抽，失败现场已保存: $FAIL_FILE" >&2
fi

# QueueStore 完成态必须由当前 lease token 条件 ACK；重复 ACK 幂等成功。
ACK_OK=0
for ACK_ATTEMPT in 1 2 3; do
    set +e
    ACK_RESULT=$(python3 "$QUEUE_SCRIPT" ack \
        --job-id "$JOB_ID" \
        --lease-token "$LEASE_TOKEN" \
        --result-file "$DONE_FILE")
    ACK_RC=$?
    set -e
    ACK_OK=$(ACK_JSON="$ACK_RESULT" python3 -c '
import json, os
try:
    data = json.loads(os.environ.get("ACK_JSON") or "{}")
    print("1" if data.get("ok") and data.get("status") in {"completed", "already_completed"} else "0")
except Exception:
    print("0")
')
    [ "$ACK_RC" -eq 0 ] && [ "$ACK_OK" = "1" ] && break
    echo "⚠️ QueueStore ACK 失败 (${ACK_ATTEMPT}/3): ${ACK_RESULT}" >&2
    [ "$ACK_ATTEMPT" -lt 3 ] && sleep 0.2
done
if [ "$ACK_OK" != "1" ]; then
    echo "❌ 交付已完成但队列 ACK 未确认；保留 meta/done 现场并返回失败" >&2
    exit 1
fi
echo "✅ QueueStore ACK: $ACK_RESULT"

# 仅在 QueueStore 已确认当前 lease 完成后，才允许该 job 更新卡片。
if [ "${DELIVERY_WEBUI:-1}" = "1" ]; then
    STATUS_SERVICE="${CU_STATUS_SERVICE:-${SCRIPT_DIR}/../webui/card_status_service.py}"
    set +e
    STATUS_RESULT=$(python3 "$STATUS_SERVICE" complete \
        --card "$CARD_ID" \
        --job-id "$JOB_ID" \
        --image "$FILE")
    STATUS_RC=$?
    set -e
    if [ "$STATUS_RC" -eq 0 ]; then
        echo "✅ 卡片完成态同步: $STATUS_RESULT"
    else
        echo "⚠️ 卡片完成态同步已跳过或失败（队列 ACK 已完成）: $STATUS_RESULT" >&2
    fi
else
    echo "ℹ️  WebUI 本地卡片更新已被配置关闭，跳过卡片状态更新"
fi

rm -f "$META_FILE" "$DONE_FILE"
echo "🧹 Cleaned meta + done"

# 统一释放 GPU 锁，保证后续任务可继续
release_gpu_lock

# ── 8. 检查队列：自动续跑下一张；若队列空则延迟自动停 ComfyUI ──
# SCRIPT_DIR, CONFIG_FILE, WORKSPACE are already defined at the top

DETACHED_SPAWN="${SCRIPT_DIR}/detached_spawn.py"
COMFY_STOP_SCRIPT="${SCRIPT_DIR}/comfyui-start.sh"
AUTO_STOP_DELAY="${CU_AUTO_STOP_DELAY:-60}"

# 连抽卡间策略（与 /free 平级可切换；仅队列非空时执行；单张跳过）
# CU_BETWEEN_CARDS=restart（默认）| free | off
# 注意：set -u 下 $VAR 若紧贴全角字符（如（）会被误解析成变量名后缀，
# 因此本段所有插值一律用 ${VAR} 花括号形式。
BETWEEN_MODE="restart"
BETWEEN_RAW=$(printf '%s' "${CU_BETWEEN_CARDS:-restart}" | tr '[:upper:]' '[:lower:]' | tr -d '[:space:]')
case "$BETWEEN_RAW" in
    0|false|no|off|none|skip) BETWEEN_MODE="off" ;;
    free|unload) BETWEEN_MODE="free" ;;
    restart|reboot|stop) BETWEEN_MODE="restart" ;;
    *)
        echo "⚠️ 未知 CU_BETWEEN_CARDS='${BETWEEN_RAW}'，回退默认 restart"
        BETWEEN_MODE="restart"
        ;;
esac

set +e
QUEUE_STATUS_RESULT=$(python3 "$QUEUE_SCRIPT" status 2>/dev/null)
QUEUE_STATUS_RC=$?
set -e
if [ "$QUEUE_STATUS_RC" -eq 0 ]; then
    QUEUE_LEN=$(QUEUE_JSON="$QUEUE_STATUS_RESULT" python3 -c 'import json,os; print(int(json.loads(os.environ.get("QUEUE_JSON") or "{}").get("length") or 0))' 2>/dev/null || echo "1")
else
    # fail closed：队列状态不可确认时按“仍有任务”处理，禁止误判空队列。
    QUEUE_LEN=1
    echo "⚠️ 队列状态读取失败，保守跳过空队列停机判定: $QUEUE_STATUS_RESULT" >&2
fi
if [ "$QUEUE_LEN" -gt 0 ] 2>/dev/null; then
    echo "📌 连抽卡间策略=${BETWEEN_MODE}（队列剩余 ${QUEUE_LEN}）"
    case "$BETWEEN_MODE" in
        restart)
            echo "♻️ 停止 ComfyUI，进程级释放内存后再续跑下一张"
            set +e
            bash "$COMFY_STOP_SCRIPT" stop
            STOP_RC=$?
            set -e
            if [ "$STOP_RC" -ne 0 ]; then
                echo "⚠️ ComfyUI stop 返回非零($STOP_RC)，仍继续 resume（下一 worker 会再 start）"
            fi
            # 给 macOS unified memory / MPS 一点回收窗口（与 cu-worker 自愈分支 sleep 3 对齐）
            sleep 3
            echo "✅ 卡间 restart 完成，准备 resume"
            ;;
        free)
            FREE_RESULT=$(python3 "$QUEUE_SCRIPT" free-memory --if-queued 2>/dev/null || echo '{"status":"error"}')
            FREE_STATUS=$(echo "$FREE_RESULT" | python3 -c 'import json,sys; print((json.load(sys.stdin).get("status") or ""))' 2>/dev/null || echo "")
            if [ "$FREE_STATUS" = "ok" ]; then
                echo "🧹 已 /free 卸载模型，准备续跑下一张"
            elif [ "$FREE_STATUS" = "timeout" ]; then
                echo "⚠️ /free 等待超时，仍继续续跑: $FREE_RESULT"
            elif [ "$FREE_STATUS" = "skipped" ]; then
                echo "ℹ️ 跳过 /free: $FREE_RESULT"
            else
                echo "⚠️ /free 未完全成功($FREE_STATUS)，继续续跑: $FREE_RESULT"
            fi
            ;;
        off)
            echo "ℹ️ 卡间策略=off，跳过 free/restart，直接续跑"
            ;;
    esac
else
    echo "ℹ️ 队列已空（单张或末张），跳过卡间 free/restart"
fi

set +e
RESUME_RESULT=$(python3 "$QUEUE_SCRIPT" resume 2>/dev/null)
RESUME_RC=$?
set -e
RESUME_STATUS=$(echo "$RESUME_RESULT" | python3 -c 'import json,sys; print((json.load(sys.stdin).get("status") or ""))' 2>/dev/null || echo "")

if [ "$RESUME_STATUS" = "started" ]; then
    NEXT_PID=$(echo "$RESUME_RESULT" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("pid",""))' 2>/dev/null || echo "")
    NEXT_LOG=$(echo "$RESUME_RESULT" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("log",""))' 2>/dev/null || echo "")
    echo "🆔 已启动下一张 worker: $NEXT_PID"
    echo "📝 下一张日志: $NEXT_LOG"
    if [ "$DELIVERY_STATUS" = "failed" ]; then
        echo "📋 虽然上一张交付失败，下一张也已继续提交（图文仍按各自 META_FILE 独立对应）"
    else
        echo "📋 队列下一张已自动提交"
    fi
elif [ "$RESUME_STATUS" = "empty" ]; then
    echo "🛌 队列已空，安排 ${AUTO_STOP_DELAY}s 空闲后自动停止 ComfyUI 释放内存"
    STOP_TS=$(date +%s)_$$_$RANDOM
    STOP_LOG="$TMP_DIR/comfyui-auto-stop_${STOP_TS}.log"
    STOP_PID="$TMP_DIR/comfyui-auto-stop_${STOP_TS}.pid"
    python3 "$DETACHED_SPAWN" \
        --cwd "${WORKSPACE}" \
        --log "$STOP_LOG" \
        --pid-file "$STOP_PID" \
        -- bash -lc "sleep ${AUTO_STOP_DELAY}; if [ ! -e '$TMP_DIR/cu-gpu.lock' ] && [ \"\$(python3 '$QUEUE_SCRIPT' status | python3 -c 'import json,sys; print(json.load(sys.stdin).get(\"length\",0))')\" = \"0\" ] && ! pgrep -f 'cu-worker\.sh|cu-draw-card\.py' >/dev/null 2>&1; then bash '$COMFY_STOP_SCRIPT' stop; echo 'AUTO_STOP=done'; else echo 'AUTO_STOP=skipped'; fi" >/dev/null || true
    echo "🧹 已安排 ComfyUI 自动停机检查: $STOP_LOG"
else
    echo "⚠️ 队列续跑未成功(rc=${RESUME_RC}): $RESUME_RESULT"
    if [ "$DELIVERY_STATUS" = "failed" ]; then
        echo "⚠️ 本轮交付失败，且队列续跑也未成功"
    fi
fi
