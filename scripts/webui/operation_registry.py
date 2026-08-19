#!/usr/bin/env python3
"""Chat operation registry with an atomic metadata journal.

The registry owns lifecycle state and SSE subscriptions.  A browser connection is
only a subscriber: closing it never owns or cancels the background operation.
Runtime handles stay in-process; restart recovery restores only durable state.
"""

from __future__ import annotations

import asyncio
import copy
import contextlib
import concurrent.futures
import hashlib
import json
import os
import re
import tempfile
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import (
    Any,
    AsyncGenerator,
    Awaitable,
    Callable,
    Dict,
    List,
    Optional,
    Set,
    Tuple,
)


TERMINAL_STATES = frozenset({"completed", "failed", "cancelled"})
ACTIVE_STATES = frozenset(
    {
        "queued",
        "starting",
        "ws_sent",
        "accepted",
        "streaming",
        "cancelling",
        "unknown_remote",
    }
)

_ALLOWED_TRANSITIONS = {
    "queued": {
        "starting",
        "cancelling",
        "cancelled",
        "failed",
        "unknown_remote",
    },
    "starting": {
        "ws_sent",
        "accepted",
        "streaming",
        "completed",
        "cancelling",
        "cancelled",
        "failed",
        "unknown_remote",
    },
    "ws_sent": {
        "accepted",
        "streaming",
        "completed",
        "cancelling",
        "cancelled",
        "failed",
        "unknown_remote",
    },
    "accepted": {
        "streaming",
        "completed",
        "cancelling",
        "cancelled",
        "failed",
        "unknown_remote",
    },
    "streaming": {
        "completed",
        "cancelling",
        "cancelled",
        "failed",
        "unknown_remote",
    },
    "cancelling": {"cancelled", "completed", "failed", "unknown_remote"},
    "unknown_remote": {"cancelling", "cancelled", "completed", "failed"},
    "completed": set(),
    "failed": set(),
    "cancelled": set(),
}

_OPERATION_ID_RE = re.compile(r"^[0-9A-Za-z_.:-]{1,160}$")
_JOURNAL_SCHEMA_VERSION = 1


def _request_fingerprint(request: "OperationRequest") -> str:
    canonical = {
        "operation_id": request.operation_id,
        "session_id": request.session_id,
        "chat_mode": request.chat_mode,
        "card_id": request.card_id,
        "message": request.message,
        "include_context": request.include_context,
        "confirm": request.confirm,
    }
    payload = json.dumps(
        canonical,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


class OperationRegistryError(RuntimeError):
    """Base registry error."""


class OperationNotFoundError(OperationRegistryError):
    """Requested operation does not exist."""


class OperationConflictError(OperationRegistryError):
    """An operation id was reused with a different immutable request."""


class SessionTombstonedError(OperationRegistryError):
    """A deleted/tombstoned session may not accept new work."""


@dataclass(frozen=True)
class OperationRequest:
    """Immutable enqueue-time request snapshot."""

    operation_id: str
    session_id: str
    chat_mode: str
    card_id: Optional[str]
    message: str
    include_context: bool
    confirm: bool
    backend: str = field(compare=False)

    @classmethod
    def from_mapping(cls, raw: Dict[str, Any]) -> "OperationRequest":
        operation_id = str(raw.get("operation_id") or "").strip()
        if not _OPERATION_ID_RE.fullmatch(operation_id):
            raise ValueError("operation_id must be 1-160 safe identifier characters")
        session_id = str(raw.get("session_id") or "").strip()
        if not session_id:
            raise ValueError("session_id is required")
        message = str(raw.get("message") or "")
        if not message.strip():
            raise ValueError("message is required")
        return cls(
            operation_id=operation_id,
            session_id=session_id,
            chat_mode=str(raw.get("chat_mode") or "cards"),
            card_id=(
                str(raw["card_id"])
                if raw.get("card_id") is not None
                else None
            ),
            message=message,
            include_context=bool(raw.get("include_context")),
            confirm=bool(raw.get("confirm")),
            backend=str(raw.get("backend") or "openclaw"),
        )


Subscriber = Tuple[asyncio.AbstractEventLoop, asyncio.Queue]
CancelHandler = Callable[[], Awaitable[Dict[str, Any]]]


@dataclass
class CliProcessRecord:
    """One operation-owned CLI process group."""

    process: Any
    pgid: int
    cancel_requested: bool = False


@dataclass
class ChatOperation:
    request: OperationRequest
    request_fingerprint: str = ""
    state: str = "queued"
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    terminal_at: Optional[float] = None
    transport: Optional[str] = None
    state_history: List[str] = field(default_factory=lambda: ["queued"])
    events: List[Dict[str, Any]] = field(default_factory=list)
    subscribers: Set[Subscriber] = field(default_factory=set, repr=False)
    task: Optional[asyncio.Task] = field(default=None, repr=False)
    cancel_handler: Optional[CancelHandler] = field(default=None, repr=False)
    cancel_requested: bool = False
    cancel_confirmed: bool = False
    cancel_error: Optional[str] = None
    error: Optional[str] = None
    reply_text: str = ""
    result_meta: Optional[Dict[str, Any]] = None
    history_persisted: bool = False
    history_persisting: bool = False
    cancel_future: Optional[concurrent.futures.Future] = field(
        default=None,
        repr=False,
    )
    cancel_result: Optional[Dict[str, Any]] = field(default=None, repr=False)
    dispatch_started: bool = False
    recovered: bool = False
    recovered_from_state: Optional[str] = None

    @property
    def operation_id(self) -> str:
        return self.request.operation_id

    @property
    def run_id(self) -> str:
        """The stable OpenClaw run id is the immutable operation id."""
        return self.request.operation_id

    @property
    def session_id(self) -> str:
        return self.request.session_id

    @property
    def is_terminal(self) -> bool:
        return self.state in TERMINAL_STATES

    @property
    def is_recovered_unknown(self) -> bool:
        return self.recovered and self.state == "unknown_remote"


class OperationRegistry:
    """Thread-safe registry with async subscribers and cancellation hooks."""

    def __init__(self, journal_path: Optional[Path] = None) -> None:
        self._operations: Dict[str, ChatOperation] = {}
        self._cli_processes: Dict[str, CliProcessRecord] = {}
        self._tombstones: Set[str] = set()
        self._lock = threading.RLock()
        self._journal_path: Optional[Path] = None
        self._journal_error: Optional[str] = None
        if journal_path is not None:
            self.configure_journal(journal_path)

    @property
    def journal_path(self) -> Optional[Path]:
        with self._lock:
            return self._journal_path

    @property
    def journal_error(self) -> Optional[str]:
        with self._lock:
            return self._journal_error

    def configure_journal(self, path: Path) -> None:
        """Load a schema-v1 journal and atomically record recovery states."""
        journal_path = Path(path).expanduser().resolve()
        with self._lock:
            if self._journal_path == journal_path:
                return
            journal_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            self._journal_path = journal_path
            self._journal_error = None
            self._operations.clear()
            self._cli_processes.clear()
            self._tombstones.clear()
            if journal_path.exists():
                try:
                    self._load_journal_locked()
                except Exception as exc:
                    self._journal_error = str(exc)
                    quarantine = journal_path.with_name(
                        f"{journal_path.name}.corrupt-{time.time_ns()}"
                    )
                    with contextlib.suppress(OSError):
                        os.replace(journal_path, quarantine)
                    self._operations.clear()
                    self._tombstones.clear()
            self._commit_locked()

    def _load_journal_locked(self) -> None:
        if self._journal_path is None:
            return
        raw = json.loads(self._journal_path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise ValueError("operation journal root must be an object")
        if raw.get("schema_version") != _JOURNAL_SCHEMA_VERSION:
            raise ValueError("unsupported operation journal schema")
        records = raw.get("operations")
        if not isinstance(records, dict):
            raise ValueError("operation journal operations must be an object")

        restored: Dict[str, ChatOperation] = {}
        for operation_id, item in records.items():
            if not _OPERATION_ID_RE.fullmatch(str(operation_id)):
                raise ValueError("invalid operation id in journal")
            if not isinstance(item, dict):
                raise ValueError("invalid operation record in journal")
            session_id = str(item.get("session_id") or "").strip()
            fingerprint = str(item.get("request_fingerprint") or "")
            if not session_id or not re.fullmatch(r"[0-9a-f]{64}", fingerprint):
                raise ValueError("incomplete operation identity in journal")

            original_state = str(item.get("state") or "")
            if (
                original_state not in TERMINAL_STATES
                and original_state not in ACTIVE_STATES
            ):
                raise ValueError("invalid operation state in journal")
            recovered_state = (
                original_state
                if original_state in TERMINAL_STATES
                else "unknown_remote"
            )
            state_history = [
                str(value)
                for value in (item.get("state_history") or [])
                if isinstance(value, str)
            ]
            if not state_history:
                state_history = [original_state]
            if state_history[-1] != recovered_state:
                state_history.append(recovered_state)

            request = OperationRequest(
                operation_id=str(operation_id),
                session_id=session_id,
                chat_mode=str(item.get("chat_mode") or "cards"),
                card_id=(
                    str(item["card_id"])
                    if item.get("card_id") is not None
                    else None
                ),
                message="",
                include_context=bool(item.get("include_context")),
                confirm=bool(item.get("confirm")),
                backend=str(item.get("backend") or "openclaw"),
            )
            operation = ChatOperation(
                request=request,
                request_fingerprint=fingerprint,
                state=recovered_state,
                created_at=float(item.get("created_at") or time.time()),
                updated_at=time.time(),
                terminal_at=(
                    float(item["terminal_at"])
                    if item.get("terminal_at") is not None
                    else None
                ),
                transport=(
                    str(item["transport"])
                    if item.get("transport") is not None
                    else None
                ),
                state_history=state_history,
                cancel_requested=bool(item.get("cancel_requested")),
                cancel_confirmed=bool(item.get("cancel_confirmed")),
                history_persisted=bool(item.get("history_persisted")),
                dispatch_started=bool(item.get("dispatch_started")),
                recovered=True,
                recovered_from_state=(
                    str(
                        item.get("recovered_from_state")
                        or original_state
                    )
                    if original_state not in TERMINAL_STATES
                    else None
                ),
            )
            operation.events = [self._state_event(operation)]
            restored[operation.operation_id] = operation

        self._operations = restored
        tombstones = raw.get("session_tombstones") or []
        if not isinstance(tombstones, list):
            raise ValueError("operation journal tombstones must be an array")
        self._tombstones = {
            str(session_id)
            for session_id in tombstones
            if str(session_id).strip()
        }

    def _journal_document_locked(self) -> Dict[str, Any]:
        operations = {}
        for operation_id, operation in self._operations.items():
            operations[operation_id] = {
                "operation_id": operation_id,
                "session_id": operation.session_id,
                "chat_mode": operation.request.chat_mode,
                "card_id": operation.request.card_id,
                "include_context": operation.request.include_context,
                "confirm": operation.request.confirm,
                "backend": operation.request.backend,
                "request_fingerprint": operation.request_fingerprint,
                "state": operation.state,
                "state_history": list(operation.state_history),
                "transport": operation.transport,
                "dispatch_started": operation.dispatch_started,
                "cancel_requested": operation.cancel_requested,
                "cancel_confirmed": operation.cancel_confirmed,
                "history_persisted": operation.history_persisted,
                "created_at": operation.created_at,
                "updated_at": operation.updated_at,
                "terminal_at": operation.terminal_at,
                "recovered_from_state": operation.recovered_from_state,
            }
        return {
            "schema_version": _JOURNAL_SCHEMA_VERSION,
            "updated_at": time.time(),
            "operations": operations,
            "session_tombstones": sorted(self._tombstones),
        }

    def _commit_locked(self) -> None:
        if self._journal_path is None:
            return
        payload = json.dumps(
            self._journal_document_locked(),
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
            allow_nan=False,
        ).encode("utf-8")
        handle = tempfile.NamedTemporaryFile(
            prefix=f".{self._journal_path.name}.",
            suffix=".tmp",
            dir=str(self._journal_path.parent),
            delete=False,
        )
        temp_path = Path(handle.name)
        try:
            os.chmod(temp_path, 0o600)
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
            handle.close()
            os.replace(temp_path, self._journal_path)
            os.chmod(self._journal_path, 0o600)
            with contextlib.suppress(OSError):
                directory_fd = os.open(
                    self._journal_path.parent,
                    os.O_RDONLY,
                )
                try:
                    os.fsync(directory_fd)
                finally:
                    os.close(directory_fd)
        except Exception:
            handle.close()
            temp_path.unlink(missing_ok=True)
            raise

    def create(self, raw: Dict[str, Any]) -> ChatOperation:
        request = OperationRequest.from_mapping(copy.deepcopy(raw))
        fingerprint = _request_fingerprint(request)
        with self._lock:
            if request.session_id in self._tombstones:
                raise SessionTombstonedError(
                    f"session is tombstoned: {request.session_id}"
                )
            existing = self._operations.get(request.operation_id)
            if existing is not None:
                if existing.request_fingerprint != fingerprint:
                    raise OperationConflictError(
                        f"operation_id already belongs to another request: "
                        f"{request.operation_id}"
                    )
                return existing

            self._prune_terminal_locked(keep=500)
            operation = ChatOperation(
                request=request,
                request_fingerprint=fingerprint,
            )
            self._operations[request.operation_id] = operation
            initial = self._state_event(operation)
            operation.events.append(initial)
            self._commit_locked()
            return operation

    def get(self, operation_id: str) -> ChatOperation:
        with self._lock:
            operation = self._operations.get(operation_id)
            if operation is None:
                raise OperationNotFoundError(operation_id)
            return operation

    def attach_task(self, operation_id: str, task: asyncio.Task) -> None:
        with self._lock:
            self.get(operation_id).task = task

    def set_cancel_handler(
        self, operation_id: str, handler: Optional[CancelHandler]
    ) -> None:
        with self._lock:
            self.get(operation_id).cancel_handler = handler

    def mark_dispatch_started(
        self,
        operation_id: str,
        *,
        transport: str,
    ) -> None:
        """Persist the no-replay barrier before an external dispatch attempt."""
        with self._lock:
            operation = self.get(operation_id)
            if operation.is_terminal:
                return
            operation.transport = str(transport)
            operation.dispatch_started = True
            operation.updated_at = time.time()
            self._commit_locked()

    def register_cli_process(
        self,
        operation_id: str,
        process: Any,
        *,
        pgid: int,
    ) -> CliProcessRecord:
        """Attach one process group to an operation before it can be cancelled."""
        record = CliProcessRecord(process=process, pgid=int(pgid))
        with self._lock:
            existing = self._cli_processes.get(operation_id)
            if existing is not None:
                if existing.process is process:
                    return existing
                raise OperationConflictError(
                    f"CLI process already registered for operation: {operation_id}"
                )
            self._cli_processes[operation_id] = record
            operation = self._operations.get(operation_id)
            if operation is not None:
                operation.transport = "cli"
                operation.dispatch_started = True
                operation.updated_at = time.time()
                self._commit_locked()
        return record

    def get_cli_process(
        self,
        operation_id: str,
    ) -> Optional[CliProcessRecord]:
        with self._lock:
            return self._cli_processes.get(operation_id)

    def detach_cli_process(
        self,
        operation_id: str,
        expected: Optional[CliProcessRecord] = None,
    ) -> bool:
        """Detach only the record owned by the caller, avoiding PID reuse races."""
        with self._lock:
            current = self._cli_processes.get(operation_id)
            if current is None:
                return False
            if expected is not None and current is not expected:
                return False
            self._cli_processes.pop(operation_id, None)
            return True

    def mark_cli_cancel_requested(
        self,
        operation_id: str,
        expected: CliProcessRecord,
    ) -> bool:
        with self._lock:
            current = self._cli_processes.get(operation_id)
            if current is not expected:
                return False
            current.cancel_requested = True
            return True

    def transition(
        self,
        operation_id: str,
        state: str,
        *,
        transport: Optional[str] = None,
        error: Optional[str] = None,
        **metadata: Any,
    ) -> ChatOperation:
        with self._lock:
            operation = self.get(operation_id)
            if operation.is_terminal:
                return operation
            if state != operation.state:
                allowed = _ALLOWED_TRANSITIONS.get(operation.state, set())
                if state not in allowed:
                    raise OperationRegistryError(
                        f"invalid operation transition {operation.state!r} -> {state!r}"
                    )
                operation.state = state
                operation.state_history.append(state)
            if transport is not None:
                operation.transport = transport
            if metadata.get("dispatch_started") is True or state in {
                "ws_sent",
                "accepted",
                "streaming",
            }:
                operation.dispatch_started = True
            if error is not None:
                operation.error = str(error)
            operation.updated_at = time.time()
            if state in TERMINAL_STATES:
                operation.terminal_at = operation.updated_at
            event = self._state_event(operation, metadata)
            self._commit_locked()
            self._publish_locked(operation, event)
            return operation

    def publish(self, operation_id: str, event: Dict[str, Any]) -> None:
        with self._lock:
            operation = self.get(operation_id)
            payload = copy.deepcopy(event)
            payload.setdefault("operation_id", operation_id)
            self._publish_locked(operation, payload)

    def append_reply(self, operation_id: str, text: str) -> None:
        with self._lock:
            operation = self.get(operation_id)
            operation.reply_text += str(text or "")
            operation.updated_at = time.time()

    def set_result_meta(self, operation_id: str, meta: Dict[str, Any]) -> None:
        with self._lock:
            operation = self.get(operation_id)
            operation.result_meta = copy.deepcopy(meta)
            operation.updated_at = time.time()

    def claim_history_persistence(self, operation_id: str) -> bool:
        """Return True exactly once for the caller allowed to append history."""
        with self._lock:
            operation = self.get(operation_id)
            if operation.history_persisted or operation.history_persisting:
                return False
            operation.history_persisting = True
            return True

    def finish_history_persistence(
        self,
        operation_id: str,
        *,
        succeeded: bool,
    ) -> None:
        """Commit the once guard only after both history records were written."""
        with self._lock:
            operation = self.get(operation_id)
            operation.history_persisting = False
            if succeeded:
                operation.history_persisted = True
            self._commit_locked()

    def snapshot(self, operation_id: str) -> Dict[str, Any]:
        with self._lock:
            operation = self.get(operation_id)
            cli_process = self._cli_processes.get(operation_id)
            return {
                "operation_id": operation.operation_id,
                "run_id": operation.run_id,
                "runId": operation.run_id,
                "session_id": operation.request.session_id,
                "chat_mode": operation.request.chat_mode,
                "card_id": operation.request.card_id,
                "request": {
                    "operation_id": operation.request.operation_id,
                    "session_id": operation.request.session_id,
                    "chat_mode": operation.request.chat_mode,
                    "card_id": operation.request.card_id,
                    "include_context": operation.request.include_context,
                    "confirm": operation.request.confirm,
                    "backend": operation.request.backend,
                },
                "request_fingerprint": operation.request_fingerprint,
                "state": operation.state,
                "state_history": list(operation.state_history),
                "transport": operation.transport,
                "cancel_requested": operation.cancel_requested,
                "cancel_confirmed": operation.cancel_confirmed,
                "cancel_error": operation.cancel_error,
                "error": operation.error,
                "history_persisted": operation.history_persisted,
                "history_persisting": operation.history_persisting,
                "created_at": operation.created_at,
                "updated_at": operation.updated_at,
                "terminal_at": operation.terminal_at,
                "terminal": operation.is_terminal,
                "live": (
                    operation.task is not None
                    and not operation.task.done()
                ),
                "recovered": operation.recovered,
                "recovered_from_state": operation.recovered_from_state,
                "outcome_known": operation.is_terminal,
                "can_resume": False,
                "can_cancel": (
                    not operation.is_terminal
                    and (
                        not operation.recovered
                        or not operation.dispatch_started
                        or operation.transport == "gateway"
                    )
                ),
                "dispatch_started": operation.dispatch_started,
                "result_meta": copy.deepcopy(operation.result_meta),
                "subscriber_count": len(operation.subscribers),
                "cli_pid": (
                    cli_process.process.pid
                    if cli_process is not None
                    else None
                ),
                "cli_pgid": (
                    cli_process.pgid if cli_process is not None else None
                ),
                "cli_cancel_requested": (
                    cli_process.cancel_requested
                    if cli_process is not None
                    else False
                ),
            }

    def active_for_session(self, session_id: str) -> List[ChatOperation]:
        with self._lock:
            return self._active_for_session_locked(session_id)

    def snapshots_for_session(self, session_id: str) -> List[Dict[str, Any]]:
        with self._lock:
            operations = sorted(
                (
                    operation
                    for operation in self._operations.values()
                    if operation.session_id == session_id
                ),
                key=lambda operation: operation.created_at,
            )
            return [
                self.snapshot(operation.operation_id)
                for operation in operations
            ]

    def prepare_session_delete(
        self,
        session_id: str,
        *,
        force: bool,
    ) -> Tuple[List[ChatOperation], bool]:
        """Atomically reject active ordinary deletes or tombstone forced ones."""
        with self._lock:
            active = self._active_for_session_locked(session_id)
            if active and not force:
                return active, False
            self._tombstones.add(session_id)
            self._commit_locked()
            return active, True

    def tombstone_session(self, session_id: str) -> None:
        with self._lock:
            self._tombstones.add(session_id)
            self._commit_locked()

    @contextlib.contextmanager
    def session_mutation_guard(self, session_id: str):
        """Serialize local session creation with tombstone/delete preparation."""
        with self._lock:
            if session_id in self._tombstones:
                raise SessionTombstonedError(
                    f"session is tombstoned: {session_id}"
                )
            yield

    def is_tombstoned(self, session_id: str) -> bool:
        with self._lock:
            return session_id in self._tombstones

    def _active_for_session_locked(
        self,
        session_id: str,
    ) -> List[ChatOperation]:
        return sorted(
            [
                operation
                for operation in self._operations.values()
                if operation.session_id == session_id
                and operation.state in ACTIVE_STATES
            ],
            key=lambda operation: operation.created_at,
        )

    async def cancel(self, operation_id: str) -> Dict[str, Any]:
        with self._lock:
            operation = self.get(operation_id)
            if operation.is_terminal:
                return {
                    "status": "already_terminal",
                    "cancelled": operation.state == "cancelled",
                    "state": operation.state,
                    "operation_id": operation_id,
                }
            if (
                operation.state == "cancelling"
                and operation.cancel_result is not None
            ):
                return copy.deepcopy(operation.cancel_result)
            if (
                operation.cancel_future is not None
                and not operation.cancel_future.done()
            ):
                shared_future = operation.cancel_future
                is_leader = False
            else:
                shared_future = concurrent.futures.Future()
                operation.cancel_future = shared_future
                is_leader = True
            operation.cancel_requested = True
            operation.cancel_confirmed = False
            operation.cancel_error = None
            handler = operation.cancel_handler
            task = operation.task
            pre_transport = (
                operation.state in {"queued", "starting"}
                and operation.transport is None
            )
            self._commit_locked()

        if not is_leader:
            return copy.deepcopy(
                await asyncio.shield(
                    asyncio.wrap_future(shared_future)
                )
            )

        try:
            result = await self._cancel_once(
                operation_id,
                handler=handler,
                task=task,
                pre_transport=pre_transport,
            )
        except BaseException as exc:
            if not shared_future.done():
                shared_future.set_exception(exc)
            with self._lock:
                operation = self._operations.get(operation_id)
                if operation is not None:
                    operation.cancel_requested = False
                    operation.cancel_error = str(exc)
                    self._commit_locked()
            raise
        else:
            if not shared_future.done():
                shared_future.set_result(copy.deepcopy(result))
            return result
        finally:
            with self._lock:
                operation = self._operations.get(operation_id)
                if (
                    operation is not None
                    and operation.cancel_future is shared_future
                ):
                    operation.cancel_future = None

    async def _cancel_once(
        self,
        operation_id: str,
        *,
        handler: Optional[CancelHandler],
        task: Optional[asyncio.Task],
        pre_transport: bool,
    ) -> Dict[str, Any]:
        if pre_transport:
            self.transition(operation_id, "cancelling")
            if task is not None and not task.done():
                task.cancel()
                with contextlib.suppress(
                    asyncio.CancelledError,
                    Exception,
                ):
                    await task
            if not self.get(operation_id).is_terminal:
                self.transition(operation_id, "cancelled")
            current = self.get(operation_id)
            with self._lock:
                current.cancel_requested = True
                current.cancel_confirmed = True
                self._commit_locked()
            result = {
                "status": (
                    "cancelled"
                    if current.state == "cancelled"
                    else "already_terminal"
                ),
                "cancelled": current.state == "cancelled",
                "state": current.state,
                "operation_id": operation_id,
            }
            with self._lock:
                self.get(operation_id).cancel_result = copy.deepcopy(result)
            return result

        if handler is None:
            with self._lock:
                operation = self.get(operation_id)
                operation.cancel_requested = operation.is_recovered_unknown
                operation.cancel_error = (
                    "no cancellation transport is registered"
                )
                self._commit_locked()
                self._publish_locked(
                    operation,
                    self._state_event(operation),
                )
            return {
                "status": "unavailable",
                "cancelled": False,
                "state": operation.state,
                "operation_id": operation_id,
                "detail": operation.cancel_error,
            }

        try:
            result = await handler()
        except Exception as exc:
            result = {
                "status": "error",
                "cancelled": False,
                "detail": str(exc),
            }

        status = str(result.get("status") or "error")
        accepted = (
            status in {"accepted", "cancelled"}
            or result.get("cancelled") is True
        )
        if not accepted:
            with self._lock:
                operation = self.get(operation_id)
                if operation.is_terminal:
                    terminal_result = {
                        **result,
                        "status": "already_terminal",
                        "cancelled": operation.state == "cancelled",
                        "state": operation.state,
                        "operation_id": operation_id,
                    }
                    operation.cancel_requested = (
                        operation.state == "cancelled"
                    )
                    operation.cancel_confirmed = operation.state == "cancelled"
                    operation.cancel_error = None
                    operation.cancel_result = copy.deepcopy(
                        terminal_result
                    )
                    self._commit_locked()
                    return terminal_result
                operation.cancel_requested = operation.is_recovered_unknown
                operation.cancel_error = str(
                    result.get("detail")
                    or result.get("error")
                    or status
                )
                self._commit_locked()
                self._publish_locked(
                    operation,
                    self._state_event(operation),
                )
            return {
                **result,
                "cancelled": False,
                "state": operation.state,
                "operation_id": operation_id,
            }

        operation = self.get(operation_id)
        if operation.is_terminal:
            terminal_result = {
                **result,
                "status": "already_terminal",
                "cancelled": operation.state == "cancelled",
                "state": operation.state,
                "operation_id": operation_id,
            }
            with self._lock:
                operation.cancel_requested = operation.state == "cancelled"
                operation.cancel_confirmed = operation.state == "cancelled"
                operation.cancel_result = copy.deepcopy(terminal_result)
                self._commit_locked()
            return terminal_result

        with self._lock:
            operation = self.get(operation_id)
            operation.cancel_confirmed = True
            self._commit_locked()
        self.transition(
            operation_id,
            "cancelling",
            transport=operation.transport,
        )
        operation = self.get(operation_id)
        if operation.is_terminal and operation.state != "cancelling":
            terminal_result = {
                **result,
                "status": "already_terminal",
                "cancelled": operation.state == "cancelled",
                "state": operation.state,
                "operation_id": operation_id,
            }
            with self._lock:
                operation.cancel_requested = operation.state == "cancelled"
                operation.cancel_result = copy.deepcopy(terminal_result)
            return terminal_result
        if task is not None and not task.done():
            task.cancel()
        elif not self.get(operation_id).is_terminal:
            self.transition(operation_id, "cancelled")
        current = self.get(operation_id)
        cancellation_won = current.state in {"cancelling", "cancelled"}
        final_result = {
            **result,
            "status": (
                str(result.get("status") or "cancelled")
                if cancellation_won
                else "already_terminal"
            ),
            "cancelled": cancellation_won,
            "state": current.state,
            "operation_id": operation_id,
        }
        with self._lock:
            current.cancel_requested = cancellation_won
            current.cancel_confirmed = cancellation_won
            current.cancel_result = copy.deepcopy(
                final_result
            )
            self._commit_locked()
        return final_result

    async def wait_terminal(
        self, operation_id: str, timeout: float = 10.0
    ) -> ChatOperation:
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout
        while True:
            operation = self.get(operation_id)
            if operation.is_terminal:
                return operation
            if loop.time() >= deadline:
                raise asyncio.TimeoutError(
                    f"operation did not become terminal: {operation_id}"
                )
            await asyncio.sleep(0.01)

    async def subscribe(
        self, operation_id: str, heartbeat_seconds: float = 12.0
    ) -> AsyncGenerator[Optional[Dict[str, Any]], None]:
        """Replay existing events, then stream new ones.

        ``None`` is a heartbeat marker.  Removing this generator only removes its
        queue from ``subscribers``; the operation task is deliberately untouched.
        """
        loop = asyncio.get_running_loop()
        queue: asyncio.Queue = asyncio.Queue()
        subscriber: Subscriber = (loop, queue)
        with self._lock:
            operation = self.get(operation_id)
            replay = copy.deepcopy(operation.events)
            terminal_at_subscribe = operation.is_terminal
            unknown_at_subscribe = operation.state == "unknown_remote"
            if not terminal_at_subscribe and not unknown_at_subscribe:
                operation.subscribers.add(subscriber)

        try:
            for event in replay:
                yield event
            if terminal_at_subscribe or unknown_at_subscribe:
                return

            while True:
                try:
                    event = await asyncio.wait_for(
                        queue.get(), timeout=heartbeat_seconds
                    )
                except asyncio.TimeoutError:
                    yield None
                    continue
                yield copy.deepcopy(event)
                if (
                    event.get("type") == "operation"
                    and (
                        event.get("state") in TERMINAL_STATES
                        or event.get("state") == "unknown_remote"
                    )
                ):
                    return
        finally:
            with self._lock:
                operation = self._operations.get(operation_id)
                if operation is not None:
                    operation.subscribers.discard(subscriber)

    def reset_for_tests(self) -> None:
        """Clear in-memory state without awaiting external work."""
        with self._lock:
            tasks = [
                operation.task
                for operation in self._operations.values()
                if operation.task is not None and not operation.task.done()
            ]
            self._operations.clear()
            self._cli_processes.clear()
            self._tombstones.clear()
            self._journal_path = None
            self._journal_error = None
        for task in tasks:
            try:
                task.cancel()
            except (RuntimeError, AttributeError):
                pass

    def _state_event(
        self,
        operation: ChatOperation,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        event = {
            "type": "operation",
            "operation_id": operation.operation_id,
            "run_id": operation.run_id,
            "runId": operation.run_id,
            "session_id": operation.session_id,
            "state": operation.state,
            "transport": operation.transport,
            "terminal": operation.is_terminal,
            "cancel_requested": operation.cancel_requested,
            "cancel_confirmed": operation.cancel_confirmed,
            "dispatch_started": operation.dispatch_started,
            "recovered": operation.recovered,
        }
        if operation.recovered_from_state:
            event["recovered_from_state"] = operation.recovered_from_state
        if operation.error:
            event["error"] = operation.error
        if operation.cancel_error:
            event["cancel_error"] = operation.cancel_error
        if metadata:
            event.update(copy.deepcopy(metadata))
        return event

    def _publish_locked(
        self, operation: ChatOperation, event: Dict[str, Any]
    ) -> None:
        payload = copy.deepcopy(event)
        operation.events.append(payload)
        subscribers = list(operation.subscribers)
        for loop, queue in subscribers:
            try:
                current_loop = asyncio.get_running_loop()
            except RuntimeError:
                current_loop = None
            if current_loop is loop:
                queue.put_nowait(copy.deepcopy(payload))
            elif loop.is_running():
                try:
                    loop.call_soon_threadsafe(
                        queue.put_nowait,
                        copy.deepcopy(payload),
                    )
                except RuntimeError:
                    # Subscriber loops can close concurrently with disconnect.
                    # A dead subscriber must never fail the background operation.
                    operation.subscribers.discard((loop, queue))
            else:
                operation.subscribers.discard((loop, queue))

    def _prune_terminal_locked(self, keep: int) -> None:
        if len(self._operations) < keep:
            return
        terminal = sorted(
            (
                operation
                for operation in self._operations.values()
                if operation.is_terminal and not operation.subscribers
            ),
            key=lambda operation: operation.terminal_at or operation.updated_at,
        )
        remove_count = max(0, len(self._operations) - keep + 1)
        for operation in terminal[:remove_count]:
            self._operations.pop(operation.operation_id, None)
            self._cli_processes.pop(operation.operation_id, None)


operation_registry = OperationRegistry()

