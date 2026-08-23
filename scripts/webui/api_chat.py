#!/usr/bin/env python3
"""Chat sessions, numeric quick commands, and POST /api/chat SSE routes."""

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
import asyncio
import base64
import contextlib
import io
import json
import os
import re
import time
import uuid
from pathlib import Path
from card_config import TMP_DIR, CARDS_DIR
from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from web_server import (
    CARDS_DIR,
    CHAT_HISTORY_DIR,
    SCRIPT_DIR,
    append_chat_history,
    append_chat_history_once,
    chat_history_file,
    clear_chat_history,
    extract_session_timestamp,
    get_cached_session_title,
    get_chat_history_dir,
    load_system_config,
    safe_chat_id,
    webui_session_file,
    webui_session_id,
)

from card_cli_commands import cmd_create, cmd_options
from card_io import InvalidCardIdError, card_path, validate_card_id
import web_server as _web_server  # stream_agent_chat monkeypatch target
from agent_bridge import (
    abort_openclaw_operation,
    cancel_openclaw_operation,
    delete_openclaw_session,
)
from operation_registry import (
    OperationConflictError,
    OperationNotFoundError,
    SessionTombstonedError,
    TERMINAL_STATES,
    operation_registry,
)
from prompt_rules import (
    get_chat_rules,
    should_inject_full_rules,
    mark_rule_injected,
    reset_rule_session,
    clean_user_message,
    normalize_chat_mode,
    is_draw_mode,
)

router = APIRouter(tags=["chat"])


_ACTIVE_QUEUE_STATUSES = frozenset({"submitted", "queued", "rendering"})


def _card_queue_job_id(card: Dict[str, Any]) -> str:
    render = card.get("render")
    if not isinstance(render, dict):
        return ""
    return str(render.get("queue_job_id") or "").strip()


def _infer_card_action(
    card_before: Dict[str, Any],
    card_after: Dict[str, Any],
) -> tuple[str, bool]:
    """Infer only confirmed end-state changes; this is not a real-time event feed."""
    status_before = str(card_before.get("status") or "").strip().lower()
    status_after = str(card_after.get("status") or "").strip().lower()
    job_before = _card_queue_job_id(card_before)
    job_after = _card_queue_job_id(card_after)

    newly_queued = status_after in _ACTIVE_QUEUE_STATUSES and (
        status_before not in _ACTIVE_QUEUE_STATUSES
        or bool(job_after and job_after != job_before)
    )
    if newly_queued:
        return "submit", True

    content_changed = (
        card_before.get("slots") != card_after.get("slots")
        or card_before.get("director") != card_after.get("director")
        or card_before.get("narrative_zh") != card_after.get("narrative_zh")
    )
    if content_changed:
        return "patch", True

    state_changed = (
        status_before != status_after
        or card_before.get("version") != card_after.get("version")
        or card_before.get("render_image") != card_after.get("render_image")
    )
    return ("status", True) if state_changed else ("none", False)


def run_core_cmd(*args, **kwargs):
    """Delegate so tests can patch web_server.run_core_cmd."""
    import web_server as _ws
    return _ws.run_core_cmd(*args, **kwargs)



@router.get("/api/chat/sessions")
def get_chat_sessions():
    config = load_system_config()
    backend = (config.get("agent_backend", "openclaw") or "openclaw").lower()
    
    sessions = []
    
    if backend == "openclaw":
        # 唯一数据源：对话历史目录。抽卡会话一律是 uuid 命名，
        # 卡片模式（以 card_id 或 webui-draw-card- 命名）与 home/direct 等杂项天然被过滤掉。
        directory = CHAT_HISTORY_DIR
        if directory.exists():
            for p in directory.glob("*.jsonl"):
                session_id = p.stem
                import re as _re
                if not _re.match(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$", session_id):
                    continue
                if session_id.startswith("cron_"):
                    continue
                # 历史文件每轮追加，mtime 就是真正的最后活跃时间
                mtime = extract_session_timestamp(session_id, p.stat().st_mtime)
                title = get_cached_session_title(p)
                if not title:
                    title = f"OpenClaw会话 {session_id[:8]}"
                if "cron" in session_id.lower() or "cron" in title.lower():
                    continue
                if title.startswith("[IMPORTANT:") or "You are running as" in title:
                    continue
                sessions.append({
                    "session_id": session_id,
                    "title": title,
                    "updated_at": mtime
                })
                



    sessions.sort(key=lambda x: x["updated_at"], reverse=True)
    return {"sessions": sessions, "total": len(sessions)}


@router.get("/api/chat/history")
def get_chat_history(card_id: Optional[str] = None, session_id: Optional[str] = None, chat_mode: Optional[str] = None):
    config = load_system_config()
    chat_mode = normalize_chat_mode(chat_mode or config.get("chat_mode"), "cards")
    
    hist_key = session_id if is_draw_mode(chat_mode) else card_id
    if not hist_key:
        hist_key = card_id or session_id or "home"
        
    items = []
    path = chat_history_file(hist_key)
    if path.exists():
        try:
            for line in path.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    items.append(json.loads(line))
        except Exception as e:
            print(f"Error loading chat history from {path}: {e}")
            
    active_session_id = session_id or (webui_session_id(card_id) if card_id else None)
    return {"card_id": card_id, "session_id": active_session_id, "messages": items[-200:]}


@router.post("/api/chat/new")
def new_chat_window(req: Dict[str, Any]):
    card_id = req.get("card_id")
    session_id = req.get("session_id")
    chat_mode = normalize_chat_mode(req.get("chat_mode") or load_system_config().get("chat_mode"), "cards")
    
    if is_draw_mode(chat_mode):
        if not session_id:
            active_session_id = str(uuid.uuid4())
        else:
            active_session_id = session_id
        try:
            with operation_registry.session_mutation_guard(
                active_session_id
            ):
                # 建一个空历史文件，让尚未发言的新会话也能出现在列表里
                path = chat_history_file(active_session_id)
                path.parent.mkdir(parents=True, exist_ok=True)
                path.touch(exist_ok=True)
                reset_rule_session(active_session_id)
        except SessionTombstonedError as exc:
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "session_tombstoned",
                    "message": str(exc),
                },
            )
            
        return {"status": "ok", "session_id": active_session_id}
        
    clear_chat_history(card_id)
    reset_rule_session(webui_session_id(card_id))
    session_file = webui_session_file(webui_session_id(card_id))
    try:
        session_file.parent.mkdir(parents=True, exist_ok=True)
        session_file.write_text("", encoding="utf-8")
    except Exception:
        pass
    return {"status": "ok", "session_id": webui_session_id(card_id)}



@router.delete("/api/chat/sessions/{session_id}")
async def delete_chat_session(session_id: str, cancel_active: bool = False):
    config = load_system_config()
    backend = (config.get("agent_backend", "openclaw") or "openclaw").lower()

    active, _ = operation_registry.prepare_session_delete(
        session_id,
        force=cancel_active,
    )
    if active and not cancel_active:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "session_active",
                "message": "会话仍有活动操作；请明确 cancel_active=true 后再删除。",
                "active_operation_ids": [op.operation_id for op in active],
            },
        )

    # The registry checked active work and applied this tombstone under one
    # lock, so no enqueue can slip between the two steps.
    cancel_results = []
    if active:
        for operation in active:
            result = await operation_registry.cancel(operation.operation_id)
            cancel_results.append(result)
        unsafe = [
            result
            for result in cancel_results
            if not result.get("cancelled")
            and result.get("status") != "already_terminal"
        ]
        if unsafe:
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "cancel_failed",
                    "message": "活动操作未确认取消；会话已 tombstone，但尚未删除。",
                    "results": unsafe,
                },
            )
        for operation in active:
            try:
                await operation_registry.wait_terminal(
                    operation.operation_id,
                    timeout=6.0,
                )
            except asyncio.TimeoutError:
                raise HTTPException(
                    status_code=409,
                    detail={
                        "code": "cancellation_pending",
                        "message": "取消已受理但操作尚未结束，请稍后重试删除。",
                        "active_operation_ids": [
                            op.operation_id
                            for op in operation_registry.active_for_session(session_id)
                        ],
                    },
                )

    gateway_delete = None
    if backend == "openclaw":
        gateway_delete = await delete_openclaw_session(session_id)
        if gateway_delete.get("status") != "deleted":
            raise HTTPException(
                status_code=502,
                detail={
                    "code": "gateway_session_delete_failed",
                    "message": "OpenClaw sessions.delete 未确认，保留本地历史。",
                    "gateway": gateway_delete,
                },
            )

    deleted_files = []
    path = chat_history_file(session_id)
    existed = path.exists()
    clear_chat_history(session_id)
    if existed:
        deleted_files.append(str(path))

    if backend == "openclaw":
        reset_rule_session(session_id)

    return {
        "status": "ok",
        "deleted": deleted_files,
        "tombstoned": True,
        "cancel_results": cancel_results,
        "gateway": gateway_delete,
    }


def delete_message_from_history(hist_key: str, index: int) -> bool:
    path = chat_history_file(hist_key)
    if not path.exists():
        return False
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
        valid_lines = [l for l in lines if l.strip()]
        if 0 <= index < len(valid_lines):
            valid_lines.pop(index)
            path.write_text("\n".join(valid_lines) + ("\n" if valid_lines else ""), encoding="utf-8")
            return True
    except Exception as e:
        print(f"Error deleting message at index {index} from {path}: {e}")
    return False

@router.post("/api/chat/delete_message")
def delete_chat_message(req: Dict[str, Any]):
    card_id = req.get("card_id")
    session_id = req.get("session_id")
    index = req.get("index")
    
    if index is None:
        raise HTTPException(status_code=400, detail="Missing message index")
        
    try:
        index = int(index)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid message index format")
        
    config = load_system_config()
    chat_mode = normalize_chat_mode(req.get("chat_mode") or config.get("chat_mode"), "cards")
    backend = (config.get("agent_backend", "openclaw") or "openclaw").lower()
    
    hist_key = session_id if is_draw_mode(chat_mode) else card_id
    if not hist_key:
        hist_key = card_id or session_id or "home"
        
    deleted = delete_message_from_history(hist_key, index)
    return {"status": "ok", "deleted": deleted}



def cancel_render_reply() -> Dict[str, Any]:
    """队列取消：供自然语言「取消渲染」走同一套锁清理逻辑。"""
    from api_queue import cancel_current_render
    result = cancel_current_render()
    status = result.get("status")
    if status == "cancelled":
        return {"reply": "🛑 已发送取消：ComfyUI 已中断，worker/锁已清理。", "action": "cancel", "refresh": True}
    if status == "no_active_task":
        return {"reply": "ℹ️ 当前没有检测到正在渲染的任务。", "action": "none", "refresh": True}
    return {
        "reply": f"⚠️ 取消可能未完全成功：`{status}`\n```json\n{json.dumps(result, ensure_ascii=False, indent=2)}\n```",
        "action": "none",
        "refresh": True,
    }



def base64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode('utf-8').rstrip('=')

def get_gateway_info():
    config_path = Path.home() / ".openclaw" / "openclaw.json"
    if not config_path.exists():
        return 18789, ""
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            config = json.load(f)
        gateway = config.get("gateway", {})
        port = gateway.get("port", 18789)
        token = gateway.get("auth", {}).get("token", "")
        return port, token
    except Exception:
        return 18789, ""

def get_device_info():
    device_path = Path.home() / ".openclaw" / "identity" / "device.json"
    if not device_path.exists():
        return None
    try:
        with open(device_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

@contextlib.contextmanager
def clear_env_proxies():
    proxies = ["http_proxy", "https_proxy", "all_proxy", "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY"]
    saved = {p: os.environ[p] for p in proxies if p in os.environ}
    for p in saved:
        del os.environ[p]
    try:
        yield
    finally:
        for p, v in saved.items():
            os.environ[p] = v

CHAT_MAP_PATH = Path(str(TMP_DIR) + "/webui-chat/chat_map.json")

def resolve_card_id_by_chat_id(chat_id: str) -> str:
    """根据 Open WebUI 的 chat_id 寻找或自动生成本地卡片 ID"""
    CHAT_MAP_PATH.parent.mkdir(parents=True, exist_ok=True)
    mapping = {}
    if CHAT_MAP_PATH.exists():
        try:
            mapping = json.loads(CHAT_MAP_PATH.read_text(encoding="utf-8"))
        except:
            pass
            
    if chat_id in mapping:
        card_id = mapping[chat_id]
        try:
            if card_path(card_id).exists():
                return validate_card_id(card_id)
        except InvalidCardIdError:
            mapping.pop(chat_id, None)

    # 自动新建空白卡片
    from card_cli_commands import cmd_create, cmd_options
    import argparse
    import io
    import contextlib
    import re
    
    create_args = argparse.Namespace(
        mode="amateur",
        scene="general_scenes",
        person="写真模特",
        freedom="guided",
        workflow=None,
        size=None,
        aspect="portrait",
        seed=None,
        profile="default"
    )
    
    res = run_core_cmd(cmd_create, create_args)
    new_card_id = res.get("return_value")
    if not new_card_id:
        match = re.search(r"card_id=([0-9a-zA-Z_]+)", res["stdout"])
        new_card_id = match.group(1) if match else None
        
    if new_card_id:
        # 立即写入 option_map 动态映射以备微调
        try:
            cmd_options(argparse.Namespace(card=new_card_id, auto=True, file=None, json=None))
        except:
            pass
            
        # 强制重置新会话的规则注入状态，确保首轮加载完整规则大包
        try:
            reset_rule_session(webui_session_id(new_card_id))
        except:
            pass
            
        mapping[chat_id] = new_card_id
        CHAT_MAP_PATH.write_text(json.dumps(mapping, ensure_ascii=False, indent=2), encoding="utf-8")
        return new_card_id
        
    raise HTTPException(status_code=500, detail="Failed to auto-create card skeleton for chat")


@router.get("/api/chat/operations")
def get_chat_operations_for_session(session_id: str):
    """Return durable operation states for one session only."""
    return {
        "session_id": session_id,
        "operations": operation_registry.snapshots_for_session(session_id),
    }


@router.get("/api/chat/operations/{operation_id}")
def get_chat_operation_status(operation_id: str):
    try:
        return operation_registry.snapshot(operation_id)
    except OperationNotFoundError:
        raise HTTPException(status_code=404, detail="operation not found")


@router.post("/api/chat/operations/{operation_id}/cancel")
async def cancel_chat_operation(operation_id: str):
    try:
        operation = operation_registry.get(operation_id)
        if operation.is_recovered_unknown and operation.cancel_handler is None:
            if not operation.dispatch_started:
                async def cancel_undispatched_recovered_operation():
                    return {
                        "status": "cancelled",
                        "cancelled": True,
                        "operation_id": operation_id,
                    }

                operation_registry.set_cancel_handler(
                    operation_id,
                    cancel_undispatched_recovered_operation,
                )
            elif operation.transport == "gateway":
                async def abort_recovered_gateway_operation():
                    return await abort_openclaw_operation(
                        operation_id,
                        operation.request.session_id,
                    )

                operation_registry.set_cancel_handler(
                    operation_id,
                    abort_recovered_gateway_operation,
                )
            # Recovered CLI operations intentionally keep no handler: a PID from
            # a previous process lifetime is not a safe cancellation identity.
        result = await operation_registry.cancel(operation_id)
    except OperationNotFoundError:
        raise HTTPException(status_code=404, detail="operation not found")

    if not result.get("cancelled") and result.get("status") != "already_terminal":
        raise HTTPException(
            status_code=409,
            detail={
                "code": "cancel_not_confirmed",
                "message": "后端未确认精确取消；SSE 保持连接，操作继续。",
                "result": result,
            },
        )
    return {
        **result,
        "operation": operation_registry.snapshot(operation_id),
    }



@router.post("/api/chat")
async def chat_api(req: Dict[str, Any]):
    # Freeze every execution-relevant field before the request can enter a
    # queue.  The rest of this function only reads this canonical snapshot.
    incoming = dict(req)
    message = str(incoming.get("message") or "").strip()
    card_id = req.get("card_id")
    chat_id = req.get("chat_id")

    if chat_id and not card_id:
        card_id = resolve_card_id_by_chat_id(chat_id)
    if card_id is not None:
        try:
            card_id = validate_card_id(card_id)
        except InvalidCardIdError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    if not message:
        raise HTTPException(status_code=400, detail="Message is empty")

    config = load_system_config()
    backend = (config.get("agent_backend", "openclaw") or "openclaw").lower()
    chat_mode = normalize_chat_mode(
        incoming.get("chat_mode") or config.get("chat_mode"),
        "cards",
    )
    operation_id = str(incoming.get("operation_id") or uuid.uuid4())
    session_id = incoming.get("session_id")
    generated_session = False
    if not session_id and is_draw_mode(chat_mode):
        session_id = str(
            uuid.uuid5(
                uuid.NAMESPACE_URL,
                f"amazing-draw:webui-operation:{operation_id}",
            )
        )
        generated_session = True
    elif not session_id:
        session_id = webui_session_id(card_id)

    include_context = (
        incoming.get("include_context") is True
        or incoming.get("include_card_context") is True
    )
    frozen_request = {
        "operation_id": operation_id,
        "session_id": session_id,
        "chat_mode": chat_mode,
        "card_id": card_id,
        "message": message,
        "include_context": include_context,
        "confirm": incoming.get("confirm") is True,
        "backend": backend,
    }
    try:
        operation = operation_registry.create(frozen_request)
    except SessionTombstonedError as exc:
        raise HTTPException(
            status_code=409,
            detail={"code": "session_tombstoned", "message": str(exc)},
        )
    except OperationConflictError as exc:
        raise HTTPException(
            status_code=409,
            detail={"code": "operation_id_conflict", "message": str(exc)},
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    # From here on every execution path reads only the registry-owned immutable
    # snapshot, including idempotent retries that attach to an existing task.
    operation_id = operation.request.operation_id
    session_id = operation.request.session_id
    chat_mode = operation.request.chat_mode
    card_id = operation.request.card_id
    message = operation.request.message
    include_context = operation.request.include_context
    backend = operation.request.backend
    frozen_request = {
        "operation_id": operation_id,
        "session_id": session_id,
        "chat_mode": chat_mode,
        "card_id": card_id,
        "message": message,
        "include_context": include_context,
        "confirm": operation.request.confirm,
        "backend": backend,
    }

    if generated_session:
        try:
            with operation_registry.session_mutation_guard(
                operation.request.session_id
            ):
                path = chat_history_file(operation.request.session_id)
                path.parent.mkdir(parents=True, exist_ok=True)
                path.touch(exist_ok=True)
        except SessionTombstonedError as exc:
            await operation_registry.cancel(operation_id)
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "session_tombstoned",
                    "message": str(exc),
                },
            )

    # Canonical compatibility view for the legacy execution body below.
    req = {
        **frozen_request,
        "include_card_context": include_context,
    }

    async def _with_heartbeat(agen, interval: float = 12.0):
        """在异步生成器静默期间产出心跳信号。

        Agent 思考/跑工具时可能连续数分钟不吐字节，SSE 连接全程零数据，
        浏览器与中间层会判定连接失效并抛 network error。定期发一帧 SSE 注释即可保活。
        产出形如 ("item", chunk) / ("beat", None)。
        """
        queue: asyncio.Queue = asyncio.Queue()

        async def pump():
            try:
                async for item in agen:
                    await queue.put(("item", item))
            except BaseException as exc:  # 交回主协程抛出，保持原有降级语义
                await queue.put(("error", exc))
            else:
                await queue.put(("done", None))

        task = asyncio.create_task(pump())
        try:
            while True:
                try:
                    kind, payload = await asyncio.wait_for(queue.get(), timeout=interval)
                except asyncio.TimeoutError:
                    yield ("beat", None)
                    continue
                if kind == "item":
                    yield ("item", payload)
                elif kind == "error":
                    raise payload
                else:
                    return
        finally:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await task

    async def event_generator():
        ns_ctx = None
        try:
            # 1. 指令分流：自然语言取消渲染（斜杠命令已移除，取消请用队列停止按钮）
            if message in {"取消", "取消渲染", "停止渲染", "停止当前渲染", "cancel", "stop render"}:
                res = cancel_render_reply()
                yield f"data: {json.dumps({'type': 'text', 'chunk': res.get('reply', '')}, ensure_ascii=False)}\n\n"
                yield f"data: {json.dumps({'type': 'meta', 'action': res.get('action', 'none'), 'card_id': card_id, 'refresh': res.get('refresh', False)}, ensure_ascii=False)}\n\n"
                return

            if message.startswith("/"):
                res = {
                    "reply": "ℹ️ WebUI 已不再支持斜杠命令。取消渲染请用队列停止按钮；清空对话请用界面重置；建卡/提交请用工作台按钮或自然语言。",
                    "action": "none",
                    "refresh": False,
                }
                yield f"data: {json.dumps({'type': 'text', 'chunk': res.get('reply', '')}, ensure_ascii=False)}\n\n"
                yield f"data: {json.dumps({'type': 'meta', 'action': res.get('action', 'none'), 'card_id': card_id, 'refresh': False}, ensure_ascii=False)}\n\n"
                return
                
            # 2. 载入执行前的卡片状态以便比对
            card_before = None
            if card_id:
                source_card_path = card_path(card_id)
                if source_card_path.exists():
                    try:
                        card_before = json.loads(source_card_path.read_text(encoding="utf-8"))
                    except:
                        pass

            # 3. 构造卡片上下文（仅交接首条 / include_card_context 时注入）
            # 包装说明：上下文仅供参考，用户原文才是本轮意图；禁止闲聊时自动走 present/流水线
            card_context = ""
            include_card_context = req.get("include_card_context") is True
            if card_id and card_before and include_card_context:
                director = card_before.get('director', {})
                slots = card_before.get('slots', {})
                narrative = card_before.get('director', {}).get('story_elevation_zh', '') or card_before.get('narrative_zh', '') or ''
                ai_notes = (card_before.get('creative', {}) or {}).get('ai_notes', '')
                # 交接首条用精简摘要，避免整卡 JSON 淹没用户意图（如「你好」）
                slim_director = {}
                if isinstance(director, dict):
                    for k in (
                        "story_elevation_zh", "theme_zh", "intent",
                        "exposure_mode", "style_recipe_zh", "lighting_palette_zh",
                    ):
                        if director.get(k):
                            slim_director[k] = director.get(k)
                slim_slots = {}
                if isinstance(slots, dict):
                    for k, v in slots.items():
                        if not v:
                            continue
                        s = v if isinstance(v, str) else json.dumps(v, ensure_ascii=False)
                        slim_slots[k] = (s[:180] + "…") if len(s) > 180 else s
                ctx_data = {k: v for k, v in {
                    'director': slim_director or None,
                    'slots': slim_slots or None,
                    'narrative_zh': (narrative[:400] + "…") if isinstance(narrative, str) and len(narrative) > 400 else narrative,
                    'ai_notes': (ai_notes[:300] + "…") if isinstance(ai_notes, str) and len(ai_notes) > 300 else ai_notes,
                }.items() if v}
                card_context = (
                    f"[Card:{card_id} 背景参考] "
                    f"主体:{card_before.get('subject', {}).get('display_name', '')} "
                    f"场景:{card_before.get('scene', {}).get('name', '')} "
                    f"状态:{card_before.get('status', 'draft')}\n"
                    f"{json.dumps(ctx_data, ensure_ascii=False, separators=(',', ':'))}\n"
                    f"[用户原文]\n"
                )

            start_time = time.time()

            # 4. 构造及调用代理逻辑
            config = load_system_config()
            backend = operation.request.backend
            # 对话主模型：使用「AI 对话模型」llm_model
            # 独立调用（特征检索/合规判定）走 card_llm_client 的 independent_llm_model，勿混用
            model_id = config.get("llm_model") or config.get("independent_llm_model")
            chat_mode = operation.request.chat_mode
            session_id = operation.request.session_id

            async def on_transport_status(state: str, **metadata: Any):
                current = operation_registry.get(operation_id)
                if current.state in TERMINAL_STATES or current.state == "cancelling":
                    return
                operation_registry.transition(
                    operation_id,
                    state,
                    **metadata,
                )

            inject_full_rules = should_inject_full_rules(backend, session_id, chat_mode)
            if inject_full_rules:
                # 发出即登记。等这轮跑完再记的话，主人在长任务途中追发的消息
                # 会看到「尚未注入」，白吃一份完整规则。本轮无果时下面再回滚。
                mark_rule_injected(backend, session_id, chat_mode)

            # 组装最终发给 Agent 的 message：极简规则 + 可选卡片上下文 + 用户原文
            rules_text = get_chat_rules(chat_mode, inject_full_rules)
            full_message = (rules_text + "\n") if rules_text else ""
            if card_context:
                full_message += card_context + "\n"
            full_message += message

            reply_text = ""

            # 对话模型降级链：主模型故障时按 llm_fallback_models 依次降级重试
            # 与独立调用共用同一份备用配置；单模型 UI 下链长通常为 2
            _fb = config.get("llm_fallback_models") or []
            if isinstance(_fb, str):
                _fb = [_fb]
            model_chain = [m for m in [model_id, *_fb] if m]
            model_chain = list(dict.fromkeys(model_chain)) or [model_id]

            for chain_idx, chain_model in enumerate(model_chain):
                if chain_idx > 0:
                    notice = f"⚠️ 模型 {model_chain[chain_idx - 1]} 无响应，降级到 {chain_model} …\n\n"
                    reply_text += notice
                    yield f"data: {json.dumps({'type': 'text', 'chunk': notice}, ensure_ascii=False)}\n\n"
                yielded_text = False
                got_error_chunk = False
                attempt_failed = False
                try:
                    async for _kind, chunk_obj in _with_heartbeat(_web_server.stream_agent_chat(
                        backend=backend,
                        full_message=full_message,
                        session_id=session_id,
                        chat_mode=chat_mode,
                        model_id=chain_model,
                        card_id=card_id,
                        operation_id=operation_id,
                        on_status=on_transport_status,
                    )):
                        if _kind == "beat":
                            # SSE 注释帧：浏览器忽略内容，只用于维持连接
                            yield ": keepalive\n\n"
                            continue
                        chunk_type = chunk_obj.get("type")
                        if chunk_type == "text":
                            chunk_val = chunk_obj.get("chunk", "")
                            reply_text += chunk_val
                            yielded_text = True
                            yield f"data: {json.dumps({'type': 'text', 'chunk': chunk_val}, ensure_ascii=False)}\n\n"
                        elif chunk_type == "error":
                            got_error_chunk = True
                            error_val = chunk_obj.get("error", "")
                            reply_text += f"\n\n❌ 发生错误: {error_val}"
                            yield f"data: {json.dumps({'type': 'error', 'error': error_val}, ensure_ascii=False)}\n\n"
                        elif chunk_type == "cancelled":
                            reason = chunk_obj.get("reason") or "operation cancelled"
                            yield f"data: {json.dumps({'type': 'cancelled', 'reason': reason}, ensure_ascii=False)}\n\n"
                            return
                    # 只有任何传输都尚未发送时才允许换模型重试；ws_sent 后
                    # operation_id 虽稳定，也不能再进入新的执行分支。
                    current_state = operation_registry.get(operation_id).state
                    attempt_failed = (
                        got_error_chunk
                        and not yielded_text
                        and current_state == "starting"
                    )
                except Exception as stream_err:
                    if yielded_text:
                        # 正文已开流：降级重试会造成重复回复，直接终止
                        err_msg = f"调用后台 Agent 失败: {str(stream_err)}"
                        reply_text += f"\n\n❌ {err_msg}"
                        yield f"data: {json.dumps({'type': 'error', 'error': err_msg}, ensure_ascii=False)}\n\n"
                        attempt_failed = False
                    else:
                        attempt_failed = (
                            operation_registry.get(operation_id).state == "starting"
                        )
                        if not attempt_failed:
                            yield f"data: {json.dumps({'type': 'error', 'error': str(stream_err)}, ensure_ascii=False)}\n\n"
                if not attempt_failed or chain_idx >= len(model_chain) - 1:
                    break

            # 5. 比对执行前后的卡片状态，自动推导联动 action 与 card_id 变更
            ret_card_id = card_id
            newest_mtime = 0
            newest_id = None
            if CARDS_DIR.exists():
                for f in CARDS_DIR.glob("*.json"):
                    mtime = f.stat().st_mtime
                    if mtime > start_time - 2.0:
                        if mtime > newest_mtime:
                            newest_mtime = mtime
                            newest_id = f.stem

            action = "none"
            refresh = False

            if newest_id and newest_id != card_id:
                ret_card_id = newest_id
                action = "create"
                refresh = True
            else:
                card_after = None
                if ret_card_id:
                    card_path_after = card_path(ret_card_id)
                    if card_path_after.exists():
                        try:
                            card_after = json.loads(card_path_after.read_text(encoding="utf-8"))
                        except:
                            pass

                if card_before and card_after:
                    action, refresh = _infer_card_action(card_before, card_after)

            if inject_full_rules and not reply_text:
                # 这轮没出任何结果，规则等于没送达，撤销登记让下一轮重新注入
                reset_rule_session(session_id)

            meta = {
                "type": "meta",
                "operation_id": operation_id,
                "action": action,
                "card_id": ret_card_id,
                "refresh": refresh,
                "session_id": session_id
            }
            yield f"data: {json.dumps(meta, ensure_ascii=False)}\n\n"

        except Exception as err:
            yield f"data: {json.dumps({'type': 'error', 'error': f'❌ 对话发生异常: {str(err)}'}, ensure_ascii=False)}\n\n"
        except BaseException:
            raise

    def operation_history_key():
        return (
            operation.request.session_id
            if is_draw_mode(operation.request.chat_mode)
            else operation.request.card_id
            or operation.request.session_id
        )

    def persist_user_history():
        append_chat_history_once(
            operation_history_key(),
            operation_id,
            "user",
            operation.request.message,
            operation_state="queued",
        )

    def persist_terminal_history(terminal_state: str, terminal_error: Optional[str] = None):
        if not operation_registry.claim_history_persistence(operation_id):
            return
        try:
            current = operation_registry.get(operation_id)
            assistant_text = current.reply_text.strip()
            if terminal_state == "cancelled":
                cancel_tail = "⏹️ [操作已取消]"
                assistant_text = (
                    f"{assistant_text}\n\n{cancel_tail}"
                    if assistant_text
                    else cancel_tail
                )
            elif terminal_state == "failed" and not assistant_text:
                assistant_text = (
                    f"❌ [操作失败] {terminal_error or 'unknown error'}"
                )
            elif not assistant_text:
                assistant_text = "✅ 指令执行成功。"

            append_chat_history_once(
                operation_history_key(),
                operation_id,
                "assistant",
                assistant_text,
                operation_state=terminal_state,
            )
        except BaseException:
            operation_registry.finish_history_persistence(
                operation_id,
                succeeded=False,
            )
            raise
        else:
            operation_registry.finish_history_persistence(
                operation_id,
                succeeded=True,
            )

    async def run_operation():
        terminal_state = "completed"
        terminal_error = None
        saw_cancel_event = False
        try:
            persist_user_history()
            operation_registry.transition(operation_id, "starting")
            async for frame in event_generator():
                if not isinstance(frame, str) or not frame.startswith("data: "):
                    continue
                data_line = frame.splitlines()[0]
                payload = json.loads(data_line[6:])
                payload.setdefault("operation_id", operation_id)
                payload_type = payload.get("type")

                if payload_type == "text":
                    chunk = str(payload.get("chunk") or "")
                    current = operation_registry.get(operation_id)
                    if current.state in {"starting", "ws_sent", "accepted"}:
                        operation_registry.transition(
                            operation_id,
                            "streaming",
                            transport=current.transport,
                        )
                    operation_registry.append_reply(operation_id, chunk)
                elif payload_type == "error":
                    terminal_state = "failed"
                    terminal_error = str(payload.get("error") or "unknown error")
                    operation_registry.append_reply(
                        operation_id,
                        f"\n\n❌ 发生错误: {terminal_error}",
                    )
                elif payload_type == "cancelled":
                    terminal_state = "cancelled"
                    saw_cancel_event = True
                elif payload_type == "unknown_remote":
                    terminal_state = "unknown_remote"
                    terminal_error = str(
                        payload.get("error")
                        or "remote operation outcome is unknown"
                    )
                elif payload_type == "meta":
                    operation_registry.set_result_meta(operation_id, payload)

                operation_registry.publish(operation_id, payload)
                if saw_cancel_event or terminal_state == "unknown_remote":
                    break
        except asyncio.CancelledError:
            current = operation_registry.get(operation_id)
            if current.cancel_confirmed:
                terminal_state = "cancelled"
            else:
                terminal_state = "unknown_remote"
                terminal_error = "WebUI restarted while operation state was unresolved"
            if terminal_state == "cancelled" and not saw_cancel_event:
                operation_registry.publish(
                    operation_id,
                    {
                        "type": "cancelled",
                        "operation_id": operation_id,
                        "reason": "cancel confirmed",
                    },
                )
        except Exception as exc:
            terminal_state = "failed"
            terminal_error = str(exc)
            operation_registry.append_reply(
                operation_id,
                f"\n\n❌ 发生错误: {terminal_error}",
            )
            operation_registry.publish(
                operation_id,
                {
                    "type": "error",
                    "operation_id": operation_id,
                    "error": terminal_error,
                },
            )
        finally:
            if terminal_state in TERMINAL_STATES:
                try:
                    persist_terminal_history(terminal_state, terminal_error)
                except Exception as persist_error:
                    terminal_state = "failed"
                    terminal_error = f"history persistence failed: {persist_error}"

            current = operation_registry.get(operation_id)
            if not current.is_terminal:
                operation_registry.transition(
                    operation_id,
                    terminal_state,
                    transport=current.transport,
                    error=terminal_error,
                )

    async def cancel_handler():
        return await cancel_openclaw_operation(
            operation_id,
            operation.request.session_id,
        )

    # Idempotent retries attach to the existing event log.  Only the creator
    # whose operation still has no task may start execution.
    if operation.task is None and operation.state == "queued":
        operation_registry.set_cancel_handler(operation_id, cancel_handler)
        task = asyncio.create_task(
            run_operation(),
            name=f"webui-chat-{operation_id}",
        )
        operation_registry.attach_task(operation_id, task)
        # Let the task enter its guarded runner before exposing the operation;
        # this closes the tiny "cancel before finally exists" persistence race.
        await asyncio.sleep(0)

    async def subscriber():
        async for payload in operation_registry.subscribe(operation_id):
            if payload is None:
                yield ": keepalive\n\n"
            else:
                yield (
                    f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
                )

    return StreamingResponse(
        subscriber(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
            "X-Operation-ID": operation_id,
        }
    )

# 挂载前端静态文件目录
STATIC_DIR = SCRIPT_DIR / "static"
STATIC_DIR.mkdir(parents=True, exist_ok=True)
# --- domain routers (after helpers defined) ---
