#!/usr/bin/env python3
"""Queue / models / docs / workflow-convert API routes."""

from __future__ import annotations
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


import argparse
import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from fastapi import APIRouter, HTTPException

from web_server import (
    CARDS_DIR,
    SCRIPT_DIR,
    load_system_config,
)
from card_cli_commands import cmd_progress
from card_config import TMP_DIR
from card_io import card_path
from card_status_service import restore_card_after_cancel
from workflow_convert_lib import (
    _is_api_workflow,
    perform_workflow_conversion,
)

router = APIRouter(tags=["queue"])

def _tmp_path(*parts: str) -> Path:
    return Path(TMP_DIR).joinpath(*parts)


def _gpu_pipeline_script(name: str) -> Path:
    """Resolve gpu-pipeline scripts next to this WebUI package."""
    return SCRIPT_DIR.parent / "gpu-pipeline" / name


def _run_queue_cli(*args: str, timeout: float = 12.0) -> tuple[subprocess.CompletedProcess, Dict[str, Any]]:
    """Run QueueStore CLI and parse its final structured ACK."""
    env = os.environ.copy()
    env["CU_WORK_DIR"] = str(TMP_DIR)
    env["CU_CARDS_DIR"] = str(CARDS_DIR)
    proc = subprocess.run(
        [sys.executable, str(_gpu_pipeline_script("cu-queue.py")), *args],
        capture_output=True,
        text=True,
        timeout=timeout,
        env=env,
    )
    payload: Dict[str, Any] = {}
    for line in reversed((proc.stdout or "").splitlines()):
        try:
            candidate = json.loads(line)
        except (TypeError, ValueError, json.JSONDecodeError):
            continue
        if isinstance(candidate, dict):
            payload = candidate
            break
    if not payload:
        payload = {
            "ok": False,
            "status": "invalid_ack",
            "error": (proc.stderr or proc.stdout or "queue CLI returned no JSON").strip(),
        }
    return proc, payload


def run_core_cmd(*args, **kwargs):
    """Delegate so tests can patch web_server.run_core_cmd."""
    import web_server as _ws
    return _ws.run_core_cmd(*args, **kwargs)




# 进度面板缓存：缓存期限 10 秒
_progress_cache_lock = threading.Lock()
_progress_cache = {
    "last_updated": 0.0,
    "stdout": "📊 进度获取中..."
}

# ComfyUI 队列状态缓存：缓存期限 5 秒
_comfy_queue_cache_lock = threading.Lock()
_comfy_queue_cache = {
    "last_updated": 0.0,
    "queue": {"running": 0, "pending": 0},
    "online": False
}

def _telegram_token_configured(cfg: Dict[str, Any]) -> bool:
    """True if a bot token is available: config.json telegram_bot_token → env TELEGRAM_BOT_TOKEN.

    Keep the same order as cu-deliver.sh (no .bot_tokens, no other env names).
    """
    if str(cfg.get("telegram_bot_token") or "").strip():
        return True
    return bool("".join((os.environ.get("TELEGRAM_BOT_TOKEN") or "").split()))


def _cheap_integrations_status() -> Dict[str, bool]:
    """Configured + locally present (not a live network ping)."""
    telegram = False
    obsidian = False
    try:
        cfg = load_system_config()
        delivery_on = cfg.get("delivery_telegram") is not False
        chat_id = str(cfg.get("telegram_chat_id") or "").strip()
        telegram = bool(delivery_on and chat_id and _telegram_token_configured(cfg))

        vault_raw = str(cfg.get("obsidian_vault_dir") or "").strip()
        if vault_raw:
            vault = Path(os.path.expanduser(vault_raw))
            # 配置了路径，且 vault 存在、含灵感库（或 .obsidian）即视为已安装可用
            obsidian = vault.is_dir() and (
                (vault / "灵感库").is_dir() or (vault / ".obsidian").is_dir()
            )
    except Exception:
        pass

    llm_ok = False
    try:
        from card_llm_client import list_models
        llm_ok = bool(list_models(load_system_config()))
    except Exception:
        llm_ok = False

    return {
        "llm": bool(llm_ok),
        "openclaw": bool(llm_ok),  # 旧前端字段，等同 llm
        "telegram": bool(telegram),
        "obsidian": bool(obsidian),
    }


@router.get("/api/config/integrations")
def get_integrations_status():
    """LLM / Telegram / Obsidian readiness for settings chips."""
    return {"integrations": _cheap_integrations_status()}

@router.get("/api/queue/status")
def get_queue_status():
    """队列状态查询"""
    global _progress_cache, _comfy_queue_cache
    
    current_time = time.time()
    cache_ttl = 10.0  # 缓存 10 秒
    comfy_ttl = 5.0   # ComfyUI 队列缓存 5 秒
    
    # 若缓存过期，尝试非阻塞获取锁来更新缓存。如果失败（有其他线程正在更新），则直接使用现有缓存，不阻塞当前请求。
    if current_time - _progress_cache["last_updated"] > cache_ttl:
        acquired = _progress_cache_lock.acquire(blocking=False)
        if acquired:
            try:
                # 双重检查锁
                if time.time() - _progress_cache["last_updated"] > cache_ttl:
                    res = run_core_cmd(cmd_progress, argparse.Namespace())
                    _progress_cache["stdout"] = res.get("stdout", "")
                    _progress_cache["last_updated"] = time.time()
            except Exception as e:
                # 异常时冷却 5 秒，防止频繁失败重试
                _progress_cache["stdout"] = f"⚠️ 获取进度超时或失败: {str(e)}\n\n" + _progress_cache.get("stdout", "")
                _progress_cache["last_updated"] = time.time() - 5.0
            finally:
                _progress_cache_lock.release()
                
    with _progress_cache_lock:
        stdout_val = _progress_cache["stdout"]
    
    # 捕获 ComfyUI 系统与队列（增加非阻塞缓存，TTL 5 秒）
    comfy_queue = {"running": 0, "pending": 0}
    if current_time - _comfy_queue_cache["last_updated"] > comfy_ttl:
        acquired_comfy = _comfy_queue_cache_lock.acquire(blocking=False)
        if acquired_comfy:
            try:
                if time.time() - _comfy_queue_cache["last_updated"] > comfy_ttl:
                    c_status = load_system_config()
                    host = c_status.get("comfyui_host", "http://127.0.0.1:8188")
                    import requests
                    q_resp = requests.get(f"{host}/queue", timeout=1).json()
                    _comfy_queue_cache["queue"] = {
                        "running": len(q_resp.get("queue_running", [])),
                        "pending": len(q_resp.get("queue_pending", []))
                    }
                    _comfy_queue_cache["online"] = True
                    _comfy_queue_cache["last_updated"] = time.time()
            except Exception:
                _comfy_queue_cache["online"] = False
                # 异常时继承上次的值并冷却 2 秒（设置更新时间戳为 current_time - 3s 相当于已过 3s，再过 2s 可重试，防止频繁阻塞 1s 超时）
                _comfy_queue_cache["last_updated"] = time.time() - 3.0
            finally:
                _comfy_queue_cache_lock.release()

    with _comfy_queue_cache_lock:
        comfy_queue = _comfy_queue_cache["queue"]
        comfy_online = _comfy_queue_cache["online"]

    # 检查 GPU 锁文件状态
    gpu_lock_active = False
    gpu_lock_age = 0
    lock_file = _tmp_path("cu-gpu.lock")
    if lock_file.exists():
        gpu_lock_active = True
        try:
            gpu_lock_age = int(time.time() - lock_file.stat().st_mtime)
        except Exception:
            pass

    # QueueStore 是唯一队列入口；WebUI 不直接读取或改写 cu-queue.json。
    local_queue = []
    queue_store: Dict[str, Any] = {"ok": False, "status": "unavailable"}
    try:
        queue_proc, queue_store = _run_queue_cli("status", timeout=5)
        if queue_proc.returncode == 0 and queue_store.get("ok"):
            for raw_item in queue_store.get("queue") or []:
                item = dict(raw_item)
                meta_path = item.get("meta") or item.get("meta_file")
                person = ""
                scene = ""
                if meta_path and Path(meta_path).exists():
                    try:
                        meta_data = json.loads(Path(meta_path).read_text(encoding="utf-8"))
                        person = meta_data.get("person", "")
                        scene = meta_data.get("scene", "")
                    except Exception:
                        pass
                item["person"] = person
                item["scene"] = scene
                local_queue.append(item)
    except Exception as exc:
        queue_store = {"ok": False, "status": "status_failed", "error": str(exc)}

    # 解析当前正在渲染信息 (从 cu-runtime.json 中读)
    runtime_info = {}
    runtime_file = _tmp_path("cu-runtime.json")
    if runtime_file.exists():
        try:
            runtime_info = json.loads(runtime_file.read_text(encoding="utf-8"))
        except Exception:
            pass

    return {
        "gpu_lock": {
            "active": gpu_lock_active,
            "age_seconds": gpu_lock_age
        },
        "comfyui": comfy_queue,
        "comfyui_online": comfy_online,
        "local_queue": local_queue,
        "queue_store": {
            "ok": bool(queue_store.get("ok")),
            "status": queue_store.get("status"),
            "schema_version": queue_store.get("schema_version"),
            "revision": queue_store.get("revision"),
            "state_counts": queue_store.get("state_counts") or {},
            "error": queue_store.get("error"),
        },
        "runtime": runtime_info,
        "stdout": stdout_val,
        "integrations": _cheap_integrations_status(),
    }

@router.post("/api/queue/unlock")
def unlock_queue():
    """强制解锁 GPU 锁"""
    lock_file = _tmp_path("cu-gpu.lock")
    if lock_file.exists():
        lock_file.unlink()
        return {"status": "unlocked"}
    return {"status": "no_lock_found"}

def _reset_queued_card_to_draft(card_id: Optional[str]) -> None:
    """Compatibility wrapper for older callers; restores a captured status."""
    if not card_id:
        return
    try:
        restore_card_after_cancel(
            card_id,
            reason="queue_removed",
            fallback_status="draft",
        )
    except (Exception, SystemExit):
        pass


def _set_card_status(card_id: Optional[str], status: str, error: str = "") -> None:
    """Best-effort card status synchronization for queue job transitions."""
    if not card_id:
        return
    try:
        from card_io import save_card, load_card
        path = card_path(card_id)
        if not path.exists():
            return
        card = load_card(card_id)
        card["status"] = status
        if error:
            card["render_error"] = error
        save_card(card)
    except (Exception, SystemExit):
        pass


@router.post("/api/queue/remove")
def remove_queue_item(req: Dict[str, Any]):
    """按稳定 job_id 移出任务；position 仅用于兼容旧前端定位。"""
    req = req or {}
    job_id = str(req.get("job_id") or "")
    position = req.get("position")
    if not job_id:
        if position is None:
            raise HTTPException(status_code=400, detail="缺少 job_id 或 position 参数")
        try:
            position = int(position)
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail="position 必须是整数")
        try:
            status_proc, status_ack = _run_queue_cli("status")
        except subprocess.TimeoutExpired:
            raise HTTPException(status_code=503, detail="队列状态查询超时")
        if status_proc.returncode != 0 or not status_ack.get("ok"):
            code = 409 if status_ack.get("status") == "lock_busy" else 503
            raise HTTPException(status_code=code, detail=status_ack)
        queue = status_ack.get("queue") or []
        if not (1 <= position <= len(queue)):
            return {
                "ok": False,
                "status": "invalid_position",
                "position": position,
                "length": len(queue),
            }
        job_id = str(queue[position - 1].get("job_id") or "")
        if not job_id:
            raise HTTPException(status_code=500, detail="队列项缺少 job_id")

    try:
        remove_proc, payload = _run_queue_cli("remove", "--job-id", job_id)
        status = payload.get("status")
        if status == "lock_busy":
            raise HTTPException(status_code=409, detail="队列正忙（锁被占用），请稍后重试")
        if remove_proc.returncode != 0 or not payload.get("ok"):
            if status == "active_job":
                code = 409
            elif status == "not_found":
                code = 404
            else:
                code = 500
            raise HTTPException(status_code=code, detail=payload)
        if status == "removed":
            affected_card_id = str(payload.get("card_id") or "")
            if affected_card_id:
                restore_card_after_cancel(
                    affected_card_id,
                    reason="queue_removed",
                    fallback_status="draft",
                    expected_job_id=job_id,
                )
        return payload
    except subprocess.TimeoutExpired:
        raise HTTPException(status_code=503, detail="队列删除超时")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))



def cancel_current_render() -> Dict[str, Any]:
    """取消当前渲染：中断 ComfyUI + 终止 worker/draw/delivery + 清当前锁；不清空本地队列。"""
    import os
    import signal
    import subprocess
    import time as _time
    import requests

    work_dir = Path(TMP_DIR)
    runtime_file = work_dir / "cu-runtime.json"
    lock_file = work_dir / "cu-gpu.lock"
    cancelled_pid = None
    killed = []
    errors = []
    interrupted = False
    stopped_comfyui = False
    runtime_info: Dict[str, Any] = {}
    queue_ack: Dict[str, Any] = {}

    def add_pid(pids: list[int], pid: int):
        if pid > 0 and pid != os.getpid() and pid not in pids:
            pids.append(pid)

    def alive(pid: int) -> bool:
        try:
            os.kill(pid, 0)
            return True
        except OSError:
            return False

    def command_for(pid: int) -> str:
        try:
            return subprocess.check_output(["ps", "-p", str(pid), "-o", "command="], text=True, timeout=2).strip()
        except Exception:
            return ""

    # 1) 先通知 ComfyUI 中断当前 prompt；只 kill watcher 不足以停止 GPU 采样。
    host = load_system_config().get("comfyui_host", "http://127.0.0.1:8188")
    try:
        r = requests.post(f"{host}/interrupt", timeout=3)
        interrupted = r.status_code < 400
    except Exception as ex:
        errors.append(f"interrupt_failed: {ex}")

    pids: list[int] = []

    # 2) runtime pid：现在应是 detached worker 本体 pid，用于精准杀进程组。
    if runtime_file.exists():
        try:
            runtime_info = json.loads(runtime_file.read_text(encoding="utf-8"))
            pid = int(runtime_info.get("pid") or 0)
            if pid > 0:
                add_pid(pids, pid)
                cancelled_pid = pid
        except Exception as ex:
            errors.append(f"runtime_read_failed: {ex}")

    # 3) pid 文件兜底：与 /draw_terminate 同源，避免 runtime 丢失。
    for pid_file in sorted(work_dir.glob("cu-submit-bg_*.pid"), key=lambda p: p.stat().st_mtime, reverse=True):
        try:
            raw = pid_file.read_text(encoding="utf-8").strip()
            if raw.isdigit():
                pid = int(raw)
                cmd = command_for(pid)
                if alive(pid) and ("cu-worker.sh" in cmd or "cu-draw-card.py" in cmd):
                    add_pid(pids, pid)
        except Exception:
            pass

    # 4) 进程扫描兜底：必须包含 cu-deliver.sh，防止图片已出但交付仍继续。
    try:
        out = subprocess.check_output(["pgrep", "-f", "cu-worker\\.sh|cu-draw-card\\.py|cu-deliver\\.sh"], text=True, timeout=5).strip()
        for raw in out.splitlines():
            raw = raw.strip()
            if raw.isdigit():
                add_pid(pids, int(raw))
    except Exception:
        pass

    for pid in pids:
        try:
            pgid = os.getpgid(pid)
            os.killpg(pgid, signal.SIGTERM)
            killed.append({"pid": pid, "pgid": pgid, "signal": "TERM"})
        except ProcessLookupError:
            killed.append({"pid": pid, "signal": "missing"})
        except Exception as ex:
            errors.append(f"killpg_term_failed:{pid}:{ex}")
            try:
                os.kill(pid, signal.SIGTERM)
                killed.append({"pid": pid, "signal": "TERM"})
            except Exception as ex2:
                errors.append(f"kill_term_failed:{pid}:{ex2}")

    _time.sleep(1.0)
    survivors = [pid for pid in pids if alive(pid)]
    for pid in survivors:
        try:
            os.killpg(os.getpgid(pid), signal.SIGKILL)
            killed.append({"pid": pid, "signal": "KILL"})
        except Exception:
            try:
                os.kill(pid, signal.SIGKILL)
                killed.append({"pid": pid, "signal": "KILL"})
            except Exception as ex:
                errors.append(f"kill_force_failed:{pid}:{ex}")

    _time.sleep(0.8)
    still_alive = [pid for pid in pids if alive(pid)]

    # 5) 如果进程还在或 ComfyUI 仍在执行，兜底停止 ComfyUI；这不清本地队列，只取消当前 GPU 后端。
    should_stop_comfyui = bool(still_alive)
    try:
        q = requests.get(f"{host}/queue", timeout=3).json()
        running = q.get("queue_running") or []
        if running:
            should_stop_comfyui = True
    except Exception:
        pass

    if should_stop_comfyui:
        try:
            subprocess.run(["bash", str(_gpu_pipeline_script("comfyui-start.sh")), "stop"], capture_output=True, text=True, timeout=30)
            stopped_comfyui = True
        except Exception as ex:
            errors.append(f"comfyui_stop_failed: {ex}")

    # 6) 以 runtime 中的稳定 job_id + lease token 条件 nack。
    job_id = str(runtime_info.get("job_id") or "")
    lease_token = str(runtime_info.get("lease_token") or "")
    card_id = str(runtime_info.get("card_id") or "")
    if job_id and lease_token:
        try:
            queue_proc, queue_ack = _run_queue_cli(
                "nack",
                "--job-id",
                job_id,
                "--lease-token",
                lease_token,
                "--error",
                "cancelled_by_webui",
                "--no-retry",
            )
            if queue_proc.returncode != 0 or not queue_ack.get("ok"):
                if queue_ack.get("status") == "lease_mismatch":
                    get_proc, get_ack = _run_queue_cli("get", "--job-id", job_id)
                    current_state = ((get_ack.get("job") or {}).get("state"))
                    if get_proc.returncode == 0 and current_state == "failed":
                        queue_ack = {
                            "ok": True,
                            "status": "already_failed",
                            "job_id": job_id,
                            "state": "failed",
                        }
                    else:
                        errors.append(f"queue_nack_failed:{queue_ack}")
                else:
                    errors.append(f"queue_nack_failed:{queue_ack}")
            nack_won = bool(
                queue_ack.get("ok")
                and queue_ack.get("status") == "failed"
                and not still_alive
            )
            if nack_won:
                restore_card_after_cancel(
                    card_id,
                    reason="active_render_cancelled",
                    fallback_status="failed",
                    expected_job_id=job_id,
                )
            elif queue_ack.get("ok"):
                errors.append(
                    f"status_restore_skipped: cancellation did not win ({queue_ack.get('status')})"
                )
        except Exception as ex:
            errors.append(f"queue_nack_failed:{ex}")
    elif cancelled_pid or pids:
        errors.append("queue_nack_skipped: runtime missing job_id/lease_token")

    # 7) 清理当前运行态；不清空 QueueStore。
    for path in (lock_file, runtime_file):
        try:
            path.unlink(missing_ok=True)
        except Exception as ex:
            errors.append(f"unlink_failed:{path}:{ex}")

    had_local_active = bool(cancelled_pid or pids or lock_file.exists() or runtime_file.exists())
    if interrupted or killed or stopped_comfyui:
        status = "cancelled"
    elif not had_local_active:
        status = "no_active_task"
    elif errors:
        status = "cancel_failed"
    else:
        status = "no_active_task"

    return {
        "status": status,
        "pid": cancelled_pid,
        "interrupted": interrupted,
        "stopped_comfyui": stopped_comfyui,
        "killed": killed,
        "still_alive": still_alive,
        "job_id": job_id,
        "queue_ack": queue_ack,
        "errors": errors,
    }

@router.post("/api/queue/cancel")
def cancel_queue_task():
    """取消当前运行的任务"""
    return cancel_current_render()

@router.post("/api/queue/clear")
def clear_queue_api():
    """通过 QueueStore 清空等待任务，并只同步受影响卡片。"""
    try:
        proc, payload = _run_queue_cli("clear", "--force")
    except subprocess.TimeoutExpired:
        raise HTTPException(status_code=503, detail="队列清空超时")
    if payload.get("status") == "lock_busy":
        raise HTTPException(status_code=409, detail="队列正忙（锁被占用），请稍后重试")
    if proc.returncode != 0 or not payload.get("ok"):
        raise HTTPException(status_code=500, detail=payload)
    job_ids = list(payload.get("job_ids") or [])
    seen_pairs = set()
    for index, card_id in enumerate(payload.get("card_ids") or []):
        expected_job_id = str(job_ids[index] if index < len(job_ids) else "")
        pair = (str(card_id or ""), expected_job_id)
        if not pair[0] or pair in seen_pairs:
            continue
        seen_pairs.add(pair)
        restore_card_after_cancel(
            pair[0],
            reason="queue_cleared",
            fallback_status="draft",
            expected_job_id=expected_job_id or None,
        )
    return payload

@router.delete("/api/queue/items/{position}")
def remove_queue_item_by_position(position: int):
    """兼容旧 position 路由，内部先解析稳定 job_id 再删除。"""
    return remove_queue_item({"position": position})


@router.delete("/api/queue/jobs/{job_id}")
def remove_queue_job(job_id: str):
    """稳定删除入口：WebUI 新调用方只传 QueueStore job_id。"""
    return remove_queue_item({"job_id": job_id})


@router.post("/api/queue/terminate")
def terminate_queue_api():
    """停当前任务并退出 ComfyUI。队列和卡文件保留，只清草稿。与 /draw_terminate 相同。"""
    import subprocess
    cmd = [sys.executable, str(_gpu_pipeline_script("cu-control.py")), "terminate"]
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=40)
        if res.returncode != 0:
            raise HTTPException(
                status_code=500,
                detail=res.stderr.strip() or res.stdout.strip() or "终止任务失败",
            )
        return {
            "status": "terminated",
            "stdout": res.stdout,
            "stderr": res.stderr,
            "returncode": res.returncode
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/api/queue/logs")
def get_logs(lines: int = 80):
    """获取本地引擎日志（与 cu-draw-card.py 同文件：tmp_dir/cu-draw-card.log）"""
    cfg = load_system_config()
    tmp_dir = Path(os.path.expanduser(cfg.get("tmp_dir") or "/tmp/cu-card")).resolve()
    log_path = tmp_dir / "cu-draw-card.log"
    if not log_path.exists():
        return {"logs": "Log file not found."}
    
    try:
        from collections import deque
        with open(log_path, "r", encoding="utf-8", errors="ignore") as f:
            log_lines = list(deque(f, maxlen=lines))
        return {"logs": "".join(log_lines)}
    except Exception as e:
        return {"logs": f"Error reading logs: {e}"}

_MODELS_CACHE = {
    "scanned": True,
    "openclaw_models": [],
    "cliproxy_models": [],
}

def _resolve_bin_path(name: str) -> str:
    """Backward-compatible wrapper around agent_install_paths.resolve_bin_path."""
    from agent_install_paths import resolve_bin_path
    return resolve_bin_path(name)

@router.get("/api/config/models")
def list_available_models():
    """从 llm.base_url 拉取可用文本模型。"""
    cfg = load_system_config()
    try:
        from card_llm_client import list_models, resolve_llm_config
        models = list_models(cfg)
        llm = resolve_llm_config(cfg)
        return {
            "scanned": True,
            "models": models,
            "openclaw_models": models,
            "cliproxy_models": models,
            "base_url": llm.get("base_url"),
        }
    except Exception as exc:
        print(f"⚠️ LLM 模型目录获取失败: {exc}", flush=True)
        return {
            "scanned": True,
            "models": [],
            "openclaw_models": [],
            "cliproxy_models": [],
            "error": str(exc),
        }

@router.get("/api/docs/{doc_name}")
def get_doc(doc_name: str):
    """读取并返回 markdown 格式的帮助文档"""
    # 文档映射防路径穿透
    # 对外三件套：操作指南(人) / SKILL(AI) / README(安装)
    # 其余工程文档仍在 doc/，不默认挂 WebUI
    skill_root = SCRIPT_DIR.parent.parent
    webui_doc_dir = skill_root / "doc" / "webui"

    allowed_docs = {
        "user_guide": webui_doc_dir / "USER_GUIDE.md",
        "dependencies": webui_doc_dir / "DEPENDENCIES_GUIDE.md",
        "skill": skill_root / "SKILL.md",
        "config": webui_doc_dir / "CONFIG_GUIDE.md",
        "sponsor": webui_doc_dir / "COMMUNITY_SPONSOR.md",
        "commands": webui_doc_dir / "CARD_ENGINE_COMMANDS.md",
    }
    
    doc_path = allowed_docs.get(doc_name)
    if not doc_path or not doc_path.exists():
        raise HTTPException(status_code=404, detail="Doc not found")
        
    try:
        return {"content": doc_path.read_text(encoding="utf-8")}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))



@router.post("/api/workflow/convert")
def convert_workflow_api(req: Dict[str, Any]):
    """ComfyUI UI-JSON → API-JSON. Surfaces warnings; detects already-API payloads."""
    ui_json = req.get("json_data")
    if not ui_json:
        raise HTTPException(status_code=400, detail="Missing json_data")

    if _is_api_workflow(ui_json):
        return {
            "status": "ok",
            "api_workflow": ui_json,
            "warnings": ["input already API-format; returned as pass-through"],
            "already_api": True,
        }

    config = load_system_config()
    host = config.get("comfyui_host", "http://127.0.0.1:8188")

    import requests

    try:
        object_info = requests.get(f"{host}/object_info", timeout=15).json()
    except Exception:
        raise HTTPException(
            status_code=500,
            detail=(
                f"无法连接 ComfyUI 服务 ({host})，转换功能需要 ComfyUI 处于启动运行状态，"
                "请先在 Settings 中确认并开启 ComfyUI 后端！"
            ),
        )

    try:
        api_json, warnings = perform_workflow_conversion(ui_json, object_info)
    except Exception as err:
        raise HTTPException(status_code=500, detail=f"工作流转换失败: {str(err)}")

    status = "ok" if not warnings else "ok_with_warnings"
    return {
        "status": status,
        "api_workflow": api_json,
        "warnings": warnings,
        "already_api": False,
        "node_count": len(api_json),
        "warning_count": len(warnings),
    }

