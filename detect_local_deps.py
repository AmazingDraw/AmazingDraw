#!/usr/bin/env python3
"""Discover local ComfyUI + LLM endpoint (default 127.0.0.1:8317) for AmazingDraw install."""
from __future__ import annotations

import argparse
import json
import os
import socket
import sys
from pathlib import Path
from urllib.parse import urlparse
from typing import Any, Dict, List, Optional, Tuple


def _configure_stdio() -> None:
    """Avoid UnicodeEncodeError on Windows consoles still on GBK/cp936."""
    if sys.platform != "win32":
        return
    for stream in (sys.stdout, sys.stderr):
        reconf = getattr(stream, "reconfigure", None)
        if callable(reconf):
            try:
                reconf(encoding="utf-8", errors="replace")
            except Exception:
                pass


def _eprint(msg: str) -> None:
    try:
        print(msg, flush=True)
    except UnicodeEncodeError:
        enc = getattr(sys.stdout, "encoding", None) or "utf-8"
        raw = (str(msg) + chr(10)).encode(enc, errors="replace")
        buf = getattr(sys.stdout, "buffer", None)
        if buf is not None:
            buf.write(raw)
            buf.flush()
        else:
            sys.stdout.write(raw.decode(enc, errors="replace"))
            sys.stdout.flush()


_configure_stdio()

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


def _is_scanned_comfyui_root(p: Path) -> bool:
    """Stricter check for shallow-scanned dirs so unrelated main.py projects are skipped."""
    if not _is_comfyui_root(p):
        return False
    try:
        return (
            (p / "comfy").is_dir()
            or (p / "nodes.py").is_file()
            or (p / "comfy_extras").is_dir()
        )
    except Exception:
        return False


_WIN_DRIVES: Tuple[str, ...] = ("C", "D", "E", "F", "G", "H")
_WIN_SCAN_SKIP_DIRS = frozenset({
    "$recycle.bin",
    "$windows.~bt",
    "$windows.~ws",
    "system volume information",
    "windows",
    "windows.old",
    "programdata",
    "recovery",
    "perflogs",
    "msocache",
    "config.msi",
    "documents and settings",
    "intel",
    "amd",
    "nvidia",
    "node_modules",
    ".git",
    "__pycache__",
    "appdata",
})
_WIN_SCAN_MAX_ENTRIES_PER_DIR = 200


def _iter_subdirs_bounded(parent: Path, limit: int = _WIN_SCAN_MAX_ENTRIES_PER_DIR) -> List[Path]:
    """List up to `limit` non-system direct child directories of `parent`. Never raises."""
    out: List[Path] = []
    try:
        with os.scandir(parent) as it:
            for entry in it:
                name = entry.name
                low = name.casefold()
                if not name or name[0] in (".", "$") or low in _WIN_SCAN_SKIP_DIRS:
                    continue
                try:
                    if not entry.is_dir(follow_symlinks=False):
                        continue
                except OSError:
                    continue
                out.append(Path(entry.path))
                if len(out) >= limit:
                    break
    except OSError:
        return []
    return out


def _probe_comfy_dir_variants(entry: Path) -> List[Path]:
    """Given a dir whose name contains 'comfy', check it and portable/nested ComfyUI subdirs."""
    hits: List[Path] = []
    if _is_scanned_comfyui_root(entry):
        hits.append(entry)
    nested = entry / "ComfyUI"
    if _is_scanned_comfyui_root(nested):
        hits.append(nested)
    for sub in _iter_subdirs_bounded(entry, limit=40):
        if sub.name.casefold() == "comfyui":
            continue
        if "comfy" in sub.name.casefold() and _is_scanned_comfyui_root(sub):
            hits.append(sub)
    return hits


def _windows_drive_roots(drives: Tuple[str, ...] = _WIN_DRIVES) -> List[Path]:
    """Return existing drive roots for C–H (handles both native Windows and MSYS/Git Bash)."""
    roots: List[Path] = []
    seen = set()
    is_msys = bool(os.environ.get("MSYSTEM")) and sys.platform != "win32"
    for drive in drives:
        cands = [Path(drive + ":/")]
        if is_msys:
            cands.insert(0, Path("/" + drive.lower()))
        for root in cands:
            try:
                if not root.is_dir():
                    continue
                key = str(root.resolve()).casefold()
            except OSError:
                continue
            if key in seen:
                continue
            seen.add(key)
            roots.append(root)
            break
    return roots


def _scan_windows_comfyui_roots(
    drive_roots: List[Path],
    extra_parents: Optional[List[Path]] = None,
) -> List[Path]:
    """Shallow 1–2 level scan across drive roots and common user folders for ComfyUI installs.

    Catches portable packs (ComfyUI_windows_portable/ComfyUI), aki packs (ComfyUI-aki-*),
    and second-level folders like D:/AI/ComfyUI or G:/Games/ComfyUI without full-disk crawl.
    """
    hits: List[Path] = []
    for root in drive_roots:
        for entry in _iter_subdirs_bounded(root):
            if "comfy" in entry.name.casefold():
                hits.extend(_probe_comfy_dir_variants(entry))
                continue
            for sub in _iter_subdirs_bounded(entry):
                if "comfy" in sub.name.casefold():
                    hits.extend(_probe_comfy_dir_variants(sub))
    for parent in extra_parents or []:
        try:
            if not parent.is_dir():
                continue
        except OSError:
            continue
        for sub in _iter_subdirs_bounded(parent):
            if "comfy" in sub.name.casefold():
                hits.extend(_probe_comfy_dir_variants(sub))
    return hits


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
        extra_parents: List[Path] = [
            home / "Desktop",
            home / "Documents",
            home / "Downloads",
        ]
        add(str(home / "Downloads" / "ComfyUI"), 5)
        for drive in _WIN_DRIVES:
            add("/" + drive.lower() + "/ComfyUI", 6)
            add(drive + ":/ComfyUI", 6)
            if user:
                base_u = "/" + drive.lower() + "/Users/" + user
                add(base_u + "/ComfyUI", 3)
                add(drive + ":/Users/" + user + "/ComfyUI", 3)
                add(base_u + "/Desktop/ComfyUI", 5)
                add(base_u + "/Documents/ComfyUI", 5)
                add(base_u + "/Downloads/ComfyUI", 5)
                add(drive + ":/Users/" + user + "/Desktop/ComfyUI", 5)
                add(drive + ":/Users/" + user + "/Documents/ComfyUI", 5)
                add(drive + ":/Users/" + user + "/Downloads/ComfyUI", 5)
        for hit in _scan_windows_comfyui_roots(_windows_drive_roots(), extra_parents=extra_parents):
            add(str(hit), 7)

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


DEFAULT_LLM_BASE_URL = "http://127.0.0.1:8317/v1"


def llm_base_url(cfg: Optional[Dict[str, Any]] = None) -> str:
    llm = (cfg or {}).get("llm") if isinstance((cfg or {}).get("llm"), dict) else {}
    base = str(llm.get("base_url") or DEFAULT_LLM_BASE_URL).strip()
    return base or DEFAULT_LLM_BASE_URL


def probe_llm_endpoint(cfg: Optional[Dict[str, Any]] = None, timeout: float = 0.4) -> Tuple[str, bool]:
    """TCP probe of llm.base_url host:port. Never raises."""
    base = llm_base_url(cfg)
    raw = base if "://" in base else "http://" + base
    u = urlparse(raw)
    host = u.hostname or "127.0.0.1"
    port = u.port
    if port is None:
        port = 443 if (u.scheme or "http") == "https" else 80
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return base, True
    except OSError:
        return base, False


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
            "[i] 未侦测到 AmazingDraw 所需的 ComfyUI CLI（含 main.py 的 git/源码根目录）。"
            "仅安装 Comfy Desktop App 不够：请打开 Application Support/ComfyUI/config.json "
            "查看 basePath，或把 CLI 路径贴进安装向导 / WebUI「配置」，"
            "或设置环境变量 COMFYUI_DIR 后再跑一次安装。"
            "非默认安装位置必须粘贴路径或设 COMFYUI_DIR。"
        )
        if sys.platform == "win32" or os.environ.get("MSYSTEM"):
            tip += " 若装在其它盘，可设 COMFYUI_DIR=D:/ComfyUI 之类路径。"
        result["comfyui_note"] = tip
        _eprint(tip)

    llm_url, llm_ok = probe_llm_endpoint(cfg)
    result["llm_base_url"] = llm_url
    result["llm_ok"] = llm_ok
    if llm_ok:
        _eprint("✓ LLM 端点可达：" + llm_url)
    else:
        _eprint(
            "[i] LLM 端点暂不可达：" + llm_url
            + "（填槽 / 连抽需要本机 OpenAI 兼容 HTTP，常见为 CLI Proxy 8317。"
            "不影响装完；可稍后启动网关，或在 WebUI「配置」改 llm.base_url。）"
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
    ap = argparse.ArgumentParser(description="Detect local ComfyUI / LLM endpoint")
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
            "llm_base_url": result.get("llm_base_url"),
            "llm_ok": result.get("llm_ok"),
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
