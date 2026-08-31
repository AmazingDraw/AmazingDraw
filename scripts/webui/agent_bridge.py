import os
import json
import time
import uuid
import asyncio
import contextlib
import base64
import inspect
import signal
from pathlib import Path
from typing import AsyncGenerator, Awaitable, Callable, Dict, Any, Optional

from operation_registry import CliProcessRecord, operation_registry

SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_DIR = SCRIPT_DIR.parent.parent

# 同一 OpenClaw sessionKey 上串行：避免 sessions.patch + chat.send 与并发 reply-init 撞 revision
_SESSION_LOCKS: Dict[str, asyncio.Lock] = {}
_SESSION_LOCK_USERS: Dict[str, int] = {}
_INIT_CONFLICT_RETRIES = 3
_INIT_CONFLICT_BASE_DELAY_S = 0.45


class OperationCancelledError(RuntimeError):
    """The exact OpenClaw/CLI operation was cancelled."""


class AgentExecutionError(RuntimeError):
    """The selected transport failed without a valid assistant result."""


StatusCallback = Callable[..., Awaitable[None]]


def _is_reply_init_conflict_text(msg: str) -> bool:
    text = str(msg or "")
    return (
        "reply session initialization conflicted" in text
        or "initialization conflicted" in text
    )


def _is_reply_init_conflict(err: BaseException) -> bool:
    return _is_reply_init_conflict_text(str(err or ""))


def _operation_cancel_requested(operation_id: Optional[str]) -> bool:
    """True only when WebUI itself asked to abort this run."""
    if not operation_id:
        return False
    try:
        return bool(operation_registry.get(operation_id).cancel_requested)
    except Exception:
        return False


# OpenClaw 的静默哨兵：agent 回这个词表示「本轮故意不出声」，原生端会识别并吞掉。
# WebUI 是对话界面，既不能把哨兵原样显示，也不能把它造成的空正文当成失败报红。
_SILENT_TOKEN = "NO_REPLY"
_SILENT_REPLY_HINT = "💬 本轮 agent 判定无需回复（NO_REPLY）。把要求说得更明确一些再发一次即可。"


def _session_key(session_id: str) -> str:
    """WebUI 会话到 OpenClaw sessionKey 的唯一换算入口。

    WS 与 CLI 两条通道必须用同一个 key，否则会落到两个互不相通的会话上。
    """
    return f"agent:main:explicit:{session_id}"


def _connect_challenge_signed_at_ms(challenge: dict) -> int:
    """OpenClaw 2026.8.1：device.signedAt 必须等于 connect.challenge.payload.ts。

    官方 gateway-client 在有 deviceIdentity 时，challenge ts 缺失/非整型直接拒连。
    不能再用本机 Date.now() 去签，否则会 DEVICE_AUTH_SIGNATURE_*。
    """
    payload = challenge.get("payload") if isinstance(challenge, dict) else None
    if not isinstance(payload, dict):
        raise ValueError("connect.challenge payload missing")
    ts = payload.get("ts")
    if isinstance(ts, bool) or not isinstance(ts, (int, float)):
        raise ValueError("connect.challenge timestamp invalid")
    ts_int = int(ts)
    if ts_int != ts or ts_int < 0:
        raise ValueError("connect.challenge timestamp invalid")
    return ts_int


def _visible_text_from_message(message_obj: Any) -> str:
    """Assistant-visible text only. Thinking blocks are not streamed as reply tokens."""
    if not isinstance(message_obj, dict):
        return ""
    content_list = message_obj.get("content", [])
    if isinstance(content_list, list):
        parts = []
        for item in content_list:
            if not isinstance(item, dict):
                continue
            if item.get("type") == "text":
                parts.append(item.get("text") or "")
        return "".join(parts)
    return message_obj.get("text") or ""


def _merge_visible_stream_text(payload: Dict[str, Any], sent_text: str) -> str:
    """Protocol v4: prefer cumulative ``message`` text, else ``deltaText`` / ``replace``."""
    message_obj = payload.get("message") if isinstance(payload.get("message"), dict) else {}
    snapshot = _visible_text_from_message(message_obj)
    delta = payload.get("deltaText") if isinstance(payload.get("deltaText"), str) else ""
    if payload.get("replace") is True and delta:
        return delta
    if snapshot:
        return snapshot
    if delta:
        return f"{sent_text}{delta}"
    return snapshot or ""


def _silent_reply_state(text: str) -> str:
    """判断累积文本与静默哨兵的关系：silent / pending / text。

    pending 表示目前还是哨兵的前缀，分不清是静默还是正文开头，先攒着别吐，
    否则流式会把半个 "NO_REPLY" 打到用户屏幕上。
    """
    s = (text or "").strip()
    if not s:
        return "pending"
    if s == _SILENT_TOKEN:
        return "silent"
    if _SILENT_TOKEN.startswith(s):
        return "pending"
    return "text"


@contextlib.asynccontextmanager
async def _session_guard(session_id: str):
    """按 session 串行，并在最后一个使用者离开后回收锁对象。

    锁只按 session_id 常驻的话会随运行时长单调增长；用引用计数而不是
    lock.locked() 判断闲置，因为 release 唤醒等待者到其真正上锁之间
    存在窗口，仅看 locked() 会把还有人排队的锁误删，导致两个协程同时进临界区。
    """
    # asyncio 单线程：无 await 的 get/set 不会交错
    lock = _SESSION_LOCKS.get(session_id)
    if lock is None:
        lock = asyncio.Lock()
        _SESSION_LOCKS[session_id] = lock
    _SESSION_LOCK_USERS[session_id] = _SESSION_LOCK_USERS.get(session_id, 0) + 1
    try:
        async with lock:
            yield
    finally:
        remaining = _SESSION_LOCK_USERS.get(session_id, 1) - 1
        if remaining > 0:
            _SESSION_LOCK_USERS[session_id] = remaining
        else:
            _SESSION_LOCK_USERS.pop(session_id, None)
            _SESSION_LOCKS.pop(session_id, None)


def load_system_config() -> dict:
    config_path = SCRIPT_DIR.parent / "config.json"
    if config_path.exists():
        try:
            return json.loads(config_path.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}

_WS_TOTAL_TIMEOUT_DEFAULT_S = 600.0
_WS_TOTAL_TIMEOUT_MIN_S = 60.0
_WS_TOTAL_TIMEOUT_MAX_S = 7200.0


def _ws_total_timeout_seconds() -> float:
    """一轮对话最长允许跑多久，由 config.json 的 openclaw_ws_timeout_seconds 决定。

    这是总时限而非空闲判定：agent 跑长工具链时中途连续不吐字是正常的，
    所以给足余量，只做区间钳制兜住填错的值。
    """
    raw = load_system_config().get("openclaw_ws_timeout_seconds")
    try:
        val = float(raw)
    except (TypeError, ValueError):
        return _WS_TOTAL_TIMEOUT_DEFAULT_S
    if val <= 0:
        return _WS_TOTAL_TIMEOUT_DEFAULT_S
    return max(_WS_TOTAL_TIMEOUT_MIN_S, min(val, _WS_TOTAL_TIMEOUT_MAX_S))


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
        if token:
            token = os.path.expandvars(token)
        return port, token
    except Exception:
        return 18789, ""

def get_device_info():
    """Load the Gateway device keypair for connect signatures.

    OpenClaw 2026.8.1 stores the canonical identity in sqlite
    ``device_identities`` (key ``primary``). ``identity/device.json`` is only a
    retired Doctor-import leftover and is often already gone.
    """
    device_path = Path.home() / ".openclaw" / "identity" / "device.json"
    if device_path.exists():
        try:
            with open(device_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if data.get("deviceId") and data.get("privateKeyPem") and data.get("publicKeyPem"):
                return data
        except Exception:
            pass
    return _device_info_from_sqlite()


def _device_info_from_sqlite():
    db_path = Path.home() / ".openclaw" / "state" / "openclaw.sqlite"
    if not db_path.exists():
        return None
    try:
        import sqlite3

        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        try:
            row = conn.execute(
                "SELECT device_id, public_key_pem, private_key_pem "
                "FROM device_identities WHERE identity_key = ? LIMIT 1",
                ("primary",),
            ).fetchone()
            if not row:
                row = conn.execute(
                    "SELECT device_id, public_key_pem, private_key_pem "
                    "FROM device_identities ORDER BY updated_at_ms DESC LIMIT 1"
                ).fetchone()
        finally:
            conn.close()
    except Exception:
        return None
    if not row or not row[0] or not row[1] or not row[2]:
        return None
    return {
        "deviceId": row[0],
        "publicKeyPem": row[1],
        "privateKeyPem": row[2],
    }


async def _notify_status(
    callback: Optional[StatusCallback],
    state: str,
    **metadata: Any,
) -> None:
    if callback is None:
        return
    result = callback(state, **metadata)
    if inspect.isawaitable(result):
        await result


@contextlib.asynccontextmanager
async def _open_authenticated_gateway():
    """Open one authenticated Gateway connection.

    Data streams and control methods intentionally call this independently so a
    cancellation request never depends on the possibly-broken stream socket.
    """
    import websockets
    from cryptography.hazmat.primitives import serialization

    port, token = get_gateway_info()
    device = get_device_info()
    if not device:
        raise ValueError("device.json not found, cannot sign payload")

    url = f"ws://127.0.0.1:{port}"
    async with websockets.connect(
        url,
        proxy=None,
        close_timeout=2,
        open_timeout=10,
        ping_interval=20,
        ping_timeout=60,
        max_size=32 * 1024 * 1024,
    ) as ws:
        challenge_msg = await asyncio.wait_for(ws.recv(), timeout=3.0)
        challenge = json.loads(challenge_msg)
        nonce = challenge.get("payload", {}).get("nonce", "")
        if not nonce:
            raise ValueError("nonce missing in challenge")

        signed_at_ms = _connect_challenge_signed_at_ms(challenge)
        scopes_list = ["operator.admin", "operator.read", "operator.write"]
        scopes_str = ",".join(scopes_list)
        client_id = "cli"
        client_mode = "cli"
        platform = "darwin"
        device_family = "macos"

        payload = (
            f"v3|{device['deviceId']}|{client_id}|{client_mode}|operator|"
            f"{scopes_str}|{signed_at_ms}|{token}|{nonce}|{platform}|{device_family}"
        )
        private_key = serialization.load_pem_private_key(
            device["privateKeyPem"].encode("utf-8"),
            password=None,
        )
        signature_b64url = base64url_encode(
            private_key.sign(payload.encode("utf-8"))
        )
        public_key = serialization.load_pem_public_key(
            device["publicKeyPem"].encode("utf-8")
        )
        public_key_b64url = base64url_encode(
            public_key.public_bytes(
                encoding=serialization.Encoding.Raw,
                format=serialization.PublicFormat.Raw,
            )
        )

        handshake_id = f"connect-{uuid.uuid4()}"
        await ws.send(
            json.dumps(
                {
                    "type": "req",
                    "id": handshake_id,
                    "method": "connect",
                    "params": {
                        "role": "operator",
                        "auth": {"token": token},
                        "scopes": scopes_list,
                        "minProtocol": 4,
                        "maxProtocol": 4,
                        "client": {
                            "id": client_id,
                            "displayName": "Antigravity WebUI",
                            "version": "2026.8.1",
                            "platform": platform,
                            "deviceFamily": device_family,
                            "mode": client_mode,
                            "instanceId": str(uuid.uuid4()),
                        },
                        "device": {
                            "id": device["deviceId"],
                            "publicKey": public_key_b64url,
                            "signature": signature_b64url,
                            "signedAt": signed_at_ms,
                            "nonce": nonce,
                        },
                    },
                }
            )
        )
        connect_res = json.loads(
            await asyncio.wait_for(ws.recv(), timeout=3.0)
        )
        if not connect_res.get("ok"):
            raise ValueError(f"Handshake failed: {connect_res.get('error')}")
        yield ws


async def _gateway_control_request(
    method: str,
    params: Dict[str, Any],
) -> Dict[str, Any]:
    """Execute one control-plane method over its own authenticated socket."""
    request_id = f"control-{uuid.uuid4()}"
    async with _open_authenticated_gateway() as ws:
        await ws.send(
            json.dumps(
                {
                    "type": "req",
                    "id": request_id,
                    "method": method,
                    "params": params,
                }
            )
        )
        deadline = time.monotonic() + 8.0
        while time.monotonic() < deadline:
            raw = await asyncio.wait_for(
                ws.recv(),
                timeout=max(0.1, deadline - time.monotonic()),
            )
            frame = json.loads(raw)
            if frame.get("type") == "res" and frame.get("id") == request_id:
                return frame
    raise TimeoutError(f"Gateway control request timed out: {method}")


def _is_unsupported_method_response(response: Dict[str, Any]) -> bool:
    error = response.get("error") or {}
    if isinstance(error, dict):
        code = str(error.get("code") or "").lower()
        message = str(error.get("message") or error.get("detail") or "")
    else:
        code = ""
        message = str(error)
    probe = f"{code} {message}".lower()
    return any(
        marker in probe
        for marker in (
            "method_not_found",
            "method not found",
            "unknown method",
            "unsupported method",
            "not implemented",
        )
    )


def _is_not_found_response(response: Dict[str, Any]) -> bool:
    error = response.get("error") or {}
    if isinstance(error, dict):
        probe = " ".join(
            str(error.get(key) or "")
            for key in ("code", "message", "detail")
        )
    else:
        probe = str(error)
    normalized = probe.lower()
    return "not_found" in normalized or "not found" in normalized


async def abort_openclaw_operation(
    operation_id: str,
    session_id: str,
) -> Dict[str, Any]:
    """Precisely abort one run; never substitute a broad session/process kill."""
    response = await _gateway_control_request(
        "chat.abort",
        {
            "sessionKey": _session_key(session_id),
            "runId": operation_id,
            "preserveSideRuns": True,
        },
    )
    if response.get("ok"):
        return {
            "status": "accepted",
            "cancelled": True,
            "operation_id": operation_id,
            "payload": response.get("payload"),
        }
    if _is_unsupported_method_response(response):
        return {
            "status": "unsupported",
            "cancelled": False,
            "operation_id": operation_id,
            "detail": "OpenClaw Gateway does not support chat.abort",
        }
    return {
        "status": "rejected",
        "cancelled": False,
        "operation_id": operation_id,
        "detail": response.get("error") or "chat.abort rejected",
    }


async def delete_openclaw_session(session_id: str) -> Dict[str, Any]:
    """Delete the exact OpenClaw session after local active-work checks."""
    try:
        response = await _gateway_control_request(
            "sessions.delete",
            {"key": _session_key(session_id)},
        )
    except Exception as err:
        return {
            "status": "rejected",
            "detail": str(err) or "sessions.delete failed",
        }
    if response.get("ok") or _is_not_found_response(response):
        return {
            "status": "deleted",
            "absent": not response.get("ok"),
            "payload": response.get("payload"),
        }
    if _is_unsupported_method_response(response):
        return {
            "status": "unsupported",
            "detail": "OpenClaw Gateway does not support sessions.delete",
        }
    return {
        "status": "rejected",
        "detail": response.get("error") or "sessions.delete rejected",
    }


async def _call_openclaw_gateway_ws_once(
    full_message: str,
    session_id: str,
    model_id: str = None,
    progress: Optional[Dict[str, Any]] = None,
    operation_id: Optional[str] = None,
    on_status: Optional[StatusCallback] = None,
):
    """Execute one stable-id ``chat.send`` and parse its ACK/events."""
    operation_id = operation_id or str(uuid.uuid4())
    if progress is None:
        progress = {}
    async with _open_authenticated_gateway() as ws:
        session_key = _session_key(session_id)

        # model patch 与 reply-session init 共享 store revision；失败只警告，不阻断 chat.send。
        # 这里在 chat.send 之前，连接上不会有本轮的 chat 事件，丢弃无关帧是安全的；
        # 等不到 patch 应答也只降级为「沿用会话原模型」，绝不能把整轮对话拖死。
        if model_id:
            patch_frame = {
                "type": "req",
                "id": "patchmodel-1",
                "method": "sessions.patch",
                "params": {
                    "key": session_key,
                    "model": model_id
                }
            }
            await ws.send(json.dumps(patch_frame))

            patch_deadline = time.time() + 5.0
            patch_res = None
            try:
                while time.time() < patch_deadline:
                    raw = await asyncio.wait_for(
                        ws.recv(), timeout=max(0.1, patch_deadline - time.time())
                    )
                    frame = json.loads(raw)
                    if frame.get("id") == "patchmodel-1":
                        patch_res = frame
                        break
            except (asyncio.TimeoutError, json.JSONDecodeError):
                pass

            if patch_res is None:
                print(
                    f"⚠️ sessions.patch model 无应答（沿用会话原模型，继续 chat.send）"
                    f" session={session_id} model={model_id}",
                    flush=True,
                )
            elif not patch_res.get("ok"):
                print(
                    f"⚠️ sessions.patch model 失败（忽略，继续 chat.send）: {patch_res.get('error')}",
                    flush=True,
                )

        chat_params = {
            "sessionKey": session_key,
            "message": full_message,
            "idempotencyKey": operation_id
        }

        chat_frame = {
            "type": "req",
            "id": "chatsend-1",
            "method": "chat.send",
            "params": chat_params
        }

        # Mark the send attempt before yielding to socket I/O.  If cancellation
        # or disconnect races this await, delivery is uncertain and a CLI replay
        # would be unsafe.
        progress["ws_sent"] = True
        await _notify_status(on_status, "ws_sent", transport="gateway")
        await ws.send(json.dumps(chat_frame))

        # 总时限可配；单次 recv 空闲 15s 不视为失败——模型思考/agent 流期间常有长静默
        total_timeout = _ws_total_timeout_seconds()
        timeout_limit = time.time() + total_timeout
        sent_text = ""
        idle_rounds = 0
        ack_received = False
        final_received = False

        while time.time() < timeout_limit:
            try:
                recv_timeout = min(
                    15.0,
                    max(0.1, timeout_limit - time.time()),
                )
                msg = await asyncio.wait_for(
                    ws.recv(),
                    timeout=recv_timeout,
                )
                idle_rounds = 0
            except asyncio.TimeoutError:
                idle_rounds += 1
                # 仍在总时限内：继续等 chat 事件，避免误降级 CLI
                print(
                    f"⏳ OpenClaw WS 空闲 {recv_timeout:.0f}s"
                    f"（第 {idle_rounds} 次），继续等待 chat 事件 "
                    f"session={session_id} run={operation_id[:8]}…",
                    flush=True,
                )
                continue

            data = json.loads(msg)

            if data.get("type") == "event" and data.get("event") == "chat":
                payload = data.get("payload", {})
                if payload.get("runId") == operation_id:
                    # 网关已经把这轮跑起来了：即便后面失败，也不能当作「什么都没发生」
                    progress["run_started"] = True
                    if not progress.get("accepted"):
                        progress["accepted"] = True
                        await _notify_status(
                            on_status, "accepted", transport="gateway"
                        )
                    if not progress.get("streaming"):
                        progress["streaming"] = True
                        await _notify_status(
                            on_status, "streaming", transport="gateway"
                        )

                    state = payload.get("state")
                    full_text = _merge_visible_stream_text(payload, sent_text)

                    # 冲突常以 assistant text 先到达，再标 state=error；
                    # 绝不能先 yield，否则上层会当成已开流而跳过重试
                    err_msg = payload.get("errorMessage") or ""
                    if state in ("aborted", "cancelled", "canceled"):
                        # 网关把非 done 的收尾一律标成 aborted。429 故障转移
                        # 成功后还会对同一 runId 补一帧 aborted：不是用户点停止。
                        # 这帧经常还是节流后的半句；真正的尾巴在随后的 final 里。
                        silent_state = _silent_reply_state(full_text)
                        extra = ""
                        if (
                            silent_state == "text"
                            and full_text.startswith(sent_text)
                            and len(full_text) > len(sent_text)
                        ):
                            extra = full_text[len(sent_text):]
                            yield {"type": "text", "chunk": extra}
                            sent_text = full_text
                        if _operation_cancel_requested(operation_id):
                            raise OperationCancelledError(
                                err_msg or f"OpenClaw run cancelled: {operation_id}"
                            )
                        if sent_text or silent_state == "text":
                            print(
                                "⚠️ OpenClaw 在已有正文后标 aborted，"
                                "忽略并继续等 final "
                                f"session={session_id} run={operation_id[:8]}… "
                                f"reason={err_msg or payload.get('stopReason') or state}",
                                flush=True,
                            )
                            # 有增量才可能这就是唯一收尾；没增量则必须等真正的 final。
                            if extra:
                                final_received = True
                                if ack_received:
                                    break
                            timeout_limit = min(timeout_limit, time.time() + 8.0)
                            continue
                        raise ValueError(
                            err_msg or f"OpenClaw run aborted: {operation_id}"
                        )
                    if state == "error" or _is_reply_init_conflict_text(full_text) or _is_reply_init_conflict_text(err_msg):
                        detail = err_msg or full_text or "unknown chat error"
                        if _is_reply_init_conflict_text(detail):
                            raise ValueError(detail)
                        if state == "error":
                            raise ValueError(f"Chat execution failed: {detail}")

                    # 每帧都携带完整正文，增量吐字靠「新正文是已吐内容的延长」这一前提。
                    # 网关若改写了已发出的部分，按旧偏移切片会把错位的碎片打给用户，
                    # 故显式校验前缀；对不上就重新对齐，宁可这帧不吐也不吐乱码。
                    if not full_text.startswith(sent_text):
                        print(
                            f"⚠️ 流式正文与已发送内容不一致，重新对齐 "
                            f"session={session_id} run={operation_id[:8]}…",
                            flush=True,
                        )
                        sent_text = full_text

                    silent_state = _silent_reply_state(full_text)

                    if silent_state == "text" and len(full_text) > len(sent_text):
                        yield {"type": "text", "chunk": full_text[len(sent_text):]}
                        sent_text = full_text

                    if state == "final":
                        if silent_state == "silent":
                            yield {"type": "text", "chunk": _SILENT_REPLY_HINT}
                        elif len(full_text) > len(sent_text):
                            # pending 攒下的尾巴：到 final 才确定不是哨兵，补吐
                            yield {"type": "text", "chunk": full_text[len(sent_text):]}
                            sent_text = full_text
                        elif not sent_text:
                            yield {"type": "text", "chunk": _SILENT_REPLY_HINT}
                        final_received = True
                        if ack_received:
                            break
                        # A chat event may race ahead of the chat.send response.
                        # Do not claim success until the ACK (and its runId) has
                        # been consumed, but also do not wait the full model
                        # timeout after a final event.
                        timeout_limit = min(timeout_limit, time.time() + 8.0)

            if data.get("type") == "res" and data.get("id") == "chatsend-1":
                if not data.get("ok"):
                    err_obj = data.get("error")
                    raise ValueError(f"chat.send request failed: {err_obj}")
                ack_payload = data.get("payload") or {}
                ack_run_id = ack_payload.get("runId")
                if ack_run_id != operation_id:
                    raise ValueError(
                        f"chat.send ACK runId mismatch: {ack_run_id!r} "
                        f"!= {operation_id!r}"
                    )
                ack_received = True
                if not progress.get("accepted"):
                    progress["accepted"] = True
                    await _notify_status(
                        on_status, "accepted", transport="gateway"
                    )
                if final_received:
                    break
        else:
            # while 因 timeout_limit 自然结束（未 break）
            if sent_text and ack_received and not _operation_cancel_requested(
                operation_id
            ):
                # stale aborted 把等待窗口收到 8s 后仍无 final：保住已吐正文，
                # 不要把成功重试误报成超时/未知远端。
                return
            waiting_for = (
                "chat.send ACK"
                if final_received and not ack_received
                else "final chat event"
            )
            raise TimeoutError(
                f"OpenClaw WS chat 超时未收到 {waiting_for}"
                f"（session={session_id}）"
            )


async def _terminate_cli_operation(
    operation_id: str,
    grace_seconds: float = 5.0,
) -> Dict[str, Any]:
    """TERM then KILL the CLI process group and always await reaping."""
    record = operation_registry.get_cli_process(operation_id)
    if record is None:
        return {
            "status": "not_found",
            "cancelled": False,
            "operation_id": operation_id,
        }

    process = record.process
    if process.returncode is not None:
        return {
            "status": "already_terminal",
            "cancelled": False,
            "operation_id": operation_id,
            "pid": process.pid,
            "pgid": record.pgid,
        }

    try:
        os.killpg(record.pgid, signal.SIGTERM)
    except ProcessLookupError:
        await process.wait()
        return {
            "status": "already_terminal",
            "cancelled": False,
            "operation_id": operation_id,
            "pid": process.pid,
            "pgid": record.pgid,
        }
    if not operation_registry.mark_cli_cancel_requested(
        operation_id,
        record,
    ):
        return {
            "status": "not_found",
            "cancelled": False,
            "operation_id": operation_id,
        }

    try:
        await asyncio.wait_for(
            process.wait(),
            timeout=max(0.0, grace_seconds),
        )
    except asyncio.TimeoutError:
        try:
            os.killpg(record.pgid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        await process.wait()

    return {
        "status": "cancelled",
        "cancelled": True,
        "operation_id": operation_id,
        "pid": process.pid,
        "pgid": record.pgid,
    }


async def cancel_openclaw_operation(
    operation_id: str,
    session_id: str,
) -> Dict[str, Any]:
    """Cancel the registered CLI tree or exact Gateway run."""
    if operation_registry.get_cli_process(operation_id) is not None:
        return await _terminate_cli_operation(operation_id)
    with contextlib.suppress(Exception):
        operation = operation_registry.get(operation_id)
        if operation.recovered and operation.transport == "cli":
            return {
                "status": "unavailable",
                "cancelled": False,
                "operation_id": operation_id,
                "detail": "重启前的 CLI PID 不可安全复用，未执行进程终止",
            }
    return await abort_openclaw_operation(operation_id, session_id)


async def _run_openclaw_cli_fallback(
    full_message: str,
    session_id: str,
    model_id: Optional[str] = None,
    operation_id: Optional[str] = None,
    on_status: Optional[StatusCallback] = None,
) -> str:
    operation_id = operation_id or str(uuid.uuid4())
    env = dict(os.environ)
    home = str(Path.home())
    local_bin = os.path.join(home, ".local", "bin")
    if local_bin not in env.get("PATH", ""):
        env["PATH"] = f"{local_bin}:{env.get('PATH', '')}"

    # 必须用 --session-key 对齐 WS 路径的 sessionKey，不能用 --session-id。
    # 网关把 agent:main:explicit:<id> 映射到它自己生成的内部会话（id 与这里的 <id> 不同），
    # 而 --session-id <id> 会另开一个字面同名的空会话：降级一次，整段历史就被换掉，
    # 表现为「同一个对话，模型突然不记得前面说过什么」。
    cmd = [
        "openclaw", "agent",
        "--agent", "main",
        "--session-key", _session_key(session_id),
        "--message", full_message,
        "--json"
    ]
    if model_id:
        cmd.extend(["--model", model_id])
    cmd.extend(["--thinking", "off"])

    process = None
    record: Optional[CliProcessRecord] = None
    communicate_task: Optional[asyncio.Task] = None
    stdout_raw: Any = b""
    stderr_raw: Any = b""
    try:
        # Persist the uncertainty barrier before spawning.  A restart after this
        # point must never replay the same request or signal a stale PID.
        await _notify_status(
            on_status,
            "starting",
            transport="cli",
            dispatch_started=True,
        )
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
            start_new_session=True,
        )
        # start_new_session makes the child the process-group leader.
        record = operation_registry.register_cli_process(
            operation_id,
            process,
            pgid=process.pid,
        )
        await _notify_status(
            on_status,
            "accepted",
            transport="cli",
            pid=process.pid,
            pgid=record.pgid,
        )

        cli_timeout = _ws_total_timeout_seconds() + 60.0
        communicate_task = asyncio.create_task(process.communicate())
        try:
            stdout_raw, stderr_raw = await asyncio.wait_for(
                asyncio.shield(communicate_task),
                timeout=cli_timeout,
            )
        except asyncio.TimeoutError:
            await _terminate_cli_operation(operation_id)
            with contextlib.suppress(asyncio.CancelledError, Exception):
                stdout_raw, stderr_raw = await asyncio.shield(
                    communicate_task
                )
            raise AgentExecutionError(
                f"❌ OpenClaw CLI 总超时 {cli_timeout:.0f}s，"
                "已清理整个进程组。"
            )

        stdout = (
            stdout_raw.decode("utf-8", errors="replace")
            if isinstance(stdout_raw, bytes)
            else str(stdout_raw or "")
        ).strip()
        stderr = (
            stderr_raw.decode("utf-8", errors="replace")
            if isinstance(stderr_raw, bytes)
            else str(stderr_raw or "")
        ).strip()

        if record.cancel_requested:
            raise OperationCancelledError(
                f"CLI 操作已取消并回收进程树。{stderr}".strip()
            )
        if process.returncode != 0:
            raise AgentExecutionError(
                f"❌ OpenClaw CLI 执行出错 (Exit {process.returncode}):\n"
                f"```\n{stderr or stdout}\n```"
            )

        try:
            data = json.loads(stdout)
        except json.JSONDecodeError:
            import re as _re
            clean = _re.sub(r'\x1b\[[0-9;]*m', '', stdout)
            start_idx = clean.find("{")
            end_idx = clean.rfind("}")
            if start_idx == -1 or end_idx == -1 or end_idx <= start_idx:
                raise ValueError("stdout 中未找到有效 JSON 边界")
            data = json.loads(clean[start_idx:end_idx + 1])

        result_obj = data.get("result", data)
        reply_text = (
            result_obj.get("finalAssistantVisibleText")
            or result_obj.get("finalAssistantRawText")
            or next((p.get("text") for p in result_obj.get("payloads", []) if p.get("text")), None)
            or data.get("finalAssistantVisibleText")
            or ""
        )
        # returncode==0 且 JSON 可解析 = 这轮跑通了。此时正文为空的常见来源是
        # 上游吞掉了静默哨兵，属于 agent 的主动选择，不是失败，不该报红。
        if _silent_reply_state(reply_text) == "silent" or not reply_text:
            return _SILENT_REPLY_HINT
        return reply_text
    except asyncio.CancelledError:
        if process is not None and process.returncode is None:
            with contextlib.suppress(Exception):
                await asyncio.shield(_terminate_cli_operation(operation_id))
        if communicate_task is not None and not communicate_task.done():
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await asyncio.shield(communicate_task)
        raise
    except OperationCancelledError:
        raise
    except AgentExecutionError:
        raise
    except Exception as e:
        raise AgentExecutionError(
            f"❌ 降级调用 OpenClaw CLI 失败: {str(e)}"
        ) from e
    finally:
        if record is not None:
            operation_registry.detach_cli_process(operation_id, record)


async def stream_agent_chat(
    backend: str,
    full_message: str,
    session_id: str,
    chat_mode: str,
    model_id: Optional[str] = None,
    card_id: Optional[str] = None,
    operation_id: Optional[str] = None,
    on_status: Optional[StatusCallback] = None,
) -> AsyncGenerator[Dict[str, Any], None]:
    if backend != "openclaw":
        yield {"type": "text", "chunk": f"❌ 不支持的后端: {backend}"}
        return

    if backend == "openclaw":
        operation_id = operation_id or str(uuid.uuid4())
        # WS 重试 + CLI 降级 全程占同一 session 锁，避免双通道撞 revision
        async with _session_guard(session_id):
            last_err: Optional[BaseException] = None
            progress: Dict[str, Any] = {}
            for attempt in range(_INIT_CONFLICT_RETRIES):
                yielded_any = False
                try:
                    async for chunk_obj in _call_openclaw_gateway_ws_once(
                        full_message,
                        session_id,
                        model_id,
                        progress=progress,
                        operation_id=operation_id,
                        on_status=on_status,
                    ):
                        # 防御：once 若仍吐出冲突正文，当作失败触发重试
                        if (
                            isinstance(chunk_obj, dict)
                            and chunk_obj.get("type") == "text"
                            and _is_reply_init_conflict_text(chunk_obj.get("chunk") or "")
                        ):
                            raise ValueError(chunk_obj.get("chunk") or "reply session initialization conflicted")
                        yielded_any = True
                        yield chunk_obj
                    return
                except OperationCancelledError as err:
                    yield {
                        "type": "cancelled",
                        "reason": str(err),
                    }
                    return
                except Exception as err:
                    last_err = err
                    is_conflict = _is_reply_init_conflict(err)
                    if yielded_any and not is_conflict:
                        # 真实正文已开流：不再降级 CLI，避免重复回复
                        yield {
                            "type": "unknown_remote",
                            "error": f"流式中断: {err}",
                        }
                        return
                    if progress.get("ws_sent"):
                        # 从 chat.send 写 socket 起，投递结果就可能未知。无论 ACK
                        # 是否已到，都禁止 CLI 开新 run；operation_id 仍保留给状态查询。
                        yield {
                            "type": "unknown_remote",
                            "error": (
                                f"本轮在后端中断：{err}\n\n"
                                "这轮已向 OpenClaw 发送，为避免重复操作卡片/渲染，"
                                "没有自动重跑。确认无副作用后再发一次即可。"
                            ),
                        }
                        return
                    if not is_conflict or attempt >= _INIT_CONFLICT_RETRIES - 1:
                        break
                    delay = _INIT_CONFLICT_BASE_DELAY_S * (2 ** attempt)
                    print(
                        f"⚠️ reply session init conflict ({session_id}) "
                        f"attempt {attempt + 1}/{_INIT_CONFLICT_RETRIES}, "
                        f"retry in {delay:.2f}s: {err}",
                        flush=True,
                    )
                    await asyncio.sleep(delay)

            print(
                f"⚠️ OpenClaw WebSocket 调用失败，降级 to CLI 执行: "
                f"{type(last_err).__name__ if last_err else 'Unknown'}: {last_err!r}",
                flush=True,
            )
            if last_err and _is_reply_init_conflict(last_err):
                await asyncio.sleep(_INIT_CONFLICT_BASE_DELAY_S * 2)
            try:
                reply_text = await _run_openclaw_cli_fallback(
                    full_message,
                    session_id,
                    model_id,
                    operation_id=operation_id,
                    on_status=on_status,
                )
            except OperationCancelledError as err:
                yield {
                    "type": "cancelled",
                    "reason": str(err),
                }
                return
            except Exception as err:
                yield {
                    "type": "error",
                    "error": str(err),
                }
                return
            # CLI 若也回冲突字样，原样透出；否则正常回复
            yield {"type": "text", "chunk": reply_text}
