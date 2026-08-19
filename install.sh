#!/bin/bash
# ============================================================
# Card Engine 发行版安装引导
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
_native_has_39=0
_native_has_312=0
if [ -d "$NATIVE_DIR" ]; then
  for f in "$NATIVE_DIR"/*.so "$NATIVE_DIR"/*.pyd; do
    [ -f "$f" ] || continue
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
_try_py() {
  if command -v "$1" >/dev/null 2>&1; then
    PY="$1"
    return 0
  fi
  return 1
}
PY=""
case "$WANT_PY" in
  3.9) _try_py python3.9 || _try_py python3 || _try_py python || _try_py python3.12 || PY=python3.9 ;;
  3.12) _try_py python3.12 || _try_py python3 || _try_py python || _try_py python3.9 || PY=python3.12 ;;
  *) _try_py python3 || _try_py python3.12 || _try_py python3.9 || _try_py python || PY=python3 ;;
esac

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

OPENCLAW_DIR="${OPENCLAW_DIR:-$HOME/.openclaw/draw-cards}"
WORKSPACE_DIR="${OPENCLAW_WORKSPACE_DIR:-$HOME/.openclaw/workspace}"
CONFIG_SRC="$ROOT/scripts/config.json"
CONFIG_DST="$OPENCLAW_DIR/config.json"
NATIVE_DIR="$ROOT/card_engine_core/native"

echo "== Card Engine 安装引导 =="
echo "  发行版: $ROOT"
echo "  平台: $UNAME_S  IS_WIN=$IS_WIN  python=$PY"
echo "  HOME: $HOME"
echo "  OpenClaw 数据目录: $OPENCLAW_DIR"
echo "  OpenClaw 工作区:   $WORKSPACE_DIR"
if [ "$IS_WIN" = 1 ]; then
  echo "  Windows Git Bash：~/ 即 $HOME（通常 /c/Users/<你>）"
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
if [ "$IS_WIN" = 1 ] && [ -f "$CONFIG_DST" ]; then
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
if [ -d "$ROOT/workflows" ]; then
  CFG_PY="$(py_path "$CONFIG_DST")"
  WF_COMFYUI_DIR=$($PY -c "import json,os,sys; p=sys.argv[1]; print(os.path.expanduser(json.load(open(p,encoding='utf-8')).get('comfyui_dir','~/ComfyUI')))" "$CFG_PY" 2>/dev/null || echo "$HOME/ComfyUI")
  WF_COMFYUI_DIR="$(bash_path "$WF_COMFYUI_DIR")"
  COMFYUI_WF_DIR="$WF_COMFYUI_DIR/workflows"
  mkdir -p "$COMFYUI_WF_DIR"
  cp -R "$ROOT/workflows/"* "$COMFYUI_WF_DIR/" 2>/dev/null && echo "✓ 默认工作流已复制到 $COMFYUI_WF_DIR"
fi

# ── 4. 校验运行环境 ──
echo ""
echo "== 环境校验 =="
$PY --version 2>&1 | sed 's/^/  Python: /' || echo "  ⚠ 未找到 $PY（Windows 请装 Python 并勾选 Add to PATH，或在 Git Bash 能跑 python/python3）"

PY_MM="$($PY -c "import sys; print(f'{sys.version_info[0]}.{sys.version_info[1]}')" 2>/dev/null || true)"
if [ -n "$PY_MM" ]; then
  echo "  Python 主版本: $PY_MM"
fi
echo "  Releases 两套包：cp39=Python 3.9，cp312=Python 3.12。跑 WebUI/CLI 必须和 zip 标签一致。"
echo "  Apple 自带 /usr/bin/python3 是 3.9，请下 cp39；本机 3.12 请下 cp312。ComfyUI 可用独立 venv。"
echo "  不要把 .so 和 .pyd 混放，也不要混 3.9/3.12 native。"
if [ "$WANT_PY" = "mixed" ]; then
  echo "  ⚠ native/ 同时有 3.9 和 3.12 内核，禁止混装。请只保留一套。"
elif [ -n "$PY_MM" ] && [ -n "$WANT_PY" ] && [ "$PY_MM" != "$WANT_PY" ]; then
  echo "  ⚠ 当前解释器是 ${PY_MM}，本包内核是 Python ${WANT_PY}。"
  echo "     请改用匹配的 Python，或改下对应 cp39/cp312 压缩包。"
fi

COMFYUI_DIR="${COMFYUI_DIR:-}"
if [ -z "$COMFYUI_DIR" ] && [ -f "$CONFIG_DST" ]; then
  CFG_PY="$(py_path "$CONFIG_DST")"
  COMFYUI_DIR=$($PY -c "import json,os,sys; p=sys.argv[1]; print(os.path.expanduser(json.load(open(p,encoding='utf-8')).get('comfyui_dir','~/ComfyUI')))" "$CFG_PY" 2>/dev/null || true)
  [ -n "$COMFYUI_DIR" ] && COMFYUI_DIR="$(bash_path "$COMFYUI_DIR")"
fi
[ -n "$COMFYUI_DIR" ] || COMFYUI_DIR="$HOME/ComfyUI"
if [ -f "$COMFYUI_DIR/main.py" ]; then
  echo "  ✓ ComfyUI: $COMFYUI_DIR"
  PLUGIN_SRC="$ROOT/ComfyUI-Card-Engine"
  if [ -d "$PLUGIN_SRC" ]; then
    PLUGIN_DST="$COMFYUI_DIR/custom_nodes/ComfyUI-Card-Engine"
    mkdir -p "$COMFYUI_DIR/custom_nodes"
    rm -rf "$PLUGIN_DST"
    cp -R "$PLUGIN_SRC" "$PLUGIN_DST"
    echo "  ✓ ComfyUI 节点已安装到 $PLUGIN_DST"
  fi
else
  echo "  ⚠ ComfyUI 未安装于 ${COMFYUI_DIR}（需手动安装）"
  if [ -d "$ROOT/ComfyUI-Card-Engine" ]; then
    echo "     装好后把 $ROOT/ComfyUI-Card-Engine 拷到 ComfyUI/custom_nodes/"
  fi
fi

AGENT_BACKEND=""
if [ -f "$CONFIG_DST" ]; then
  CFG_PY="$(py_path "$CONFIG_DST")"
  AGENT_BACKEND=$($PY -c "import json,sys; print(json.load(open(sys.argv[1],encoding='utf-8')).get('agent_backend',''))" "$CFG_PY" 2>/dev/null || true)
fi
if [ -d "$WORKSPACE_DIR" ]; then
  echo "  ✓ OpenClaw 工作区: $WORKSPACE_DIR"
else
  if [ "$AGENT_BACKEND" = "custom" ]; then
    echo "  ℹ OpenClaw 可选，不是必须（当前 agent_backend=custom）"
  else
    echo "  ⚠ OpenClaw 工作区不存在: ${WORKSPACE_DIR}（当前 agent_backend=${AGENT_BACKEND:-未设置}）"
  fi
fi

# native 内核：Windows 必须是 .pyd，macOS/Linux 是 .so
# 没有内核时只提示下一步，不中断（目录/配置仍然有用）
warn_no_native() {
  echo "  ⚠ 未找到内核（$NATIVE_DIR 内无 .so 也无 .pyd）。目录与配置仍可用。"
  echo "     内核不在 git 里。请到 GitHub Releases 下载对应平台压缩包："
  echo "     AmazingDraw-darwin-cp39.zip / AmazingDraw-darwin-cp312.zip"
  echo "     AmazingDraw-windows-cp39.zip / AmazingDraw-windows-cp312.zip"
}

HAVE_SO=0
HAVE_PYD=0
if [ -d "$NATIVE_DIR" ]; then
  for f in "$NATIVE_DIR"/*.so; do
    [ -f "$f" ] && HAVE_SO=$((HAVE_SO + 1))
  done
  for f in "$NATIVE_DIR"/*.pyd; do
    [ -f "$f" ] && HAVE_PYD=$((HAVE_PYD + 1))
  done
fi

if [ "$HAVE_SO" -eq 0 ] && [ "$HAVE_PYD" -eq 0 ]; then
  warn_no_native
elif [ "$IS_WIN" = 1 ]; then
  if [ "$HAVE_PYD" -gt 0 ]; then
    echo "  ✓ native Windows 核心: $HAVE_PYD 个 .pyd（$NATIVE_DIR）"
  else
    warn_no_native
    echo "     Windows 不能用 macOS 的 .so"
  fi
  if [ "$HAVE_SO" -gt 0 ]; then
    echo "  ⚠ 目录里还有 .so，在 Windows 上加载不了（Mach-O/ELF ≠ PE）"
    echo "     正确位置：card_engine_core/native/（只放 .pyd，不要和 .so 混放）"
  fi
else
  if [ "$HAVE_SO" -gt 0 ]; then
    echo "  ✓ native 核心: $HAVE_SO 个 .so（$NATIVE_DIR）"
  else
    warn_no_native
  fi
fi

if [ -d "$NATIVE_DIR" ] && [ -n "$PY_MM" ] && { [ "$HAVE_SO" -gt 0 ] || [ "$HAVE_PYD" -gt 0 ]; }; then
  NATIVE_PYS="$($PY - "$NATIVE_DIR" <<'PY'
import re
import sys
from pathlib import Path

d = Path(sys.argv[1])
tags = set()
for p in d.iterdir():
    if not p.is_file() or p.suffix.lower() not in {".so", ".pyd"}:
        continue
    m = re.search(r"cpython-(\d{2,3})", p.name)
    if not m:
        m = re.search(r"(?:^|[._-])cp(\d{2,3})(?:[._-]|$)", p.name)
    if not m:
        continue
    raw = m.group(1)
    if len(raw) == 2:
        tags.add(f"{raw[0]}.{raw[1]}")
    else:
        tags.add(f"{raw[0]}.{raw[1:]}")
print(",".join(sorted(tags)))
PY
)"
  if [ -n "$NATIVE_PYS" ]; then
    case ",$NATIVE_PYS," in
      *",$PY_MM,"*) echo "  ✓ 内核 Python 标签 $NATIVE_PYS 与当前 $PY_MM 一致" ;;
      *) echo "  ⚠ 内核 Python 标签为 $NATIVE_PYS，与当前解释器 $PY_MM 不一致，可能无法 import" ;;
    esac
  fi
fi

echo ""
echo "== 完成 =="
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
