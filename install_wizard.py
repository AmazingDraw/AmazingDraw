#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""AmazingDraw install wizard helpers (Python 3.9+).

Called from install.sh after detect_local_deps.

Exit codes (documented):
  0  success (path written / step done / already valid)
  2  user skipped (stdout empty or note only)
  1  hard error / usage

Non-interactive when any of:
  - AMAZINGDRAW_INSTALL_NONINTERACTIVE=1
  - --non-interactive
  - stdin is not a TTY

Skip tokens (path prompts): empty Enter, s, skip, 稍后
"""
from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import socket
import sys
import traceback
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

EXIT_OK = 0
EXIT_ERR = 1
EXIT_SKIP = 2

SKIP_TOKENS = frozenset({"", "s", "skip", "稍后", "S", "SKIP"})

# Moody default model checklist (relative to $COMFYUI_DIR/models/)
MOODY_MODELS: List[Tuple[str, str, str]] = [
    # (label, filename, subdir under models/)
    ("一阶段 UNET（ZIB）", "MoodyWildMix-zib-base.safetensors", "diffusion_models"),
    ("二阶段 UNET（ZIT）", "MoodyRealMix-zit-write.safetensors", "diffusion_models"),
    ("文本编码器", "qwen_3_4b.safetensors", "text_encoders"),
    ("VAE", "ae.safetensors", "vae"),
]

DEFAULT_WF_JSON = "Moody_ZIB_ZIT_20步_CFG3_512x768.json"
DEFAULT_WF_ID = "moody_zib_zit"


def _eprint(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


def _out(msg: str) -> None:
    print(msg, flush=True)


def is_interactive(flag_non_interactive: bool = False) -> bool:
    if flag_non_interactive:
        return False
    env = (os.environ.get("AMAZINGDRAW_INSTALL_NONINTERACTIVE") or "").strip()
    if env in ("1", "true", "TRUE", "yes", "YES"):
        return False
    try:
        return sys.stdin.isatty() and sys.stderr.isatty()
    except Exception:
        return False


def _load_cfg(path: Path) -> Dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def merge_config(path: Path, updates: Dict[str, Any]) -> None:
    """Merge keys into config.json; preserve other keys."""
    cfg = _load_cfg(path)
    cfg.update(updates)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(cfg, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def _expand(raw: str) -> Path:
    return Path(os.path.expanduser(str(raw).strip())).expanduser()


def _is_comfyui_root(p: Path) -> bool:
    try:
        return p.is_dir() and (p / "main.py").is_file()
    except Exception:
        return False


def _is_openclaw_home(p: Path) -> bool:
    try:
        return p.is_dir() and (p / "openclaw.json").is_file()
    except Exception:
        return False


def _is_bin_file(p: Path) -> bool:
    try:
        return p.is_file()
    except Exception:
        return False


def find_hints_file(root: Optional[Path] = None) -> Optional[Path]:
    """Locate workflow_moody_zib_zit.txt (mirrors detect_local_deps search)."""
    name = "workflow_moody_zib_zit.txt"
    candidates: List[Path] = []
    here = Path(__file__).resolve().parent
    if root is not None:
        candidates.extend(
            [
                root / "tools" / "install_hints" / name,
                root / "install_hints" / name,
            ]
        )
    candidates.extend(
        [
            here / "install_hints" / name,
            here.parent / "install_hints" / name,
            Path.cwd() / "tools" / "install_hints" / name,
            Path.cwd() / "install_hints" / name,
        ]
    )
    for c in candidates:
        if c.is_file():
            return c
    return None


def ask_line(prompt: str) -> str:
    try:
        return input(prompt)
    except EOFError:
        return ""


def prompt_path(
    kind: str,
    *,
    max_retries: int = 3,
    interactive: bool = True,
) -> Tuple[Optional[str], str]:
    """Ask user for a path. Returns (path_or_None, status) status=ok|skip|invalid.

    kind: comfyui | openclaw_home | openclaw_bin
    """
    if not interactive:
        return None, "skip"

    validators = {
        "comfyui": (
            "请粘贴本机 ComfyUI CLI 根目录（需含 main.py；仅 Comfy Desktop App 不够）。"
            "可设环境变量 COMFYUI_DIR。直接回车 / s / skip / 稍后 可跳过：\n> ",
            _is_comfyui_root,
            "无效：目录下找不到 main.py（需要 CLI 根目录，不是 Desktop App）",
        ),
        "openclaw_home": (
            "请粘贴 OpenClaw 家目录（需含 openclaw.json，常见 ~/.openclaw）。回车 / s / skip / 稍后 可跳过：\n> ",
            _is_openclaw_home,
            "无效：目录下找不到 openclaw.json",
        ),
        "openclaw_bin": (
            "请粘贴 openclaw 可执行文件路径。回车 / s / skip / 稍后 可跳过：\n> ",
            _is_bin_file,
            "无效：不是可读文件",
        ),
    }
    if kind not in validators:
        _eprint("未知 kind: " + kind)
        return None, "invalid"
    prompt, validator, err_msg = validators[kind]

    for attempt in range(1, max_retries + 1):
        raw = ask_line(prompt)
        token = raw.strip()
        if token in SKIP_TOKENS or token.lower() in ("s", "skip"):
            return None, "skip"
        # also treat pure skip-like Chinese
        if token in SKIP_TOKENS:
            return None, "skip"
        try:
            p = _expand(token)
        except Exception:
            _eprint("  路径无法解析，请重试（%d/%d）" % (attempt, max_retries))
            continue
        if validator(p):
            try:
                return str(p.resolve()), "ok"
            except Exception:
                return str(p), "ok"
        _eprint("  %s（%d/%d）" % (err_msg, attempt, max_retries))

    _eprint("  已达最大重试次数，跳过本项。")
    # offer explicit skip confirmation is already done by max retries
    return None, "skip"


def cfg_comfyui_valid(cfg: Dict[str, Any]) -> Optional[Path]:
    raw = cfg.get("comfyui_dir")
    if isinstance(raw, str) and raw.strip():
        p = _expand(raw)
        if _is_comfyui_root(p):
            return p
    return None


def cfg_openclaw_home_valid(cfg: Dict[str, Any]) -> Optional[Path]:
    raw = cfg.get("openclaw_home")
    if isinstance(raw, str) and raw.strip():
        p = _expand(raw)
        if _is_openclaw_home(p):
            return p
    return None


def cfg_openclaw_bin_valid(cfg: Dict[str, Any]) -> Optional[str]:
    raw = cfg.get("openclaw_bin")
    if isinstance(raw, str) and raw.strip():
        p = _expand(raw)
        if _is_bin_file(p):
            try:
                return str(p.resolve())
            except Exception:
                return str(p)
    return None



def _normalize_comfy_host(raw: str) -> str:
    """Ensure scheme; empty stays empty."""
    s = (raw or "").strip()
    if not s:
        return ""
    if "://" not in s:
        s = "http://" + s
    return s


def resolve_comfy_display_url(cfg: Dict[str, Any]) -> Tuple[str, bool]:
    """Return (url, from_config). Default http://127.0.0.1:8188 when unset."""
    raw = _normalize_comfy_host(str(cfg.get("comfyui_host") or ""))
    if raw:
        return raw, True
    return "http://127.0.0.1:8188", False


def resolve_webui_display_url(cfg: Dict[str, Any]) -> Tuple[str, bool]:
    """Build AmazingDraw WebUI URL from webui_host/webui_port; default :8318.

    Bind address 0.0.0.0 / :: is shown as 127.0.0.1 for browser copy-paste.
    """
    host = str(cfg.get("webui_host") or "").strip()
    port_raw = cfg.get("webui_port")
    from_cfg = bool(host) or (port_raw is not None and str(port_raw).strip() != "")
    if not from_cfg:
        return "http://127.0.0.1:8318", False
    if not host or host in ("0.0.0.0", "::", "[::]"):
        host = "127.0.0.1"
    try:
        port_i = int(port_raw) if port_raw is not None and str(port_raw).strip() != "" else 8318
    except (TypeError, ValueError):
        port_i = 8318
    return "http://%s:%d" % (host, port_i), True


def _parse_req_pin(requirements_text: str, dist_name: str) -> Optional[str]:
    """Return pinned version for dist_name==X from requirements.txt, else None."""
    key = dist_name.strip().lower().replace("_", "-")
    for line in requirements_text.splitlines():
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        s = s.split(";", 1)[0].strip()
        low = s.lower().replace("_", "-")
        if low.startswith(key + "=="):
            return s.split("==", 1)[1].strip()
        if low.startswith(key + "==="):
            return s.split("===", 1)[1].strip()
    return None


def check_comfy_venv_aimdo(comfy: Optional[Path]) -> None:
    """Warn-only: prefer production .venv; check comfy_aimdo pin / vram_buffer import."""
    if comfy is None:
        return
    if sys.platform == "win32":
        venv_py = comfy / ".venv" / "Scripts" / "python.exe"
    else:
        venv_py = comfy / ".venv" / "bin" / "python"
    if not venv_py.is_file():
        _eprint("  ComfyUI venv 依赖:   （无 .venv，跳过 comfy-aimdo 检查）")
        return

    pinned = None
    req = comfy / "requirements.txt"
    if req.is_file():
        try:
            pinned = _parse_req_pin(
                req.read_text(encoding="utf-8", errors="replace"), "comfy-aimdo"
            )
        except Exception:
            pinned = None

    probe_src = (
        "import importlib, importlib.metadata as m\n"
        "out = {}\n"
        "try:\n"
        "    out['ver'] = m.version('comfy-aimdo')\n"
        "except Exception as e:\n"
        "    out['ver_err'] = str(e)\n"
        "try:\n"
        "    importlib.import_module('comfy_aimdo.vram_buffer')\n"
        "    out['vram'] = True\n"
        "except Exception as e:\n"
        "    out['vram'] = False\n"
        "    out['vram_err'] = str(e)\n"
        "print(out)\n"
    )
    try:
        import ast
        import subprocess

        proc = subprocess.run(
            [str(venv_py), "-c", probe_src],
            capture_output=True,
            text=True,
            timeout=12,
        )
        raw_out = (proc.stdout or "").strip().splitlines()
        info: Dict[str, Any] = {}
        if raw_out:
            try:
                info = ast.literal_eval(raw_out[-1])
            except Exception:
                info = {}
        if proc.returncode != 0 and not info:
            err = ((proc.stderr or proc.stdout or "unknown").strip())[:160]
            _eprint(
                "  ComfyUI venv 依赖:   ⚠  .venv Python 无法运行探测（安装不失败）：%s"
                % err
            )
            return
        ver = info.get("ver")
        vram_ok = bool(info.get("vram"))
        problems = []
        if pinned and ver and str(ver) != str(pinned):
            problems.append(
                "已装 comfy-aimdo==%s，requirements 钉 %s" % (ver, pinned)
            )
        elif pinned and not ver:
            problems.append(
                "requirements 钉 comfy-aimdo==%s，但 .venv 未安装或无法读取版本（%s）"
                % (pinned, info.get("ver_err") or "n/a")
            )
        if not vram_ok:
            problems.append(
                "import comfy_aimdo.vram_buffer 失败（%s）"
                % (info.get("vram_err") or "n/a")
            )
        if problems:
            _eprint(
                "  ComfyUI venv 依赖:   ⚠  "
                + "；".join(problems)
                + "。安装不失败；请在 ComfyUI 的 .venv 中按 requirements.txt 安装/对齐 comfy-aimdo。"
            )
        else:
            msg = "comfy_aimdo"
            if ver:
                msg += "==%s" % ver
            if pinned:
                msg += "（与 requirements 一致）"
            msg += "；vram_buffer 可导入"
            _eprint("  ComfyUI venv 依赖:   ✓  " + msg)
    except Exception as e:
        _eprint(
            "  ComfyUI venv 依赖:   ⚠  探测异常（安装不失败）：%s" % (str(e)[:160],)
        )


def scan_moody_models(comfyui: Optional[Path]) -> List[Tuple[str, str, str, bool]]:
    """Return list of (label, filename, rel_subdir, found)."""
    rows: List[Tuple[str, str, str, bool]] = []
    models_root = (comfyui / "models") if comfyui is not None else None
    for label, fname, sub in MOODY_MODELS:
        found = False
        if models_root is not None:
            target = models_root / sub / fname
            found = target.is_file()
            if not found:
                # also search under models/ recursively by name
                try:
                    for hit in models_root.rglob(fname):
                        if hit.is_file():
                            found = True
                            break
                except Exception:
                    pass
        rows.append((label, fname, sub, found))
    return rows


def print_model_checklist(comfyui: Optional[Path], root: Optional[Path] = None) -> None:
    hints = find_hints_file(root)
    if hints is not None:
        try:
            _eprint(hints.read_text(encoding="utf-8"))
        except Exception:
            pass
    else:
        _eprint("（未找到 install_hints/workflow_moody_zib_zit.txt，打印内置简表）")
        for label, fname, sub in MOODY_MODELS:
            _eprint("  - %s: models/%s/%s" % (label, sub, fname))

    rows = scan_moody_models(comfyui)
    if comfyui is None:
        _eprint("本机尚未确认 ComfyUI 路径，无法扫描模型文件是否已就位。")
        return
    _eprint("")
    _eprint("模型就位扫描（$COMFYUI_DIR/models/）：")
    for label, fname, sub, found in rows:
        mark = "✓" if found else "✗"
        _eprint("  %s  %s  → models/%s/%s" % (mark, label, sub, fname))
    missing = [r for r in rows if not r[3]]
    if missing:
        _eprint("  缺 %d 个；装好模型前默认 Moody 出图可能失败。" % len(missing))
    else:
        _eprint("  清单内模型均已找到。")


def copy_default_workflows(root: Path, comfyui: Path) -> List[str]:
    """Copy ROOT/workflows/* into ComfyUI/workflows/. Return copied basenames."""
    src_dir = root / "workflows"
    if not src_dir.is_dir():
        return []
    dest = comfyui / "workflows"
    dest.mkdir(parents=True, exist_ok=True)
    copied: List[str] = []
    for item in sorted(src_dir.iterdir()):
        if item.name.startswith("."):
            continue
        if item.is_file():
            shutil.copy2(item, dest / item.name)
            copied.append(item.name)
        elif item.is_dir():
            target = dest / item.name
            if target.exists():
                shutil.rmtree(target)
            shutil.copytree(item, target)
            copied.append(item.name + "/")
    return copied


def append_install_report_note(config_path: Path, note: str) -> None:
    """Append a note near the config's install-report.txt if present/creatable."""
    report = config_path.parent / "install-report.txt"
    try:
        with report.open("a", encoding="utf-8") as fh:
            fh.write("\n# wizard note\n")
            fh.write(note.rstrip() + "\n")
    except Exception:
        pass


def cmd_prompt_comfyui(args: argparse.Namespace) -> int:
    config = Path(os.path.expanduser(args.config))
    cfg = _load_cfg(config)
    existing = cfg_comfyui_valid(cfg)
    interactive = is_interactive(args.non_interactive)
    if existing is not None:
        _eprint("✓ ComfyUI 已配置：" + str(existing))
        _out(str(existing))
        return EXIT_OK
    if not interactive:
        _eprint("ℹ 非交互模式：跳过 ComfyUI 路径粘贴。")
        return EXIT_SKIP
    _eprint("")
    _eprint("—— ComfyUI CLI 路径 ——")
    _eprint("自动侦测未找到有效 ComfyUI CLI（需含 main.py 的源码/git 根目录）。")
    _eprint("仅有 Comfy Desktop App 不够；可查看 Application Support 配置里的 basePath，")
    _eprint("或粘贴 CLI 路径 / 设 COMFYUI_DIR。")
    path, status = prompt_path("comfyui", max_retries=args.max_retries, interactive=True)
    if status != "ok" or not path:
        _eprint("已跳过。之后可在 WebUI「配置」填写 CLI 根目录，或设环境变量 COMFYUI_DIR 再跑安装。")
        return EXIT_SKIP
    # store ~/ComfyUI form when possible
    store = path
    try:
        home = Path.home().resolve()
        resolved = Path(path).resolve()
        if resolved == home / "ComfyUI":
            store = "~/ComfyUI"
    except Exception:
        pass
    merge_config(config, {"comfyui_dir": store})
    _eprint("✓ 已写入 comfyui_dir = " + store)
    _out(path)
    return EXIT_OK


def cmd_prompt_openclaw(args: argparse.Namespace) -> int:
    config = Path(os.path.expanduser(args.config))
    cfg = _load_cfg(config)
    interactive = is_interactive(args.non_interactive)
    home_ok = cfg_openclaw_home_valid(cfg)
    bin_ok = cfg_openclaw_bin_valid(cfg)
    if home_ok is not None or bin_ok is not None:
        if home_ok is not None:
            _eprint("✓ OpenClaw home 已配置：" + str(home_ok))
        if bin_ok is not None:
            _eprint("✓ OpenClaw bin 已配置：" + bin_ok)
        _out(str(home_ok or bin_ok or ""))
        return EXIT_OK
    if not interactive:
        _eprint("ℹ 非交互模式：跳过 OpenClaw 路径粘贴。")
        _eprint("  没有 OpenClaw 时，WebUI 的 AI 连抽/常规对话不可用；直投/精选/出图可先用。")
        return EXIT_SKIP
    _eprint("")
    _eprint("—— OpenClaw（可选）——")
    _eprint("未侦测到 OpenClaw。AI 连抽/常规对话需要它；直投/精选/出图可先跳过。")
    updates: Dict[str, Any] = {}
    path, status = prompt_path("openclaw_home", max_retries=args.max_retries, interactive=True)
    if status == "ok" and path:
        updates["openclaw_home"] = path
        _eprint("✓ 已记录 openclaw_home")
    path2, status2 = prompt_path("openclaw_bin", max_retries=args.max_retries, interactive=True)
    if status2 == "ok" and path2:
        updates["openclaw_bin"] = path2
        _eprint("✓ 已记录 openclaw_bin")
    if updates:
        merge_config(config, updates)
        _out(updates.get("openclaw_home") or updates.get("openclaw_bin") or "")
        return EXIT_OK
    _eprint("已跳过 OpenClaw。WebUI 对话相关能力将不完整，不影响内核/native 出图主路径。")
    return EXIT_SKIP


def _repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _read_version(root: Optional[Path] = None) -> str:
    root = root or _repo_root()
    vf = root / "VERSION"
    try:
        if vf.is_file():
            return vf.read_text(encoding="utf-8").strip() or "unknown"
    except Exception:
        pass
    return "unknown"


def _probe_comfy_endpoint(comfy_host: str, path: str, timeout: float = 3.0) -> Dict[str, Any]:
    """Probe a ComfyUI HTTP endpoint; return status dict (never raises)."""
    import urllib.error
    import urllib.request

    url = comfy_host.rstrip("/") + path
    out: Dict[str, Any] = {"url": url, "ok": False, "http_code": None, "error": None, "bytes": 0}
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            body = resp.read()
            out["http_code"] = getattr(resp, "status", None) or resp.getcode()
            out["bytes"] = len(body)
            out["ok"] = True
            out["body"] = body
    except urllib.error.HTTPError as e:
        out["http_code"] = e.code
        out["error"] = f"HTTPError {e.code}: {e.reason}"
    except Exception as e:
        out["error"] = f"{type(e).__name__}: {e}"
    return out


def _detect_workflow_shape(data: Any) -> str:
    if not isinstance(data, dict) or not data:
        return "unknown/empty"
    if isinstance(data.get("nodes"), list):
        return "UI (has nodes list)"
    sample = []
    for key, val in data.items():
        if str(key).startswith("_"):
            continue
        if not isinstance(val, dict):
            return "unknown/non-node-map"
        sample.append(val)
        if len(sample) >= 5:
            break
    if sample and all("class_type" in n and "inputs" in n for n in sample):
        return "API (class_type map)"
    return "unknown"


def _default_convert_report_path(dest_api: Path, config_path: Optional[Path] = None) -> Path:
    """Stable report location: next to attempted API output."""
    return Path(str(dest_api) + ".convert-report.md")


def _write_convert_report(
    report_path: Path,
    *,
    status: str,
    input_path: Path,
    output_path: Path,
    comfy_host: str,
    object_info_probe: Dict[str, Any],
    system_stats_probe: Dict[str, Any],
    comfyui_dir: Optional[Path],
    converter_module: str,
    input_shape: str,
    warnings: List[str],
    exc_text: Optional[str],
    api_json: Optional[Dict[str, Any]],
    root: Optional[Path] = None,
) -> Path:
    root = root or _repo_root()
    ts_local = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S %z")
    try:
        host = socket.gethostname()
    except Exception:
        host = "unknown"
    version = _read_version(root)
    in_size = input_path.stat().st_size if input_path.is_file() else -1
    out_size = output_path.stat().st_size if output_path.is_file() else -1
    node_count = len(api_json) if isinstance(api_json, dict) else 0

    sample_lines: List[str] = []
    if isinstance(api_json, dict) and api_json:
        for i, (nid, node) in enumerate(api_json.items()):
            if i >= 2:
                break
            snippet = json.dumps({nid: node}, ensure_ascii=False, indent=2)
            if len(snippet) > 800:
                snippet = snippet[:800] + "\n… (truncated)"
            sample_lines.append(snippet)

    warn_block = "\n".join(f"- {w}" for w in warnings) if warnings else "- (none)"
    oi = object_info_probe
    ss = system_stats_probe

    body = f"""# AmazingDraw UI→API convert report / 转换反馈报告

- **timestamp (local)**: {ts_local}
- **hostname**: {host}
- **AmazingDraw / construction VERSION**: {version}
- **status**: `{status}`

## Paths

- **input**: `{input_path}` (size={in_size} bytes)
- **output attempted**: `{output_path}` (size={out_size} bytes)
- **report**: `{report_path.resolve()}`

## ComfyUI connectivity

- **comfyui_host**: `{comfy_host}`
- **/object_info**: ok={oi.get('ok')} http={oi.get('http_code')} err={oi.get('error')!r} bytes={oi.get('bytes')}
- **/system_stats**: ok={ss.get('ok')} http={ss.get('http_code')} err={ss.get('error')!r} bytes={ss.get('bytes')}
- **comfyui_dir (config)**: `{comfyui_dir or '(none)'}`

## Input shape

- **detected**: {input_shape}

## Converter

- **module used**: `{converter_module}`
- **expected API**: `perform_workflow_conversion(ui_json, object_info) -> (api_json, warnings)`

## Result

- **node_count**: {node_count}
- **warnings ({len(warnings)})**:
{warn_block}

## Exception / traceback

```
{exc_text or '(none)'}
```

## Sample API nodes (first 1–2, truncated)

```json
{chr(10).join(sample_lines) if sample_lines else '(none written)'}
```

## Environment

- **python**: {sys.version.replace(chr(10), ' ')}
- **platform**: {platform.platform()}
- **executable**: `{sys.executable}`

## Next actions for local AI agent / 给本地 AI agent 的下一步

1. Verify ComfyUI is running and `/object_info` returns 200 with node class definitions.
2. Re-run convert:
   - `python3 tools/install_wizard.py convert-workflow --input <ui.json> --output <out.api.json> [--report <path>] [--host http://127.0.0.1:8188]`
   - or import `scripts/webui/workflow_convert_lib.perform_workflow_conversion`.
3. Known issue classes to check if graph looks wrong:
   - leftover **Power Lora** / rgthree widget mapping
   - missing `class_type` (custom node not installed → absent from object_info)
   - bad / dangling **links** (incl. 4-tuple vs 6-tuple link formats)
   - virtual/muted nodes (Reroute/Note/Primitive) skipped
4. Reminder: **convert ≠** `config.json` → `workflows.<id>` prompt_nodes / negative_nodes / seed_nodes / size_nodes / lora_nodes binding. Node metadata remains manual.
5. If warnings only: API JSON was still written — inspect graph before relying on it for AmazingDraw queue.

---
请把本报告文件完整发给本地 AI agent 继续处理。
"""
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(body, encoding="utf-8")
    return report_path.resolve()


def _import_perform_workflow_conversion() -> Tuple[Any, str]:
    """Prefer workflow_convert_lib; fall back to api_queue. Returns (fn, module_label)."""
    root_guess = _repo_root()
    webui = str(root_guess / "scripts" / "webui")
    if webui not in sys.path:
        sys.path.insert(0, webui)
    try:
        from workflow_convert_lib import perform_workflow_conversion  # type: ignore

        mod_path = Path(sys.modules["workflow_convert_lib"].__file__ or "").resolve()
        return perform_workflow_conversion, f"workflow_convert_lib ({mod_path})"
    except Exception as e1:
        try:
            from api_queue import perform_workflow_conversion  # type: ignore

            mod_path = Path(sys.modules["api_queue"].__file__ or "").resolve()
            return (
                perform_workflow_conversion,
                f"api_queue fallback ({mod_path}); workflow_convert_lib import failed: {e1}",
            )
        except Exception as e2:
            raise ImportError(
                f"cannot import perform_workflow_conversion "
                f"(workflow_convert_lib: {e1}; api_queue: {e2})"
            ) from e2


def _normalize_conversion_result(raw: Any) -> Tuple[Optional[Dict[str, Any]], List[str]]:
    """Accept (api, warnings) tuple or legacy single-dict return."""
    if isinstance(raw, tuple) and len(raw) >= 1:
        api = raw[0]
        warnings = list(raw[1]) if len(raw) > 1 and isinstance(raw[1], list) else []
        if isinstance(api, dict):
            return api, warnings
        return None, warnings + [f"converter returned non-dict api: {type(api).__name__}"]
    if isinstance(raw, dict):
        return raw, ["legacy converter returned bare dict (no warnings list)"]
    return None, [f"converter returned unexpected type: {type(raw).__name__}"]


def _try_convert_api(
    ui_json_path: Path,
    dest_api: Path,
    comfy_host: str,
    *,
    config_path: Optional[Path] = None,
    comfyui_dir: Optional[Path] = None,
    root: Optional[Path] = None,
    report_path: Optional[Path] = None,
    write_report_on_success: bool = False,
) -> Tuple[str, Optional[Path], List[str]]:
    """Convert UI workflow JSON → API JSON via workflow_convert_lib.

    Returns (status, report_path_or_None, warnings) where status is:
      "ok" | "ok_with_warnings" | "fail"
    On fail or warnings, always writes a comprehensive AI-agent report.
    """
    root = root or _repo_root()
    host = (comfy_host or "http://127.0.0.1:8188").strip()
    warnings: List[str] = []
    api_json: Optional[Dict[str, Any]] = None
    exc_text: Optional[str] = None
    converter_module = "(not loaded)"
    input_shape = "unknown"
    object_info: Optional[Dict[str, Any]] = None

    oi_probe = _probe_comfy_endpoint(host, "/object_info")
    ss_probe = _probe_comfy_endpoint(host, "/system_stats")
    if oi_probe.get("ok") and oi_probe.get("body"):
        try:
            object_info = json.loads(oi_probe["body"].decode("utf-8"))
        except Exception as e:
            oi_probe["ok"] = False
            oi_probe["error"] = f"JSON decode: {e}"
            exc_text = traceback.format_exc()

    ui_json: Any = None
    try:
        ui_json = json.loads(ui_json_path.read_text(encoding="utf-8"))
        input_shape = _detect_workflow_shape(ui_json)
    except Exception:
        exc_text = traceback.format_exc()
        status = "fail"
        rp = _write_convert_report(
            report_path or _default_convert_report_path(dest_api, config_path),
            status=status,
            input_path=ui_json_path,
            output_path=dest_api,
            comfy_host=host,
            object_info_probe={k: v for k, v in oi_probe.items() if k != "body"},
            system_stats_probe={k: v for k, v in ss_probe.items() if k != "body"},
            comfyui_dir=comfyui_dir,
            converter_module=converter_module,
            input_shape=input_shape,
            warnings=warnings + ["failed to read/parse input JSON"],
            exc_text=exc_text,
            api_json=None,
            root=root,
        )
        return status, rp, warnings

    if not oi_probe.get("ok") or not isinstance(object_info, dict):
        status = "fail"
        warnings.append("ComfyUI /object_info not reachable or invalid — conversion requires it")
        rp = _write_convert_report(
            report_path or _default_convert_report_path(dest_api, config_path),
            status=status,
            input_path=ui_json_path,
            output_path=dest_api,
            comfy_host=host,
            object_info_probe={k: v for k, v in oi_probe.items() if k != "body"},
            system_stats_probe={k: v for k, v in ss_probe.items() if k != "body"},
            comfyui_dir=comfyui_dir,
            converter_module=converter_module,
            input_shape=input_shape,
            warnings=warnings,
            exc_text=exc_text or oi_probe.get("error"),
            api_json=None,
            root=root,
        )
        return status, rp, warnings

    try:
        perform, converter_module = _import_perform_workflow_conversion()
        raw = perform(ui_json, object_info)
        api_json, conv_warns = _normalize_conversion_result(raw)
        warnings.extend(conv_warns)
    except Exception:
        exc_text = traceback.format_exc()
        api_json = None
        warnings.append("converter raised or import failed")

    if not isinstance(api_json, dict) or not api_json:
        status = "fail"
        if not warnings:
            warnings.append("empty or invalid API JSON from converter")
        rp = _write_convert_report(
            report_path or _default_convert_report_path(dest_api, config_path),
            status=status,
            input_path=ui_json_path,
            output_path=dest_api,
            comfy_host=host,
            object_info_probe={k: v for k, v in oi_probe.items() if k != "body"},
            system_stats_probe={k: v for k, v in ss_probe.items() if k != "body"},
            comfyui_dir=comfyui_dir,
            converter_module=converter_module,
            input_shape=input_shape,
            warnings=warnings,
            exc_text=exc_text,
            api_json=api_json if isinstance(api_json, dict) else None,
            root=root,
        )
        return status, rp, warnings

    try:
        dest_api.parent.mkdir(parents=True, exist_ok=True)
        dest_api.write_text(
            json.dumps(api_json, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
    except Exception:
        exc_text = traceback.format_exc()
        status = "fail"
        warnings.append("failed to write API JSON to disk")
        rp = _write_convert_report(
            report_path or _default_convert_report_path(dest_api, config_path),
            status=status,
            input_path=ui_json_path,
            output_path=dest_api,
            comfy_host=host,
            object_info_probe={k: v for k, v in oi_probe.items() if k != "body"},
            system_stats_probe={k: v for k, v in ss_probe.items() if k != "body"},
            comfyui_dir=comfyui_dir,
            converter_module=converter_module,
            input_shape=input_shape,
            warnings=warnings,
            exc_text=exc_text,
            api_json=api_json,
            root=root,
        )
        return status, rp, warnings

    if warnings:
        status = "ok_with_warnings"
        rp = _write_convert_report(
            report_path or _default_convert_report_path(dest_api, config_path),
            status=status,
            input_path=ui_json_path,
            output_path=dest_api,
            comfy_host=host,
            object_info_probe={k: v for k, v in oi_probe.items() if k != "body"},
            system_stats_probe={k: v for k, v in ss_probe.items() if k != "body"},
            comfyui_dir=comfyui_dir,
            converter_module=converter_module,
            input_shape=input_shape,
            warnings=warnings,
            exc_text=exc_text,
            api_json=api_json,
            root=root,
        )
        return status, rp, warnings

    status = "ok"
    rp = None
    if write_report_on_success:
        rp = _write_convert_report(
            report_path or _default_convert_report_path(dest_api, config_path),
            status=status,
            input_path=ui_json_path,
            output_path=dest_api,
            comfy_host=host,
            object_info_probe={k: v for k, v in oi_probe.items() if k != "body"},
            system_stats_probe={k: v for k, v in ss_probe.items() if k != "body"},
            comfyui_dir=comfyui_dir,
            converter_module=converter_module,
            input_shape=input_shape,
            warnings=warnings,
            exc_text=None,
            api_json=api_json,
            root=root,
        )
    return status, rp, warnings


def cmd_workflow_step(args: argparse.Namespace) -> int:
    config = Path(os.path.expanduser(args.config))
    root = Path(os.path.expanduser(args.root))
    cfg = _load_cfg(config)
    comfy = cfg_comfyui_valid(cfg)
    interactive = is_interactive(args.non_interactive)

    _eprint("")
    _eprint("—— 工作流 ——")

    # Always try to copy default Moody json when ComfyUI is known
    copied: List[str] = []
    if comfy is not None:
        copied = copy_default_workflows(root, comfy)
        if copied:
            _eprint("✓ 默认工作流已复制到 %s/workflows/（%s）" % (comfy, ", ".join(copied)))
        else:
            _eprint("ℹ 发行版 workflows/ 为空或缺失，跳过复制。")
    else:
        _eprint("ℹ 尚无有效 ComfyUI 路径，跳过默认工作流复制。")

    print_model_checklist(comfy, root=root)

    if not interactive:
        _eprint("ℹ 非交互模式：使用默认 dual-sample（moody_zib_zit），不询问自定义工作流。")
        return EXIT_OK

    _eprint("")
    _eprint("工作流选项：")
    _eprint("  1  使用默认 Moody 双采样（推荐，已复制 JSON + 上表模型清单）")
    _eprint("  2  导入我自己的工作流 JSON")
    _eprint("  s  跳过")
    choice = ask_line("请选择 [1/2/s]（默认 1）：").strip().lower()
    if choice in SKIP_TOKENS or choice in ("s", "skip", "稍后"):
        _eprint("已跳过工作流步骤。")
        return EXIT_SKIP
    if choice in ("", "1"):
        _eprint("✓ 使用默认 moody_zib_zit。请按清单补齐模型后再出图。")
        # ensure default_workflow key if empty
        if not str(cfg.get("default_workflow") or "").strip():
            merge_config(config, {"default_workflow": DEFAULT_WF_ID})
        return EXIT_OK

    if choice != "2":
        _eprint("未识别选项，按跳过处理。")
        return EXIT_SKIP

    # Custom path
    _eprint("")
    _eprint("【重要说明】自定义工作流 ≠ 一键接好 AmazingDraw")
    _eprint("  · 后端可以把 ComfyUI「界面 JSON」转成「API JSON」（需本机 ComfyUI")
    _eprint("    提供 /object_info），但这只是格式转换。")
    _eprint("  · AmazingDraw 出图还要在 config.json 的 workflows.<id> 里填写")
    _eprint("    prompt_nodes / negative_nodes / seed_nodes / size_nodes / lora_nodes 等。")
    _eprint("  · 任意第三方图的节点 ID 自动发现尚未实现，需要你手工/进阶配置。")
    _eprint("  · 因此：导入只会把 JSON 拷进 ComfyUI/workflows/，不会自动写节点绑定。")
    _eprint("")

    custom_path = None
    for attempt in range(1, args.max_retries + 1):
        raw = ask_line("请粘贴工作流 JSON 文件路径（回车 / s / skip / 稍后 可跳过）：\n> ")
        token = raw.strip()
        if token in SKIP_TOKENS or token.lower() in ("s", "skip"):
            _eprint("已跳过自定义导入。")
            append_install_report_note(
                config,
                "custom_workflow: skipped by user after warning (convert≠AmazingDraw metadata)",
            )
            return EXIT_SKIP
        try:
            p = _expand(token)
        except Exception:
            _eprint("  路径无法解析（%d/%d）" % (attempt, args.max_retries))
            continue
        if p.is_file() and p.suffix.lower() == ".json":
            custom_path = p
            break
        _eprint("  无效：需要存在的 .json 文件（%d/%d）" % (attempt, args.max_retries))
    if custom_path is None:
        _eprint("已达最大重试，跳过自定义导入。")
        append_install_report_note(
            config, "custom_workflow: retries exhausted; skipped"
        )
        return EXIT_SKIP

    if comfy is None:
        _eprint("没有有效 ComfyUI 目录，无法拷贝。请先配置 comfyui_dir。")
        append_install_report_note(
            config,
            "custom_workflow: had file %s but no comfyui_dir" % custom_path,
        )
        return EXIT_SKIP

    dest_dir = comfy / "workflows"
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / custom_path.name
    shutil.copy2(custom_path, dest)
    _eprint("✓ 已复制到 " + str(dest))

    note_lines = [
        "custom_workflow: copied %s → %s" % (custom_path, dest),
        "  WARN: UI→API convert ≠ AmazingDraw workflows.<id> node metadata;",
        "  prompt_nodes/seed_nodes/etc. remain MANUAL / advanced.",
    ]

    # Optional UI→API convert (shared workflow_convert_lib)
    _eprint("")
    _eprint("【可选】UI→API 转换")
    _eprint("  若本机 ComfyUI 已在跑（提供 /object_info），可将界面 JSON 转成 API JSON，")
    _eprint("  并保存为旁边的 *.api.json。失败或有警告时会写一份可粘贴给本地 AI 的报告。")
    _eprint("  注意：转换成功 ≠ 已接好 AmazingDraw 的 workflows.<id> 节点绑定。")
    do_convert = ask_line("是否现在尝试 UI→API 转换？[y/N]：").strip().lower()
    if do_convert in ("y", "yes", "是"):
        host = str(cfg.get("comfyui_host") or "http://127.0.0.1:8188").strip()
        api_dest = dest.with_name(dest.stem + ".api.json")
        status, report_path, conv_warns = _try_convert_api(
            dest,
            api_dest,
            host,
            config_path=config,
            comfyui_dir=comfy,
            root=root,
        )
        if status == "ok":
            _eprint("✓ 已保存 API JSON：" + str(api_dest))
            _eprint("  提醒：AmazingDraw 节点元数据（prompt_nodes 等）仍需手工配置。")
            note_lines.append("  convert: ok wrote %s (node-id config still manual)" % api_dest)
        elif status == "ok_with_warnings":
            _eprint("✓ 已保存 API JSON：" + str(api_dest))
            _eprint("  ⚠ 转换有 %d 条警告；若图看起来不对，请把报告发给本地 AI agent。" % len(conv_warns))
            if report_path:
                _eprint("  报告文件：" + str(report_path))
                _eprint("  请把下面的报告文件发给本地 AI agent 继续处理")
            _eprint("  提醒：AmazingDraw 节点元数据仍需手工配置。")
            note_lines.append(
                "  convert: ok_with_warnings wrote %s; report=%s; warnings=%d"
                % (api_dest, report_path, len(conv_warns))
            )
        else:
            _eprint("✗ UI→API 转换失败（ComfyUI 未响应 /object_info、导入错误、或结果为空）。")
            if report_path:
                _eprint("  报告文件：" + str(report_path))
                _eprint("  请把下面的报告文件发给本地 AI agent 继续处理")
            else:
                _eprint("  （未能写出报告文件）")
            note_lines.append(
                "  convert: fail report=%s warnings=%d" % (report_path, len(conv_warns))
            )

    _eprint("")
    _eprint("可跳过进阶配置，或查阅 doc/CONFIG_GUIDE.md / config.example.json 里 moody_zib_zit 示例。")
    append_install_report_note(config, "\n".join(note_lines))
    _out(str(dest))
    return EXIT_OK


def cmd_telegram_step(args: argparse.Namespace) -> int:
    config = Path(os.path.expanduser(args.config))
    cfg = _load_cfg(config)
    interactive = is_interactive(args.non_interactive)
    if not interactive:
        _eprint("ℹ 非交互模式：跳过 Telegram 询问。")
        return EXIT_SKIP

    _eprint("")
    _eprint("—— Telegram 推送（可选）——")
    existing = str(cfg.get("telegram_chat_id") or "").strip()
    if existing:
        _eprint("配置里已有 telegram_chat_id（不在此打印）。回车保留；或输入新 ID；s/skip/稍后 跳过。")
    raw = ask_line("Telegram chat_id（回车保留已有 / s 跳过）：\n> ")
    token = raw.strip()
    if token.lower() in ("s", "skip") or token in ("稍后",):
        _eprint("已跳过 Telegram。")
        return EXIT_SKIP
    updates: Dict[str, Any] = {}
    if token:
        updates["telegram_chat_id"] = token
        _eprint("✓ 已写入 telegram_chat_id")
    elif not existing:
        _eprint("未填写 chat_id。")

    has_token = ask_line(
        "你是否已有 Bot Token？(y=已有，稍后自己填进配置；n/回车=没有或跳过) [y/N]："
    ).strip().lower()
    if has_token in ("y", "yes", "是"):
        _eprint("请把 Token 写到配置项 telegram_bot_token（WebUI「配置」页或编辑")
        _eprint("  %s" % config)
        _eprint("安装过程不会询问或打印 Token。也可使用环境变量，勿把 Token 提交到 git。")
    else:
        _eprint("未配置 Bot Token 时 Telegram 推送不会发送；不影响本地出图。")

    if updates:
        merge_config(config, updates)
        return EXIT_OK
    return EXIT_SKIP


def cmd_print_webui_blurb(_args: argparse.Namespace) -> int:
    _eprint("")
    _eprint("—— WebUI 与其它后端 ——")
    _eprint("  · WebUI（可选）：装好后可用 scripts/webui/webui-start.sh 启动控制台。")
    _eprint("  · 对话后端默认走 OpenClaw；未装 OpenClaw 时 AI 连抽/常规对话不可用，")
    _eprint("    直投 / 精选 / 出图仍可先用。")
    _eprint("  · 其它 agent 后端若日后开放，不改动本包内核/native；出图主路径不变。")
    return EXIT_OK


def cmd_print_checklist(args: argparse.Namespace) -> int:
    comfy = None
    if args.comfyui:
        p = _expand(args.comfyui)
        if _is_comfyui_root(p):
            comfy = p
    root = Path(os.path.expanduser(args.root)) if args.root else None
    print_model_checklist(comfy, root=root)
    return EXIT_OK


def cmd_is_interactive(args: argparse.Namespace) -> int:
    if is_interactive(args.non_interactive):
        _out("1")
        return EXIT_OK
    _out("0")
    return EXIT_OK


def cmd_merge_config(args: argparse.Namespace) -> int:
    config = Path(os.path.expanduser(args.config))
    updates: Dict[str, Any] = {}
    for item in args.set or []:
        if "=" not in item:
            _eprint("无效 --set（需要 key=value）：" + item)
            return EXIT_ERR
        k, v = item.split("=", 1)
        updates[k.strip()] = v
    if not updates:
        return EXIT_ERR
    merge_config(config, updates)
    return EXIT_OK



def cmd_prompt_extras(args: argparse.Namespace) -> int:
    """Skippable prompts: output_dir, comfyui_host, openclaw_workspace_dir; optional obsidian_vault_dir."""
    config = Path(os.path.expanduser(args.config))
    cfg = _load_cfg(config)
    interactive = is_interactive(args.non_interactive)
    if not interactive:
        _eprint("ℹ 非交互模式：跳过 output_dir / comfyui_host / openclaw_workspace / obsidian 询问。")
        return EXIT_SKIP

    updates: Dict[str, Any] = {}
    _eprint("")
    _eprint("—— 可选路径与主机 ——")

    # output_dir
    cur_out = str(cfg.get("output_dir") or "").strip() or "~/Downloads/card-engine-out"
    _eprint("当前 output_dir：%s" % cur_out)
    raw = ask_line("出图输出目录 output_dir（回车保留 / s / skip / 稍后 跳过）：\n> ").strip()
    if raw and raw not in SKIP_TOKENS and raw.lower() not in ("s", "skip"):
        try:
            pth = _expand(raw)
            store = str(pth)
            try:
                home = Path.home().resolve()
                resolved = pth.expanduser().resolve()
                if str(resolved).startswith(str(home)):
                    store = "~/" + str(resolved.relative_to(home)).replace("\\", "/")
            except Exception:
                pass
            updates["output_dir"] = store
            _eprint("✓ 将写入 output_dir = " + store)
        except Exception:
            _eprint("  路径无法解析，保留原值。")
    elif raw in SKIP_TOKENS or raw.lower() in ("s", "skip") or raw in ("稍后",):
        _eprint("已跳过 output_dir。")
    else:
        _eprint("保留 output_dir。")

    # comfyui_host
    cur_host = str(cfg.get("comfyui_host") or "").strip() or "http://127.0.0.1:8188"
    _eprint("当前 comfyui_host：%s" % cur_host)
    raw = ask_line("ComfyUI 地址 comfyui_host（回车保留 / s 跳过）：\n> ").strip()
    if raw and raw not in SKIP_TOKENS and raw.lower() not in ("s", "skip") and raw != "稍后":
        if "://" not in raw:
            raw = "http://" + raw
        updates["comfyui_host"] = raw
        _eprint("✓ 将写入 comfyui_host = " + raw)
    elif raw.lower() in ("s", "skip") or raw in ("稍后",):
        _eprint("已跳过 comfyui_host。")
    else:
        _eprint("保留 comfyui_host。")

    # openclaw_workspace_dir
    cur_ws = str(cfg.get("openclaw_workspace_dir") or "").strip()
    hint = cur_ws or "~/.openclaw/workspace"
    _eprint("当前 openclaw_workspace_dir：%s" % (cur_ws or "（空，常见 %s）" % hint))
    raw = ask_line("OpenClaw 工作区目录（回车保留/空 / s 跳过）：\n> ").strip()
    if raw and raw not in SKIP_TOKENS and raw.lower() not in ("s", "skip") and raw != "稍后":
        try:
            pth = _expand(raw)
            updates["openclaw_workspace_dir"] = str(pth)
            _eprint("✓ 将写入 openclaw_workspace_dir = " + str(pth))
        except Exception:
            _eprint("  路径无法解析，跳过。")
    elif raw.lower() in ("s", "skip") or raw in ("稍后",):
        _eprint("已跳过 openclaw_workspace_dir。")
    else:
        _eprint("保留 openclaw_workspace_dir。")

    # obsidian_vault_dir — optional one-line
    cur_ob = str(cfg.get("obsidian_vault_dir") or "").strip()
    _eprint("当前 obsidian_vault_dir：%s" % (cur_ob or "（空）"))
    raw = ask_line("Obsidian 库目录（可选，一行；回车/s 跳过）：\n> ").strip()
    if raw and raw not in SKIP_TOKENS and raw.lower() not in ("s", "skip") and raw != "稍后":
        try:
            pth = _expand(raw)
            updates["obsidian_vault_dir"] = str(pth)
            _eprint("✓ 将写入 obsidian_vault_dir = " + str(pth))
        except Exception:
            _eprint("  路径无法解析，跳过。")
    else:
        _eprint("已跳过 obsidian_vault_dir。")

    if updates:
        merge_config(config, updates)
        _out(",".join(updates.keys()))
        return EXIT_OK
    return EXIT_SKIP


def cmd_readiness_summary(args: argparse.Namespace) -> int:
    """Always print readiness matrix (interactive or not). Exit 0."""
    config = Path(os.path.expanduser(args.config))
    root = Path(os.path.expanduser(args.root)) if getattr(args, "root", None) else Path.cwd()
    cfg = _load_cfg(config)

    comfy = cfg_comfyui_valid(cfg)
    oc_home = cfg_openclaw_home_valid(cfg)
    oc_bin = cfg_openclaw_bin_valid(cfg)
    oc_ok = oc_home is not None or oc_bin is not None
    # also treat default ~/.openclaw if openclaw.json exists
    if not oc_ok:
        default_oc = Path.home() / ".openclaw"
        if _is_openclaw_home(default_oc):
            oc_ok = True
            oc_home = default_oc

    model_rows = scan_moody_models(comfy)
    models_found = sum(1 for r in model_rows if r[3])
    models_total = len(model_rows)
    models_ok = comfy is not None and models_found == models_total
    models_partial = comfy is not None and 0 < models_found < models_total

    webui_sh = root / "scripts" / "webui" / "webui-start.sh"
    webui_py = root / "scripts" / "webui" / "web_server.py"
    webui_ok = webui_sh.is_file() or webui_py.is_file()

    tg_chat = str(cfg.get("telegram_chat_id") or "").strip()
    tg_ok = bool(tg_chat)

    def mark(ok: bool, partial: bool = False) -> str:
        if ok:
            return "✓"
        if partial:
            return "△"
        return "✗"

    _eprint("")
    _eprint("== 就绪矩阵 ==")
    _eprint("  出图 / ComfyUI:     %s  %s" % (
        mark(comfy is not None),
        str(comfy) if comfy is not None else "未配置（无 main.py 根目录）",
    ))
    if comfy is None:
        _eprint("  Moody 模型:         ✗  无法扫描（先配置 ComfyUI）")
    elif models_ok:
        _eprint("  Moody 模型:         ✓  %d/%d 就位" % (models_found, models_total))
    elif models_partial:
        missing = [r[1] for r in model_rows if not r[3]]
        _eprint("  Moody 模型:         △  %d/%d 就位；缺: %s" % (
            models_found, models_total, ", ".join(missing),
        ))
    else:
        _eprint("  Moody 模型:         ✗  0/%d 就位" % models_total)

    oc_detail = ""
    if oc_home is not None:
        oc_detail = str(oc_home)
    elif oc_bin:
        oc_detail = oc_bin
    _eprint("  OpenClaw / AI 对话: %s  %s" % (
        mark(oc_ok),
        oc_detail or "未配置（AI 连抽/常规对话不可用）",
    ))
    _eprint("  WebUI（可选）:      %s  %s" % (
        mark(webui_ok),
        "脚本在发行版内" if webui_ok else "未找到 webui-start.sh / web_server.py",
    ))
    _eprint("  Telegram（可选）:   %s  %s" % (
        mark(tg_ok),
        "已配置 chat_id" if tg_ok else "未配置（不影响本地出图）",
    ))

    # Light probe of configured comfyui_host (warn only; never fail install).
    # Prefer config.comfyui_host; fall back to :8188 only when unset — do not assume everyone uses 8188.
    host, host_from_cfg = resolve_comfy_display_url(cfg)
    webui_url, _webui_from_cfg = resolve_webui_display_url(cfg)
    check_comfy_venv_aimdo(comfy)
    probe = _probe_comfy_endpoint(host, "/system_stats", timeout=1.5)
    if probe.get("ok"):
        _eprint("  ComfyUI 服务探活:    ✓  %s 可达（/system_stats）" % host)
    else:
        if host_from_cfg:
            _eprint(
                "  ComfyUI 服务探活:    ⚠  配置的 comfyui_host=%s 暂不可达（安装不失败；"
                "启动对应端口的 Comfy 后再用）" % host
            )
        else:
            _eprint(
                "  ComfyUI 服务探活:    ⚠  默认 %s 暂不可达（未设置 comfyui_host 时用此默认；"
                "若你的 Comfy 不在 8188，请在配置里设 comfyui_host 为完整 URL，如 "
                "http://127.0.0.1:8190。安装不失败。）" % host
            )

    _eprint("")
    _eprint("下一步：")
    if comfy is None:
        _eprint("  · 无 ComfyUI CLI：请安装含 main.py 的 CLI（仅 Desktop App 不够），")
        _eprint("    在 WebUI「配置」填写 comfyui_dir，或设 COMFYUI_DIR 再跑 ./install.sh；")
        _eprint("    并把发行版 ComfyUI-Card-Engine 拷到 ComfyUI/custom_nodes/。")
        _eprint("  · 若 Comfy 不在默认端口，请设置 comfyui_host（完整 URL，如 http://127.0.0.1:8190）。")
        _eprint("  · 启动示例：bash '%s/scripts/gpu-pipeline/comfyui-start.sh' start" % root)
    if comfy is not None and not models_ok:
        _eprint("  · 无/缺 Moody 模型：按清单下载到 $COMFYUI_DIR/models/ 对应子目录")
        _eprint("    （见 install_hints/workflow_moody_zib_zit.txt）。缺模型时默认出图可能失败。")
    if not oc_ok:
        _eprint("  · 无 OpenClaw：AI 连抽/常规对话不可用；直投/精选/出图可先用。")
        _eprint("    安装 OpenClaw 后填写 openclaw_home / openclaw_bin，或再跑安装向导。")
    if comfy is not None and models_ok and oc_ok:
        _eprint("  · 核心就绪。可启动：")
        if webui_sh.is_file():
            _eprint("      bash '%s' start" % webui_sh)
        elif webui_py.is_file():
            _eprint("      cd '%s' && python3 web_server.py" % webui_py.parent)
        _eprint("      bash '%s/scripts/gpu-pipeline/comfyui-start.sh' start" % root)
        comfy_label = host if host_from_cfg else "%s（默认）" % host
        webui_label = webui_url if _webui_from_cfg else "%s（WebUI 默认）" % webui_url
        _eprint("    WebUI %s  ·  ComfyUI %s" % (webui_label, comfy_label))
    elif comfy is not None and models_ok and not oc_ok:
        _eprint("  · 出图路径就绪（无 AI 对话）。可先：")
        if webui_sh.is_file():
            _eprint("      bash '%s' start" % webui_sh)
        _eprint("      bash '%s/scripts/gpu-pipeline/comfyui-start.sh' start" % root)
    if not tg_ok:
        _eprint("  · Telegram 可选：在配置里填 telegram_chat_id / telegram_bot_token（勿提交 token）。")
    if webui_ok and comfy is None and not oc_ok:
        _eprint("  · 仅内核/WebUI 时也可先开控制台查看配置页。")

    return EXIT_OK


def cmd_convert_workflow(args: argparse.Namespace) -> int:
    """Standalone UI→API convert (no full wizard)."""
    inp = Path(os.path.expanduser(args.input)).expanduser()
    if not inp.is_file():
        _eprint("输入文件不存在：" + str(inp))
        return EXIT_ERR
    if args.output:
        out = Path(os.path.expanduser(args.output)).expanduser()
    else:
        out = inp.with_name(inp.stem + ".api.json")
    host = (args.host or "http://127.0.0.1:8188").strip()
    report = Path(os.path.expanduser(args.report)).expanduser() if args.report else None
    comfy_dir = None
    cfg_path = None
    root = _repo_root()
    if args.config:
        cfg_path = Path(os.path.expanduser(args.config)).expanduser()
        cfg = _load_cfg(cfg_path)
        if not args.host:
            host = str(cfg.get("comfyui_host") or host).strip()
        comfy_dir = cfg_comfyui_valid(cfg)
    if args.root:
        root = Path(os.path.expanduser(args.root)).expanduser()

    _eprint("UI→API 转换：%s → %s" % (inp, out))
    status, report_path, warns = _try_convert_api(
        inp,
        out,
        host,
        config_path=cfg_path,
        comfyui_dir=comfy_dir,
        root=root,
        report_path=report,
    )
    if status == "ok":
        _eprint("✓ 转换成功（无警告）：" + str(out))
        _eprint("  提醒：AmazingDraw 节点元数据仍需手工配置。")
        _out(str(out))
        return EXIT_OK
    if status == "ok_with_warnings":
        _eprint("✓ 已写出 API JSON（含 %d 条警告）：%s" % (len(warns), out))
        if report_path:
            _eprint("  报告文件：" + str(report_path))
            _eprint("  请把下面的报告文件发给本地 AI agent 继续处理")
        _out(str(out))
        return EXIT_OK
    _eprint("✗ 转换失败。")
    if report_path:
        _eprint("  报告文件：" + str(report_path))
        _eprint("  请把下面的报告文件发给本地 AI agent 继续处理")
    return EXIT_ERR


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        description="AmazingDraw install wizard helpers",
    )
    ap.add_argument(
        "--non-interactive",
        action="store_true",
        help="Disable prompts (also AMAZINGDRAW_INSTALL_NONINTERACTIVE=1)",
    )
    ap.add_argument("--max-retries", type=int, default=3)

    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("is-interactive", help="Print 1/0; exit 0")
    p.set_defaults(func=cmd_is_interactive)

    p = sub.add_parser("prompt-comfyui", help="Ask/validate ComfyUI root; write config")
    p.add_argument("--config", required=True)
    p.set_defaults(func=cmd_prompt_comfyui)

    p = sub.add_parser("prompt-openclaw", help="Ask OpenClaw home/bin; write config")
    p.add_argument("--config", required=True)
    p.set_defaults(func=cmd_prompt_openclaw)

    p = sub.add_parser("workflow-step", help="Copy default WF / checklist / custom import")
    p.add_argument("--config", required=True)
    p.add_argument("--root", required=True, help="Dist/repo root (has workflows/)")
    p.set_defaults(func=cmd_workflow_step)

    p = sub.add_parser("telegram-step", help="Optional telegram_chat_id")
    p.add_argument("--config", required=True)
    p.set_defaults(func=cmd_telegram_step)

    p = sub.add_parser("webui-blurb", help="Print WebUI optional blurb")
    p.set_defaults(func=cmd_print_webui_blurb)

    p = sub.add_parser("print-checklist", help="Print Moody model checklist + optional scan")
    p.add_argument("--comfyui", default="")
    p.add_argument("--root", default="")
    p.set_defaults(func=cmd_print_checklist)

    p = sub.add_parser("merge-config", help="Merge key=value into config.json")
    p.add_argument("--config", required=True)
    p.add_argument("--set", action="append", default=[])
    p.set_defaults(func=cmd_merge_config)

    p = sub.add_parser(
        "prompt-extras",
        help="Ask output_dir / comfyui_host / openclaw_workspace_dir / obsidian_vault_dir",
    )
    p.add_argument("--config", required=True)
    p.set_defaults(func=cmd_prompt_extras)

    p = sub.add_parser(
        "readiness-summary",
        help="Always print readiness matrix (ComfyUI/models/OpenClaw/WebUI/Telegram)",
    )
    p.add_argument("--config", required=True)
    p.add_argument("--root", default="", help="Dist/repo root")
    p.set_defaults(func=cmd_readiness_summary)

    p = sub.add_parser(
        "convert-workflow",
        help="Standalone UI-JSON → API-JSON convert (writes AI report on fail/warnings)",
    )
    p.add_argument("--input", required=True, help="UI (or API pass-through) workflow JSON")
    p.add_argument("--output", default="", help="API JSON output path (default: <stem>.api.json)")
    p.add_argument("--report", default="", help="Convert report markdown path (optional)")
    p.add_argument("--host", default="", help="ComfyUI base URL (default http://127.0.0.1:8188)")
    p.add_argument("--config", default="", help="Optional config.json for host/comfyui_dir")
    p.add_argument("--root", default="", help="Repo/dist root (VERSION lookup)")
    p.set_defaults(func=cmd_convert_workflow)

    return ap


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = build_parser()
    args = ap.parse_args(list(argv) if argv is not None else None)
    try:
        return int(args.func(args))
    except KeyboardInterrupt:
        _eprint("已中断。")
        return EXIT_SKIP


if __name__ == "__main__":
    raise SystemExit(main())
