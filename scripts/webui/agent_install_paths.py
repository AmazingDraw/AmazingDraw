"""Locate CLI binaries; Windows-aware for .cmd/.bat and npm dirs."""
from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path


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
            for child in programs.glob(f"{name}*"):
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


_resolve_bin_path = resolve_bin_path
