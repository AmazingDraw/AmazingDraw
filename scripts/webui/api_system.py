#!/usr/bin/env python3
"""System environment probing + ComfyUI selection API routes.

Implements the four-light readiness gate described in
`doc/ops/AMAZING_DRAW_DESKTOP_DELIVERY_PLAN.md` §6.

Design contract (prototype stage):
  * MOSTLY READ-ONLY. `GET /api/system/environment` and `/api/system/test-llm`
    never write config, never download, never start or stop ComfyUI.
    **One deliberate exception**: `POST /api/system/select-path` (§4-1) is the
    first endpoint here that persists config — it writes only `comfyui_dir` /
    `comfyui_host`, and only through `web_server.save_system_config` (atomic
    replace + file lock + rolling backups). `download` stays out of scope and
    lands in a later milestone; this module still never starts or stops ComfyUI.
  * Probe failures are data, not 500s: a dead ComfyUI / missing file / unreadable
    workflow degrades to a dark light plus a readable reason. Only malformed
    *input* yields 400 — see `select_path`.
  * Node readiness is decided by asking ComfyUI's own `/object_info` whether the
    workflow's class_types exist, instead of hardcoding a core-vs-custom node
    list. A hardcoded list would drift and produce false green lights.
"""

from __future__ import annotations

import json
import shutil
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple
from urllib.parse import urlsplit

import requests
from fastapi import APIRouter, HTTPException

router = APIRouter(tags=["system"])

# Folder candidates per loader node type, in probe priority order.
# Used only as a filesystem fallback when /object_info is unavailable.
_LOADER_FOLDERS: Dict[str, Tuple[str, ...]] = {
    "UNETLoader": ("diffusion_models", "unet"),
    "CheckpointLoaderSimple": ("checkpoints",),
    "CLIPLoader": ("text_encoders", "clip"),
    "DualCLIPLoader": ("text_encoders", "clip"),
    "VAELoader": ("vae",),
    "LoraLoader": ("loras",),
    "LoraLoaderModelOnly": ("loras",),
}

# node type -> (object_info section, input key holding the filename choices)
_OBJECT_INFO_CHOICES: Dict[str, Tuple[str, str]] = {
    "UNETLoader": ("required", "unet_name"),
    "CheckpointLoaderSimple": ("required", "ckpt_name"),
    "CLIPLoader": ("required", "clip_name"),
    "DualCLIPLoader": ("required", "clip_name1"),
    "VAELoader": ("required", "vae_name"),
    "LoraLoader": ("required", "lora_name"),
    "LoraLoaderModelOnly": ("required", "lora_name"),
}

# 健康检查超时。要快，但不能快到把「忙」误判成「死」：
# ComfyUI 单进程排队，正在采样时连 /system_stats 也会被堵住，4s 在 Apple Silicon 上
# 容易擦线假红（灯灭文案却是「未响应」）。调到 6s：真宕机时连接被拒会**立刻**返回，
# 只有「可达但卡住」才会真等满，代价可接受。
_HTTP_TIMEOUT = 6.0

# `/object_info` 一次要吐约 3MB（1500+ 个节点定义），ComfyUI 正在采样时会明显变慢。
# 早先健康检查与节点清单共用同一个超时，结果健康检查通过、节点清单却超时，灯灭文案
# 还写成「ComfyUI 未响应」——自相矛盾，也会把绿灯机器误判成红灯。故单独放宽。
_OBJECT_INFO_TIMEOUT = 15.0

# 视为「可直接加载」的 LoRA 权重后缀。`.part` 之类的半截下载文件不算数。
_LORA_SUFFIXES: Tuple[str, ...] = (".safetensors", ".ckpt", ".pt")


def _load_config() -> Dict[str, Any]:
    """延迟导入 `web_server.load_system_config`。

    `web_server` 在初始化末尾会 `from api_system import router`，所以本模块顶层
    不能再反向 `from web_server import ...`：一旦调用方先导入 `api_system`
    （冒烟测试、单测探针常见的写法），就会撞上
    `ImportError: cannot import name 'router' from partially initialized module`。
    把导入推迟到调用时刻即可彻底断开这个环。
    """
    from web_server import load_system_config

    return load_system_config()


def _is_rgthree_node(class_type: str) -> bool:
    return class_type.endswith("(rgthree)")


def _first_widget(node: Dict[str, Any]) -> Optional[str]:
    """First string widget of a node — the filename slot for loader nodes."""
    for value in node.get("widgets_values") or []:
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _fetch_object_info(host: str) -> Optional[Dict[str, Any]]:
    try:
        resp = requests.get(f"{host.rstrip('/')}/object_info", timeout=_OBJECT_INFO_TIMEOUT)
        resp.raise_for_status()
        data = resp.json()
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def _fetch_system_stats(host: str) -> Optional[Dict[str, Any]]:
    try:
        resp = requests.get(f"{host.rstrip('/')}/system_stats", timeout=_HTTP_TIMEOUT)
        resp.raise_for_status()
        data = resp.json()
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def _resolve_workflow_path(cfg: Dict[str, Any]) -> Optional[Path]:
    """Resolve the default workflow JSON: relative paths live under comfyui_dir."""
    workflows = cfg.get("workflows") or {}
    name = cfg.get("default_workflow") or ""
    entry = workflows.get(name) or {}
    raw = entry.get("workflow_path")
    if not raw:
        return None
    candidate = Path(str(raw)).expanduser()
    if candidate.is_absolute():
        return candidate
    comfy_dir = Path(str(cfg.get("comfyui_dir") or "")).expanduser()
    return comfy_dir / candidate


def _load_workflow(path: Optional[Path]) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    if path is None:
        return None, "默认工作流未在 config.json 中配置"
    if not path.exists():
        return None, f"工作流文件不存在: {path}"
    try:
        return json.loads(path.read_text(encoding="utf-8")), None
    except Exception as exc:
        return None, f"工作流解析失败: {exc}"


def _collect_requirements(
    workflow: Dict[str, Any],
) -> Tuple[List[Dict[str, Any]], List[str]]:
    """Derive required assets and node class_types from the workflow itself."""
    assets: List[Dict[str, Any]] = []
    class_types: List[str] = []
    seen_assets: set = set()

    for node in workflow.get("nodes") or []:
        class_type = node.get("type")
        if not isinstance(class_type, str):
            continue
        class_types.append(class_type)

        if class_type in _LOADER_FOLDERS:
            filename = _first_widget(node)
            if filename and (class_type, filename) not in seen_assets:
                seen_assets.add((class_type, filename))
                assets.append(
                    {
                        "node_type": class_type,
                        "filename": filename,
                        "folders": list(_LOADER_FOLDERS[class_type]),
                        "kind": _asset_kind(class_type),
                    }
                )

    return assets, class_types


def _asset_kind(node_type: str) -> str:
    if node_type in ("UNETLoader", "CheckpointLoaderSimple"):
        return "base_model"
    if node_type in ("CLIPLoader", "DualCLIPLoader"):
        return "text_encoder"
    if node_type == "VAELoader":
        return "vae"
    return "lora"


def _lookup_object_info_choices(
    object_info: Optional[Dict[str, Any]], node_type: str
) -> Optional[List[str]]:
    """Available filenames ComfyUI itself would accept for this loader."""
    if not object_info:
        return None
    spec = _OBJECT_INFO_CHOICES.get(node_type)
    if not spec:
        return None
    section, key = spec
    node_def = object_info.get(node_type) or {}
    inputs = ((node_def.get("input") or {}).get(section) or {})
    entry = inputs.get(key)
    if isinstance(entry, list) and entry and isinstance(entry[0], list):
        return [str(x) for x in entry[0]]
    return None


def _scan_disk(models_root: Path, asset: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Filesystem fallback: locate the asset under its candidate folders."""
    for folder in asset["folders"]:
        candidate = models_root / folder / asset["filename"]
        if candidate.is_file():
            try:
                size = candidate.stat().st_size
            except OSError:
                size = None
            return {"path": str(candidate), "size_bytes": size}
    return None


def _check_assets(
    assets: Sequence[Dict[str, Any]],
    models_root: Optional[Path],
    object_info: Optional[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    results: List[Dict[str, Any]] = []
    for asset in assets:
        choices = _lookup_object_info_choices(object_info, asset["node_type"])
        found: Optional[Dict[str, Any]] = None
        source = "unavailable"

        if choices is not None:
            # Authoritative: ComfyUI reports what it can actually load.
            source = "object_info"
            if asset["filename"] in choices:
                found = {"path": None, "size_bytes": None}
        elif models_root:
            source = "filesystem"
            found = _scan_disk(models_root, asset)

        # Size is only knowable when we hit the disk directly.
        if found and found.get("size_bytes") is None and models_root:
            disk_hit = _scan_disk(models_root, asset)
            if disk_hit and disk_hit.get("size_bytes") is not None:
                found = {**found, "size_bytes": disk_hit["size_bytes"]}

        results.append(
            {
                **asset,
                "present": found is not None,
                "resolved_path": (found or {}).get("path"),
                "size_bytes": (found or {}).get("size_bytes"),
                "verify_source": source,
            }
        )
    return results


def _check_nodes(
    class_types: Sequence[str],
    object_info: Optional[Dict[str, Any]],
    unavailable_reason: str = "ComfyUI 未响应，无法校验节点齐备性",
) -> Dict[str, Any]:
    required = sorted(set(class_types))
    if object_info is None:
        return {
            "known": False,
            "required": required,
            "missing": [],
            "missing_custom": [],
            "reason": unavailable_reason,
        }
    missing = [t for t in required if t not in object_info]
    return {
        "known": True,
        "required": required,
        "missing": missing,
        "missing_custom": [t for t in missing if _is_rgthree_node(t)],
        "reason": "" if not missing else f"缺失节点: {', '.join(missing)}",
    }


def _resolve_lora_root(cfg: Dict[str, Any], models_root: Path) -> Path:
    """LoRA 库根目录 = `models/loras[/<lora_subdir>]`。

    默认工作流里的 `Power Lora Loader (rgthree)` 是**空**的：具体加载哪几张 LoRA
    由 Card Engine 在抽卡时按角色/场景注入。所以 LoRA 灯该回答的是「库里有没有牌
    可打」，而不是「静态工作流里写死了哪几张」——后者恒为空，会把门禁永远钉在
    红灯，主流程只能一直停在环境页。
    """
    workflows = cfg.get("workflows") or {}
    entry = workflows.get(cfg.get("default_workflow") or "") or {}
    subdir = str(entry.get("lora_subdir") or "").strip().strip("/\\")
    root = models_root / "loras"
    return (root / subdir) if subdir else root


def _scan_lora_library(root: Path) -> Dict[str, Any]:
    """统计 LoRA 库里可直接加载的权重文件（`.part` 之类的半截文件不算）。"""
    info: Dict[str, Any] = {
        "root": str(root),
        "exists": root.is_dir(),
        "count": 0,
        "sample": [],
    }
    if not info["exists"]:
        return info
    try:
        files = sorted(
            p.name
            for p in root.rglob("*")
            if p.is_file() and p.suffix.lower() in _LORA_SUFFIXES
        )
    except OSError as exc:
        info["error"] = str(exc)
        return info
    info["count"] = len(files)
    info["sample"] = files[:5]
    return info


def _check_required_loras(
    cfg: Dict[str, Any], lora_root: Path
) -> Tuple[List[str], List[str]]:
    """校验可选的 LoRA 核心清单 `workflows.<name>.required_loras`。

    现状 config 未声明清单，此时只做目录级检查（库里有牌即绿灯）。等 §4-3 的
    「MVP 核心包」清单落地，填上文件名即可自动收紧门禁，无需再改代码。
    """
    workflows = cfg.get("workflows") or {}
    entry = workflows.get(cfg.get("default_workflow") or "") or {}
    declared = entry.get("required_loras") or []
    if not isinstance(declared, (list, tuple)):
        return [], []
    names = [str(item).strip() for item in declared if str(item).strip()]
    missing = [name for name in names if not (lora_root / name).is_file()]
    return names, missing


# ── LLM 连通性实测（§4-4 /api/system/test-llm，§6 灯 1 的真实依据）──────
# §6 要求 API 灯以「测试连通成功」为准，而不是「字段非空」——后者在 Key 失效、
# 中转挂掉时会给出假绿灯。探测复用 card_llm_client.chat_completion 这个公开入口，
# 于是与真实抽卡走同一套路由/降级链，不另造一套 HTTP 逻辑。
_LLM_PROBE_TIMEOUT = 15.0
_LLM_PROBE_MAX_TOKENS = 8
_LLM_PROBE_MESSAGES = [{"role": "user", "content": "ping"}]
_LLM_PROBE_SAMPLE_CHARS = 80

# 最近一次实测结果（内存态）。WebUI 重启后需重新点一次「测试连通」。
_LAST_LLM_PROBE: Dict[str, Any] = {}


def _classify_llm_error(message: str) -> str:
    """把底层异常话术翻成小白能懂的结论（§9「API 失败」一行）。"""
    text = (message or "").lower()
    if "api key not found" in text or "401" in text or "unauthorized" in text:
        return "Key 或中转不可用（鉴权失败）"
    if (
        "curl failed" in text
        or "timed out" in text
        or "timeout" in text
        or "connection refused" in text
        or "could not resolve" in text
    ):
        return "无法连接中转 / 网络不通"
    if "is empty" in text:
        return "模型有响应但内容为空（模型 ID 可能不对）"
    if "not json" in text:
        return "中转返回的不是标准 JSON（中转地址可能填错）"
    return "调用失败"


def _probe_llm(model: Optional[str] = None) -> Dict[str, Any]:
    """真实打一枪。任何异常都收敛成结构化结果，绝不向上抛。"""
    started = time.time()
    result: Dict[str, Any] = {
        "ok": False,
        "model": (model or "").strip() or None,
        "latency_ms": None,
        "sample": None,
        "reason": "",
        "error": None,
        "checked_at": None,
    }
    try:
        from card_llm_client import chat_completion
    except Exception as exc:  # 引擎模块缺失/损坏
        result["reason"] = "找不到 LLM 客户端模块（card_llm_client）"
        result["error"] = str(exc)[:240]
    else:
        try:
            content = chat_completion(
                _LLM_PROBE_MESSAGES,
                max_tokens=_LLM_PROBE_MAX_TOKENS,
                timeout=_LLM_PROBE_TIMEOUT,
                model=(model or "").strip() or None,
            )
        except Exception as exc:
            result["reason"] = _classify_llm_error(str(exc))
            result["error"] = str(exc)[:400]
        else:
            result["ok"] = True
            result["sample"] = str(content or "")[:_LLM_PROBE_SAMPLE_CHARS]
            result["reason"] = "连通成功"

    result["latency_ms"] = int((time.time() - started) * 1000)
    result["checked_at"] = time.time()
    return result


def _build_light(green: bool, reason: str, **extra: Any) -> Dict[str, Any]:
    return {"green": bool(green), "reason": reason, **extra}


@router.get("/api/system/environment")
def get_environment():
    """四盏绿灯 + 探测详情。纯只读，任何子系统故障都降级为灯灭 + 原因。"""
    cfg = _load_config()
    host = str(cfg.get("comfyui_host") or "")
    comfy_dir = Path(str(cfg.get("comfyui_dir") or "")).expanduser()
    models_root = comfy_dir / "models"
    workflow_path = _resolve_workflow_path(cfg)
    workflow, workflow_err = _load_workflow(workflow_path)

    stats = _fetch_system_stats(host) if host else None
    object_info = _fetch_object_info(host) if host else None

    # 清单拿不到时要说清是哪种「拿不到」：进程没了，还是清单拉取超时。
    # 早先两种情况共用一句「ComfyUI 未响应」，与 reachable=True 自相矛盾。
    if not host:
        nodes_unavailable_reason = "未配置 comfyui_host，无法校验节点齐备性"
    elif stats is None:
        nodes_unavailable_reason = "ComfyUI 未响应，无法校验节点齐备性"
    else:
        nodes_unavailable_reason = (
            f"节点清单拉取超时（{_OBJECT_INFO_TIMEOUT:.0f}s），未能校验节点齐备性"
        )

    assets: List[Dict[str, Any]] = []
    nodes = _check_nodes([], object_info, nodes_unavailable_reason)
    if workflow:
        raw_assets, class_types = _collect_requirements(workflow)
        assets = _check_assets(raw_assets, models_root if models_root.is_dir() else None, object_info)
        nodes = _check_nodes(class_types, object_info, nodes_unavailable_reason)

    # ── 灯 1: API（§6：以「测试连通成功」为准，字段非空不算绿）──
    llm_model = str(cfg.get("llm_model") or "").strip()
    probed = dict(_LAST_LLM_PROBE)
    if not llm_model:
        api_green, api_reason = False, "未配置导演模型（llm_model 为空）"
    elif not probed:
        api_green, api_reason = False, "尚未实测连通，请点「测试连通」"
    elif not probed.get("ok"):
        api_green, api_reason = False, f"连不通：{probed.get('reason') or '调用失败'}"
    else:
        api_green = True
        api_reason = f"实测连通成功（{probed.get('latency_ms')}ms）"
    api_light = _build_light(
        api_green,
        api_reason,
        model=llm_model or None,
        checked=bool(probed),
        probe=probed or None,
    )

    # ── 灯 2: 引擎（进程活着 + 节点齐备，两段都过才算绿）──
    engine_reasons: List[str] = []
    if stats is None:
        engine_reasons.append(f"ComfyUI 未响应（{host or '未配置 comfyui_host'}）")
    elif not nodes["known"]:
        engine_reasons.append(nodes["reason"])
    elif nodes["missing"]:
        engine_reasons.append(nodes["reason"])
    engine_light = _build_light(
        not engine_reasons,
        "；".join(engine_reasons) if engine_reasons else "进程健康且节点齐备",
        host=host,
        reachable=stats is not None,
        device=((stats or {}).get("system") or {}).get("comfyui_version"),
        missing_nodes=nodes["missing"],
        process_green=stats is not None,
        nodes_green=bool(nodes["known"] and not nodes["missing"]),
    )

    # ── 灯 3 / 灯 4: 分资产判定 ──
    base_assets = [a for a in assets if a["kind"] != "lora"]
    lora_assets = [a for a in assets if a["kind"] == "lora"]

    def _asset_light(items: List[Dict[str, Any]], empty_reason: str, ok_reason: str) -> Dict[str, Any]:
        if not items:
            return _build_light(False, empty_reason, assets=[])
        missing = [a["filename"] for a in items if not a["present"]]
        return _build_light(
            not missing,
            ok_reason if not missing else f"缺失: {', '.join(missing)}",
            assets=items,
        )

    base_light = _asset_light(base_assets, "工作流未声明底模依赖", "底模齐备")

    # ── 灯 4: LoRA ──
    # 三件事一起看：库就绪（能抽卡）、工作流挂载项不缺失（若工作流写死了 LoRA）、
    # 可选核心清单齐备（§4-3 的 MVP 核心包上线后填 required_loras 自动收紧）。
    lora_root = _resolve_lora_root(cfg, models_root)
    lora_library = _scan_lora_library(lora_root)
    required_loras, required_missing = _check_required_loras(cfg, lora_root)

    lora_reasons: List[str] = []
    workflow_lora_missing = [a["filename"] for a in lora_assets if not a["present"]]
    if workflow_lora_missing:
        lora_reasons.append(f"工作流挂载的 LoRA 缺失: {', '.join(workflow_lora_missing)}")
    if not lora_library["exists"]:
        lora_reasons.append(f"未找到 LoRA 目录: {lora_library['root']}")
    elif not lora_library["count"]:
        lora_reasons.append(f"LoRA 目录为空: {lora_library['root']}")
    if required_missing:
        lora_reasons.append(f"核心清单缺失: {', '.join(required_missing)}")

    lora_light = _build_light(
        not lora_reasons,
        "；".join(lora_reasons)
        if lora_reasons
        else f"LoRA 库就绪（{lora_library['count']} 个可用权重）",
        assets=lora_assets,
        library=lora_library,
        required=required_loras,
        required_missing=required_missing,
    )

    # ── 磁盘 ──
    measured = sum(a["size_bytes"] or 0 for a in assets)
    unknown = [a["filename"] for a in assets if a["size_bytes"] is None]
    disk: Dict[str, Any] = {"target": str(comfy_dir), "free_bytes": None, "known_asset_bytes": measured}
    try:
        usage = shutil.disk_usage(comfy_dir if comfy_dir.exists() else Path.home())
        disk["free_bytes"] = usage.free
        disk["total_bytes"] = usage.total
        disk["target"] = str(comfy_dir if comfy_dir.exists() else Path.home())
    except OSError:
        pass
    if unknown:
        disk["unknown_size_assets"] = unknown

    lights = {
        "api": api_light,
        "engine": engine_light,
        "base_model": base_light,
        "lora": lora_light,
    }

    return {
        "lights": lights,
        "all_green": all(l["green"] for l in lights.values()),
        "workflow": {
            "name": cfg.get("default_workflow"),
            "path": str(workflow_path) if workflow_path else None,
            "exists": workflow is not None,
            "error": workflow_err,
        },
        "comfy": {
            "host": host,
            "dir": str(comfy_dir),
            "models_root": str(models_root),
            "models_root_exists": models_root.is_dir(),
            "node_check": nodes,
        },
        "assets": assets,
        "disk": disk,
        "config": {
            "agent_backend": cfg.get("agent_backend"),
            "lora_subdir": ((cfg.get("workflows") or {}).get(cfg.get("default_workflow") or "") or {}).get("lora_subdir"),
        },
    }


@router.post("/api/system/test-llm")
def test_llm(payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """真实打一枪探测导演模型连通性（§5）。

    只读契约不变：不写配置、不改任何状态文件；唯一副作用是一次按需的出站探测请求。
    入参可给 `{"model": "..."}` 覆盖本次探测的模型（面板「先测后存」用）；不给则用
    当前生效配置。结果缓存供 §6 灯 1 引用。
    """
    body = payload if isinstance(payload, dict) else {}
    result = _probe_llm(body.get("model"))
    _LAST_LLM_PROBE.clear()
    _LAST_LLM_PROBE.update(result)
    return result


# ── 选用本机 ComfyUI 目录 / URL（§4-1「选用」/ §15-2）────────────────────
#
# 策略：**分级放行**
#   * 形态非法 / 目录不存在 / 不像 ComfyUI 安装  → HTTPException 400，且**不写盘**；
#   * 合法但 ComfyUI 没启动                      → 写入配置 + 如实报红灯。
#
# 依据 §2-2：「选用」是**配置动作**，不是**可用性验证** —— 用户完全可能先把路径选好、
# 再去启引擎，不能因引擎没开就拒绝配置；同时也不能把「配置合法但引擎没开」和
# 「配置写错了」混为一谈（前者写入 + 灯红，后者 400 不写）。
#
# 写盘统一走 `web_server.save_system_config`（原子替换 + 文件锁 + 滚动备份），
# 不自己造轮子。

# 「像 ComfyUI 安装」的判据：三者必居其一。
# 只查固定子路径的**存在性**，**不递归扫目录** —— 大目录递归会把请求卡死。
_COMFY_MARKERS: Tuple[str, ...] = ("models", "main.py", "custom_nodes")


def _save_config(updates: Dict[str, Any]) -> None:
    """延迟导入 `web_server.save_system_config`。

    同 `_load_config`：本模块顶层不能反向 `from web_server import ...`，否则调用方
    先导入 `api_system` 时（冒烟测试最常见写法）会撞循环导入。
    """
    from web_server import save_system_config

    save_system_config(dict(updates))


def _normalize_comfy_host(raw: Any) -> Tuple[Optional[str], Optional[str]]:
    """规范化 `comfyui_host`。返回 `(host, 错误原因)`，二者恰有一个为 None。"""
    text = str(raw or "").strip()
    if not text:
        return None, "comfyui_host 不能为空"
    if "://" not in text:
        text = "http://" + text
    parsed = urlsplit(text)
    if parsed.scheme not in ("http", "https"):
        return None, f"comfyui_host 仅支持 http/https，收到「{parsed.scheme or '空协议'}」"
    if not parsed.netloc:
        return None, "comfyui_host 缺少主机名或端口"
    # 只保留 scheme://netloc：丢掉 path/query/fragment，避免配置里留下 `/system_stats` 之类的尾巴
    return f"{parsed.scheme}://{parsed.netloc}", None


def _validate_comfy_dir(raw: Any) -> Tuple[Optional[Path], Optional[str]]:
    """校验目录像不像 ComfyUI 安装。返回 `(resolved_path, 错误原因)`。"""
    text = str(raw or "").strip()
    if not text:
        return None, "comfyui_dir 不能为空"
    try:
        resolved = Path(text).expanduser().resolve()
    except (OSError, RuntimeError) as exc:
        return None, f"comfyui_dir 无法解析：{exc}"
    if not resolved.exists():
        return None, f"comfyui_dir 不存在：{resolved}"
    if not resolved.is_dir():
        return None, f"comfyui_dir 不是目录：{resolved}"
    if not any((resolved / marker).exists() for marker in _COMFY_MARKERS):
        markers = "、".join(_COMFY_MARKERS)
        return None, f"这个目录看起来不是 ComfyUI 安装（未找到 {markers}）：{resolved}"
    return resolved, None


@router.post("/api/system/select-path")
def select_path(payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """选用本机 ComfyUI 目录 / URL 并持久化（§4-1「选用」/ §15-2）。

    * 至少提供 `comfyui_dir` / `comfyui_host` 之一；**缺项不动既有配置**（部分更新，
      避免前端只想改一项时把另一项清空）。
    * 只做 `/system_stats` 快检（`_HTTP_TIMEOUT`，6s）决定灯色，**不拉** 15s 的
      `/object_info`：用户刚改完配置不该等 15 秒；完整四灯以
      `GET /api/system/environment` 为准，避免两处判定逻辑各自漂移。
    * 配置改完**即时生效**：WebUI 与 Card Engine 都从 `scripts/config.json` 按次读盘
      （`load_system_config` 无缓存），不需要重启。
    """
    body = payload if isinstance(payload, dict) else {}
    # 「没传」与「传了空值」是两件事：前者不动既有配置，后者是明确的非法输入
    if "comfyui_dir" not in body and "comfyui_host" not in body:
        raise HTTPException(
            status_code=400,
            detail="至少需要提供 comfyui_dir 或 comfyui_host 之一",
        )

    updates: Dict[str, Any] = {}
    if "comfyui_dir" in body:
        resolved_dir, dir_err = _validate_comfy_dir(body.get("comfyui_dir"))
        if dir_err:
            raise HTTPException(status_code=400, detail=dir_err)
        updates["comfyui_dir"] = str(resolved_dir)
    if "comfyui_host" in body:
        normalized_host, host_err = _normalize_comfy_host(body.get("comfyui_host"))
        if host_err:
            raise HTTPException(status_code=400, detail=host_err)
        updates["comfyui_host"] = normalized_host

    # 校验全过才落盘：任何一项非法都已在上面 400 返回，配置保持原样
    before = _load_config()
    changed = [
        key for key, value in updates.items()
        if str(before.get(key) or "") != str(value)
    ]
    try:
        _save_config(updates)
    except Exception as exc:  # 磁盘不可写等真实故障：如实报错，不静默吞
        raise HTTPException(status_code=500, detail=f"配置写入失败：{exc}") from exc

    effective_host = str(updates.get("comfyui_host") or before.get("comfyui_host") or "")
    stats = _fetch_system_stats(effective_host) if effective_host else None
    engine_light = _build_light(
        stats is not None,
        "进程健康" if stats is not None
        else f"ComfyUI 未响应（{effective_host or '未配置 comfyui_host'}）",
        host=effective_host,
        reachable=stats is not None,
        device=((stats or {}).get("system") or {}).get("comfyui_version"),
    )

    effective_dir = str(updates.get("comfyui_dir") or before.get("comfyui_dir") or "")
    models_root = (Path(effective_dir).expanduser() / "models") if effective_dir else None

    return {
        "ok": True,
        "changed": changed,
        "saved": updates,
        "engine": engine_light,
        "models_root": {
            "path": str(models_root) if models_root else None,
            "exists": bool(models_root and models_root.is_dir()),
        },
        "hint": (
            "配置已持久化并即时生效（WebUI 与引擎均按次读盘，无需重启）。"
            "四灯权威状态请读 GET /api/system/environment"
        ),
    }
