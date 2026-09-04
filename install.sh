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
    fatal_add "无法创建 $local_bin（python3 别名目录）。请手动把匹配的 Python 加到 PATH，或自行 ln -s '$target' '$local_bin/python3'"
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

  # 持久化：PATH 若长期缺 ~/.local/bin，往 ~/.bashrc 追加守卫块
  case ":$PATH:" in
    *":$local_bin:"*) ;;
    *) PATH_APPENDED=1 ;;
  esac
  local bashrc="$HOME/.bashrc"
  local marker="# AmazingDraw: ensure python3 alias for card-engine subprocesses"
  if [ ! -f "$bashrc" ] || ! grep -qF "$marker" "$bashrc" 2>/dev/null; then
    {
      echo ""
      echo "$marker"
      echo "export PATH=\"\$HOME/.local/bin:\$PATH\""
    } >> "$bashrc" || {
      fatal_add "已写 $SHIM_PATH，但无法追加 PATH 到 $bashrc。请手动：export PATH=\"\$HOME/.local/bin:\$PATH\""
      return 1
    }
  fi

  # 校验：现在的 python3 必须是 WANT_PY
  hash -r 2>/dev/null || true
  local verify
  verify="$(py_mm python3)"
  if [ -z "$verify" ] || [ "$verify" != "$WANT_PY" ]; then
    fatal_add "已创建 $SHIM_PATH → $target，但 python3 仍报告 ${verify:-不可用}（期望 $WANT_PY）。请检查 PATH 是否含 $local_bin，新开终端后再试。"
    return 1
  fi
  SHIM_CREATED=1
  return 0
}

# 先选 Python（后续步骤可能调用 $PY）
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
  echo "  Windows Git Bash：~/ 即 $HOME（通常 /c/Users/<你>）"
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
    echo "⚠ 未找到默认配置 $CONFIG_SRC，请手动创建 $CONFIG_DST"
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

# ── 3.6 默认工作流：把发行版自带的 ComfyUI 图复制到用户 ComfyUI（开箱即用）──
if [ -d "$ROOT/workflows" ] && [ -n "$PY" ]; then
  CFG_PY="$(py_path "$CONFIG_DST")"
  WF_COMFYUI_DIR=$($PY -c "import json,os,sys; p=sys.argv[1]; print(os.path.expanduser(json.load(open(p,encoding='utf-8')).get('comfyui_dir','~/ComfyUI')))" "$CFG_PY" 2>/dev/null || echo "$HOME/ComfyUI")
  WF_COMFYUI_DIR="$(bash_path "$WF_COMFYUI_DIR")"
  COMFYUI_WF_DIR="$WF_COMFYUI_DIR/workflows"
  mkdir -p "$COMFYUI_WF_DIR"
  cp -R "$ROOT/workflows/"* "$COMFYUI_WF_DIR/" 2>/dev/null && echo "✓ 默认工作流已复制到 $COMFYUI_WF_DIR"
fi

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
  fatal_add "缺少目录 $NATIVE_DIR（内核）。请从 Releases 下载带 native 的压缩包，不要只用公开仓 git 树"
elif [ "$HAVE_SO" -eq 0 ] && [ "$HAVE_PYD" -eq 0 ]; then
  fatal_add "native/ 内无 .so 也无 .pyd。请下载 AmazingDraw-darwin-cp39|cp312.zip 或 AmazingDraw-windows-cp39|cp312.zip"
elif [ "$IS_WIN" = 1 ]; then
  if [ "$HAVE_PYD" -eq 0 ]; then
    fatal_add "Windows 需要 .pyd 内核，当前 native/ 只有 .so（不能用 macOS 包）"
  else
    echo "  ✓ native Windows 核心: $HAVE_PYD 个 .pyd（$NATIVE_DIR）"
  fi
  if [ "$HAVE_SO" -gt 0 ]; then
    fatal_add "native/ 同时含 .so 与 .pyd；Windows 上请只保留 .pyd"
  fi
else
  if [ "$HAVE_SO" -eq 0 ]; then
    fatal_add "macOS/Linux 需要 .so 内核，当前 native/ 只有 .pyd（请下 darwin 包）"
  else
    echo "  ✓ native 核心: $HAVE_SO 个 .so（$NATIVE_DIR）"
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

# ComfyUI 插件拷贝（找到有效根目录时）
if [ -n "$COMFYUI_DIR" ] && [ -f "$COMFYUI_DIR/main.py" ]; then
  PLUGIN_SRC="$ROOT/ComfyUI-Card-Engine"
  if [ -d "$PLUGIN_SRC" ]; then
    PLUGIN_DST="$COMFYUI_DIR/custom_nodes/ComfyUI-Card-Engine"
    mkdir -p "$COMFYUI_DIR/custom_nodes"
    rm -rf "$PLUGIN_DST"
    cp -R "$PLUGIN_SRC" "$PLUGIN_DST"
    echo "✓ ComfyUI 节点已安装到 $PLUGIN_DST"
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
if [ "$SMOKE_OK" = 1 ]; then
  if (
    cd "$ROOT"
    PYTHONPATH=card_engine_core/native "$PY" -c "from card_scene_router import sample_library_entries as s; r=s(\"workplace_scenes\", include_tags=[\"workplace\"], count=1); assert r; print((r[0].get(\"label\") or r[0].get(\"id\") or \"\")[:40])"
  ); then
    echo "  ✓ smoke: workplace 进程内抽样通过"
  else
    echo "  ⚠ smoke: workplace 进程内抽样未通过（health 已过；若 create 仍失败请升级含抽样修复的版本）"
  fi
fi

fail_if_fatal

# ── 摘要 ──
echo ""
echo "== 完成 =="
echo "  摘要:"
echo "    解释器: $PY ($PY_MM)"
if [ "$SHIM_CREATED" = 1 ]; then
  echo "    python3 别名: 已创建 $SHIM_PATH → $(py_abspath "$PY")"
  echo "    PATH: 已确保 \$HOME/.local/bin 优先（当前会话 + ~/.bashrc 守卫块）"
else
  if command -v python3 >/dev/null 2>&1; then
    echo "    python3 别名: 未改动（已有 python3=$(py_mm python3)，与本包一致或无需 shim）"
  else
    echo "    python3 别名: 未创建"
  fi
fi
echo "    smoke: 通过"
if [ -f "$ROOT/scripts/webui/webui-start.sh" ]; then
  echo "  启动 WebUI: bash '$ROOT/scripts/webui/webui-start.sh' start"
else
  echo "  启动 WebUI: cd '$ROOT/scripts/webui' && $PY web_server.py"
fi
echo "  启动 ComfyUI: bash '$ROOT/scripts/gpu-pipeline/comfyui-start.sh' start"
echo "  WebUI  http://127.0.0.1:8318"
echo "  ComfyUI  http://127.0.0.1:8188"
if [ "$IS_WIN" = 1 ]; then
  echo "  （Windows 请始终在 Git Bash 里跑上面两条）"
fi
