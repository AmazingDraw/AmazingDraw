#!/usr/bin/env python3
"""
cu-draw-card.py — GPU 渲染执行脚本
============================================
职责：把已生成的最终 prompt / workflow 配置注入 ComfyUI，并等待结果落盘。

定位：
- 这是 GPU 管线脚本，不参与 single / chain 的交互决策
- 它运行在 `submit` 之后，通常由 `cu-worker.sh` 调用
- 提示词组装、check、review、交互数字位都在 card-engine 层完成；这里不再重复那套逻辑

相关路径：
- 工作流元数据：`scripts/config.json` → `workflows` / `default_workflow` / `workflows_aliases`（唯一真相源）
- Comfy 图 JSON：`{comfyui_dir}/workflows/...`（由 config 里 workflow_path 指向）
- 调用链：`card_cli_commands.py (cmd_submit) -> cu-submit.sh -> cu-worker.sh -> cu-draw-card.py -> cu-deliver.sh`

常见用法（调试 / 直跑）：
- `python3 cu-draw-card.py --prompt "..." --lora xxx`
- `python3 cu-draw-card.py --prompt-file /tmp/p.txt --lora xxx`
- `python3 cu-draw-card.py --prompt-file /tmp/p.txt --amateur`
"""

import sys
from pathlib import Path as _Path
for _p in [_Path(__file__).resolve().parent] + list(_Path(__file__).resolve().parent.parents):
    _native = _p / 'card_engine_core' / 'native'
    if _native.is_dir() and (
        list(_native.glob('card_asset_loader*.so'))
        or list(_native.glob('card_asset_loader*.pyd'))
    ):
        if str(_native) not in sys.path:
            sys.path.insert(0, str(_native))
        break
import hashlib, json, os, random, re, sys, time, argparse
from pathlib import Path
from card_config import TMP_DIR, CARDS_DIR
import requests
import logging
import logging.handlers
from collections import deque

SCRIPT_DIR = Path(__file__).resolve().parent
SYSTEM_CONFIG_PATH = SCRIPT_DIR.parent / "config.json"
STATE_DIR = TMP_DIR
RANDOM_HISTORY_FILE = STATE_DIR / "random-history.json"
RECENT_CELEBRITY_WINDOW = 3
API = "http://127.0.0.1:8188"
LOG_FILE = str(TMP_DIR) + "/cu-draw-card.log"

def load_global_config() -> dict:
    """加载 scripts/config.json（全局 + workflows 元数据）。"""
    if SYSTEM_CONFIG_PATH.exists():
        try:
            with open(SYSTEM_CONFIG_PATH, encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                return data
        except Exception:
            pass
    return {}

GLOBAL_CONFIG = load_global_config()
COMFYUI_DIR = os.path.expanduser(GLOBAL_CONFIG.get("comfyui_dir", "~/ComfyUI"))
OPENCLAW_WORKSPACE = os.path.expanduser(GLOBAL_CONFIG.get("openclaw_workspace_dir") or "~/.openclaw/workspace")
API = GLOBAL_CONFIG.get("comfyui_host", "http://127.0.0.1:8188")

def resolve_workflow_path(path_str: str) -> str:
    if not path_str:
        return ""
    # Support placeholder replacement
    path_str = path_str.replace("{comfyui_dir}", COMFYUI_DIR)
    # Support split mapping for backward compatibility
    if "ComfyUI" in path_str and not os.path.exists(path_str):
        parts = path_str.split("ComfyUI/", 1)
        if len(parts) > 1:
            resolved = str(Path(COMFYUI_DIR) / parts[1])
            if os.path.exists(resolved):
                return resolved
    # Support relative paths
    if not os.path.isabs(path_str):
        return str(Path(COMFYUI_DIR) / path_str)
    return os.path.expanduser(path_str)



def init_logger():
    logger = logging.getLogger("cu-draw-card")
    logger.setLevel(logging.INFO)
    handler = logging.handlers.TimedRotatingFileHandler(
        LOG_FILE, when="midnight", interval=1, backupCount=30, encoding="utf-8"
    )
    handler.setFormatter(logging.Formatter(
        "%(asctime)s | %(levelname)-5s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    ))
    logger.addHandler(handler)
    return logger

log = init_logger()
# Load celebrity maps from role_resolver to keep role configs unified
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'card-engine'))
from resolver import role_resolver

celebs_data = role_resolver.load_celebrities()
CELEBRITY_MAP = celebs_data.get("z", {})
FLUX_CELEBRITY_MAP = celebs_data.get("flux", {})


RGTHREE_CONTROLS = {'randomize', 'fixed', 'increment', 'decrement', 'randomize (GPU)', 'fixed (GPU)'}

def load_workflow_defaults() -> dict:
    """默认工作流与别名：唯一来源 scripts/config.json。"""
    return {
        "default_workflow": GLOBAL_CONFIG.get("default_workflow", "moody_zib_zit"),
        "lock_size_to_workflow": GLOBAL_CONFIG.get("lock_size_to_workflow", True),
        "aliases": GLOBAL_CONFIG.get("workflows_aliases") or {
            "moody": "moody_zib_zit",
        },
    }


# 节点类型 → widgets_values 中（未在 inputs 定义的）widget 名称映射
WIDGET_NAMES = {
    "SaveImage": ["filename_prefix"],
    "LoraLoader": ["lora_name", "strength_model", "strength_clip"],
    "UnetLoaderGGUF": ["unet_name"],
    "DualCLIPLoaderGGUF": ["clip_name1", "clip_name2", "type"],
    "VAELoader": ["vae_name"],
    "EmptySD3LatentImage": ["width", "height", "batch_size"],
    "FluxSamplerParams+": ["seed", "sampler", "scheduler", "steps", "guidance", "max_shift", "base_shift", "denoise"],
    "CheckpointLoaderSimple": ["ckpt_name"],
    "UNETLoader": ["unet_name", "weight_dtype"],
    "CLIPLoader": ["clip_name", "type", "device"],
    "EmptyLatentImage": ["width", "height", "batch_size"],
    "KSampler": ["seed", "control_after_generate", "steps", "cfg", "sampler_name", "scheduler", "denoise"],
}



def load_random_history() -> dict:
    if RANDOM_HISTORY_FILE.exists():
        try:
            with open(RANDOM_HISTORY_FILE) as f:
                data = json.load(f)
            if isinstance(data, dict):
                return data
        except Exception:
            pass
    return {"recent_celebrities": []}


def save_random_history(data: dict):
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    with open(RANDOM_HISTORY_FILE, "w") as f:
        json.dump(data, f, ensure_ascii=False)


def load_recent_celebrities(limit: int = RECENT_CELEBRITY_WINDOW) -> list[str]:
    history = load_random_history().get("recent_celebrities", [])
    return history[-limit:]


def save_recent_celebrity(name: str, limit: int = RECENT_CELEBRITY_WINDOW):
    data = load_random_history()
    history = data.get("recent_celebrities", [])
    history.append(name)
    data["recent_celebrities"] = history[-limit:]
    save_random_history(data)


def pick_non_repeating_celebrity(pool: dict, model_name: str):
    recent_names = set(load_recent_celebrities())
    available_keys = [key for key, (name, _trigger) in pool.items() if name not in recent_names]
    if not available_keys:
        available_keys = list(pool.keys())
    key = random.choice(available_keys)
    name, trigger = pool[key]
    save_recent_celebrity(name)
    log.info(f"CELEBRITY_PICK | model={model_name} name={name} recent={list(recent_names)}")
    return key, name, trigger, model_name


def pick_non_repeating_celebrity_auto():
    recent_names = set(load_recent_celebrities())
    # 目前仅接入并支持 Z-Image，Flux 预留为空
    candidates = [(key, name, trigger, 'z') for key, (name, trigger) in CELEBRITY_MAP.items()]

    available = [item for item in candidates if item[1] not in recent_names]
    if not available:
        available = candidates

    if not available:
        log.error("CELEBRITY_PICK_ERROR | Z-Image celebrity pool is empty")
        raise RuntimeError("zimage_celebrity_pool_empty")

    key, name, trigger, model_name = random.choice(available)
    save_recent_celebrity(name)
    log.info(f"CELEBRITY_PICK | model={model_name} name={name} recent={list(recent_names)} mode=auto-global")
    return key, name, trigger, model_name


def pick_celebrity(args):
    model_type = getattr(args, 'model_type', 'auto')
    if args.lora and args.lora in CELEBRITY_MAP:
        return args.lora, *CELEBRITY_MAP[args.lora], 'z'
    if args.lora and args.lora in FLUX_CELEBRITY_MAP:
        return args.lora, *FLUX_CELEBRITY_MAP[args.lora], 'flux'
    if args.trigger:
        for k, (n, t) in CELEBRITY_MAP.items():
            if args.trigger in t or args.trigger in n:
                return k, n, t, 'z'
        for k, (n, t) in FLUX_CELEBRITY_MAP.items():
            if args.trigger in t or args.trigger in n:
                return k, n, t, 'flux'
    # 随机抽：目前仅支持 Z-Image 独占，最近3次不重复
    if model_type == 'z':
        return pick_non_repeating_celebrity(CELEBRITY_MAP, 'z')
    elif model_type == 'flux':
        return pick_non_repeating_celebrity(FLUX_CELEBRITY_MAP, 'flux')
    else:  # auto
        return pick_non_repeating_celebrity_auto()


def normalize_workflow_name(mode: str) -> str:
    defaults = load_workflow_defaults()
    aliases = defaults.get('aliases') or {}
    mode = mode or defaults.get('default_workflow') or 'moody_zib_zit'
    return aliases.get(mode, mode)


def get_default_workflow_name() -> str:
    defaults = load_workflow_defaults()
    return defaults.get('default_workflow') or 'moody_zib_zit'


def load_workflow_config(mode: str) -> dict:
    """加载指定工作流元数据：唯一来源 scripts/config.json → workflows。"""
    mode = normalize_workflow_name(mode)
    workflows = GLOBAL_CONFIG.get("workflows")
    cfg = None
    if isinstance(workflows, dict) and mode in workflows and isinstance(workflows[mode], dict):
        cfg = dict(workflows[mode])

    if not cfg:
        available = sorted(workflows.keys()) if isinstance(workflows, dict) else []
        print(
            f"❌ 工作流配置不存在: {mode}\n"
            f"   请在 scripts/config.json 的 workflows 中配置。\n"
            f"   当前可用: {', '.join(available) if available else '(无)'}",
            file=sys.stderr,
        )
        sys.exit(1)

    cfg.setdefault("name", mode)
    validate_config_and_workflow(mode, cfg)
    log.info(f"WORKFLOW_CFG_SOURCE | config.json#workflows.{mode}")
    return cfg


# 兼容旧调用名（main 等仍用 load_config(mode)）
def load_config(mode: str) -> dict:
    return load_workflow_config(mode)


def validate_config_and_workflow(mode: str, cfg: dict):
    workflow_path = resolve_workflow_path(cfg.get("workflow_path"))
    if not workflow_path or not os.path.exists(workflow_path):
        print(f"❌ workflow 不存在: {workflow_path}", file=sys.stderr)
        sys.exit(1)
    try:
        with open(workflow_path) as f:
            wf = json.load(f)
    except Exception as e:
        print(f"❌ workflow JSON 解析失败: {workflow_path} | {e}", file=sys.stderr)
        sys.exit(1)

    if not isinstance(wf, dict):
        print(f"❌ workflow 格式无效: {workflow_path}", file=sys.stderr)
        sys.exit(1)

    nodes = wf.get("nodes")
    links = wf.get("links")
    is_api_format = False

    if not isinstance(nodes, list) or not isinstance(links, list):
        # Check if it looks like API format (dict of node_id -> node_details)
        if all(isinstance(v, dict) and "class_type" in v for v in wf.values() if isinstance(v, dict)):
            is_api_format = True
        else:
            print(f"❌ workflow 不是受支持的 UI 格式（需要 nodes[] + links[]）或 API 格式: {workflow_path}", file=sys.stderr)
            sys.exit(1)

    if is_api_format:
        node_ids = set(wf.keys())
        for key in ("prompt_nodes", "negative_nodes", "lora_nodes", "seed_nodes", "size_nodes"):
            for nid in cfg.get(key, []):
                if str(nid) not in node_ids:
                    print(f"❌ config={mode} 引用了不存在的节点: {key} -> {nid}", file=sys.stderr)
                    sys.exit(1)
        if not any(n.get("class_type") == "SaveImage" for n in wf.values() if isinstance(n, dict)):
            print(f"❌ workflow 缺少 SaveImage 节点: {workflow_path}", file=sys.stderr)
            sys.exit(1)
    else:
        node_ids = {str(n.get('id')) for n in nodes if isinstance(n, dict) and n.get('id') is not None}
        for key in ("prompt_nodes", "negative_nodes", "lora_nodes", "seed_nodes", "size_nodes"):
            for nid in cfg.get(key, []):
                if str(nid) not in node_ids:
                    print(f"❌ config={mode} 引用了不存在的节点: {key} -> {nid}", file=sys.stderr)
                    sys.exit(1)

        if not any((n.get("type") or n.get("class_type")) == "SaveImage" for n in nodes if isinstance(n, dict)):
            print(f"❌ workflow 缺少 SaveImage 节点: {workflow_path}", file=sys.stderr)
            sys.exit(1)



def prompt_hash(text: str) -> str:
    """对 prompt 文本做 SHA256，返回前 32 字符用于快速比对"""
    return hashlib.sha256(text.encode()).hexdigest()[:32]


def convert_ui_to_api(workflow_data: dict) -> dict:
    """将 ComfyUI 保存的 UI 格式转换为 API 格式 ({id: {class_type, inputs}})

    已全面增强对现代 DiT、Qwen3-VL、LatentUpscale及三方自定义节点的智能转换与鲁棒对齐。
    支持 dict/list 两种 widgets_values 结构的精确解析。
    """
    nodes = {str(n["id"]): n for n in workflow_data.get("nodes", [])}
    links = workflow_data.get("links", [])

    # 构建 link 索引: link_id → (origin_node_id, origin_slot, type)
    link_index = {}
    for link in links:
        if len(link) >= 6:
            lid, src_nid, src_slot, tgt_nid, tgt_slot, ltype = link
            link_index[lid] = (str(src_nid), src_slot)

    api = {}
    for nid_str, node in nodes.items():
        class_type = node.get("class_type", node.get("type", ""))
        inputs = {}
        input_defs = node.get("inputs", [])
        wv = node.get("widgets_values", [])

        # 支撑新版 ComfyUI 的 dict 格式 widgets_values
        if isinstance(wv, dict):
            for wk, wv_val in wv.items():
                if wv_val is not None:
                    inputs[wk] = wv_val
            wv = []

        widget_idx = 0
        for inp in input_defs:
            if not isinstance(inp, dict):
                continue
            name = inp.get("name", "")
            link_id = inp.get("link")
            is_widget = "widget" in inp or inp.get("type") not in ["MODEL", "CLIP", "VAE", "LATENT", "IMAGE", "CONDITIONING", "MASK", "INT", "FLOAT", "STRING"]

            if link_id is not None and link_id in link_index:
                # 连线输入 -> [src_node, src_slot]
                src_nid, src_slot = link_index[link_id]
                inputs[name] = [src_nid, src_slot]
                if is_widget:
                    widget_idx += 1
            elif is_widget and isinstance(wv, list) and widget_idx < len(wv):
                val = wv[widget_idx]
                # 跳过 rgthree 控制控件（randomize/fixed 等）
                if isinstance(val, str) and val.lower() in RGTHREE_CONTROLS:
                    widget_idx += 1
                    if widget_idx < len(wv):
                        val = wv[widget_idx]
                widget_idx += 1
                if val is not None:
                    inputs[name] = val
            elif is_widget:
                inputs[name] = ""

        known_names = WIDGET_NAMES.get(class_type, [])
        for i in range(widget_idx, len(wv)):
            if i < len(known_names) and known_names[i] not in inputs:
                val = wv[i]
                if val is not None:
                    inputs[known_names[i]] = val

        api[nid_str] = {"class_type": class_type, "inputs": inputs}

    return api


def inject_and_submit(cfg: dict, prompt_text: str, lora_file: str = None, seed: int = None, width: int = None, height: int = None):
    """加载工作流 → UI→API转换 / 直接使用 API 格式 → 注入提示词/LoRA/种子/画幅 → 提交"""
    # ── 提交流程 ───────────────────────────────────────────────
    with open(resolve_workflow_path(cfg.get("workflow_path"))) as f:
        data = json.load(f)

    # 1. UI→API 格式转换
    if "nodes" in data and "links" in data:
        api = convert_ui_to_api(data)
    else:
        api = data


    # 1.5. 自动注入纹身皮肤融合词（有纹身但缺融合词时补齐）
    TATTOO_FUSION = (
        "realistic tattoo, ink embedded in dermis, "
        "beneath skin surface, follows body contours, "
        "pores visible through ink"
    )
    FUSION_SIGNALS = [
        "realistic tattoo", "ink embedded in dermis",
        "beneath skin surface", "follows body contour",
        "slightly faded edge", "pores visible through ink"
    ]
    if re.search(r'\b(tattoo|tattooed|branded.*skin|brand mark|hand-poked|irezumi|ink.*dermis|ink.*tattoo)', prompt_text, re.IGNORECASE):
        if sum(1 for s in FUSION_SIGNALS if s in prompt_text.lower()) < 2:
            prompt_text = prompt_text.rstrip() + ", " + TATTOO_FUSION
            logging.info("tattoo auto-inject: appended skin fusion words")

    # 2. 注入 prompt
    for nid in cfg["prompt_nodes"]:
        nid_str = str(nid)
        if nid_str in api:
            api[nid_str]["inputs"]["text"] = prompt_text

    # 2.5 注入 filename_prefix（确保 wait_for_result / rename / deliver 能找到正确文件）
    filename_prefix = cfg.get("filename_prefix")
    if filename_prefix:
        for nid_str, node in api.items():
            if node.get("class_type") == "SaveImage":
                node.setdefault("inputs", {})["filename_prefix"] = filename_prefix

    # 2.6 config 节点输入覆盖（例如 workflow 内置 LoRA 强度、CFG、采样器参数等）
    for nid_str, overrides in (cfg.get("node_input_overrides") or {}).items():
        nid_key = str(nid_str)
        if nid_key in api and isinstance(overrides, dict):
            api[nid_key].setdefault("inputs", {}).update(overrides)

    # 3. 注入 LoRA
    lora_dir = cfg.get("lora_subdir", "girls_like_zi")
    lora_input_key = cfg.get("lora_input_key", "LORA_1")
    static_loras = cfg.get("static_loras", {})
    has_any_lora = bool(lora_file or static_loras)

    if has_any_lora:
        for nid in cfg.get("lora_nodes", []):
            nid_str = str(nid)
            if nid_str not in api:
                continue

            lora_path = None
            if nid_str in static_loras:
                # Static LoRA (e.g. skin detail) — use hardcoded path
                lora_path = static_loras[nid_str]
            elif lora_file:
                # Celebrity LoRA
                if "/" in lora_file:
                    lora_name = os.path.basename(lora_file)
                    lora_path = f"{lora_dir}/{lora_name}"
                elif lora_file.endswith('.safetensors'):
                    lora_path = f"{lora_dir}/{lora_file}"
                else:
                    lora_path = f"{lora_dir}/{lora_file}.safetensors"

            if not lora_path:
                continue

            if lora_input_key == "lora_name":
                # Flux LoraLoader 格式：直接设 lora_name widget
                api[nid_str]["inputs"]["lora_name"] = lora_path
            else:
                # Z-Image PowerLoraLoader 格式：LORA_1 dict
                api[nid_str]["inputs"]["LORA_1"] = {
                    "on": True,
                    "lora": lora_path,
                    "strength": 1.0
                }

    # 4. 注入负面词
    for nid in cfg.get("negative_nodes", []):
        nid_str = str(nid)
        if nid_str in api:
            api[nid_str]["inputs"]["text"] = cfg.get("negative_text", "")

    # 5. 随机种子 + 默认 steps
    seed_val = seed if seed else random.randint(1, 2**48 - 1)
    default_steps = cfg.get("default_steps")
    if default_steps:
        for nid in cfg.get("seed_nodes", []):
            nid_str = str(nid)
            if nid_str in api and "steps" in api[nid_str].get("inputs", {}):
                api[nid_str]["inputs"]["steps"] = int(default_steps)
    seed_type = cfg.get("seed_type", "rgthree")
    for nid in cfg.get("seed_nodes", []):
        nid_str = str(nid)
        if nid_str in api:
            if seed_type == "flux":
                # FluxSamplerParams+ seed 是 string widget
                api[nid_str]["inputs"]["seed"] = str(seed_val)
            else:
                api[nid_str]["inputs"]["seed"] = seed_val

    # 5.5 注入画幅（未显式传入时，使用 config 默认尺寸）
    if not width and not height:
        width = cfg.get("default_width")
        height = cfg.get("default_height")

    if width and height:
        size_nodes = [str(n) for n in cfg.get("size_nodes", [])]
        injected = False
        if not size_nodes:
            size_nodes = [nid for nid, node in api.items()
                         if isinstance(node, dict)
                         and isinstance(node.get("inputs"), dict)
                         and "width" in node["inputs"] and "height" in node["inputs"]]
        for nid_str in size_nodes:
            if nid_str in api and "width" in api[nid_str].get("inputs", {}) and "height" in api[nid_str].get("inputs", {}):
                api[nid_str]["inputs"]["width"] = int(width)
                api[nid_str]["inputs"]["height"] = int(height)
                injected = True
        if injected:
            log.info(f"SIZE | {width}x{height}")
            print(f"📐 画幅: {width}x{height}")
        else:
            log.warning(f"SIZE_UNSUPPORTED | requested={width}x{height} workflow={cfg.get('name','?')}")
            print(f"⚠️ 工作流未找到可注入的 width/height 节点，画幅请求 {width}x{height} 未生效")

    # 6. 提交
    payload = {"prompt": api, "client_id": "cu-draw-card"}
    resp = requests.post(f"{API}/prompt", json=payload, timeout=10)

    if resp.status_code != 200:
        print(f"❌ 提交失败: {resp.status_code} {resp.text[:300]}", file=sys.stderr)
        sys.exit(1)

    pid = resp.json().get("prompt_id")
    log.info(f"SUBMIT | pid={pid} prompt_hash={prompt_hash(prompt_text)}")
    print(f"✅ PID: {pid}")
    return pid


def _tail_lines(path: Path, limit: int = 80) -> list[str]:
    try:
        with path.open("r", encoding="utf-8", errors="ignore") as f:
            return list(deque(f, maxlen=limit))
    except Exception:
        return []


def detect_recent_output_dir_interrupt(output_dir: str) -> bool:
    """检测 ComfyUI 最近是否在保存输出目录阶段被系统中断。"""
    comfy_log = Path(COMFYUI_DIR) / "user/comfyui_8188.log"
    lines = _tail_lines(comfy_log, 120)
    if not lines:
        return False
    blob = "".join(lines)
    return (
        "Interrupted system call" in blob
        and output_dir in blob
        and "save_images" in blob
    )


def wait_for_result(pid: str, output_dir: str, filename_prefix: str, timeout: int = 3600, done_file: str = str(TMP_DIR) + "/cu-draw-card-done.json"):
    """轮询 ComfyUI history，等待出图结果写入磁盘。失败时抛异常，由上层决定是否重试。"""
    start = time.time()
    last_progress_mark = 0
    seen_outputs_without_file = False
    outputs_seen_at = None          # 首次检测到 OUTPUTS_SEEN_WAIT_FILE 的时间
    consecutive_connection_failures = 0
    log.info(f"WAIT_START | pid={pid} timeout={timeout}s output_dir={output_dir} prefix={filename_prefix}")
    while time.time() - start < timeout:
        elapsed = int(time.time() - start)
        if elapsed >= last_progress_mark + 60:
            print(f"  ⏳ {elapsed}s...")
            last_progress_mark = elapsed
        try:
            h = requests.get(f"{API}/history/{pid}", timeout=5).json()
            consecutive_connection_failures = 0
            if pid in h:
                status = h[pid].get("status", {})
                completed = status.get("completed", False)
                status_str = status.get("status_str", "")
                messages = status.get("messages", [])
                # ── 错误早退：Comfy 节点级失败（如 SaveImage EINTR）时 completed=false，
                #    不再空等；Interrupted 映射为 output_dir_interrupted 以走渐进重试。
                err_msgs = [m for m in messages if isinstance(m, list) and len(m) > 1 and m[0] == "execution_error"]
                if status_str == "error" or err_msgs:
                    err_details = (err_msgs[0][1].get("exception_message", "Unknown ComfyUI Error") if err_msgs else f"status_str={status_str}")
                    log.error(f"COMFYUI_NODE_ERROR | pid={pid} completed={completed} status_str={status_str} error={err_details}")
                    if "Interrupted system call" in str(err_details):
                        raise RuntimeError("output_dir_interrupted")
                    raise RuntimeError(f"comfyui_execution_error: {err_details}")
                if completed:

                    if "outputs" in h[pid]:
                        found_output_entry = False
                        for node_id, output in h[pid]["outputs"].items():
                            if "images" in output:
                                found_output_entry = True
                                for img in output["images"]:
                                    name = img.get("filename", "")
                                    fpath = os.path.join(output_dir, name)
                                    if os.path.exists(fpath) and name.startswith(filename_prefix):
                                        elapsed_min = int((time.time() - start) / 60)
                                        log.info(f"DONE | pid={pid} file={name} elapsed_min={elapsed_min}")
                                        print(f"\n✅ {name}\n📁 {fpath}\n⏱️ {elapsed_min}min")
                                        seed_val = None
                                        try:
                                            prompt_nodes = h[pid].get("prompt", [])
                                            if isinstance(prompt_nodes, list) and len(prompt_nodes) > 2:
                                                api_nodes = prompt_nodes[2]
                                                for nid, node in api_nodes.items():
                                                    s = node.get("inputs", {}).get("seed")
                                                    if s is not None:
                                                        seed_val = s
                                                        break
                                        except Exception:
                                            pass

                                        marker = {
                                            "file": fpath,
                                            "filename": name,
                                            "prompt_id": pid,
                                            "seed": seed_val,
                                            "done_at": time.time(),
                                            "elapsed_min": elapsed_min
                                        }
                                        os.makedirs("/tmp/cu-card", exist_ok=True)
                                        with open(done_file, "w") as mf:
                                            json.dump(marker, mf)
                                        log.info(f"DONE_MARKER | pid={pid} done_file={done_file}")
                                        return fpath

                        if found_output_entry and not seen_outputs_without_file:
                            log.warning(f"OUTPUTS_SEEN_WAIT_FILE | pid={pid} output_dir={output_dir} prefix={filename_prefix}")
                            seen_outputs_without_file = True
                            outputs_seen_at = time.time()

                        # ── 搜救：等待 60s 主目录仍无文件，改搜 ComfyUI/output（硬编码，不读配置）──
                        if seen_outputs_without_file and outputs_seen_at and (time.time() - outputs_seen_at) > 60:
                            comfy_output = os.path.join(COMFYUI_DIR, "output")
                            log.warning(f"FALLBACK_TRIGGERED | pid={pid} searching in {comfy_output}")
                            print(f"\n⚠️ 主输出目录 60s 未出现文件，触发搜救，搜索 ComfyUI 本地目录...")
                            expected_files = set()
                            for node_id, output in h[pid]["outputs"].items():
                                if "images" in output:
                                    for img in output["images"]:
                                        name = img.get("filename", "")
                                        if name:
                                            expected_files.add(name)
                            candidates = []
                            if os.path.isdir(comfy_output):
                                rescue_time_limit = (outputs_seen_at - 10) if outputs_seen_at else start
                                for f in expected_files:
                                    src_path = os.path.join(comfy_output, f)
                                    if os.path.exists(src_path) and os.path.getmtime(src_path) >= rescue_time_limit:
                                        candidates.append(f)
                                # Fallback to prefix matching if exact files not found
                                if not candidates:
                                    candidates = [
                                        f for f in os.listdir(comfy_output)
                                        if f.startswith(filename_prefix) and f.endswith(".png")
                                        and os.path.getmtime(os.path.join(comfy_output, f)) >= rescue_time_limit
                                    ]
                            candidates = sorted(
                                candidates,
                                key=lambda f: os.path.getmtime(os.path.join(comfy_output, f)),
                                reverse=True
                            )

                            if candidates:
                                src = os.path.join(comfy_output, candidates[0])
                                # 若主目录与 Comfy output 不同，拷到主目录；否则直接用源路径
                                dst = os.path.join(output_dir, candidates[0])
                                if os.path.abspath(src) != os.path.abspath(dst):
                                    import shutil
                                    os.makedirs(output_dir, exist_ok=True)
                                    shutil.copy2(src, dst)
                                else:
                                    dst = src
                                elapsed_min = int((time.time() - start) / 60)
                                log.info(f"FALLBACK_DONE | pid={pid} src={src} dst={dst} elapsed_min={elapsed_min}")
                                print(f"✅ [搜救] {candidates[0]}\n📁 {dst}\n⏱️ {elapsed_min}min")
                                seed_val = None
                                try:
                                    prompt_nodes = h[pid].get("prompt", [])
                                    if isinstance(prompt_nodes, list) and len(prompt_nodes) > 2:
                                        api_nodes = prompt_nodes[2]
                                        for nid, node in api_nodes.items():
                                            s = node.get("inputs", {}).get("seed")
                                            if s is not None:
                                                seed_val = s
                                                break
                                except Exception:
                                    pass
                                marker = {
                                    "file": dst,
                                    "filename": candidates[0],
                                    "prompt_id": pid,
                                    "seed": seed_val,
                                    "done_at": time.time(),
                                    "elapsed_min": elapsed_min,
                                    "fallback": True
                                }
                                os.makedirs("/tmp/cu-card", exist_ok=True)
                                with open(done_file, "w") as mf:
                                    json.dump(marker, mf)
                                log.info(f"FALLBACK_MARKER | pid={pid} done_file={done_file}")
                                return dst
                            else:
                                log.error(f"FALLBACK_NOT_FOUND | pid={pid} comfy_output={comfy_output}")
                                print(f"❌ [Fallback] ComfyUI 本地 output 目录也未找到 {filename_prefix}*.png，继续等待...")
                                outputs_seen_at = time.time()  # 重置，避免每 10s 重复搜索

                    else:
                        log.error(f"COMFYUI_COMPLETED_WITHOUT_OUTPUTS | pid={pid}")
                        raise RuntimeError("comfyui_completed_without_outputs")
        except (requests.exceptions.RequestException, ValueError) as e:
            consecutive_connection_failures += 1
            log.warning(f"CONNECTION_FAILURE | err={e} count={consecutive_connection_failures}")
            if consecutive_connection_failures > 6:
                log.error("COMFYUI_DIED | consecutive connection failures exceeded limit")
                raise RuntimeError("comfyui_died")
        time.sleep(10)

    reason = "timeout"
    if detect_recent_output_dir_interrupt(output_dir):
        reason = "output_dir_interrupted"
        log.error(f"TIMEOUT_INTERRUPT_SAVE | pid={pid} output_dir={output_dir}")
    else:
        log.error(f"TIMEOUT | pid={pid} elapsed={time.time()-start:.0f}s")
    raise RuntimeError(reason)


def main():
    p = argparse.ArgumentParser(description="cu-draw-card v3.2")
    p.add_argument("--pick-celebrity", action="store_true")
    p.add_argument("--amateur", action="store_true")
    p.add_argument("--lora")
    p.add_argument("--trigger")
    p.add_argument("--prompt")
    p.add_argument("--prompt-file")
    p.add_argument("--model-type", dest="model_type", default="auto", choices=["auto","z","flux"],
                        help="z=Z-Image, flux=Flux GGUF, auto=随机选")
    p.add_argument("--mode", default=get_default_workflow_name())
    p.add_argument("--seed", type=int, default=None,
                        help="指定种子（不传则随机）")
    p.add_argument("--width", type=int, default=None,
                        help="指定输入工作流宽度（仅工作流支持时生效）")
    p.add_argument("--height", type=int, default=None,
                        help="指定输入工作流高度（仅工作流支持时生效）")
    p.add_argument("--reply-to", dest="reply_to", default=None,
                        help="Telegram message_id to reply to when sending the photo")

    args = p.parse_args()

    if args.pick_celebrity and args.amateur:
        print(json.dumps({
            "celebrity": "女大学生",
            "lora": None,
            "model_type": 'flux' if args.model_type == 'flux' else 'z',
            "trigger": None,
            "instruction": "根据 STEP 1 场景自行脑补身份职业+外貌体型描述填入prompt，场景匹配为王，裸露尺度自由大胆无下限"
        }, ensure_ascii=False))
        return

    if args.pick_celebrity:
        lora, name, trig, mtype = pick_celebrity(args)
        log.info(f"CELEBRITY | name={name} lora={lora} trigger={trig} model={mtype}")
        print(json.dumps({"celebrity":name,"lora":lora,"trigger":trig,"model_type":mtype}, ensure_ascii=False))
        return

    prompt_text = args.prompt or (open(args.prompt_file).read().strip() if args.prompt_file else None)
    if not prompt_text:
        print("❌ 需要 --prompt 或 --prompt-file", file=sys.stderr); sys.exit(1)

    lora_file = args.lora
    if args.amateur:
        log.info("MODE | amateur")
        lora_file = None

    try: requests.get(f"{API}/system_stats", timeout=5)
    except Exception:
        log.warning("COMFYUI_DOWN | attempting auto-start")
        print("⚠️ ComfyUI 未启动，尝试启动...")
        os.system(f"bash {Path(__file__).resolve().parent / 'comfyui-start.sh'} start")
        
        started = False
        for i in range(1, 7):
            time.sleep(5)
            try:
                requests.get(f"{API}/system_stats", timeout=5)
                started = True
                log.info(f"COMFYUI_AUTO_START_SUCCESS | connected after {i*5}s")
                break
            except Exception:
                log.warning(f"COMFYUI_AUTO_START_WAIT | elapsed {i*5}s, retrying...")
                
        if not started:
            log.error("COMFYUI_START_FAILED")
            print("❌ ComfyUI 启动失败，连接超时", file=sys.stderr)
            sys.exit(1)

    # 根据 --model-type / --workflow 或 LoRA 前缀自动选择 workflow 配置
    default_mode = get_default_workflow_name()
    if args.mode and args.mode != default_mode:
        mode = args.mode
    else:
        is_flux_lora = False
        if args.lora:
            if args.lora in FLUX_CELEBRITY_MAP or args.lora.startswith('girlslikeflux_'):
                is_flux_lora = True
        if args.model_type == 'flux' or is_flux_lora:
            mode = 'flux'
        else:
            mode = args.mode
    cfg = load_config(mode)
    log.info(f"CONFIG | mode={mode} workflow={cfg['name']}")
    print(f"🔗 工作流: {cfg['name']}")
    if lora_file:
        log.info(f"LORA | {lora_file}")
        print(f"🔗 LoRA: {lora_file}")
    print(f"📝 prompt: {prompt_text[:100]}{'...' if len(prompt_text)>100 else ''}\n")

    done_file = os.environ.get("DONE_FILE", str(TMP_DIR) + "/cu-draw-card-done.json")
    output_dir = os.path.expanduser(GLOBAL_CONFIG.get("output_dir") or cfg.get("output_dir") or "~/Downloads/draw_things")
    prefix = cfg.get("filename_prefix", "Moody")

    max_attempts = 4
    for attempt in range(1, max_attempts + 1):
        pid = inject_and_submit(cfg, prompt_text, lora_file, args.seed, args.width, args.height)
        try:
            wait_for_result(pid, output_dir, prefix, done_file=done_file)
            print("\n⏸️  冷却 30s...")
            time.sleep(30)
            return
        except RuntimeError as e:
            reason = str(e)
            if attempt < max_attempts and reason == "output_dir_interrupted":
                retry_delay = attempt * 5
                log.warning(f"AUTO_RETRY_SAVE_INTERRUPT | pid={pid} attempt={attempt}/{max_attempts-1} delay={retry_delay}s")
                print(f"⚠️ 输出目录保存阶段被系统中断，自动重试第 {attempt} 次，间隔 {retry_delay} 秒...", file=sys.stderr)
                time.sleep(retry_delay)
                continue
            if reason == "output_dir_interrupted":
                print("❌ 保存图片到输出目录时被系统中断，已达最大重试次数", file=sys.stderr)
                sys.exit(42)
            elif reason.startswith("comfyui_execution_error:"):
                err_msg = reason.split(":", 1)[1].strip()
                print(f"❌ ComfyUI 执行出错: {err_msg}", file=sys.stderr)
                sys.exit(1)
            elif reason == "comfyui_completed_without_outputs":
                print("❌ ComfyUI 运行完成但未生成任何输出图片", file=sys.stderr)
                sys.exit(1)
            else:
                print("❌ 超时", file=sys.stderr)
                sys.exit(1)


if __name__ == "__main__":
    main()


# ─── 添加节点/修改 workflow 规则 ──────────────────────────
# 所有节点变更都在 ComfyUI GUI 里操作 → 保存 JSON 即可。
# 不需要改 Python 代码，转换器自动适配。
#
# 新增 LoRA 节点 (PowerLoraLoader)：
#   1. ComfyUI 里加入节点，连线，保存 workflow JSON 到 {comfyui_dir}/workflows/...
#   2. 打开 `scripts/config.json` → workflows.<name>
#   3. 把新节点的 ID 追加到 `lora_nodes` 数组里
#   4. 完成；如有多套 workflow，分别同步。
#
# 新增 prompt 节点 (CLIPTextEncode)：
#   1. ComfyUI 加节点，保存 JSON
#   2. config.json 对应 workflow 的 `prompt_nodes` 追加节点 ID
#
# 新增 seed 节点 (rgthree Seed)：
#   1. ComfyUI 加节点，保存 JSON
#   2. config.json 对应 workflow 的 `seed_nodes` 追加节点 ID
#
# 改参数（步数/CFG/分辨率等）：
#   1. 直接在 ComfyUI GUI 里改
#   2. 保存 workflow JSON
#   3. 更新说明文档和文件名
#
# ⚠️ 删除节点后必须清理 stale link：
#   保存 JSON 后 grep 检查 link_id 是否都在 links 数组里。
#   旧的 link 引用会导致 API 400 错误。
#
# ⚠️ 不要在 Python 里硬编码 widget 索引，转换器读 input 元数据自动处理。
