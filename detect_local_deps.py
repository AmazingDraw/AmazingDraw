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
    """CLI root = directory containing main.py. Do not reject lean trees (tests)."""
    try:
        return p.is_dir() and (p / "main.py").is_file()
    except Exception:
        return False


def _comfyui_richness(p: Path) -> int:
    """Prefer installs that look complete; never used to reject main.py-only roots."""
    score = 0
    try:
        if (p / "models").is_dir():
            score += 2
        if (p / "comfy").is_dir():
            score += 1
        if (p / ".venv").is_dir() or (p / "venv").is_dir():
            score += 1
    except Exception:
        pass
    return score


def _desktop_comfy_config_paths() -> List[Path]:
    """Best-effort Desktop App config.json locations (basePath lives here)."""
    home = Path.home()
    paths: List[Path] = []
    # macOS
    paths.append(home / "Library" / "Application Support" / "ComfyUI" / "config.json")
    # Windows Roaming / Local
    appdata = os.environ.get("APPDATA")
    localappdata = os.environ.get("LOCALAPPDATA")
    if appdata:
        paths.append(Path(appdata) / "ComfyUI" / "config.json")
    else:
        paths.append(home / "AppData" / "Roaming" / "ComfyUI" / "config.json")
    if localappdata:
        paths.append(Path(localappdata) / "ComfyUI" / "config.json")
    else:
        paths.append(home / "AppData" / "Local" / "ComfyUI" / "config.json")
    # Linux-ish (rare for Desktop App; cheap)
    paths.append(home / ".config" / "ComfyUI" / "config.json")
    return paths


def read_desktop_comfy_base_path() -> Optional[Path]:
    """Read Comfy Desktop App config basePath if present. Not a CLI root by itself."""
    for cfg_path in _desktop_comfy_config_paths():
        try:
            if not cfg_path.is_file():
                continue
            data = json.loads(cfg_path.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                continue
            raw = data.get("basePath")
            if isinstance(raw, str) and raw.strip():
                return _expand(raw)
        except Exception:
            continue
    return None


def _comfyui_candidates(cfg: Dict[str, Any]) -> List[Tuple[Path, int]]:
    """Ordered (path, priority) candidates. Lower priority number = preferred.

    0 env COMFYUI_DIR → 1 config comfyui_dir → 2 Desktop basePath →
    3 ~/ComfyUI → 4 other home → 5 Documents/Desktop → 6 Applications/stubs.
    Application Support/ComfyUI itself is only a root if it has main.py.
    """
    out: List[Tuple[Path, int]] = []
    seen = set()

    def add(raw: Optional[str], priority: int) -> None:
        if not raw or not str(raw).strip():
            return
        try:
            pth = _expand(str(raw))
        except Exception:
            return
        try:
            key = str(pth.resolve()) if pth.exists() else str(pth)
        except Exception:
            key = str(pth)
        if sys.platform in ("darwin", "win32") or os.environ.get("MSYSTEM"):
            key = key.casefold()
        if key in seen:
            return
        seen.add(key)
        out.append((pth, priority))

    add(os.environ.get("COMFYUI_DIR"), 0)
    raw_cfg = cfg.get("comfyui_dir")
    if isinstance(raw_cfg, str):
        add(raw_cfg, 1)

    base = read_desktop_comfy_base_path()
    if base is not None:
        add(str(base), 2)

    home = Path.home()
    add(str(home / "ComfyUI"), 3)
    add(str(home / "comfyui"), 4)
    add(str(home / "Documents" / "ComfyUI"), 5)
    add(str(home / "Desktop" / "ComfyUI"), 5)

    if sys.platform == "darwin":
        add("/Applications/ComfyUI", 6)
        # App Support dir: only useful if someone put CLI main.py there
        add(str(home / "Library" / "Application Support" / "ComfyUI"), 6)

    if sys.platform == "win32" or os.environ.get("MSYSTEM"):
        user = os.environ.get("USER") or os.environ.get("USERNAME") or ""
        for drive in ("C", "D", "E"):
            add("/" + drive.lower() + "/ComfyUI", 6)
            add(drive + ":/ComfyUI", 6)
            if user:
                base_u = "/" + drive.lower() + "/Users/" + user
                add(base_u + "/ComfyUI", 3)
                add(drive + ":/Users/" + user + "/ComfyUI", 3)
                add(base_u + "/Desktop/ComfyUI", 5)
                add(base_u + "/Documents/ComfyUI", 5)
                add(drive + ":/Users/" + user + "/Desktop/ComfyUI", 5)
                add(drive + ":/Users/" + user + "/Documents/ComfyUI", 5)

    return out


def discover_comfyui(
    cfg: Dict[str, Any],
) -> Tuple[Optional[Path], bool, List[Path]]:
    """Find CLI ComfyUI root(s).

    Returns (chosen, keep_existing_config, all_valid_roots).
    keep_existing is True when config.comfyui_dir already points at a valid CLI root.
    """
    candidates = _comfyui_candidates(cfg)
    valid: List[Tuple[Path, int, int]] = []  # path, priority, -richness
    for cand, pri in candidates:
        if not _is_comfyui_root(cand):
            continue
        try:
            resolved = cand.resolve()
        except Exception:
            resolved = cand
        rich = _comfyui_richness(resolved)
        valid.append((resolved, pri, -rich))

    # de-dupe by resolved path keeping best (lowest pri, then richer).
    # On case-insensitive volumes (macOS default), ComfyUI vs comfyui is one root.
    best_by_key: Dict[str, Tuple[Path, int, int]] = {}
    for item in valid:
        key = str(item[0])
        if sys.platform in ("darwin", "win32") or os.environ.get("MSYSTEM"):
            key = key.casefold()
        prev = best_by_key.get(key)
        if prev is None or (item[1], item[2]) < (prev[1], prev[2]):
            best_by_key[key] = item
    ranked = sorted(best_by_key.values(), key=lambda t: (t[1], t[2], str(t[0])))
    all_roots = [t[0] for t in ranked]

    # Prefer existing valid config (do not overwrite on --write)
    raw = cfg.get("comfyui_dir")
    if isinstance(raw, str) and raw.strip():
        cur = _expand(raw)
        if _is_comfyui_root(cur):
            try:
                cur_r = cur.resolve()
            except Exception:
                cur_r = cur
            # ensure cur is in all_roots list (front for messaging)
            others = [p for p in all_roots if str(p) != str(cur_r)]
            return cur_r, True, [cur_r] + others

    if not ranked:
        return None, False, []
    return ranked[0][0], False, all_roots

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


def _normalize_comfy_host(raw: str) -> str:
    s = (raw or "").strip()
    if not s:
        return ""
    if "://" not in s:
        s = "http://" + s
    return s


def _comfy_host_empty_or_invalid(current: Any) -> bool:
    """Empty / whitespace-only treated as unset (mirror path empty/invalid)."""
    if current is None:
        return True
    if not isinstance(current, str):
        return True
    return not current.strip()


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
        "comfyui_candidates": None,
        "comfyui_note": None,
    }

    comfy, comfy_keep, comfy_all = discover_comfyui(cfg)
    if comfy is not None:
        result["comfyui_dir"] = str(comfy)
        result["comfyui_candidates"] = [str(p) for p in comfy_all]
        _eprint("✓ 已找到本机 ComfyUI CLI：" + str(comfy))
        if len(comfy_all) > 1:
            others = [str(p) for p in comfy_all if str(p) != str(comfy)]
            note = (
                "发现多份 ComfyUI CLI，已选用 %s；另有：%s。"
                "抽卡请用含 main.py 的 CLI 根目录，不要用 Comfy Desktop App。"
                % (str(comfy), "、".join(others))
            )
            result["comfyui_note"] = note
            _eprint("⚠ " + note)
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
        result["comfyui_candidates"] = []
        tip = (
            "ℹ 未侦测到 AmazingDraw 所需的 ComfyUI CLI（含 main.py 的 git/源码根目录）。"
            "仅安装 Comfy Desktop App 不够：请打开 Application Support/ComfyUI/config.json "
            "查看 basePath，或把 CLI 路径贴进安装向导 / WebUI「配置」，"
            "或设置环境变量 COMFYUI_DIR 后再跑一次安装。"
            "非默认安装位置必须粘贴路径或设 COMFYUI_DIR。"
        )
        if sys.platform == "win32" or os.environ.get("MSYSTEM"):
            tip += " 若装在其它盘，可设 COMFYUI_DIR=D:/ComfyUI 之类路径。"
        result["comfyui_note"] = tip
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

    # Honor COMFYUI_HOST env when config comfyui_host empty/invalid (mirror COMFYUI_DIR).
    env_host = _normalize_comfy_host(os.environ.get("COMFYUI_HOST") or "")
    if env_host:
        result["comfyui_host_env"] = env_host
        if do_write and _comfy_host_empty_or_invalid(cfg.get("comfyui_host")):
            cfg["comfyui_host"] = env_host
            changed = True
            result["wrote"].append("comfyui_host")
            _eprint("  已写入配置 comfyui_host（来自环境变量 COMFYUI_HOST）=" + env_host)
        elif not _comfy_host_empty_or_invalid(cfg.get("comfyui_host")):
            result["comfyui_host"] = str(cfg.get("comfyui_host")).strip()

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
        payload = {
            "comfyui_dir": result.get("comfyui_dir"),
            "openclaw_home": result.get("openclaw_home"),
            "openclaw_bin": result.get("openclaw_bin"),
            "workspace": result.get("workspace"),
            "wrote": result.get("wrote"),
        }
        if result.get("comfyui_candidates") is not None:
            payload["comfyui_candidates"] = result.get("comfyui_candidates")
        if result.get("comfyui_note"):
            payload["comfyui_note"] = result.get("comfyui_note")
        print(json.dumps(payload, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
