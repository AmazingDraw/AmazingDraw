#!/usr/bin/env python3
"""Discover local ComfyUI + OpenClaw paths for AmazingDraw install."""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


def _eprint(msg: str) -> None:
    print(msg, flush=True)


def _load_cfg(path: Path) -> Dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _save_cfg(path: Path, cfg: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(cfg, indent=2, ensure_ascii=False) + chr(10)
    path.write_text(payload, encoding="utf-8")


def _expand(raw: str) -> Path:
    return Path(os.path.expanduser(str(raw).strip())).expanduser()


def _is_comfyui_root(p: Path) -> bool:
    try:
        return p.is_dir() and (p / "main.py").is_file()
    except Exception:
        return False

def _comfyui_candidates(cfg: Dict[str, Any]) -> List[Path]:
    out: List[Path] = []
    seen = set()

    def add(raw: Optional[str]) -> None:
        if not raw or not str(raw).strip():
            return
        try:
            pth = _expand(str(raw))
        except Exception:
            return
        key = str(pth)
        if key in seen:
            return
        seen.add(key)
        out.append(pth)

    add(os.environ.get("COMFYUI_DIR"))
    raw_cfg = cfg.get("comfyui_dir")
    if isinstance(raw_cfg, str):
        add(raw_cfg)

    home = Path.home()
    for rel in ("ComfyUI", "comfyui", "Documents/ComfyUI", "Desktop/ComfyUI"):
        add(str(home / Path(rel)))

    if sys.platform == "darwin":
        add("/Applications/ComfyUI")
        add(str(home / "Library" / "Application Support" / "ComfyUI"))

    if sys.platform == "win32" or os.environ.get("MSYSTEM"):
        user = os.environ.get("USER") or os.environ.get("USERNAME") or ""
        for drive in ("C", "D", "E"):
            add("/" + drive.lower() + "/ComfyUI")
            add(drive + ":/ComfyUI")
            if user:
                base = "/" + drive.lower() + "/Users/" + user
                add(base + "/ComfyUI")
                add(drive + ":/Users/" + user + "/ComfyUI")
                add(base + "/Desktop/ComfyUI")
                add(base + "/Documents/ComfyUI")
        add(str(home / "ComfyUI"))
        add(str(home / "Desktop" / "ComfyUI"))
        add(str(home / "Documents" / "ComfyUI"))
    return out

def discover_comfyui(cfg: Dict[str, Any]) -> Tuple[Optional[Path], bool]:
    raw = cfg.get("comfyui_dir")
    if isinstance(raw, str) and raw.strip():
        cur = _expand(raw)
        if _is_comfyui_root(cur):
            return cur, True
    for cand in _comfyui_candidates(cfg):
        if _is_comfyui_root(cand):
            try:
                return cand.resolve(), False
            except Exception:
                return cand, False
    return None, False

def _win_runnable_without_x_ok(target: Path) -> bool:
    """On win32, existing .exe/.cmd/.bat are runnable even when X_OK is false."""
    return target.suffix.lower() in (".exe", ".cmd", ".bat")


def _is_runnable(target: Path) -> bool:
    if not target.exists() or not target.is_file():
        return False
    if sys.platform == "win32" and _win_runnable_without_x_ok(target):
        return True
    return os.access(target, os.X_OK)


def _windows_search_dirs(home: Path, name: str) -> list:
    appdata = Path(os.environ.get("APPDATA") or (home / "AppData" / "Roaming"))
    localappdata = Path(os.environ.get("LOCALAPPDATA") or (home / "AppData" / "Local"))

    dirs = [
        appdata / "npm",
        localappdata / "npm",
        localappdata / "Programs",
        localappdata / "Programs" / name,
        localappdata / "bin",
        home / "scoop" / "shims",
    ]

    scoop = (os.environ.get("SCOOP") or "").strip()
    if scoop:
        dirs.append(Path(scoop) / "shims")
    programs = localappdata / "Programs"
    if programs.is_dir():
        try:
            for child in programs.glob("openclaw*"):
                if child.is_dir():
                    dirs.append(child)
        except Exception:
            pass
    return dirs


def resolve_bin_path(name: str) -> str:
    """Locate an executable by name; Windows-aware for .cmd/.bat and npm dirs."""
    found = shutil.which(name)
    if found:
        return found
    if sys.platform == "win32":
        for ext in (".cmd", ".bat", ".exe"):
            found_ext = shutil.which(name + ext)
            if found_ext:
                return found_ext

    home = Path.home()
    search_dirs = [
        home / ".local" / "bin",
        home / "bin",
        Path("/usr/local/bin"),
        Path("/usr/bin"),
        Path("/opt/homebrew/bin"),
    ]
    if sys.platform == "win32":
        search_dirs.extend(_windows_search_dirs(home, name))
        exts = [".exe", ".cmd", ".bat", ""]
    else:
        exts = [""]

    seen = set()
    for sd in search_dirs:
        try:
            key = str(sd.resolve()) if sd.exists() else str(sd)
        except Exception:
            key = str(sd)
        if key in seen:
            continue
        seen.add(key)
        for ext in exts:
            target = sd / (name + ext)
            if _is_runnable(target):
                try:
                    return str(target.resolve())
                except Exception:
                    return str(target)
    return name


def _is_openclaw_home(p: Path) -> bool:
    try:
        return p.is_dir() and (p / "openclaw.json").is_file()
    except Exception:
        return False


def discover_openclaw_home(cfg: Dict[str, Any]) -> Tuple[Optional[Path], bool]:
    raw = cfg.get("openclaw_home")
    if isinstance(raw, str) and raw.strip():
        cur = _expand(raw)
        if _is_openclaw_home(cur):
            return cur, True
    env_raw = (os.environ.get("OPENCLAW_HOME") or "").strip()
    if env_raw:
        cur = _expand(env_raw)
        if _is_openclaw_home(cur):
            return cur, False
    default = Path.home() / ".openclaw"
    if _is_openclaw_home(default):
        try:
            return default.resolve(), False
        except Exception:
            return default, False
    return None, False


def discover_openclaw_bin(cfg: Dict[str, Any]) -> Tuple[Optional[str], bool]:
    raw = cfg.get("openclaw_bin")
    if isinstance(raw, str) and raw.strip():
        p = _expand(raw)
        if p.is_file():
            try:
                return str(p.resolve()), True
            except Exception:
                return str(p), True
    found = resolve_bin_path("openclaw")
    # resolve_bin_path may return bare name when missing
    if found and found != "openclaw" and Path(found).is_file():
        return found, False
    return None, False


def discover_workspace(home: Optional[Path]) -> Optional[Path]:
    env = (os.environ.get("OPENCLAW_WORKSPACE_DIR") or "").strip()
    if env:
        p = _expand(env)
        if p.is_dir():
            return p
    if home is not None:
        ws = home / "workspace"
        if ws.is_dir():
            return ws
    default = Path.home() / ".openclaw" / "workspace"
    if default.is_dir():
        return default
    return None


def _should_write_path(_current: Any, keep_existing: bool) -> bool:
    if keep_existing:
        return False
    return True

def run(config_path: Path, do_write: bool) -> Dict[str, Any]:
    cfg = _load_cfg(config_path)
    changed = False
    result: Dict[str, Any] = {
        "comfyui_dir": None,
        "openclaw_home": None,
        "openclaw_bin": None,
        "workspace": None,
        "wrote": [],
    }

    comfy, comfy_keep = discover_comfyui(cfg)
    if comfy is not None:
        result["comfyui_dir"] = str(comfy)
        _eprint("✓ 已找到本机 ComfyUI：" + str(comfy))
        if do_write and _should_write_path(cfg.get("comfyui_dir"), comfy_keep):
            store = str(comfy)
            try:
                home = Path.home().resolve()
                resolved = comfy.resolve()
                if resolved == home / "ComfyUI":
                    store = "~/ComfyUI"
            except Exception:
                pass
            cfg["comfyui_dir"] = store
            changed = True
            result["wrote"].append("comfyui_dir")
            _eprint("  已写入配置 comfyui_dir")
    else:
        tip = (
            "ℹ 本机还没侦测到 ComfyUI（可选）。装好后可在 WebUI「配置」里填写 "
            "ComfyUI 本地根目录；或设置环境变量 COMFYUI_DIR 后再跑一次安装。"
        )
        if sys.platform == "win32" or os.environ.get("MSYSTEM"):
            tip += " 若装在其它盘，可设 COMFYUI_DIR=D:/ComfyUI 之类路径。"
        _eprint(tip)

    oc_home, oc_home_keep = discover_openclaw_home(cfg)
    oc_bin, oc_bin_keep = discover_openclaw_bin(cfg)
    ws = discover_workspace(oc_home)

    found_any_oc = False
    if oc_home is not None:
        found_any_oc = True
        result["openclaw_home"] = str(oc_home)
        _eprint("✓ 已找到 OpenClaw 家目录：" + str(oc_home))
        if do_write and _should_write_path(cfg.get("openclaw_home"), oc_home_keep):
            cfg["openclaw_home"] = str(oc_home)
            changed = True
            result["wrote"].append("openclaw_home")
            _eprint("  已写入配置 openclaw_home")

    if oc_bin is not None:
        found_any_oc = True
        result["openclaw_bin"] = oc_bin
        msg = "✓ 已找到 OpenClaw 命令：" + oc_bin
        if oc_bin.lower().endswith((".cmd", ".bat")):
            msg += "（Windows 可用 openclaw.cmd）"
        _eprint(msg)
        if do_write and _should_write_path(cfg.get("openclaw_bin"), oc_bin_keep):
            cfg["openclaw_bin"] = oc_bin
            changed = True
            result["wrote"].append("openclaw_bin")
            _eprint("  已写入配置 openclaw_bin")

    if ws is not None:
        result["workspace"] = str(ws)
        _eprint("✓ OpenClaw 工作区：" + str(ws))
        found_any_oc = True

    if not found_any_oc:
        _eprint(
            "ℹ 未侦测到 OpenClaw（AI 连抽/常规对话才需要；直投/精选/出图可先不用）。"
            "需要时安装 OpenClaw，或在 WebUI 配置里填写 openclaw_home / openclaw_bin。"
        )

    if do_write and changed:
        _save_cfg(config_path, cfg)

    return result

def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Detect local ComfyUI / OpenClaw paths")
    ap.add_argument("--config", required=True, help="Path to config.json (CONFIG_DST)")
    ap.add_argument("--write", action="store_true", help="Write paths when empty/invalid")
    ap.add_argument("--json", action="store_true", help="Print final JSON result line")
    ap.add_argument("--dry-run", action="store_true", help="Discover without writing")
    args = ap.parse_args(argv)
    config_path = Path(os.path.expanduser(args.config))
    do_write = bool(args.write) and not args.dry_run
    result = run(config_path, do_write=do_write)
    if args.json:
        print(json.dumps({
            "comfyui_dir": result.get("comfyui_dir"),
            "openclaw_home": result.get("openclaw_home"),
            "openclaw_bin": result.get("openclaw_bin"),
            "workspace": result.get("workspace"),
            "wrote": result.get("wrote"),
        }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
