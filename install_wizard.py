#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""AmazingDraw install wizard helpers (Python 3.9+).

Called from install.sh / install_dist.sh after detect_local_deps.

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
import shutil
import sys
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
            "请粘贴本机 ComfyUI 根目录（需含 main.py）。直接回车 / s / skip / 稍后 可跳过：\n> ",
            _is_comfyui_root,
            "无效：目录下找不到 main.py",
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
    _eprint("—— ComfyUI 路径 ——")
    _eprint("自动侦测未找到有效 ComfyUI（需要目录内有 main.py）。")
    path, status = prompt_path("comfyui", max_retries=args.max_retries, interactive=True)
    if status != "ok" or not path:
        _eprint("已跳过。之后可在 WebUI「配置」填写，或设环境变量 COMFYUI_DIR 再跑安装。")
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


def _try_convert_api(ui_json_path: Path, dest_api: Path, comfy_host: str) -> bool:
    """Optional: if ComfyUI is up, POST convert via local WebUI API is not assumed.
    We only call ComfyUI /object_info ourselves and convert inline if api_queue is importable.
    Returns True if API json was written.
    """
    try:
        import urllib.request

        url = comfy_host.rstrip("/") + "/object_info"
        with urllib.request.urlopen(url, timeout=3) as resp:
            object_info = json.loads(resp.read().decode("utf-8"))
    except Exception:
        return False
    try:
        ui_json = json.loads(ui_json_path.read_text(encoding="utf-8"))
    except Exception:
        return False
    # Prefer in-tree converter if present
    api_json = None
    try:
        # scripts/webui may not be on path; best-effort
        root_guess = Path(__file__).resolve().parent.parent
        sys.path.insert(0, str(root_guess / "scripts" / "webui"))
        from api_queue import perform_workflow_conversion  # type: ignore

        api_json = perform_workflow_conversion(ui_json, object_info)
    except Exception:
        api_json = None
    if not isinstance(api_json, dict) or not api_json:
        return False
    try:
        dest_api.write_text(
            json.dumps(api_json, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        return True
    except Exception:
        return False


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

    # Optional convert if ComfyUI is running
    do_convert = ask_line(
        "若本机 ComfyUI 已在跑，可尝试把 UI-JSON 转成 API-JSON 并保存在旁边。"
        "转换成功也不等于接好 AmazingDraw 节点配置。是否尝试？[y/N]："
    ).strip().lower()
    if do_convert in ("y", "yes", "是"):
        host = str(cfg.get("comfyui_host") or "http://127.0.0.1:8188").strip()
        api_dest = dest.with_name(dest.stem + ".api.json")
        if _try_convert_api(dest, api_dest, host):
            _eprint("✓ 已保存 API JSON：" + str(api_dest))
            _eprint("  提醒：仍需在 config.json → workflows 里手工填写节点 ID。")
            note_lines.append("  convert: wrote %s (node-id config still manual)" % api_dest)
        else:
            _eprint("未能转换（ComfyUI 未响应 /object_info，或转换失败）。可稍后在 WebUI 调用转换接口。")
            note_lines.append("  convert: failed or ComfyUI not reachable")

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

    _eprint("")
    _eprint("下一步：")
    if comfy is None:
        _eprint("  · 无 ComfyUI：安装 ComfyUI 后在 WebUI「配置」填写 comfyui_dir，")
        _eprint("    或设环境变量 COMFYUI_DIR 再跑一次 ./install.sh；")
        _eprint("    并把发行版 ComfyUI-Card-Engine 拷到 ComfyUI/custom_nodes/。")
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
        _eprint("    WebUI http://127.0.0.1:8318  ·  ComfyUI http://127.0.0.1:8188")
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
