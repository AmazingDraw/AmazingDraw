#!/bin/bash
# ============================================================
# AmazingDraw 发行版安装引导
# 自动创建 OpenClaw 依赖目录 + 生成权威配置 + 校验运行环境
# Releases 提供两套包，文件名里的 cp39 / cp312 就是 Python 主版本。
# 跑 WebUI/CLI 的 Python 必须和 zip 标签一致。
# Apple 自带 /usr/bin/python3 是 3.9，请下 cp39；本机 3.12 请下 cp312。
# ComfyUI 用它自己的 venv，可以和引擎 Python 不是同一个。
# 不要把 .so 和 .pyd 混放，也不要混 3.9/3.12 native。
# Windows：用 Git Bash。PowerShell 直接跑本脚本不行。
# ============================================================
set -euo pipefail

# 非交互：环境变量或 --non-interactive（安装向导不提问）
AMAZINGDRAW_INSTALL_NONINTERACTIVE="${AMAZINGDRAW_INSTALL_NONINTERACTIVE:-0}"
_INSTALL_ARGS=()
for _a in "$@"; do
  case "$_a" in
    --non-interactive|--noninteractive)
      AMAZINGDRAW_INSTALL_NONINTERACTIVE=1
      ;;
    *)
      _INSTALL_ARGS+=("$_a")
      ;;
  esac
done
# 剩余参数目前忽略；保留扩展位
export AMAZINGDRAW_INSTALL_NONINTERACTIVE

ROOT="$(cd "$(dirname "$0")" && pwd)"
# zip 根或仓库根：若当前目录下已有 tree/（即在 dist/ 里跑），则进入 tree。
# 不会向上查找 dist；解压后的 zip 根没有 tree/，ROOT 保持为 zip 根。
if [ -d "$ROOT/tree" ]; then ROOT="$ROOT/tree"; fi

# ── 平台 ──
UNAME_S="$(uname -s 2>/dev/null || echo unknown)"
IS_WIN=0
case "$UNAME_S" in
  MINGW*|MSYS*|CYGWIN*) IS_WIN=1 ;;
esac

NATIVE_DIR="$ROOT/card_engine_core/native"

# Git Bash POSIX → 给 Windows python.exe（正斜杠，避免 cygpath -w 的反斜杠被 MSYS 拧）
py_path() {
  if [ "$IS_WIN" = 1 ] && command -v cygpath >/dev/null 2>&1; then
    cygpath -m "$1"
  else
    printf '%s' "$1"
  fi
}

# Windows / 混用路径 → Git Bash POSIX，供 mkdir / cp / [ -f ]
bash_path() {
  if [ "$IS_WIN" = 1 ] && command -v cygpath >/dev/null 2>&1; then
    cygpath -u "$1"
  else
    printf '%s' "$1"
  fi
}

# ── 收集致命错误（最后统一打印并 exit 1）──
FATAL_ITEMS=()
fatal_add() { FATAL_ITEMS+=("$1"); }
fail_if_fatal() {
  if [ "${#FATAL_ITEMS[@]}" -gt 0 ]; then
    echo ""
    echo "== 安装失败：硬依赖未满足 =="
    local i
    for i in "${FATAL_ITEMS[@]}"; do
      echo "  ✗ $i"
    done
    echo ""
    echo "  请按上面条目修好后重跑：bash install.sh"
    echo "  Releases：https://github.com/AmazingDraw/AmazingDraw/releases"
    exit 1
  fi
}

# 读解释器主.次版本；失败返回空
py_mm() {
  local bin="$1"
  command -v "$bin" >/dev/null 2>&1 || return 0
  "$bin" -c "import sys; print(f'{sys.version_info[0]}.{sys.version_info[1]}')" 2>/dev/null || true
}

# 绝对路径（供 shim）
py_abspath() {
  local bin="$1"
  if command -v "$bin" >/dev/null 2>&1; then
    # command -v 在函数/alias 下可能不是路径；优先 which / type -P
    local p
    p="$(command -v "$bin" 2>/dev/null || true)"
    if [ -n "$p" ] && [ -x "$p" ]; then
      # 已是绝对路径则直接用；否则拼
      case "$p" in
        /*|[A-Za-z]:/*|[A-Za-z]:\\*) printf '%s' "$p"; return 0 ;;
      esac
      if command -v realpath >/dev/null 2>&1; then
        realpath "$p" 2>/dev/null && return 0
      fi
      printf '%s' "$p"
      return 0
    fi
  fi
  printf '%s' "$bin"
}

# ── 扫描 native ABI / 种类 ──
_native_has_39=0
_native_has_312=0
HAVE_SO=0
HAVE_PYD=0
if [ -d "$NATIVE_DIR" ]; then
  for f in "$NATIVE_DIR"/*.so; do
    [ -f "$f" ] || continue
    HAVE_SO=$((HAVE_SO + 1))
    b="$(basename "$f")"
    case "$b" in
      *cpython-39*|*cp39*) _native_has_39=1 ;;
    esac
    case "$b" in
      *cpython-312*|*cp312*) _native_has_312=1 ;;
    esac
  done
  for f in "$NATIVE_DIR"/*.pyd; do
    [ -f "$f" ] || continue
    HAVE_PYD=$((HAVE_PYD + 1))
    b="$(basename "$f")"
    case "$b" in
      *cpython-39*|*cp39*) _native_has_39=1 ;;
    esac
    case "$b" in
      *cpython-312*|*cp312*) _native_has_312=1 ;;
    esac
  done
fi

WANT_PY=""
if [ "$_native_has_39" = 1 ] && [ "$_native_has_312" = 1 ]; then
  WANT_PY="mixed"
elif [ "$_native_has_312" = 1 ]; then
  WANT_PY="3.12"
elif [ "$_native_has_39" = 1 ]; then
  WANT_PY="3.9"
fi

# ── 挑选匹配 WANT_PY 的解释器（逐个跑版本，不接受错主版本的 python3）──
PY=""
PY_MM=""
_pick_py() {
  local cand mm
  local -a cands=()
  case "$WANT_PY" in
    3.9)  cands=(python3.9 python3 python python3.12) ;;
    3.12) cands=(python3.12 python3 python python3.9) ;;
    *)    cands=(python3 python3.12 python3.9 python) ;;
  esac
  for cand in "${cands[@]}"; do
    command -v "$cand" >/dev/null 2>&1 || continue
    mm="$(py_mm "$cand")"
    [ -n "$mm" ] || continue
    if [ -n "$WANT_PY" ] && [ "$WANT_PY" != "mixed" ]; then
      if [ "$mm" != "$WANT_PY" ]; then
        continue
      fi
    fi
    PY="$cand"
    PY_MM="$mm"
    return 0
  done
  return 1
}

SHIM_CREATED=0
SHIM_PATH=""
PATH_APPENDED=0

_ensure_python3_shim() {
  # 仅当需要：python3 缺失或其版本 ≠ WANT_PY，且 $PY 已匹配
  [ -n "$PY" ] || return 1
  [ -n "$WANT_PY" ] && [ "$WANT_PY" != "mixed" ] || return 0

  local need=0
  local p3_mm=""
  if ! command -v python3 >/dev/null 2>&1; then
    need=1
  else
    p3_mm="$(py_mm python3)"
    if [ -z "$p3_mm" ] || [ "$p3_mm" != "$WANT_PY" ]; then
      need=1
    fi
  fi
  [ "$need" = 1 ] || return 0

  local target
  target="$(py_abspath "$PY")"
  # 若 PY 本身就是 python3 且版本已对，不应走到这里；再保险：目标必须 WANT_PY
  local tmm
  tmm="$(py_mm "$PY")"
  if [ -z "$tmm" ] || [ "$tmm" != "$WANT_PY" ]; then
    fatal_add "需要 python3≈${WANT_PY}，但选定解释器 $PY 版本为 ${tmm:-未知}，无法创建别名"
    return 1
  fi

  local local_bin="$HOME/.local/bin"
  mkdir -p "$local_bin" || {
    fatal_add "无法创建 ${local_bin}（python3 别名目录）。请手动把匹配的 Python 加到 PATH，或自行 ln -s '$target' '$local_bin/python3'"
    return 1
  }
  SHIM_PATH="$local_bin/python3"
  # 可执行 shim：转调绝对路径，避免相对/别名漂移
  cat > "$SHIM_PATH" << SHIM
#!/bin/bash
exec "$(printf '%s' "$target" | sed 's/"/\\"/g')" "\$@"
SHIM
  chmod +x "$SHIM_PATH" || {
    fatal_add "无法 chmod +x $SHIM_PATH"
    return 1
  }

  # 当前会话优先
  export PATH="$local_bin:$PATH"
  PATH_APPENDED=1

  # 持久化：PATH 若长期缺 ~/.local/bin，往登录 rc 追加守卫块。
  # macOS 默认 zsh（不读 .bashrc）；bash 登录 shell 只读 .bash_profile——都须覆盖。
  case ":$PATH:" in
    *":$local_bin:"*) ;;
    *) PATH_APPENDED=1 ;;
  esac
  local marker="# AmazingDraw: ensure python3 alias for card-engine subprocesses"
  local rc_files=("$HOME/.bashrc")
  # .bash_profile 仅在已存在时追加（bash 登录 shell 优先读它，不读 .bashrc）
  [ -f "$HOME/.bash_profile" ] && rc_files+=("$HOME/.bash_profile")
  # zsh：已有 .zshrc 或 macOS（默认 shell 即 zsh）时写入
  if [ -f "$HOME/.zshrc" ] || [ "$UNAME_S" = "Darwin" ]; then
    rc_files+=("$HOME/.zshrc")
  fi
  local rc
  for rc in "${rc_files[@]}"; do
    if [ ! -f "$rc" ] || ! grep -qF "$marker" "$rc" 2>/dev/null; then
      {
        echo ""
        echo "$marker"
        echo "export PATH=\"\$HOME/.local/bin:\$PATH\""
      } >> "$rc" || {
        fatal_add "已写 ${SHIM_PATH}，但无法追加 PATH 到 ${rc}。请手动：export PATH=\"\$HOME/.local/bin:\$PATH\""
        return 1
      }
    fi
  done

  # 校验：现在的 python3 必须是 WANT_PY
  hash -r 2>/dev/null || true
  local verify
  verify="$(py_mm python3)"
  if [ -z "$verify" ] || [ "$verify" != "$WANT_PY" ]; then
    fatal_add "已创建 ${SHIM_PATH} → ${target}，但 python3 仍报告 ${verify:-不可用}（期望 ${WANT_PY}）。请检查 PATH 是否含 ${local_bin}，新开终端后再试。"
    return 1
  fi
  SHIM_CREATED=1
  return 0
}

# 先选 Python（后续步骤可能调用 ${PY}）
if [ "$WANT_PY" = "mixed" ]; then
  fatal_add "native/ 同时含 Python 3.9 与 3.12 内核，禁止混装。请只保留与本包标签一致的一套"
elif [ -z "$WANT_PY" ]; then
  # native 稍后统一报；若目录都没有，下面还会加
  :
fi

if [ -n "$WANT_PY" ] && [ "$WANT_PY" != "mixed" ]; then
  if ! _pick_py; then
    fatal_add "未找到可用的 Python ${WANT_PY}（试过 python3.${WANT_PY#3.}/python3/python）。请安装匹配版本并加入 PATH；zip 标签 cp39=3.9、cp312=3.12"
  fi
else
  # 无清晰 WANT 时仍尽量找一个可跑的解释器，供目录/配置步骤；硬失败留给 native/assets
  if ! _pick_py; then
    PY=""
    PY_MM=""
  fi
fi

OPENCLAW_DIR="${OPENCLAW_DIR:-$HOME/.openclaw/draw-cards}"
WORKSPACE_DIR="${OPENCLAW_WORKSPACE_DIR:-$HOME/.openclaw/workspace}"
CONFIG_SRC="$ROOT/scripts/config.json"
CONFIG_DST="$OPENCLAW_DIR/config.json"
NATIVE_DIR="$ROOT/card_engine_core/native"

echo "== AmazingDraw 安装引导 =="
echo "  发行版: $ROOT"
echo "  平台: $UNAME_S  IS_WIN=$IS_WIN  python=${PY:-（未选定）}"
echo "  HOME: $HOME"
echo "  OpenClaw 数据目录: $OPENCLAW_DIR"
echo "  OpenClaw 工作区:   $WORKSPACE_DIR"
if [ -n "$WANT_PY" ] && [ "$WANT_PY" != "mixed" ]; then
  echo "  本包内核 Python: $WANT_PY"
fi
if [ "$IS_WIN" = 1 ]; then
  echo "  Windows Git Bash：~/ 即 ${HOME}（通常 /c/Users/<你>）"
fi

# 无 Python 时目录步骤仍尽量做完，再 fail_if_fatal
if [ -z "$PY" ]; then
  fatal_add "没有可用的 Python 解释器，无法继续配置与校验"
fi

# ── 1. 创建 OpenClaw 依赖目录 ──
mkdir -p "$OPENCLAW_DIR/cards"
mkdir -p "$OPENCLAW_DIR/custom_presets/amateurs"
mkdir -p "$OPENCLAW_DIR/custom_presets/roles"
mkdir -p "$OPENCLAW_DIR/custom_presets/scenes"
echo "✓ 目录就绪: $OPENCLAW_DIR/{cards,custom_presets/...}"

# ── 2. 生成权威配置（仅当目标不存在；保留用户已有配置）──
if [ ! -f "$CONFIG_DST" ]; then
  if [ -f "$CONFIG_SRC" ]; then
    cp "$CONFIG_SRC" "$CONFIG_DST"
    echo "✓ 已从发行版默认配置生成 $CONFIG_DST"
  else
    echo "⚠ 未找到默认配置 ${CONFIG_SRC}，请手动创建 $CONFIG_DST"
  fi
else
  echo "✓ 保留已有配置 $CONFIG_DST"
fi

# ── 2.5 Windows：Unix 专属 /tmp 换成系统临时目录 ──
# 发行版在 macOS 打包，config 里是 /tmp/cu-card；不能写死打包机的 C:/Users/<打包者>。
# ~/ 路径留给运行时 expanduser（Windows Python → C:\Users\<用户>\...）。
if [ "$IS_WIN" = 1 ] && [ -f "$CONFIG_DST" ] && [ -n "$PY" ]; then
  CONFIG_DST_PY="$(py_path "$CONFIG_DST")"
  WIN_TMP="$($PY - "$CONFIG_DST_PY" <<'PY'
import json, sys, tempfile
from pathlib import Path

p = Path(sys.argv[1])
cfg = json.loads(p.read_text(encoding="utf-8"))
tmp = str(cfg.get("tmp_dir") or "").strip().replace("\\", "/")
changed = False
if not tmp or tmp.startswith("/tmp"):
    cfg["tmp_dir"] = str(Path(tempfile.gettempdir()) / "cu-card")
    changed = True
if not str(cfg.get("cards_dir") or "").strip():
    cfg["cards_dir"] = "~/.openclaw/draw-cards/cards"
    changed = True
if changed:
    p.write_text(json.dumps(cfg, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
Path(cfg["tmp_dir"]).mkdir(parents=True, exist_ok=True)
print(Path(cfg["tmp_dir"]).as_posix())
PY
)"
  echo "✓ Windows tmp_dir: $WIN_TMP"
fi

# ── 3. 让发行版 config.json 指向权威配置（复制同步，避免 Windows 软链）──
if [ -f "$CONFIG_DST" ]; then
  SRC_LINK="$(readlink "$CONFIG_SRC" 2>/dev/null || true)"
  if [ "$SRC_LINK" != "$CONFIG_DST" ]; then
    cp "$CONFIG_DST" "$CONFIG_SRC"
    echo "✓ $CONFIG_SRC 已同步为权威配置"
  fi
fi

# ── 3.6 默认工作流复制：推迟到侦测/向导之后（需有效 comfyui_dir）──
# 见下方「安装向导」workflow-step；非交互同样由向导 best-effort 复制。

# ── 4. python3 别名（仅当需要）──
if [ -n "$PY" ] && [ -n "$WANT_PY" ] && [ "$WANT_PY" != "mixed" ]; then
  _ensure_python3_shim || true
fi

# ── 5. 硬依赖校验 ──
echo ""
echo "== 环境校验 =="

if [ -n "$PY" ]; then
  $PY --version 2>&1 | sed 's/^/  Python: /' || true
  if [ -z "$PY_MM" ]; then
    PY_MM="$(py_mm "$PY")"
  fi
  if [ -n "$PY_MM" ]; then
    echo "  Python 主版本: $PY_MM"
  fi
fi
echo "  Releases 两套包：cp39=Python 3.9，cp312=Python 3.12。跑 WebUI/CLI 必须和 zip 标签一致。"
echo "  Apple 自带 /usr/bin/python3 是 3.9，请下 cp39；本机 3.12 请下 cp312。ComfyUI 可用独立 venv。"
echo "  不要把 .so 和 .pyd 混放，也不要混 3.9/3.12 native。"

# assets.bin
if [ ! -f "$ROOT/assets.bin" ]; then
  fatal_add "缺少 \$ROOT/assets.bin（场景库数据包）。请确认解压完整，或重新下载对应 AmazingDraw-*.zip"
else
  echo "  ✓ assets.bin"
fi

# native 存在与种类
if [ ! -d "$NATIVE_DIR" ]; then
  fatal_add "缺少目录 ${NATIVE_DIR}（内核）。请从 Releases 下载带 native 的压缩包，不要只用公开仓 git 树"
elif [ "$HAVE_SO" -eq 0 ] && [ "$HAVE_PYD" -eq 0 ]; then
  fatal_add "native/ 内无 .so 也无 .pyd。请下载 AmazingDraw-darwin-cp39|cp312.zip 或 AmazingDraw-windows-cp39|cp312.zip"
elif [ "$UNAME_S" = "Linux" ]; then
  # 发行版仅 macOS/Windows 两平台；darwin 的 .so 无法在 Linux 加载，直接明说
  fatal_add "暂不支持 Linux：发行版仅提供 macOS（darwin）与 Windows 包。请在 macOS / Windows（Git Bash）上安装"
elif [ "$IS_WIN" = 1 ]; then
  if [ "$HAVE_PYD" -eq 0 ]; then
    fatal_add "Windows 需要 .pyd 内核，当前 native/ 只有 .so（不能用 macOS 包）"
  else
    echo "  ✓ native Windows 核心: $HAVE_PYD 个 .pyd（${NATIVE_DIR}）"
  fi
  if [ "$HAVE_SO" -gt 0 ]; then
    fatal_add "native/ 同时含 .so 与 .pyd；Windows 上请只保留 .pyd"
  fi
else
  if [ "$HAVE_SO" -eq 0 ]; then
    fatal_add "macOS 需要 .so 内核，当前 native/ 只有 .pyd（请下 darwin 包）"
  else
    echo "  ✓ native 核心: $HAVE_SO 个 .so（${NATIVE_DIR}）"
  fi
  if [ "$HAVE_PYD" -gt 0 ]; then
    fatal_add "native/ 同时含 .so 与 .pyd；请只保留本平台对应种类"
  fi
fi

# ABI 与解释器一致
if [ -n "$PY" ] && [ -n "$PY_MM" ] && [ -n "$WANT_PY" ] && [ "$WANT_PY" != "mixed" ]; then
  if [ "$PY_MM" != "$WANT_PY" ]; then
    fatal_add "当前解释器是 ${PY_MM}，本包内核是 Python ${WANT_PY}。请改用匹配的 Python，或改下对应 cp39/cp312 压缩包"
  else
    echo "  ✓ 解释器 $PY ($PY_MM) 与内核标签一致"
  fi
fi

# ── 5.0 旧配置迁移：废弃的 agent_backend → openclaw（仅此一项）──
AGENT_BACKEND_BEFORE=""
AGENT_BACKEND_AFTER=""
AGENT_BACKEND_MIGRATED=0
if [ -f "$CONFIG_DST" ] && [ -n "$PY" ]; then
  CFG_PY="$(py_path "$CONFIG_DST")"
  _mig_out="$($PY - "$CFG_PY" <<'PY'
import json, sys
from pathlib import Path
p = Path(sys.argv[1])
cfg = json.loads(p.read_text(encoding="utf-8"))
old = str(cfg.get("agent_backend") or "").strip().lower()
legacy = ("custom", "claudecode", "hermes")
if old in legacy:
    cfg["agent_backend"] = "openclaw"
    p.write_text(json.dumps(cfg, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print("migrated:%s:openclaw" % old)
else:
    print("keep:%s" % (old or "openclaw"))
PY
)" || true
  case "$_mig_out" in
    migrated:*)
      AGENT_BACKEND_MIGRATED=1
      AGENT_BACKEND_BEFORE="${_mig_out#migrated:}"
      AGENT_BACKEND_BEFORE="${AGENT_BACKEND_BEFORE%%:*}"
      AGENT_BACKEND_AFTER="openclaw"
      echo "✓ 已迁移 agent_backend: ${AGENT_BACKEND_BEFORE} → openclaw（旧 custom / claudecode / hermes 已废弃）"
      if [ -f "$CONFIG_DST" ]; then
        SRC_LINK="$(readlink "$CONFIG_SRC" 2>/dev/null || true)"
        if [ "$SRC_LINK" != "$CONFIG_DST" ]; then
          cp "$CONFIG_DST" "$CONFIG_SRC"
        fi
      fi
      ;;
    keep:*)
      AGENT_BACKEND_AFTER="${_mig_out#keep:}"
      ;;
  esac
fi

# ComfyUI / OpenClaw：本机路径侦测（可选依赖，不阻断安装）
# 优先调用 tools/detect_local_deps.py；写入规则：仅填充空值或无效路径，不覆盖有效用户配置。
DETECT_HELPER=""
_INSTALL_DIR="$(cd "$(dirname "$0")" && pwd)"
for _cand in \
  "$ROOT/tools/detect_local_deps.py" \
  "$_INSTALL_DIR/tools/detect_local_deps.py" \
  "$_INSTALL_DIR/detect_local_deps.py" \
  "$ROOT/detect_local_deps.py"
do
  if [ -f "$_cand" ]; then
    DETECT_HELPER="$_cand"
    break
  fi
done

COMFYUI_DIR="${COMFYUI_DIR:-}"
if [ -f "$CONFIG_DST" ] && [ -n "$PY" ] && [ -n "$DETECT_HELPER" ]; then
  CFG_PY="$(py_path "$CONFIG_DST")"
  DETECT_PY="$(py_path "$DETECT_HELPER")"
  # 人话输出到终端；--write 仅在空/无效时写入 comfyui_dir / openclaw_home / openclaw_bin
  set +e
  "$PY" "$DETECT_PY" --config "$CFG_PY" --write
  _detect_rc=$?
  set -e
  if [ "$_detect_rc" -ne 0 ]; then
    echo "  ⚠ 本机依赖侦测脚本异常（已忽略，安装继续）"
  fi
  # 侦测后同步权威配置 → 发行版 scripts/config.json（既有行为）
  if [ -f "$CONFIG_DST" ]; then
    SRC_LINK="$(readlink "$CONFIG_SRC" 2>/dev/null || true)"
    if [ "$SRC_LINK" != "$CONFIG_DST" ]; then
      cp "$CONFIG_DST" "$CONFIG_SRC"
    fi
  fi
  # 读回 comfyui_dir 供插件拷贝
  COMFYUI_DIR=$($PY -c "import json,os,sys; p=sys.argv[1]; v=json.load(open(p,encoding='utf-8')).get('comfyui_dir') or ''; print(os.path.expanduser(v) if v else '')" "$CFG_PY" 2>/dev/null || true)
  [ -n "$COMFYUI_DIR" ] && COMFYUI_DIR="$(bash_path "$COMFYUI_DIR")"
elif [ -f "$CONFIG_DST" ] && [ -n "$PY" ]; then
  # 无 helper 时的精简回退（旧包）
  CFG_PY="$(py_path "$CONFIG_DST")"
  COMFYUI_DIR=$($PY -c "import json,os,sys; p=sys.argv[1]; print(os.path.expanduser(json.load(open(p,encoding='utf-8')).get('comfyui_dir','') or ''))" "$CFG_PY" 2>/dev/null || true)
  [ -n "$COMFYUI_DIR" ] && COMFYUI_DIR="$(bash_path "$COMFYUI_DIR")"
  if [ -z "$COMFYUI_DIR" ] || [ ! -f "$COMFYUI_DIR/main.py" ]; then
    for _c in "${COMFYUI_DIR:-}" "$HOME/ComfyUI" "$HOME/comfyui" "$HOME/Documents/ComfyUI"; do
      [ -n "$_c" ] || continue
      if [ -f "$_c/main.py" ]; then COMFYUI_DIR="$_c"; break; fi
    done
  fi
  if [ -n "$COMFYUI_DIR" ] && [ -f "$COMFYUI_DIR/main.py" ]; then
    echo "✓ 已找到本机 ComfyUI：$COMFYUI_DIR"
  else
    echo "ℹ 本机还没侦测到 ComfyUI（可选）。装好后可在 WebUI「配置」里填写 ComfyUI 本地根目录；或设置环境变量 COMFYUI_DIR 后再跑一次安装。"
  fi
  if [ -d "$WORKSPACE_DIR" ]; then
    echo "✓ OpenClaw 工作区：$WORKSPACE_DIR"
  else
    echo "ℹ 未侦测到 OpenClaw（AI 连抽/常规对话才需要；直投/精选/出图可先不用）。需要时安装 OpenClaw，或在 WebUI 配置里填写 openclaw_home / openclaw_bin。"
  fi
fi

# ── 安装向导（交互：补路径 / 工作流 / Telegram；非交互：静默 best-effort）──
WIZARD_HELPER=""
for _cand in \
  "$ROOT/tools/install_wizard.py" \
  "$_INSTALL_DIR/tools/install_wizard.py" \
  "$_INSTALL_DIR/install_wizard.py" \
  "$ROOT/install_wizard.py"
do
  if [ -f "$_cand" ]; then
    WIZARD_HELPER="$_cand"
    break
  fi
done

WIZARD_NI=""
if [ "${AMAZINGDRAW_INSTALL_NONINTERACTIVE}" = "1" ]; then
  WIZARD_NI="--non-interactive"
fi

# 报告字段：向导备注（写入 install-report）
WIZARD_NOTES=""
REPORT_WORKFLOW="未跑向导"
REPORT_TELEGRAM="未询问"

if [ -f "$CONFIG_DST" ] && [ -n "$PY" ] && [ -n "$WIZARD_HELPER" ]; then
  CFG_PY="$(py_path "$CONFIG_DST")"
  WIZ_PY="$(py_path "$WIZARD_HELPER")"
  ROOT_PY="$(py_path "$ROOT")"

  echo ""
  echo "== 安装向导 =="
  if [ "${AMAZINGDRAW_INSTALL_NONINTERACTIVE}" = "1" ]; then
    echo "  （非交互模式：不提问，仅 best-effort）"
  fi

  # B. ComfyUI 缺失则粘贴
  set +e
  "$PY" "$WIZ_PY" ${WIZARD_NI} prompt-comfyui --config "$CFG_PY"
  _wiz_rc=$?
  set -e
  case "$_wiz_rc" in
    0) ;;
    2) WIZARD_NOTES="${WIZARD_NOTES}comfyui:skipped;" ;;
    *) echo "  ⚠ ComfyUI 向导步骤异常（已忽略）" ;;
  esac

  # C. OpenClaw 缺失则粘贴
  set +e
  "$PY" "$WIZ_PY" ${WIZARD_NI} prompt-openclaw --config "$CFG_PY"
  _wiz_rc=$?
  set -e
  case "$_wiz_rc" in
    0) ;;
    2) WIZARD_NOTES="${WIZARD_NOTES}openclaw:skipped;" ;;
    *) echo "  ⚠ OpenClaw 向导步骤异常（已忽略）" ;;
  esac

  # 向导可能刚写入路径：读回 COMFYUI_DIR 供插件拷贝
  COMFYUI_DIR=$($PY -c "import json,os,sys; p=sys.argv[1]; v=json.load(open(p,encoding='utf-8')).get('comfyui_dir') or ''; print(os.path.expanduser(v) if v else '')" "$CFG_PY" 2>/dev/null || true)
  [ -n "$COMFYUI_DIR" ] && COMFYUI_DIR="$(bash_path "$COMFYUI_DIR")"

  # D. 工作流：复制默认 Moody + 模型清单 + 可选自定义（自定义≠一键接好）
  set +e
  "$PY" "$WIZ_PY" ${WIZARD_NI} workflow-step --config "$CFG_PY" --root "$ROOT_PY"
  _wiz_rc=$?
  set -e
  case "$_wiz_rc" in
    0) REPORT_WORKFLOW="默认/已处理" ;;
    2) REPORT_WORKFLOW="已跳过"; WIZARD_NOTES="${WIZARD_NOTES}workflow:skipped;" ;;
    *) REPORT_WORKFLOW="异常（已忽略）"; echo "  ⚠ 工作流向导步骤异常（已忽略）" ;;
  esac

  # E. Telegram 可选
  set +e
  "$PY" "$WIZ_PY" ${WIZARD_NI} telegram-step --config "$CFG_PY"
  _wiz_rc=$?
  set -e
  case "$_wiz_rc" in
    0) REPORT_TELEGRAM="已写入/确认" ;;
    2) REPORT_TELEGRAM="已跳过" ;;
    *) REPORT_TELEGRAM="异常（已忽略）" ;;
  esac

  # F. WebUI 说明
  "$PY" "$WIZ_PY" ${WIZARD_NI} webui-blurb || true

  # G. 可选路径：output_dir / comfyui_host / openclaw_workspace / obsidian（须在 readiness-summary 之前）
  set +e
  "$PY" "$WIZ_PY" ${WIZARD_NI} prompt-extras --config "$CFG_PY"
  _wiz_rc=$?
  set -e
  case "$_wiz_rc" in
    0) WIZARD_NOTES="${WIZARD_NOTES}extras:ok;" ;;
    2) WIZARD_NOTES="${WIZARD_NOTES}extras:skipped;" ;;
    *) echo "  ⚠ 可选路径向导步骤异常（已忽略）" ;;
  esac

  # 同步权威配置 → 发行版 scripts/config.json
  if [ -f "$CONFIG_DST" ]; then
    SRC_LINK="$(readlink "$CONFIG_SRC" 2>/dev/null || true)"
    if [ "$SRC_LINK" != "$CONFIG_DST" ]; then
      cp "$CONFIG_DST" "$CONFIG_SRC"
    fi
  fi
elif [ -z "$WIZARD_HELPER" ]; then
  echo "ℹ 未找到 install_wizard.py，跳过交互向导（旧包兼容）。"
  # 旧行为回退：若已有有效 ComfyUI，直接拷 workflows
  if [ -n "${COMFYUI_DIR:-}" ] && [ -f "$COMFYUI_DIR/main.py" ] && [ -d "$ROOT/workflows" ]; then
    mkdir -p "$COMFYUI_DIR/workflows"
    cp -R "$ROOT/workflows/"* "$COMFYUI_DIR/workflows/" 2>/dev/null && echo "✓ 默认工作流已复制到 $COMFYUI_DIR/workflows" || true
    REPORT_WORKFLOW="旧包回退复制"
  fi
fi

# ComfyUI 插件拷贝（找到有效根目录时）
if [ -n "$COMFYUI_DIR" ] && [ -f "$COMFYUI_DIR/main.py" ]; then
  PLUGIN_SRC="$ROOT/ComfyUI-Card-Engine"
  if [ -d "$PLUGIN_SRC" ]; then
    PLUGIN_DST="$COMFYUI_DIR/custom_nodes/ComfyUI-Card-Engine"
    # 自删防护：发行版若被解压进 ComfyUI/custom_nodes/ 内，源==目标，rm -rf 会先删源
    _src_real="$(cd "$PLUGIN_SRC" && pwd -P)"
    _dst_parent="$(cd "$COMFYUI_DIR/custom_nodes" 2>/dev/null && pwd -P)"
    if [ -n "$_dst_parent" ] && [ "$_src_real" = "$_dst_parent/ComfyUI-Card-Engine" ]; then
      echo "✓ ComfyUI 节点源即目标（发行版位于 custom_nodes 内），跳过拷贝"
    else
      mkdir -p "$COMFYUI_DIR/custom_nodes"
      rm -rf "$PLUGIN_DST"
      cp -R "$PLUGIN_SRC" "$PLUGIN_DST"
      echo "✓ ComfyUI 节点已安装到 $PLUGIN_DST"
    fi
  fi
elif [ -d "$ROOT/ComfyUI-Card-Engine" ]; then
  echo "  （装好 ComfyUI 后，把 $ROOT/ComfyUI-Card-Engine 拷到 ComfyUI/custom_nodes/）"
fi

fail_if_fatal

# ── 6. 安装后 smoke（场景库）──
echo ""
echo "== 安装后自检 =="
SMOKE_OK=0
if (
  cd "$ROOT"
  PYTHONPATH=card_engine_core/native "$PY" -c "from card_asset_loader import health; h=health(); assert h.get('assets_bin_found'); assert h.get('libraries'); print(h)"
); then
  SMOKE_OK=1
  echo "  ✓ smoke: card_asset_loader.health() 通过"
else
  fatal_add "smoke 失败：选定解释器无法加载场景库（from card_asset_loader import health）。请确认 native 与 Python ${WANT_PY:-?} 匹配，且 assets.bin 完整"
fi


# 可选：进程内 workplace 抽样（验证 create --scene 办公室 同类路径；失败仅警告）
SMOKE_WP=""
if [ "$SMOKE_OK" = 1 ]; then
  if (
    cd "$ROOT"
    PYTHONPATH=card_engine_core/native "$PY" -c "from card_scene_router import sample_library_entries as s; r=s(\"workplace_scenes\", include_tags=[\"workplace\"], count=1); assert r; print((r[0].get(\"label\") or r[0].get(\"id\") or \"\")[:40])"
  ); then
    SMOKE_WP=1
    echo "  ✓ smoke: workplace 进程内抽样通过"
  else
    SMOKE_WP=0
    echo "  ⚠ smoke: workplace 进程内抽样未通过（health 已过；若 create 仍失败请升级含抽样修复的版本）"
  fi
fi

# card_cli 启动自检（致命：证明选定 $PY 下 CLI 能起来）
SMOKE_CLI=""
if [ -f "$ROOT/scripts/card-engine/card_cli.py" ] && [ -n "$PY" ]; then
  if (
    cd "$ROOT/scripts/card-engine"
    # 相对路径：Git Bash 下绝对 POSIX 路径不会自动转给 Windows python.exe；
    # card_cli 自带 _path_bootstrap 兜底，这里仅作冗余
    PYTHONPATH="../../card_engine_core/native" "$PY" card_cli.py -h >/dev/null 2>&1
  ); then
    SMOKE_CLI=1
    echo "  ✓ smoke: card_cli.py -h 通过"
  else
    SMOKE_CLI=0
    fatal_add "smoke 失败：card_cli.py -h 无法在选定解释器下启动。请确认 scripts/card-engine 与 native 完整"
  fi
else
  SMOKE_CLI="skip"
  echo "  ℹ smoke: 未找到 scripts/card-engine/card_cli.py，跳过 CLI 自检"
fi

fail_if_fatal

# ── 安装报告 ──
# 读回配置字段供报告（detect / migrate 之后）
REPORT_AGENT_BACKEND="${AGENT_BACKEND_AFTER:-}"
REPORT_COMFYUI="未找到"
REPORT_OC_HOME="未找到"
REPORT_OC_BIN="未找到"
REPORT_OC_WS="未找到"
REPORT_WORKFLOW="${REPORT_WORKFLOW:-未跑向导}"
REPORT_TELEGRAM="${REPORT_TELEGRAM:-未询问}"
WIZARD_NOTES="${WIZARD_NOTES:-}"
if [ -f "$CONFIG_DST" ] && [ -n "$PY" ]; then
  CFG_PY="$(py_path "$CONFIG_DST")"
  _rep="$($PY - "$CFG_PY" <<'PY'
import json, os, sys
from pathlib import Path
cfg = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
def exp(v):
    v = (v or "").strip()
    return os.path.expanduser(v) if v else ""
ab = str(cfg.get("agent_backend") or "").strip() or "openclaw"
cu = exp(cfg.get("comfyui_dir"))
oh = exp(cfg.get("openclaw_home"))
ob = exp(cfg.get("openclaw_bin"))
ow = exp(cfg.get("openclaw_workspace_dir"))
print(ab)
print(cu)
print(oh)
print(ob)
print(ow)
PY
)" || true
  if [ -n "$_rep" ]; then
    REPORT_AGENT_BACKEND="$(printf '%s\n' "$_rep" | sed -n '1p')"
    _cu="$(printf '%s\n' "$_rep" | sed -n '2p')"
    _oh="$(printf '%s\n' "$_rep" | sed -n '3p')"
    _ob="$(printf '%s\n' "$_rep" | sed -n '4p')"
    _ow="$(printf '%s\n' "$_rep" | sed -n '5p')"
    if [ -n "$_cu" ]; then
      _cu_b="$(bash_path "$_cu")"
      if [ -f "$_cu_b/main.py" ] || [ -f "$_cu/main.py" ]; then
        REPORT_COMFYUI="${_cu}"
      else
        REPORT_COMFYUI="${_cu}（路径无效）"
      fi
    fi
    if [ -n "$_oh" ]; then
      _oh_b="$(bash_path "$_oh")"
      if [ -d "$_oh_b" ] || [ -d "$_oh" ]; then
        REPORT_OC_HOME="${_oh}"
      else
        REPORT_OC_HOME="${_oh}（路径无效）"
      fi
    fi
    if [ -n "$_ob" ]; then
      _ob_b="$(bash_path "$_ob")"
      if [ -x "$_ob_b" ] || [ -x "$_ob" ] || command -v "$_ob" >/dev/null 2>&1; then
        REPORT_OC_BIN="${_ob}"
      else
        REPORT_OC_BIN="${_ob}（未找到可执行）"
      fi
    fi
    if [ -n "$_ow" ]; then
      _ow_b="$(bash_path "$_ow")"
      if [ -d "$_ow_b" ] || [ -d "$_ow" ]; then
        REPORT_OC_WS="${_ow}"
      else
        REPORT_OC_WS="${_ow}（路径无效）"
      fi
    elif [ -d "$WORKSPACE_DIR" ]; then
      REPORT_OC_WS="$WORKSPACE_DIR"
    fi
  fi
fi
# 回退：detect 已写入的 COMFYUI_DIR / 默认 workspace
if [ "$REPORT_COMFYUI" = "未找到" ] && [ -n "${COMFYUI_DIR:-}" ] && [ -f "$COMFYUI_DIR/main.py" ]; then
  REPORT_COMFYUI="$COMFYUI_DIR"
fi
if [ "$REPORT_OC_WS" = "未找到" ] && [ -d "$WORKSPACE_DIR" ]; then
  REPORT_OC_WS="$WORKSPACE_DIR"
fi
if [ -z "$REPORT_AGENT_BACKEND" ]; then
  REPORT_AGENT_BACKEND="openclaw"
fi

# shim 文案
if [ "$SHIM_CREATED" = 1 ]; then
  REPORT_SHIM="已创建 $SHIM_PATH → $(py_abspath "$PY")"
elif command -v python3 >/dev/null 2>&1; then
  REPORT_SHIM="未改动（python3=$(py_mm python3)）"
else
  REPORT_SHIM="未创建"
fi

# smoke 文案
REPORT_SMOKE_HEALTH="失败"
[ "${SMOKE_OK:-0}" = 1 ] && REPORT_SMOKE_HEALTH="通过"
REPORT_SMOKE_WP="未跑"
case "${SMOKE_WP:-}" in
  1) REPORT_SMOKE_WP="通过" ;;
  0) REPORT_SMOKE_WP="未通过（仅警告）" ;;
esac
case "${SMOKE_CLI:-}" in
  1) REPORT_SMOKE_CLI="通过" ;;
  0) REPORT_SMOKE_CLI="失败" ;;
  *) REPORT_SMOKE_CLI="跳过" ;;
esac

if [ -f "$ROOT/scripts/webui/webui-start.sh" ]; then
  REPORT_WEBUI_CMD="bash '$ROOT/scripts/webui/webui-start.sh' start"
else
  REPORT_WEBUI_CMD="cd '$ROOT/scripts/webui' && $PY web_server.py"
fi
REPORT_COMFY_CMD="bash '$ROOT/scripts/gpu-pipeline/comfyui-start.sh' start"

# 就绪矩阵（在 prompt-extras 之后跑一次；交互/非交互都打印；失败不致命）
if [ -f "$CONFIG_DST" ] && [ -n "$PY" ] && [ -n "${WIZARD_HELPER:-}" ]; then
  CFG_PY="$(py_path "$CONFIG_DST")"
  WIZ_PY="$(py_path "$WIZARD_HELPER")"
  ROOT_PY="$(py_path "$ROOT")"
  "$PY" "$WIZ_PY" readiness-summary --config "$CFG_PY" --root "$ROOT_PY" || true
fi

# 报告 URL：Comfy 来自 config.comfyui_host（缺省标注默认 8188）；
# WebUI 来自 webui_host/webui_port（缺省标注 WebUI 默认 8318，与 Comfy 端口无关）。
REPORT_COMFY_URL="http://127.0.0.1:8188"
REPORT_COMFY_URL_NOTE="（默认）"
REPORT_WEBUI_URL="http://127.0.0.1:8318"
REPORT_WEBUI_URL_NOTE="（WebUI 默认）"
if [ -f "$CONFIG_DST" ] && [ -n "$PY" ]; then
  CFG_PY="$(py_path "$CONFIG_DST")"
  _url_line=$($PY -c "
import json,sys
p=sys.argv[1]
try:
  c=json.load(open(p,encoding='utf-8'))
except Exception:
  c={}
raw=(c.get('comfyui_host') or '').strip()
if raw:
  if '://' not in raw: raw='http://'+raw
  comfy=raw; cnot=''
else:
  comfy='http://127.0.0.1:8188'; cnot='（默认）'
host=(c.get('webui_host') or '').strip()
port=c.get('webui_port')
from_cfg=bool(host) or (port is not None and str(port).strip()!='')
if not from_cfg:
  webui='http://127.0.0.1:8318'; wnote='（WebUI 默认）'
else:
  if not host or host in ('0.0.0.0','::','[::]'): host='127.0.0.1'
  try: port_i=int(port) if port is not None and str(port).strip()!='' else 8318
  except Exception: port_i=8318
  webui='http://%s:%d'%(host,port_i); wnote=''
print(comfy+'|'+cnot+'|'+webui+'|'+wnote)
" "$CFG_PY" 2>/dev/null || true)
  if [ -n "${_url_line:-}" ]; then
    IFS='|' read -r REPORT_COMFY_URL REPORT_COMFY_URL_NOTE REPORT_WEBUI_URL REPORT_WEBUI_URL_NOTE <<EOF
$_url_line
EOF
  fi
fi

# 组装报告正文（终端 + 可选文件）
_report_body() {
  echo "== 安装报告 =="
  echo "  平台: $UNAME_S  IS_WIN=$IS_WIN"
  echo "  解释器: ${PY:-（未选定）}  版本=${PY_MM:-?}  内核ABI=${WANT_PY:-?}"
  echo "  python3 别名: $REPORT_SHIM"
  echo "  配置: $CONFIG_DST"
  if [ "$AGENT_BACKEND_MIGRATED" = 1 ]; then
    echo "  agent_backend: ${REPORT_AGENT_BACKEND}（已从 $AGENT_BACKEND_BEFORE 迁移）"
  else
    echo "  agent_backend: $REPORT_AGENT_BACKEND"
  fi
  echo "  ComfyUI: $REPORT_COMFYUI"
  echo "  OpenClaw home: $REPORT_OC_HOME"
  echo "  OpenClaw bin:  $REPORT_OC_BIN"
  echo "  OpenClaw workspace: $REPORT_OC_WS"
  echo "  工作流向导: ${REPORT_WORKFLOW:-未记录}"
  echo "  Telegram: ${REPORT_TELEGRAM:-未记录}"
  if [ -n "${WIZARD_NOTES:-}" ]; then
    echo "  向导备注: $WIZARD_NOTES"
  fi
  echo "  smoke:"
  echo "    card_asset_loader.health: $REPORT_SMOKE_HEALTH"
  echo "    workplace 抽样: $REPORT_SMOKE_WP"
  echo "    card_cli.py -h: $REPORT_SMOKE_CLI"
  echo "  下一步:"
  echo "    启动 WebUI: $REPORT_WEBUI_CMD"
  echo "    启动 ComfyUI: $REPORT_COMFY_CMD"
  echo "    WebUI   ${REPORT_WEBUI_URL}${REPORT_WEBUI_URL_NOTE}"
  echo "    ComfyUI ${REPORT_COMFY_URL}${REPORT_COMFY_URL_NOTE}"
  if [ "$IS_WIN" = 1 ]; then
    echo "    （Windows 请始终在 Git Bash 里跑上面两条）"
  fi
}

echo ""
_report_body

# 写入可粘贴的报告文件（优先 OpenClaw 数据目录）
REPORT_FILE=""
if [ -d "$OPENCLAW_DIR" ]; then
  REPORT_FILE="$OPENCLAW_DIR/install-report.txt"
elif [ -d "$(dirname "$CONFIG_DST")" ]; then
  REPORT_FILE="$(dirname "$CONFIG_DST")/install-report.txt"
fi
if [ -n "$REPORT_FILE" ]; then
  {
    echo "# AmazingDraw 安装报告"
    echo "# 生成时间: $(date '+%Y-%m-%d %H:%M:%S %z')"
    echo "# 发行版: $ROOT"
    echo ""
    _report_body
  } > "$REPORT_FILE" 2>/dev/null && echo "  报告已写入: $REPORT_FILE" || true
fi
