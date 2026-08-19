#!/usr/bin/env python3
"""ComfyUI 抽卡控制台 Web UI 后端服务"""

# =====================================================================
# ─── SECTION 1: SYSTEM IMPORTS & LOGGER INITIALIZATION ───────────────
# =====================================================================
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


import io
import json
import os
import re
import sys
import tempfile
import threading
import time
from pathlib import Path
from typing import Dict, Any, Optional

from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

# 设定工作路径，并导入卡引擎
SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))
sys.path.insert(0, str(SCRIPT_DIR.parent / "card-engine"))

# 兼容 `python3 web_server.py` 直跑：预登记 __main__ 为 web_server，
# 否则 api_cards 等子模块 `from web_server import ...` 会二次执行本文件，造成循环导入
sys.modules.setdefault("web_server", sys.modules[__name__])

import threading
import glob
from datetime import datetime

class DailyRotatingFile:
    def __init__(self, filename, backup_count=30):
        self.filename = os.path.abspath(filename)
        self.backup_count = backup_count
        self.file = None
        self.current_date = datetime.now().date()
        self.lock = threading.Lock()
        self._open_file()

    def _open_file(self):
        os.makedirs(os.path.dirname(self.filename), exist_ok=True)
        self.file = open(self.filename, "a", encoding="utf-8", buffering=1)

    def _rotate_if_needed(self):
        now_date = datetime.now().date()
        if now_date != self.current_date:
            with self.lock:
                if datetime.now().date() != self.current_date:
                    self.file.close()
                    suffix = self.current_date.strftime("%Y-%m-%d")
                    rotated_name = f"{self.filename}.{suffix}"
                    if os.path.exists(self.filename) and not os.path.exists(rotated_name):
                        try:
                            os.rename(self.filename, rotated_name)
                        except Exception as e:
                            sys.__stderr__.write(f"Failed to rotate log file: {e}\n")
                    self.current_date = now_date
                    self._open_file()
                    self._cleanup_old_files()

    def _cleanup_old_files(self):
        pattern = f"{self.filename}.*"
        files = sorted(glob.glob(pattern))
        if len(files) > self.backup_count:
            files_to_delete = files[:-self.backup_count]
            for f in files_to_delete:
                try:
                    os.remove(f)
                except Exception as e:
                    sys.__stderr__.write(f"Failed to delete old log file {f}: {e}\n")

    def write(self, data):
        self._rotate_if_needed()
        with self.lock:
            self.file.write(data)

    def flush(self):
        with self.lock:
            if self.file:
                self.file.flush()

    def isatty(self):
        return False

    @property
    def closed(self):
        return self.file.closed

# Redirect stdout and stderr to DailyRotatingFile with ThreadLocalStream proxy to prevent multi-threading race conditions in run_core_cmd
import threading

class ThreadLocalStream:
    def __init__(self, default_stream):
        self.default_stream = default_stream
        self.local = threading.local()

    def write(self, data):
        stream = getattr(self.local, 'stream', None)
        if stream is not None:
            stream.write(data)
        else:
            self.default_stream.write(data)

    def flush(self):
        stream = getattr(self.local, 'stream', None)
        if stream is not None:
            stream.flush()
        else:
            self.default_stream.flush()

    def isatty(self):
        return False

LOGS_DIR = SCRIPT_DIR / "logs"
LOGS_DIR.mkdir(parents=True, exist_ok=True)
rotating_file = DailyRotatingFile(str(LOGS_DIR / "web_server.log"), backup_count=30)
sys.stdout = ThreadLocalStream(rotating_file)
sys.stderr = ThreadLocalStream(rotating_file)


from card_core import CARDS_DIR, save_card, load_card
from agent_bridge import stream_agent_chat  # re-export for tests/monkeypatch
from prompt_rules import clean_user_message, normalize_chat_mode

# =====================================================================
# ─── SECTION 2: FASTAPI APP INSTANTIATION & MIDDLEWARES ──────────────
# =====================================================================

app = FastAPI(title="ComfyUI Card Engine Web UI", version="1.0.0")

# 配置 CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


CONFIG_PATH = SCRIPT_DIR.parent / "config.json"

# 已废弃的配置键：读取时剔除、保存时不写回，避免旧 config.json 长期携带无人消费的字段
DEPRECATED_CONFIG_KEYS = (
    "output_dir_fallback",   # 额外搜救目录已移除
    "agent_webhook_url",     # 随 custom_http 后端一并废弃
    "agent_api_key",
    "comfyui_extra_models_config",  # 已废弃：不再配置、启动也不再传 yaml
    "bound_scene_bypass_exposure_limit",  # 绑定场景始终绕过全局裸露限制
)
PRESETS_DIR = SCRIPT_DIR.parent / "presets"

def load_system_config() -> Dict[str, Any]:
    """载入本地 config.json，自带默认值兜底"""
    defaults = {
        "comfyui_host": "http://127.0.0.1:8188",
        # 便携占位默认值；本机真实路径只写在 config.json，禁止在此硬编码机器路径
        "output_dir": "~/Downloads/draw_things",
        "custom_presets_dir": str(PRESETS_DIR.resolve()),
        "recording_dir": "~/Downloads/draw_history",
        "llm_model": "opencode-go/mimo-v2.5",
        "agent_backend": "openclaw",
        "delivery_telegram": True,
        "delivery_webui": True,
        "independent_llm_model": "opencode-go/deepseek-v4-flash",
        "llm_fallback_models": ["cli-proxy/ds-flash"],
        "chat_mode": "cards",
        "comfyui_dir": str(Path.home() / "ComfyUI"),
        "obsidian_vault_dir": "~/Documents/ObsidianVault",
        "webui_host": "0.0.0.0",
        "webui_port": 8318,
        "openclaw_ws_timeout_seconds": 600,
        "scene_cooldown_window": 9,
        "scene_library_weights": {
            "school_scenes": 5,
            "general_scenes": 5,
            "medical_scenes": 3,
            "workplace_scenes": 3,
            "sm_scenes": 5,
            "special_scenes": 5,
            "perspective_scenes": 0
        },
        # WebUI 场景权重面板依赖此注册表；缺省时前端会空白并可能自动保存成 {}
        "scene_registry": {
            "libraries": {
                "school_scenes": {"type": "scene", "enabled": True, "name": "校园场景", "file": "school_scenes.json"},
                "general_scenes": {"type": "scene", "enabled": True, "name": "通用场景", "file": "general_scenes.json"},
                "medical_scenes": {"type": "scene", "enabled": True, "name": "医疗场景", "file": "medical_scenes.json"},
                "workplace_scenes": {"type": "scene", "enabled": True, "name": "职场场景", "file": "workplace_scenes.json"},
                "sm_scenes": {"type": "scene", "enabled": True, "name": "SM场景", "file": "sm_scenes.json"},
                "special_scenes": {"type": "scene", "enabled": True, "name": "特殊场景", "file": "special_scenes.json"},
                "perspective_scenes": {"type": "scene", "enabled": True, "name": "视角场景", "file": "perspective_scenes.json"},
            }
        },
        "llm_temperature": 0.7,
        "llm_retry_limit": 1,
        "auto_horizontal_for_multi": True,
        "lock_size_to_workflow": True,
        "resolution_presets": {
            "vertical": {
                "width": 512,
                "height": 768
            },
            "horizontal": {
                "width": 768,
                "height": 512
            },
            "square": {
                "width": 640,
                "height": 640
            },
            "widescreen": {
                "width": 1088,
                "height": 464
            }
        },
        "exposure_limit": ["half_covered", "half_nude"],
        "restrict_roles": True,
        "default_workflow": "moody",
        "workflows_aliases": {
            "moody": "moody_zib_zit"
        },
        "workflows": {
            "moody_zib_zit": {
                "name": "Moody ZIB+ZIT",
                "workflow_path": "workflows/Moody_ZIB_ZIT_20步_CFG3_512x768.json",
                "filename_prefix": "Moody",
                "prompt_nodes": ["620", "627", "660"],
                "negative_nodes": ["674"],
                "negative_text": "low quality, worst quality, blurry, jpeg artifacts, watermark, deformed, bad anatomy, bad mouth, bad teeth, weird tongue, distorted lips, extra limbs, extra fingers, mutated hands, bad proportions, ugly, disfigured, cropped, out of frame, semen on chin, cum on chin, fluid on chin",
                "lora_nodes": ["632", "671"],
                "seed_nodes": ["654", "649", "688"],
                "size_nodes": ["606"],
                "seed_type": "rgthree",
                "deforum_fix": True,
                "link_key": "links",
                "node_key": "nodes",
                "prompt_style": "photorealistic_portrait",
                "description": "Moody ZIB+ZIT 双阶段素人/明星写真，20有效步，512x768初始→768x1152输出，支持 girls_like_zi LoRA",
                "lora_subdir": "girls_like_zi",
                "lora_input_key": "LORA_1",
                "node_input_overrides": {},
                "default_steps": 20,
                "default_width": 512,
                "default_height": 768
            }
        }
    }
    
    # 智能检测：如果默认 output_dir 不存在，降级到用户 Pictures（仅作代码层占位，本机路径以 config.json 为准）
    if not os.path.exists(os.path.expanduser(defaults["output_dir"])):
        home = str(Path.home())
        defaults["output_dir"] = os.path.join(home, "Pictures", "DrawThings")

    if CONFIG_PATH.exists():
        try:
            user_config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
            # 合并默认值
            for k, v in defaults.items():
                if k not in user_config:
                    user_config[k] = v
            # 强制回退已废弃的后端
            if user_config.get("agent_backend") in ("claudecode", "hermes"):
                user_config["agent_backend"] = "openclaw"
            # 归一化 chat_mode：仅 cards | draw
            user_config["chat_mode"] = normalize_chat_mode(user_config.get("chat_mode"), "cards")
            for key in DEPRECATED_CONFIG_KEYS:
                user_config.pop(key, None)
            
            # 展开用户目录路径
            config = user_config.copy()
            for k in ["output_dir", "output_dir_archive", "obsidian_vault_dir", "comfyui_dir", "openclaw_workspace_dir", "custom_presets_dir"]:
                if k in config and isinstance(config[k], str):
                    val = os.path.expanduser(config[k])
                    if val.strip() and not os.path.isabs(val):
                        try:
                            config_real_dir = CONFIG_PATH.resolve().parent
                            val = str((config_real_dir / val).resolve())
                        except Exception:
                            pass
                    config[k] = val
            return config
        except Exception as e:
            raise RuntimeError(f"配置文件 config.json 解析失败，格式或内容不正确: {e}") from e
            
    # 初始化写回 (使用未展开的 defaults)
    try:
        safe_write_config(CONFIG_PATH, json.dumps(defaults, indent=2, ensure_ascii=False))
    except Exception:
        pass
        
    # 返回展开后的 defaults
    config = defaults.copy()
    for k in ["output_dir", "output_dir_archive", "obsidian_vault_dir", "comfyui_dir", "custom_presets_dir"]:
        if k in config and isinstance(config[k], str):
            val = os.path.expanduser(config[k])
            if val.strip() and not os.path.isabs(val):
                try:
                    config_real_dir = CONFIG_PATH.resolve().parent
                    val = str((config_real_dir / val).resolve())
                except Exception:
                    pass
            config[k] = val
    return config

def safe_write_config(file_path: Path, content: str, max_backups: int = 9):
    """
    保存配置文件：变化时滚动备份至多 9 份；原子替换写入，避免并发/中断产生 Extra data。
    """
    try:
        # 1. 解析软链接得到真实路径
        real_path = file_path.resolve()
        real_path.parent.mkdir(parents=True, exist_ok=True)

        # 2. 进程内互斥 + 文件锁，降低并行冒烟/多实例写坏 JSON 的概率
        if not hasattr(safe_write_config, "_lock"):
            safe_write_config._lock = threading.Lock()

        with safe_write_config._lock:
            lock_path = real_path.with_name(real_path.name + ".lock")
            lock_fd = None
            try:
                lock_fd = open(lock_path, "a+", encoding="utf-8")
                try:
                    import fcntl
                    fcntl.flock(lock_fd.fileno(), fcntl.LOCK_EX)
                except Exception:
                    pass

                # 3. 检查是否需要备份
                should_backup = False
                if real_path.exists():
                    try:
                        old_content = real_path.read_text(encoding="utf-8")
                        try:
                            old_json = json.loads(old_content)
                            new_json = json.loads(content)
                            if old_json != new_json:
                                should_backup = True
                        except Exception:
                            if old_content.strip() != content.strip():
                                should_backup = True
                    except Exception:
                        should_backup = True

                # 4. 滚动备份（拷贝，不 rename 原文件，避免读窗空洞）
                if should_backup and real_path.exists():
                    for i in range(max_backups - 1, 0, -1):
                        src = real_path.with_name(f"{real_path.name}.bak.{i}")
                        dst = real_path.with_name(f"{real_path.name}.bak.{i+1}")
                        if src.exists():
                            try:
                                if dst.exists():
                                    dst.unlink()
                                src.rename(dst)
                            except Exception:
                                pass
                    bak1 = real_path.with_name(f"{real_path.name}.bak.1")
                    try:
                        import shutil
                        shutil.copy2(str(real_path), str(bak1))
                    except Exception:
                        pass

                # 5. 原子写入：tmp + os.replace
                tmp_path = real_path.with_name(real_path.name + f".tmp.{os.getpid()}")
                tmp_path.write_text(content, encoding="utf-8")
                os.replace(str(tmp_path), str(real_path))
            finally:
                if lock_fd is not None:
                    try:
                        import fcntl
                        fcntl.flock(lock_fd.fileno(), fcntl.LOCK_UN)
                    except Exception:
                        pass
                    try:
                        lock_fd.close()
                    except Exception:
                        pass

    except Exception:
        # 最终安全降级：仍尽量原子写
        try:
            real_path = file_path.resolve()
            tmp_path = real_path.with_name(real_path.name + f".tmp.{os.getpid()}")
            tmp_path.write_text(content, encoding="utf-8")
            os.replace(str(tmp_path), str(real_path))
        except Exception:
            try:
                file_path.write_text(content, encoding="utf-8")
            except Exception:
                pass

def save_system_config(config_data: Dict[str, Any]):
    """保存配置并合并已有字段"""
    if config_data.get("agent_backend") in ("claudecode", "hermes"):
        config_data["agent_backend"] = "openclaw"
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    
    current_config = {}
    if CONFIG_PATH.exists():
        try:
            current_config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        except Exception:
            pass

    # 防护：空 scene_library_weights / 空 scene_registry 不覆盖已有有效配置
    if isinstance(config_data.get("scene_library_weights"), dict) and not config_data["scene_library_weights"]:
        if current_config.get("scene_library_weights"):
            config_data = dict(config_data)
            config_data.pop("scene_library_weights", None)
    reg = config_data.get("scene_registry")
    if isinstance(reg, dict) and not (reg.get("libraries") or {}):
        if current_config.get("scene_registry", {}).get("libraries"):
            config_data = dict(config_data)
            config_data.pop("scene_registry", None)
            
    for k, v in config_data.items():
        current_config[k] = v

    for key in DEPRECATED_CONFIG_KEYS:
        current_config.pop(key, None)
        
    safe_write_config(CONFIG_PATH, json.dumps(current_config, indent=2, ensure_ascii=False))

# =====================================================================
# ─── SECTION 3: SYSTEM INITIALIZATION & STATIC FOLDER MOUNTING ───────
# =====================================================================

# 载入运行期配置
sys_config = load_system_config()

# 动态挂载图片服务，带防御性容错
images_app = StaticFiles()
app.mount("/images", images_app, name="images")

def update_images_mount():
    """动态更新挂载的出图预览目录。

    ``/images``：``output_dir_archive`` 优先，同时挂载本地 ``output_dir``
    （交付外置盘超时后成品留在 Comfy 本地，WebUI 仍可预览）。
    """
    config = load_system_config()
    archive_dir = (config.get("output_dir_archive") or "").strip()
    out_dir = (config.get("output_dir") or "").strip()

    primary_dirs: list[str] = []
    seen: set[str] = set()
    for raw in (archive_dir, out_dir):
        if not raw:
            continue
        abs_path = os.path.abspath(os.path.expanduser(raw))
        try:
            key = str(Path(abs_path).resolve())
        except (OSError, RuntimeError):
            key = abs_path
        if key in seen:
            continue
        seen.add(key)
        os.makedirs(abs_path, exist_ok=True)
        primary_dirs.append(abs_path)

    if primary_dirs:
        images_app.directory = primary_dirs[0]
        images_app.all_directories = primary_dirs

# 初始挂载
update_images_mount()


def run_core_cmd(cmd_func, args):
    """安全唤起核心引擎，截获 SystemExit 以防 Web 进程崩溃，捕获控制台输出并捕获返回值"""
    stdout_buf = io.StringIO()
    stderr_buf = io.StringIO()
    exited = False
    exit_code = 0
    ret = None
    
    # Use thread-local streams to capture prints in a thread-safe manner
    if hasattr(sys.stdout, 'local'):
        sys.stdout.local.stream = stdout_buf
    if hasattr(sys.stderr, 'local'):
        sys.stderr.local.stream = stderr_buf

    try:
        ret = cmd_func(args)
    except SystemExit as e:
        exited = True
        exit_code = e.code if isinstance(e.code, int) else 1
    except BaseException as e:
        import traceback
        traceback.print_exc(file=stderr_buf)
        exited = True
        exit_code = 999
    finally:
        if hasattr(sys.stdout, 'local'):
            sys.stdout.local.stream = None
        if hasattr(sys.stderr, 'local'):
            sys.stderr.local.stream = None
            
    return {
        "stdout": stdout_buf.getvalue(),
        "stderr": stderr_buf.getvalue(),
        "exited": exited,
        "exit_code": exit_code,
        "return_value": ret
    }



# cards/settings/pipeline → api_cards.py
def get_chat_history_dir() -> Path:
    # 1. 优先使用环境变量自定义路径，极大提升 Docker/容器化部署时的移植性
    env_dir = os.environ.get("AMAZING_DRAW_CHAT_DIR")
    if env_dir:
        return Path(env_dir)
    
    # 2. 其次，若存在 ~/.openclaw 目录，则整合入 openclaw 体系
    openclaw_dir = Path.home() / ".openclaw"
    if openclaw_dir.exists() and openclaw_dir.is_dir():
        return openclaw_dir / "webui-chat"
        
    # 3. 兜底使用项目同级 data 目录，确保纯本地独立环境开箱即用，避免污染主目录
    return Path(__file__).resolve().parent / "data" / "webui-chat"

CHAT_HISTORY_DIR = get_chat_history_dir()


@app.on_event("startup")
def configure_operation_journal() -> None:
    """Restore durable operation metadata after the history path is final."""
    from operation_registry import operation_registry

    operation_registry.configure_journal(
        CHAT_HISTORY_DIR / "operations-v1.json"
    )


def safe_chat_id(card_id: Optional[str]) -> str:
    raw = card_id or "home"
    return re.sub(r"[^0-9A-Za-z_.-]", "_", raw)[:120] or "home"


def webui_session_id(card_id: Optional[str]) -> str:
    return f"webui-draw-card-{safe_chat_id(card_id)}"


def chat_history_file(card_id: Optional[str]) -> Path:
    return CHAT_HISTORY_DIR / f"{safe_chat_id(card_id)}.jsonl"





def first_user_line(history_path: Path) -> str:
    """取会话首句用户提问，用作列表标题。

    只读一行就够，历史文件可能很大，没必要整份载入。
    """
    try:
        with history_path.open("r", encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                try:
                    item = json.loads(line)
                except ValueError:
                    continue
                if item.get("role") == "user":
                    return str(item.get("content", "")).strip()
    except Exception:
        pass
    return ""








_CHAT_HISTORY_LOCKS = {}
_CHAT_HISTORY_LOCKS_GUARD = threading.Lock()


def _chat_history_lock(path: Path):
    with _CHAT_HISTORY_LOCKS_GUARD:
        return _CHAT_HISTORY_LOCKS.setdefault(path, threading.Lock())


def append_chat_history(card_id: Optional[str], role: str, content: str):
    CHAT_HISTORY_DIR.mkdir(parents=True, exist_ok=True)
    item = {"role": role, "content": content, "time": int(time.time())}
    path = chat_history_file(card_id)
    with _chat_history_lock(path):
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(item, ensure_ascii=False) + "\n")


def append_chat_history_once(
    card_id: Optional[str],
    operation_id: str,
    role: str,
    content: str,
    *,
    operation_state: Optional[str] = None,
) -> bool:
    """Atomically append one operation/role record at most once."""
    CHAT_HISTORY_DIR.mkdir(parents=True, exist_ok=True)
    path = chat_history_file(card_id)
    with _chat_history_lock(path):
        existing = path.read_text(encoding="utf-8") if path.exists() else ""
        for line in existing.splitlines():
            try:
                item = json.loads(line)
            except (TypeError, ValueError):
                continue
            if (
                item.get("operation_id") == operation_id
                and item.get("role") == role
            ):
                return False

        item = {
            "operation_id": operation_id,
            "role": role,
            "content": content,
            "time": int(time.time()),
        }
        if operation_state:
            item["operation_state"] = operation_state
        payload = existing
        if payload and not payload.endswith("\n"):
            payload += "\n"
        payload += json.dumps(item, ensure_ascii=False) + "\n"

        handle = tempfile.NamedTemporaryFile(
            prefix=f".{path.name}.",
            suffix=".tmp",
            dir=str(path.parent),
            mode="w",
            encoding="utf-8",
            delete=False,
        )
        temp_path = Path(handle.name)
        try:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
            handle.close()
            os.replace(temp_path, path)
        except Exception:
            handle.close()
            temp_path.unlink(missing_ok=True)
            raise
        return True


def clear_chat_history(card_id: Optional[str]):
    chat_history_file(card_id).unlink(missing_ok=True)


def extract_session_timestamp(session_id: str, default_time: float) -> float:
    try:
        import re as _re, datetime as _datetime
        match = _re.search(r"(\d{8})_(\d{6})", session_id)
        if match:
            date_str, time_str = match.groups()
            dt = _datetime.datetime.strptime(f"{date_str}_{time_str}", "%Y%m%d_%H%M%S")
            return dt.timestamp()
    except:
        pass
    return default_time


SESSION_TITLE_CACHE = {}

def get_cached_session_title(path: Path) -> str:
    """按 mtime+size 缓存的会话标题，取自历史文件里的首句提问。"""
    path_str = str(path.resolve())
    try:
        stat = path.stat()
        mtime = stat.st_mtime
        size = stat.st_size
    except Exception:
        return ""

    cached = SESSION_TITLE_CACHE.get(path_str)
    if cached and cached[0] == mtime and cached[1] == size:
        return cached[2]

    title = first_user_line(path)[:80].strip()
    SESSION_TITLE_CACHE[path_str] = (mtime, size, title)
    return title


# chat routes → api_chat.py

def webui_session_file(session_id: str = "webui-draw-home") -> Path:
    """会话文件 = 对话历史文件，全局唯一一份。

    早先这里另开了 scripts/webui/sessions/<backend>/ 做「会话索引」，内容恒为空，
    只靠文件名与 mtime 支撑列表。一份数据两个地方带来三处失准：
    标题永远取不到、排序按创建时间而非最后活跃、有历史但索引缺失的会话直接从列表消失。
    现在只保留 CHAT_HISTORY_DIR 这一处。
    """
    return chat_history_file(session_id)


STATIC_DIR = SCRIPT_DIR / "static"
STATIC_DIR.mkdir(parents=True, exist_ok=True)

from api_cards import router as cards_router
from api_queue import router as queue_router
from api_chat import router as chat_router
app.include_router(cards_router)
app.include_router(queue_router)
app.include_router(chat_router)

app.mount("/", StaticFiles(directory=str(STATIC_DIR), html=True), name="static")


if __name__ == "__main__":
    # 前端开发目录初始化
    STATIC_DIR.mkdir(parents=True, exist_ok=True)
    # 局域网启动监听
    cfg = load_system_config()
    host = cfg.get("webui_host", "0.0.0.0")
    port = cfg.get("webui_port", 8318)
    uvicorn.run("web_server:app", host=host, port=port, reload=False)
