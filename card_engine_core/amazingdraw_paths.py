#!/usr/bin/env python3
"""amazingdraw_paths.py — amazing-draw 自有数据目录的唯一解析入口。

数据根目录固定为 ``~/.amazingdraw``（expanduser，macOS / Linux / Windows 通用），
不提供配置键、不读环境变量。已有的单项配置键（cards_dir / custom_presets_dir）
仍可作为覆盖项，默认值落在根目录下：

    ~/.amazingdraw/
      cards/                  卡片 JSON
      custom_presets/         第三方角色/场景预设
      cloud_preview/          云端出图预览
      png_metadata_cache.json PNG 元数据缓存（跟随 cards 的父目录）
      install-report.txt      安装报告
      webui-chat/             WebUI 聊天历史（遗留；阶段 4 清场前仍可能存在）
      albums.json             WebUI 相册专辑索引

注意：/tmp/cu-card（队列、锁、日志）不在此目录内，由 tmp_dir 配置。
OpenClaw 自身的目录（~/.openclaw/openclaw.json 等）不属于本模块管辖。

仅依赖标准库。命令行用法（供 shell 脚本 / install.sh 调用）::

    python3 amazingdraw_paths.py get <home|cards_dir|custom_presets_dir|chat_dir|
                                      albums_file|workspace|cloud_preview_dir|png_cache|install_report>
    python3 amazingdraw_paths.py migrate [--dry-run] [--force]
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import sys
import time
from pathlib import Path
from typing import Dict, Iterable, List, Optional

SCRIPTS_DIR = Path(__file__).resolve().parent
DEFAULT_CONFIG_PATH = SCRIPTS_DIR / "config.json"
MIGRATION_MARKER_NAME = ".migrated-from-openclaw.json"


def amazingdraw_home() -> Path:
    """固定数据根目录 ~/.amazingdraw。"""
    return Path(os.path.expanduser("~")) / ".amazingdraw"


def legacy_openclaw_data_dir() -> Path:
    """旧默认数据目录 ~/.openclaw/draw-cards（仅供迁移与「是否等于旧默认值」判断）。"""
    return Path(os.path.expanduser("~")) / ".openclaw" / "draw-cards"


def legacy_openclaw_chat_dir() -> Path:
    return Path(os.path.expanduser("~")) / ".openclaw" / "webui-chat"


def load_config(config_path: Optional[Path] = None) -> dict:
    path = Path(config_path) if config_path else DEFAULT_CONFIG_PATH
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _override(cfg: Optional[dict], key: str, config_path: Optional[Path] = None) -> Optional[Path]:
    if cfg is None:
        cfg = load_config(config_path)
    raw = cfg.get(key)
    if not isinstance(raw, str) or not raw.strip():
        return None
    p = Path(os.path.expanduser(raw.strip()))
    if not p.is_absolute():
        base = Path(config_path).resolve().parent if config_path else SCRIPTS_DIR
        p = base / p
    return p


def cards_dir(cfg: Optional[dict] = None, config_path: Optional[Path] = None) -> Path:
    return _override(cfg, "cards_dir", config_path) or (amazingdraw_home() / "cards")


def custom_presets_dir(cfg: Optional[dict] = None, config_path: Optional[Path] = None) -> Path:
    return _override(cfg, "custom_presets_dir", config_path) or (amazingdraw_home() / "custom_presets")


def cloud_preview_dir() -> Path:
    return amazingdraw_home() / "cloud_preview"


def png_cache_path(cfg: Optional[dict] = None, config_path: Optional[Path] = None) -> Path:
    """PNG 元数据缓存：与历史行为一致，位于 cards 目录的父目录。"""
    return cards_dir(cfg, config_path).parent / "png_metadata_cache.json"


def install_report_path() -> Path:
    return amazingdraw_home() / "install-report.txt"


def chat_dir() -> Path:
    return amazingdraw_home() / "webui-chat"


def albums_file() -> Path:
    """WebUI 相册索引。可用 AMAZING_DRAW_ALBUMS_FILE 覆盖（测试 / 容器）。"""
    env = os.environ.get("AMAZING_DRAW_ALBUMS_FILE")
    if isinstance(env, str) and env.strip():
        return Path(os.path.expanduser(env.strip()))
    return amazingdraw_home() / "albums.json"


def workspace_dir(cfg: Optional[dict] = None, config_path: Optional[Path] = None,
                  create: bool = True) -> Path:
    """后台分离进程的 --cwd。

    旧键 openclaw_workspace_dir 若存在且非空仍被尊重（无害兼容），但不再必需；
    为空时使用 ~/.amazingdraw。
    """
    p = _override(cfg, "openclaw_workspace_dir", config_path) or amazingdraw_home()
    if create:
        try:
            p.mkdir(parents=True, exist_ok=True)
        except Exception:
            pass
    return p


# ─── 迁移：~/.openclaw/draw-cards + webui-chat → ~/.amazingdraw ─────────────

_SKIP_NAMES = {".DS_Store", "Thumbs.db"}


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _iter_files(root: Path) -> Iterable[Path]:
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames.sort()
        for name in sorted(filenames):
            if name in _SKIP_NAMES:
                continue
            p = Path(dirpath) / name
            if p.is_file() and not p.is_symlink():
                yield p


def migration_marker_path() -> Path:
    return amazingdraw_home() / MIGRATION_MARKER_NAME


def legacy_migration_pending() -> bool:
    """旧目录仍有数据且尚未迁移（供启动时提示用，不会读取旧目录内容）。"""
    if migration_marker_path().exists():
        return False
    for d in (legacy_openclaw_data_dir(), legacy_openclaw_chat_dir()):
        if d.is_dir() and any(True for _ in _iter_files(d)):
            return True
    return False


def _default_plan(extra_chat_sources: Optional[List[Path]] = None) -> List[dict]:
    """(source, destination, tag) 列表。tag 用于冲突时的「两份都留」命名。"""
    home = amazingdraw_home()
    old = legacy_openclaw_data_dir()
    plan: List[dict] = []
    for name in ("cards", "custom_presets", "cloud_preview"):
        plan.append({"src": old / name, "dst": home / name, "tag": "openclaw"})
    for name in ("png_metadata_cache.json", "install-report.txt"):
        plan.append({"src": old / name, "dst": home / name, "tag": "openclaw"})
    plan.append({"src": legacy_openclaw_chat_dir(), "dst": home / "webui-chat", "tag": "openclaw"})
    for p in (extra_chat_sources or []):
        plan.append({"src": Path(p), "dst": home / "webui-chat", "tag": "dsh"})
    return plan


def _conflict_name(dst: Path, tag: str, sha: str) -> Path:
    suffix = "".join(dst.suffixes[-1:]) if dst.suffix else ""
    stem = dst.name[: len(dst.name) - len(suffix)] if suffix else dst.name
    cand = dst.with_name(f"{stem}.from-{tag}{suffix}")
    n = 1
    while cand.exists():
        if _sha256(cand) == sha:
            return cand
        n += 1
        cand = dst.with_name(f"{stem}.from-{tag}-{n}{suffix}")
    return cand


def migrate_legacy_data(dry_run: bool = False, force: bool = False,
                        extra_chat_sources: Optional[List[Path]] = None,
                        plan: Optional[List[dict]] = None,
                        marker: Optional[Path] = None,
                        log=print) -> dict:
    """幂等迁移：只复制（不移动、不建符号链接），逐文件校验 sha256，
    目标已存在且内容不同则不覆盖、两份都留（源文件另存为 *.from-<tag>.*）。
    校验全部通过后写标记文件；标记存在则跳过（force=True 可重跑，仍不覆盖）。
    """
    marker = marker or migration_marker_path()
    result = {"status": "", "copied": 0, "identical": 0, "conflicts": [], "missing_sources": [],
              "source_files": 0, "verified": 0, "failed": [], "per_source": []}
    if marker.exists() and not force:
        result["status"] = "skipped_marker_exists"
        return result
    plan = plan if plan is not None else _default_plan(extra_chat_sources)
    for item in plan:
        src, dst, tag = Path(item["src"]), Path(item["dst"]), item["tag"]
        stat = {"src": str(src), "dst": str(dst), "files": 0, "copied": 0, "identical": 0, "conflicts": 0}
        if not src.exists():
            result["missing_sources"].append(str(src))
            continue
        if src.resolve() == dst.resolve():
            continue
        files = [(src, dst)] if src.is_file() else [(f, dst / f.relative_to(src)) for f in _iter_files(src)]
        for sf, df in files:
            stat["files"] += 1
            result["source_files"] += 1
            sha = _sha256(sf)
            target = df
            if df.exists():
                if _sha256(df) == sha:
                    stat["identical"] += 1
                    result["identical"] += 1
                    result["verified"] += 1
                    continue
                target = _conflict_name(df, tag, sha)
                if target.exists() and _sha256(target) == sha:
                    stat["identical"] += 1
                    result["identical"] += 1
                    result["verified"] += 1
                    result["conflicts"].append({"src": str(sf), "kept_existing": str(df), "kept_source_as": str(target)})
                    stat["conflicts"] += 1
                    continue
                result["conflicts"].append({"src": str(sf), "kept_existing": str(df), "kept_source_as": str(target)})
                stat["conflicts"] += 1
            if dry_run:
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            tmp = target.with_name(target.name + ".amzd-tmp")
            shutil.copy2(sf, tmp)
            os.replace(tmp, target)
            stat["copied"] += 1
            result["copied"] += 1
            if _sha256(target) == sha:
                result["verified"] += 1
            else:
                result["failed"].append(str(target))
        result["per_source"].append(stat)
    if dry_run:
        result["status"] = "dry_run"
        return result
    if result["failed"] or result["verified"] != result["source_files"]:
        result["status"] = "verify_failed"
        return result
    marker.parent.mkdir(parents=True, exist_ok=True)
    payload = dict(result, status="ok", finished_at=time.strftime("%Y-%m-%dT%H:%M:%S%z"))
    marker.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    result["status"] = "ok"
    return result


def _main(argv: List[str]) -> int:
    if len(argv) >= 2 and argv[0] == "get":
        name = argv[1]
        cfg = load_config()
        table: Dict[str, Path] = {
            "home": amazingdraw_home(),
            "cards_dir": cards_dir(cfg),
            "custom_presets_dir": custom_presets_dir(cfg),
            "chat_dir": chat_dir(),
            "albums_file": albums_file(),
            "workspace": workspace_dir(cfg),
            "cloud_preview_dir": cloud_preview_dir(),
            "png_cache": png_cache_path(cfg),
            "install_report": install_report_path(),
        }
        if name not in table:
            print(f"unknown name: {name}", file=sys.stderr)
            return 2
        print(table[name])
        return 0
    if argv and argv[0] == "migrate":
        extra = [SCRIPTS_DIR / "webui" / "data" / "webui-chat"]
        res = migrate_legacy_data(dry_run="--dry-run" in argv, force="--force" in argv,
                                  extra_chat_sources=extra)
        print(json.dumps(res, ensure_ascii=False, indent=2))
        return 0 if res["status"] in ("ok", "skipped_marker_exists", "dry_run") else 1
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(_main(sys.argv[1:]))
