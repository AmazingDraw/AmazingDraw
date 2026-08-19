#!/usr/bin/env python3
"""
cu-queue.py — GPU 渲染队列管理器（JSON v2）
============================================
持久状态机：所有任务先入队，再通过 lease claim 后启动 worker。

用法:
  python3 cu-queue.py status
    → 队列状态

  python3 cu-queue.py enqueue <prompt_file> <meta_file> <done_file> [--lora X]
    → 加入队列

  python3 cu-queue.py resume
    → pending → leased（先落盘）→ spawn worker

  python3 cu-queue.py remove --position N
    → 删除指定位置的卡片（1-indexed）

  python3 cu-queue.py remove --fingerprint HASH
    → 按指纹删除指定卡片

  python3 cu-queue.py clear --force
    → 清空队列

  python3 cu-queue.py health
    → 健康检查（完整性 + 僵尸锁 + 进度）

  python3 cu-queue.py drafts
    → 列出/清理孤儿草稿卡

  python3 cu-queue.py clean-stale
    → 清理队列中引用已删除文件的过期任务

队列文件: <tmp_dir>/cu-queue.json（兼容读取旧 list 并原地迁移）
排他锁文件: <tmp_dir>/cu-queue.lock (使用 fcntl.flock 实现进程级事务排他锁)
格式: {"schema_version": 2, "revision": N, "jobs": [...]}
写入: 同目录 temp → fsync → os.replace；另存 cu-queue.json.last-good。
损坏 JSON: fail closed，不自动用旧快照覆盖现场。
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
import hashlib
import json
import os
import re
import secrets
import subprocess
import sys
import time
import uuid
from contextlib import contextmanager
from copy import deepcopy
from pathlib import Path
from card_config import TMP_DIR, CARDS_DIR
from typing import Iterator, Optional, Union
import fcntl

def load_config() -> dict:
    config_path = Path(__file__).resolve().parent.parent / "config.json"
    if config_path.exists():
        try:
            with open(config_path, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def _cfg_path(key: str, default: str) -> Path:
    cfg = load_config()
    raw = cfg.get(key) or default
    return Path(os.path.expanduser(str(raw))).resolve()


_lock_file_fd = None

def acquire_queue_lock(timeout_sec: float = 30.0) -> bool:
    """Acquire exclusive queue lock with timeout (non-blocking poll).

    Returns True on success. Callers must treat False as lock_busy and exit
    without mutating the queue file.
    """
    global _lock_file_fd
    lock_path = WORK_DIR / "cu-queue.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        _lock_file_fd = open(lock_path, "a")
    except Exception as e:
        print(f"⚠️ Warning: Failed to open queue lock: {e}", file=sys.stderr)
        return False

    deadline = time.monotonic() + max(0.0, float(timeout_sec))
    while True:
        try:
            fcntl.flock(_lock_file_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return True
        except BlockingIOError:
            if time.monotonic() >= deadline:
                return False
            time.sleep(0.05)
        except Exception as e:
            print(f"⚠️ Warning: Failed to acquire queue lock: {e}", file=sys.stderr)
            return False

WORK_DIR = Path(os.path.expanduser(os.environ.get("CU_WORK_DIR") or str(
    _cfg_path("tmp_dir", "/tmp/cu-card")
))).resolve()
QUEUE_FILE = WORK_DIR / "cu-queue.json"
LOCK_FILE = WORK_DIR / "cu-gpu.lock"
PAUSED_STATE = WORK_DIR / "cu-paused-task.json"
ZOMBIE_ALERT_FILE = WORK_DIR / "cu-gpu-zombie-alert.json"
PID_GLOB = "cu-submit-bg_*.pid"
ZOMBIE_LOCK_THRESHOLD = 1800
# DONE 已落盘后交付阶段卡死阈值（外置盘 cp / Telegram 僵死等）
DELIVER_STUCK_THRESHOLD = 600
CARDS_DIR = Path(os.path.expanduser(os.environ.get("CU_CARDS_DIR") or str(
    _cfg_path("cards_dir", str(CARDS_DIR))
))).resolve()
# 与 cu-submit.sh 提交提示一致：取最近 N 次成功交付的 elapsed 均值（分钟）
ETA_HISTORY_N = 5


def avg_recent_delivery_elapsed_min(n: int = ETA_HISTORY_N) -> Optional[float]:
    """最近 N 次 success-delivery 的 elapsed 均值（分钟）。无记录则返回 None。"""
    return avg_recent_delivery_elapsed_info(n).get("avg_min")


def avg_recent_delivery_elapsed_info(n: int = ETA_HISTORY_N) -> dict:
    """供 health / avg-eta / submit 共用的 ETA 快照。"""
    success_dir = WORK_DIR / "success-delivery"
    elapsed_times: list[float] = []
    if success_dir.is_dir():
        files = sorted(success_dir.glob("delivery_success_*.json"), key=lambda p: p.stat().st_mtime)
        for path in files[-max(1, int(n)):]:
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                val = data.get("elapsed")
                if val is None:
                    continue
                minutes = float(val)
                if minutes > 0:
                    elapsed_times.append(minutes)
            except (OSError, ValueError, TypeError, json.JSONDecodeError):
                continue
    avg = (sum(elapsed_times) / len(elapsed_times)) if elapsed_times else None
    return {
        "avg_min": round(avg, 1) if avg is not None else None,
        "sample_count": len(elapsed_times),
        "window": int(n),
        "source": "success-delivery" if avg is not None else "none",
    }


def acquire_gpu_lock() -> bool:
    """原子获取 GPU 锁（O_EXCL），避免 check→touch TOCTOU 双开渲染。"""
    WORK_DIR.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(str(LOCK_FILE), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        try:
            os.write(fd, f"{os.getpid()}\n".encode())
        finally:
            os.close(fd)
        return True
    except FileExistsError:
        return False


def comfyui_host() -> str:
    return (load_config().get("comfyui_host") or "http://127.0.0.1:8188").rstrip("/")


def comfyui_queue_busy() -> bool:
    """ComfyUI /queue 是否仍有 running/pending。探测失败时保守视为 busy。"""
    try:
        import urllib.request
        resp = urllib.request.urlopen(f"{comfyui_host()}/queue", timeout=3)
        qdata = json.loads(resp.read())
        return bool(qdata.get("queue_running") or qdata.get("queue_pending"))
    except Exception:
        return True


def comfy_vram_free_bytes() -> Optional[int]:
    """读取 Comfy /system_stats 的 vram_free（字节）。失败返回 None。"""
    try:
        import urllib.request
        resp = urllib.request.urlopen(f"{comfyui_host()}/system_stats", timeout=3)
        data = json.loads(resp.read())
        devices = data.get("devices") or []
        if not devices:
            return None
        d0 = devices[0] or {}
        # 优先 torch 侧空闲，其次设备空闲
        for key in ("torch_vram_free", "vram_free"):
            val = d0.get(key)
            if isinstance(val, (int, float)):
                return int(val)
        return None
    except Exception:
        return None


def cmd_free_memory(if_queued: bool = False) -> dict:
    """交付后调用 Comfy /free，卸载模型并等内存回升后再续跑。

    由 cu-deliver 在 CU_BETWEEN_CARDS=free 时调用（与 restart 平级）。
    单张/队列空时 deliver 不会走到此路径；--if-queued 为双保险。

    环境变量:
      CU_FREE_BETWEEN=0  → 关闭本步骤（仅 free 模式）
      CU_FREE_TIMEOUT    → 等待超时秒数（默认 90）
    """
    import urllib.error
    import urllib.request

    enabled = (os.environ.get("CU_FREE_BETWEEN") or "1").strip().lower()
    if enabled in {"0", "false", "no", "off"}:
        return {"status": "skipped", "reason": "disabled"}

    queue = read_queue()
    if if_queued and not queue:
        return {"status": "skipped", "reason": "queue_empty"}

    timeout_s = 90.0
    raw_timeout = (os.environ.get("CU_FREE_TIMEOUT") or "").strip()
    if raw_timeout:
        try:
            timeout_s = max(5.0, float(raw_timeout))
        except ValueError:
            pass

    before_free = comfy_vram_free_bytes()
    host = comfyui_host()
    payload = json.dumps({"unload_models": True, "free_memory": True}).encode("utf-8")
    req = urllib.request.Request(
        f"{host}/free",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            http_status = getattr(resp, "status", 200)
    except urllib.error.HTTPError as e:
        return {"status": "error", "reason": f"http_{e.code}", "before_vram_free": before_free}
    except Exception as e:
        return {"status": "skipped", "reason": f"comfy_unreachable:{type(e).__name__}", "before_vram_free": before_free}

    # /free 通过 prompt worker flag 异步执行；轮询至空闲且显存有回升，或超时
    started = time.time()
    deadline = started + timeout_s
    after_free = before_free
    recovered = False
    while time.time() < deadline:
        busy = comfyui_queue_busy()
        after_free = comfy_vram_free_bytes()
        if not busy:
            if before_free is None or after_free is None:
                # 无法读显存时，给 worker 一点时间消化 flag
                time.sleep(2.0)
                recovered = True
                break
            # 回升至少 512MB，或绝对空闲已较高（>8GB）则认为卸载生效
            gained = after_free - before_free
            if gained >= 512 * 1024 * 1024 or after_free >= 8 * 1024 * 1024 * 1024:
                recovered = True
                break
        time.sleep(1.0)

    return {
        "status": "ok" if recovered else "timeout",
        "http_status": http_status,
        "waited_sec": round(time.time() - started, 1),
        "timeout_sec": timeout_s,
        "before_vram_free": before_free,
        "after_vram_free": after_free,
        "queue_remaining": len(queue),
    }


def deliver_stuck_entries(threshold_sec: float = DELIVER_STUCK_THRESHOLD) -> list[dict]:
    """DONE 已存在且超时、Comfy 空闲 → 判定交付僵死（典型：外置盘 cp 挂死）。"""
    if comfyui_queue_busy():
        return []
    stuck = []
    now = time.time()
    for item in active_worker_entries():
        done_file = item.get("done_file") or ""
        if not done_file:
            continue
        done_path = Path(done_file)
        if not done_path.is_file():
            continue
        try:
            age = now - done_path.stat().st_mtime
        except OSError:
            continue
        if age > threshold_sec:
            stuck.append({**item, "done_age": int(age)})
    return stuck


def heal_deliver_stuck(threshold_sec: float = DELIVER_STUCK_THRESHOLD) -> dict:
    """强杀交付僵死 worker 树并清 GPU 锁，返回处置结果。"""
    stuck = deliver_stuck_entries(threshold_sec)
    if not stuck:
        return {"healed": False, "killed": []}
    killed = []
    for item in stuck:
        pid = item.get("pid")
        if not pid:
            continue
        try:
            os.kill(int(pid), 9)
            killed.append(int(pid))
        except OSError:
            pass
        # 清理对应 pid 文件
        for pid_file in WORK_DIR.glob(PID_GLOB):
            try:
                raw = pid_file.read_text(encoding="utf-8").strip()
                if raw.isdigit() and int(raw) == int(pid):
                    pid_file.unlink(missing_ok=True)
            except Exception:
                pass
    # 连带清理可能残留的 deliver/cp（best-effort）
    try:
        import subprocess
        subprocess.run(["pkill", "-9", "-f", "cu-deliver.sh"], check=False, capture_output=True)
    except Exception:
        pass
    LOCK_FILE.unlink(missing_ok=True)
    return {"healed": True, "killed": killed, "count": len(stuck)}


GLOBAL_CONFIG = load_config()
WORKSPACE = Path(os.path.expanduser(
    os.environ.get("CU_WORKSPACE")
    or GLOBAL_CONFIG.get("openclaw_workspace_dir")
    or "~/.openclaw/workspace"
)).resolve()
_GPU_DIR = Path(__file__).resolve().parent
DETACHED_SPAWN = Path(os.environ.get("CU_DETACHED_SPAWN") or (_GPU_DIR / "detached_spawn.py")).resolve()
WORKER_SCRIPT = Path(os.environ.get("CU_WORKER_SCRIPT") or (_GPU_DIR / "cu-worker.sh")).resolve()


class QueueError(RuntimeError):
    """Base class for durable queue failures."""


class QueueLockBusy(QueueError):
    """The queue transaction lock could not be acquired in time."""


class QueueCorruptError(QueueError):
    """The queue file is unreadable or violates the v2 envelope."""


class QueueStore:
    """Durable JSON v2 GPU queue with leases and token-conditional completion."""

    SCHEMA_VERSION = 2
    STATES = {
        "pending",
        "leased",
        "running",
        "completed",
        "failed",
        "retry_wait",
        "paused",
    }
    WAITING_STATES = {"pending", "retry_wait"}
    ACTIVE_LEASE_STATES = {"leased", "running"}
    TERMINAL_STATES = {"completed", "failed"}

    def __init__(self, work_dir: Union[str, Path], lease_seconds: Optional[float] = None):
        self.work_dir = Path(work_dir).expanduser().resolve()
        self.queue_path = self.work_dir / "cu-queue.json"
        self.last_good_path = self.work_dir / "cu-queue.json.last-good"
        self.lock_path = self.work_dir / "cu-queue.lock"
        raw_lease = lease_seconds
        if raw_lease is None:
            raw_lease = os.environ.get("CU_LEASE_SECONDS") or "7200"
        try:
            self.lease_seconds = max(0.01, float(raw_lease))
        except (TypeError, ValueError):
            self.lease_seconds = 7200.0
        try:
            self.max_attempts = max(1, int(os.environ.get("CU_MAX_ATTEMPTS") or "3"))
        except ValueError:
            self.max_attempts = 3
        try:
            self.retry_delay = max(0.0, float(os.environ.get("CU_RETRY_DELAY") or "30"))
        except ValueError:
            self.retry_delay = 30.0

    @staticmethod
    def _blank() -> dict:
        return {"schema_version": 2, "revision": 0, "jobs": []}

    @staticmethod
    def _int_or_none(value) -> Optional[int]:
        if value in (None, "", "null"):
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _now() -> float:
        return time.time()

    def _job_from_raw(self, raw: dict, *, new_job: bool = False) -> dict:
        if not isinstance(raw, dict):
            raise QueueCorruptError("queue job must be an object")

        files = raw.get("files")
        if files is None:
            files = {}
        elif not isinstance(files, dict):
            raise QueueCorruptError("queue job files must be an object")
        prompt = str(
            files.get("prompt")
            or files.get("prompt_file")
            or raw.get("prompt")
            or raw.get("prompt_file")
            or ""
        )
        meta = str(
            files.get("meta")
            or files.get("meta_file")
            or raw.get("meta")
            or raw.get("meta_file")
            or ""
        )
        done = str(
            files.get("done")
            or files.get("done_file")
            or raw.get("done")
            or raw.get("done_file")
            or ""
        )
        meta_data = {}
        if meta:
            try:
                parsed = json.loads(Path(meta).read_text(encoding="utf-8"))
                meta_data = parsed if isinstance(parsed, dict) else {}
            except Exception:
                meta_data = {}

        card_id = str(raw.get("card_id") or meta_data.get("card_id") or "")
        idempotency_key = str(
            raw.get("idempotency_key")
            or raw.get("fingerprint")
            or ""
        )
        if not idempotency_key:
            idem_payload = {
                "prompt": normalize_text(read_text(Path(prompt))) if prompt else "",
                "meta": meta_data,
                "workflow": raw.get("workflow") or "",
                "seed": self._int_or_none(raw.get("seed")),
                "lora": raw.get("lora") or "",
                "width": self._int_or_none(raw.get("width")) or 0,
                "height": self._int_or_none(raw.get("height")) or 0,
            }
            encoded = json.dumps(
                idem_payload,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
            idempotency_key = hashlib.sha256(encoded).hexdigest()

        raw_job_id = str(raw.get("job_id") or "")
        if raw_job_id:
            job_id = raw_job_id
        elif new_job:
            job_id = f"job-{uuid.uuid4().hex}"
        else:
            stable = json.dumps(raw, ensure_ascii=False, sort_keys=True, default=str)
            job_id = f"legacy-{hashlib.sha256(stable.encode('utf-8')).hexdigest()[:24]}"

        state = str(raw.get("state") or "pending")
        state = {"queued": "pending"}.get(state, state)
        if state not in self.STATES:
            state = "pending"
        lease = raw.get("lease")
        if not isinstance(lease, dict) or not lease.get("token"):
            lease = None
            if state in self.ACTIVE_LEASE_STATES:
                state = "pending"

        now = self._now()
        job = {
            "job_id": job_id,
            "card_id": card_id,
            "idempotency_key": idempotency_key,
            "workflow": str(raw.get("workflow") or ""),
            "seed": self._int_or_none(raw.get("seed")),
            "lora": str(raw.get("lora") or ""),
            "width": self._int_or_none(raw.get("width")) or self._int_or_none(meta_data.get("width")) or 0,
            "height": self._int_or_none(raw.get("height")) or self._int_or_none(meta_data.get("height")) or 0,
            "files": {
                "prompt": prompt,
                "meta": meta,
                "done": done,
            },
            # Keep the v1 aliases in every v2 record so older status/health
            # consumers remain usable while `files` is the canonical bundle.
            "prompt": prompt,
            "meta": meta,
            "done": done,
            "state": state,
            "attempt": max(0, self._int_or_none(raw.get("attempt")) or 0),
            "lease": deepcopy(lease),
            "created_at": float(raw.get("created_at") or (float(raw.get("ts") or 0) / 1_000_000_000) or now),
            "updated_at": float(raw.get("updated_at") or now),
        }
        for key in (
            "retry_at",
            "completed_at",
            "failed_at",
            "paused_at",
            "error",
            "ack_token",
            "last_lease_token",
            "worker_pid",
            "worker_log",
            "result",
        ):
            if key in raw:
                job[key] = deepcopy(raw[key])
        return job

    def _decode(self, raw) -> tuple[dict, bool]:
        migrated = False
        if isinstance(raw, list):
            snapshot = self._blank()
            snapshot["jobs"] = [self._job_from_raw(item) for item in raw]
            return snapshot, True
        if not isinstance(raw, dict):
            raise QueueCorruptError("queue root must be a v1 list or v2 object")
        if raw.get("schema_version") != self.SCHEMA_VERSION:
            raise QueueCorruptError(
                f"unsupported queue schema_version: {raw.get('schema_version')!r}"
            )
        if not isinstance(raw.get("jobs"), list):
            raise QueueCorruptError("queue jobs must be a list")
        try:
            revision = int(raw.get("revision", 0))
        except (TypeError, ValueError) as exc:
            raise QueueCorruptError("queue revision must be an integer") from exc
        jobs = [self._job_from_raw(item) for item in raw["jobs"]]
        snapshot = {
            "schema_version": self.SCHEMA_VERSION,
            "revision": max(0, revision),
            "jobs": jobs,
        }
        if jobs != raw["jobs"] or set(raw) != {"schema_version", "revision", "jobs"}:
            migrated = True
        return snapshot, migrated

    def _atomic_write(self, path: Path, snapshot: dict) -> None:
        self.work_dir.mkdir(parents=True, exist_ok=True)
        payload = (
            json.dumps(snapshot, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        ).encode("utf-8")
        temp = path.parent / f".{path.name}.tmp-{os.getpid()}-{uuid.uuid4().hex}"
        fd = None
        try:
            fd = os.open(str(temp), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            with os.fdopen(fd, "wb") as handle:
                fd = None
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp, path)
            try:
                dir_fd = os.open(str(path.parent), os.O_RDONLY)
                try:
                    os.fsync(dir_fd)
                finally:
                    os.close(dir_fd)
            except OSError:
                # Some filesystems do not support fsync on directories.
                pass
        finally:
            if fd is not None:
                os.close(fd)
            temp.unlink(missing_ok=True)

    def _save_unlocked(self, snapshot: dict) -> dict:
        clean = {
            "schema_version": self.SCHEMA_VERSION,
            "revision": int(snapshot.get("revision") or 0) + 1,
            "jobs": [self._job_from_raw(job) for job in snapshot.get("jobs") or []],
        }
        # Main queue is replaced first. If this replace fails, both current and
        # last-known-good remain untouched.
        self._atomic_write(self.queue_path, clean)
        try:
            self._atomic_write(self.last_good_path, clean)
        except OSError as exc:
            print(f"⚠️ queue last-known-good update failed: {exc}", file=sys.stderr)
        snapshot.clear()
        snapshot.update(deepcopy(clean))
        return clean

    def _load_unlocked(self) -> dict:
        if not self.queue_path.exists():
            return self._blank()
        try:
            raw = json.loads(self.queue_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise QueueCorruptError(
                f"queue JSON is corrupt; refusing fallback/write: {exc}"
            ) from exc
        snapshot, migrated = self._decode(raw)
        if migrated:
            self._save_unlocked(snapshot)
        return snapshot

    @contextmanager
    def locked(self, timeout: Optional[float] = None) -> Iterator[None]:
        self.work_dir.mkdir(parents=True, exist_ok=True)
        if timeout is None:
            try:
                timeout = float(os.environ.get("CU_QUEUE_LOCK_TIMEOUT") or "30")
            except ValueError:
                timeout = 30.0
        deadline = time.monotonic() + max(0.0, float(timeout))
        handle = self.lock_path.open("a+")
        try:
            while True:
                try:
                    fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    if time.monotonic() >= deadline:
                        raise QueueLockBusy("queue lock held by another process")
                    time.sleep(0.02)
            yield
        finally:
            try:
                fcntl.flock(handle, fcntl.LOCK_UN)
            except OSError:
                pass
            handle.close()

    def _maintain_unlocked(self, snapshot: dict) -> list[str]:
        now = self._now()
        changed: list[str] = []
        for job in snapshot["jobs"]:
            state = job.get("state")
            lease = job.get("lease")
            if state in self.ACTIVE_LEASE_STATES:
                expires_at = float((lease or {}).get("expires_at") or 0)
                if not lease or expires_at <= now:
                    job["state"] = "pending"
                    job["lease"] = None
                    job["error"] = "lease_expired"
                    job["updated_at"] = now
                    changed.append(job["job_id"])
            elif state == "retry_wait":
                retry_at = float(job.get("retry_at") or 0)
                if retry_at <= now:
                    job["state"] = "pending"
                    job.pop("retry_at", None)
                    job["updated_at"] = now
                    changed.append(job["job_id"])
        return changed

    def _load_maintained_unlocked(self) -> dict:
        snapshot = self._load_unlocked()
        if self._maintain_unlocked(snapshot):
            self._save_unlocked(snapshot)
        return snapshot

    @staticmethod
    def _find_unlocked(snapshot: dict, job_id: str) -> Optional[dict]:
        return next(
            (job for job in snapshot["jobs"] if job.get("job_id") == job_id),
            None,
        )

    @staticmethod
    def _lease_matches(job: dict, token: str) -> bool:
        return bool(token) and str((job.get("lease") or {}).get("token") or "") == str(token)

    def snapshot(self) -> dict:
        with self.locked():
            return deepcopy(self._load_maintained_unlocked())

    def save_snapshot(self, snapshot: dict) -> dict:
        with self.locked():
            return deepcopy(self._save_unlocked(deepcopy(snapshot)))

    def enqueue(self, payload: dict) -> dict:
        candidate = self._job_from_raw(payload, new_job=True)
        candidate["state"] = "pending"
        candidate["attempt"] = 0
        candidate["lease"] = None
        now = self._now()
        candidate["created_at"] = now
        candidate["updated_at"] = now
        with self.locked():
            snapshot = self._load_maintained_unlocked()
            for job in snapshot["jobs"]:
                if (
                    job.get("card_id") == candidate["card_id"]
                    and job.get("idempotency_key") == candidate["idempotency_key"]
                ):
                    return {
                        "ok": True,
                        "status": "duplicate",
                        "job_id": job["job_id"],
                        "card_id": job.get("card_id") or "",
                        "state": job.get("state"),
                        "job": deepcopy(job),
                    }
            snapshot["jobs"].append(candidate)
            saved = self._save_unlocked(snapshot)
            waiting = [
                job for job in saved["jobs"] if job.get("state") in self.WAITING_STATES
            ]
            position = next(
                (idx for idx, job in enumerate(waiting, 1) if job["job_id"] == candidate["job_id"]),
                len(waiting),
            )
            return {
                "ok": True,
                "status": "queued",
                "job_id": candidate["job_id"],
                "card_id": candidate["card_id"],
                "state": "pending",
                "position": position,
                "idempotency_key": candidate["idempotency_key"],
                "job": deepcopy(candidate),
            }

    def claim(self, owner: str = "", job_id: Optional[str] = None) -> dict:
        with self.locked():
            snapshot = self._load_maintained_unlocked()
            candidates = [
                job for job in snapshot["jobs"] if job.get("state") == "pending"
            ]
            if job_id:
                candidates = [job for job in candidates if job.get("job_id") == job_id]
            if not candidates:
                return {"ok": True, "status": "empty"}
            job = candidates[0]
            now = self._now()
            token = secrets.token_urlsafe(32)
            job["state"] = "leased"
            job["attempt"] = int(job.get("attempt") or 0) + 1
            job["lease"] = {
                "token": token,
                "owner": owner or f"claim-{os.getpid()}",
                "claimed_at": now,
                "heartbeat_at": now,
                "expires_at": now + self.lease_seconds,
            }
            job["updated_at"] = now
            self._save_unlocked(snapshot)
            return {
                "ok": True,
                "status": "claimed",
                "job_id": job["job_id"],
                "card_id": job.get("card_id") or "",
                "lease_token": token,
                "job": deepcopy(job),
            }

    def ready(self, job_id: str, token: str) -> dict:
        with self.locked():
            snapshot = self._load_maintained_unlocked()
            job = self._find_unlocked(snapshot, job_id)
            if not job:
                return {"ok": False, "status": "not_found", "job_id": job_id}
            if not self._lease_matches(job, token):
                return {"ok": False, "status": "lease_mismatch", "job_id": job_id}
            if job.get("state") not in self.ACTIVE_LEASE_STATES:
                return {"ok": False, "status": "invalid_state", "state": job.get("state"), "job_id": job_id}
            now = self._now()
            job["state"] = "running"
            job["lease"]["heartbeat_at"] = now
            job["lease"]["expires_at"] = now + self.lease_seconds
            job["worker_pid"] = os.getppid()
            job["updated_at"] = now
            self._save_unlocked(snapshot)
            return {"ok": True, "status": "running", "job_id": job_id, "state": "running"}

    def heartbeat(self, job_id: str, token: str) -> dict:
        with self.locked():
            snapshot = self._load_maintained_unlocked()
            job = self._find_unlocked(snapshot, job_id)
            if not job:
                return {"ok": False, "status": "not_found", "job_id": job_id}
            if not self._lease_matches(job, token):
                return {"ok": False, "status": "lease_mismatch", "job_id": job_id}
            if job.get("state") not in self.ACTIVE_LEASE_STATES:
                return {"ok": False, "status": "invalid_state", "state": job.get("state"), "job_id": job_id}
            now = self._now()
            job["lease"]["heartbeat_at"] = now
            job["lease"]["expires_at"] = now + self.lease_seconds
            job["updated_at"] = now
            self._save_unlocked(snapshot)
            return {"ok": True, "status": "heartbeat", "job_id": job_id, "state": job.get("state")}

    def ack(self, job_id: str, token: str, result: Optional[dict] = None) -> dict:
        with self.locked():
            snapshot = self._load_maintained_unlocked()
            job = self._find_unlocked(snapshot, job_id)
            if not job:
                return {"ok": False, "status": "not_found", "job_id": job_id}
            if job.get("state") == "completed":
                if str(job.get("ack_token") or "") == str(token):
                    return {"ok": True, "status": "already_completed", "job_id": job_id, "state": "completed"}
                return {"ok": False, "status": "lease_mismatch", "job_id": job_id}
            if not self._lease_matches(job, token):
                return {"ok": False, "status": "lease_mismatch", "job_id": job_id}
            if job.get("state") not in self.ACTIVE_LEASE_STATES:
                return {"ok": False, "status": "invalid_state", "state": job.get("state"), "job_id": job_id}
            now = self._now()
            job["state"] = "completed"
            job["completed_at"] = now
            job["updated_at"] = now
            job["ack_token"] = token
            job["last_lease_token"] = token
            job["lease"] = None
            job.pop("retry_at", None)
            job.pop("error", None)
            if result is not None:
                job["result"] = deepcopy(result)
            self._save_unlocked(snapshot)
            return {"ok": True, "status": "completed", "job_id": job_id, "state": "completed"}

    def nack(
        self,
        job_id: str,
        token: str,
        error: str = "",
        *,
        retry: bool = True,
    ) -> dict:
        with self.locked():
            snapshot = self._load_maintained_unlocked()
            job = self._find_unlocked(snapshot, job_id)
            if not job:
                return {"ok": False, "status": "not_found", "job_id": job_id}
            if not self._lease_matches(job, token):
                return {"ok": False, "status": "lease_mismatch", "job_id": job_id}
            if job.get("state") not in self.ACTIVE_LEASE_STATES:
                return {"ok": False, "status": "invalid_state", "state": job.get("state"), "job_id": job_id}
            now = self._now()
            job["last_lease_token"] = token
            job["lease"] = None
            job["error"] = str(error or "worker_nack")
            job["updated_at"] = now
            if retry and int(job.get("attempt") or 0) < self.max_attempts:
                job["state"] = "retry_wait"
                job["retry_at"] = now + self.retry_delay
                status = "retry_wait"
            else:
                job["state"] = "failed"
                job["failed_at"] = now
                job.pop("retry_at", None)
                status = "failed"
            self._save_unlocked(snapshot)
            return {"ok": True, "status": status, "job_id": job_id, "state": status}

    def pause(self, job_id: str, token: str) -> dict:
        with self.locked():
            snapshot = self._load_maintained_unlocked()
            job = self._find_unlocked(snapshot, job_id)
            if not job:
                return {"ok": False, "status": "not_found", "job_id": job_id}
            if not self._lease_matches(job, token):
                return {"ok": False, "status": "lease_mismatch", "job_id": job_id}
            now = self._now()
            job["state"] = "paused"
            job["paused_at"] = now
            job["last_lease_token"] = token
            job["lease"] = None
            job["updated_at"] = now
            self._save_unlocked(snapshot)
            return {"ok": True, "status": "paused", "job_id": job_id, "state": "paused"}

    def resume_paused(self, job_id: Optional[str] = None) -> dict:
        with self.locked():
            snapshot = self._load_maintained_unlocked()
            paused = [
                job for job in snapshot["jobs"] if job.get("state") == "paused"
            ]
            if job_id:
                paused = [job for job in paused if job.get("job_id") == job_id]
            if not paused:
                return {"ok": True, "status": "no_paused"}
            job = paused[0]
            job["state"] = "pending"
            job["updated_at"] = self._now()
            job.pop("paused_at", None)
            self._save_unlocked(snapshot)
            return {"ok": True, "status": "pending", "job_id": job["job_id"], "state": "pending"}

    def reap_expired(self) -> dict:
        with self.locked():
            snapshot = self._load_unlocked()
            expired = self._maintain_unlocked(snapshot)
            if expired:
                self._save_unlocked(snapshot)
            return {"ok": True, "status": "reaped", "expired": expired}

    def get(self, job_id: str) -> Optional[dict]:
        with self.locked():
            snapshot = self._load_maintained_unlocked()
            job = self._find_unlocked(snapshot, job_id)
            return deepcopy(job) if job else None

    def remove(self, job_id: str) -> dict:
        with self.locked():
            snapshot = self._load_maintained_unlocked()
            job = self._find_unlocked(snapshot, job_id)
            if not job:
                return {"ok": False, "status": "not_found", "job_id": job_id}
            if job.get("state") in self.ACTIVE_LEASE_STATES:
                return {
                    "ok": False,
                    "status": "active_job",
                    "job_id": job_id,
                    "state": job.get("state"),
                }
            snapshot["jobs"] = [
                item for item in snapshot["jobs"] if item.get("job_id") != job_id
            ]
            self._save_unlocked(snapshot)
            remaining = sum(
                1 for item in snapshot["jobs"] if item.get("state") in self.WAITING_STATES
            )
            return {
                "ok": True,
                "status": "removed",
                "job_id": job_id,
                "card_id": job.get("card_id") or "",
                "item": deepcopy(job),
                "remaining": remaining,
            }

    def remove_by_position(self, position: int) -> dict:
        with self.locked():
            snapshot = self._load_maintained_unlocked()
            waiting = [
                job for job in snapshot["jobs"] if job.get("state") in self.WAITING_STATES
            ]
            if not waiting:
                return {"ok": True, "status": "empty"}
            if position < 1 or position > len(waiting):
                return {
                    "ok": False,
                    "status": "invalid_position",
                    "position": position,
                    "length": len(waiting),
                }
            job = waiting[position - 1]
            snapshot["jobs"] = [
                item for item in snapshot["jobs"] if item.get("job_id") != job["job_id"]
            ]
            self._save_unlocked(snapshot)
            return {
                "ok": True,
                "status": "removed",
                "job_id": job["job_id"],
                "card_id": job.get("card_id") or "",
                "item": deepcopy(job),
                "remaining": len(waiting) - 1,
            }

    def remove_by_idempotency(self, key: str) -> dict:
        with self.locked():
            snapshot = self._load_maintained_unlocked()
            matches = [
                job
                for job in snapshot["jobs"]
                if job.get("idempotency_key") == key
                and job.get("state") not in self.ACTIVE_LEASE_STATES
            ]
            if not matches:
                return {"ok": False, "status": "not_found", "fingerprint": key}
            ids = {job["job_id"] for job in matches}
            snapshot["jobs"] = [
                job for job in snapshot["jobs"] if job.get("job_id") not in ids
            ]
            self._save_unlocked(snapshot)
            return {
                "ok": True,
                "status": "removed",
                "removed_count": len(matches),
                "job_ids": sorted(ids),
                "card_ids": [job.get("card_id") or "" for job in matches],
                "remaining": sum(
                    1 for job in snapshot["jobs"] if job.get("state") in self.WAITING_STATES
                ),
            }

    def clear(self) -> dict:
        with self.locked():
            snapshot = self._load_maintained_unlocked()
            removable = [
                job
                for job in snapshot["jobs"]
                if job.get("state") in {"pending", "retry_wait", "paused"}
            ]
            if not removable:
                return {"ok": True, "status": "already_empty", "count": 0, "card_ids": []}
            ids = {job["job_id"] for job in removable}
            snapshot["jobs"] = [
                job for job in snapshot["jobs"] if job.get("job_id") not in ids
            ]
            self._save_unlocked(snapshot)
            return {
                "ok": True,
                "status": "cleared",
                "count": len(removable),
                "job_ids": sorted(ids),
                "card_ids": [job.get("card_id") or "" for job in removable],
            }

    def clean_stale(self) -> dict:
        with self.locked():
            snapshot = self._load_maintained_unlocked()
            stale = []
            for job in snapshot["jobs"]:
                if job.get("state") not in self.WAITING_STATES:
                    continue
                files = job.get("files") or {}
                prompt = str(files.get("prompt") or job.get("prompt") or "")
                meta = str(files.get("meta") or job.get("meta") or "")
                if (prompt and not Path(prompt).is_file()) or (meta and not Path(meta).is_file()):
                    stale.append(job)
            if stale:
                ids = {job["job_id"] for job in stale}
                snapshot["jobs"] = [
                    job for job in snapshot["jobs"] if job.get("job_id") not in ids
                ]
                self._save_unlocked(snapshot)
            return {
                "ok": True,
                "status": "cleaned",
                "removed": len(stale),
                "job_ids": [job["job_id"] for job in stale],
                "card_ids": [job.get("card_id") or "" for job in stale],
                "remaining": sum(
                    1 for job in snapshot["jobs"] if job.get("state") in self.WAITING_STATES
                ),
            }

    @staticmethod
    def legacy_view(job: dict) -> dict:
        item = deepcopy(job)
        files = job.get("files") or {}
        item.update(
            {
                "prompt_file": files.get("prompt") or job.get("prompt") or "",
                "meta_file": files.get("meta") or job.get("meta") or "",
                "done_file": files.get("done") or job.get("done") or "",
                "fingerprint": job.get("idempotency_key") or "",
                "ts": int(float(job.get("created_at") or 0) * 1_000_000_000),
            }
        )
        return item

    def waiting_jobs(self) -> list[dict]:
        snapshot = self.snapshot()
        return [
            self.legacy_view(job)
            for job in snapshot["jobs"]
            if job.get("state") in self.WAITING_STATES
        ]

    def status(self) -> dict:
        snapshot = self.snapshot()
        waiting = [
            job for job in snapshot["jobs"] if job.get("state") in self.WAITING_STATES
        ]
        counts = {state: 0 for state in sorted(self.STATES)}
        for job in snapshot["jobs"]:
            counts[job.get("state", "pending")] = counts.get(job.get("state", "pending"), 0) + 1
        return {
            "ok": True,
            "status": "ok",
            "schema_version": self.SCHEMA_VERSION,
            "revision": snapshot["revision"],
            "length": len(waiting),
            "jobs": deepcopy(snapshot["jobs"]),
            "queue": [self.legacy_view(job) for job in waiting],
            "state_counts": counts,
            "queue_file": str(self.queue_path),
            "last_good_file": str(self.last_good_path),
        }


QUEUE_STORE = QueueStore(WORK_DIR)


def read_queue() -> list:
    """Legacy waiting-list view used by status/health/free-memory callers."""
    return QUEUE_STORE.waiting_jobs()


def write_queue(queue: list):
    raise QueueError("direct queue replacement is disabled; use QueueStore operations")


def read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return ""


def safe_json_file(path: Union[str, Path]) -> dict:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception:
        return {}


def normalize_text(value) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip())


def summarize_meta(meta: dict) -> dict:
    if not isinstance(meta, dict):
        return {"person": "", "scene": "", "theme": "", "title": ""}
    person = normalize_text(meta.get("person"))
    scene = normalize_text(meta.get("scene"))
    theme = normalize_text(meta.get("theme"))
    title = " · ".join(x for x in [person, scene, theme] if x)
    return {"person": person, "scene": scene, "theme": theme, "title": title}


def build_fingerprint(prompt_file: str, meta_file: str, lora: str = None, width=None, height=None) -> str:
    prompt_text = normalize_text(read_text(Path(prompt_file)))
    meta = safe_json_file(meta_file)
    payload = {
        "prompt": prompt_text,
        "person": normalize_text(meta.get("person")),
        "scene": normalize_text(meta.get("scene")),
        "theme": normalize_text(meta.get("theme")),
        "narrative": normalize_text(meta.get("narrative")),
        "lighting": normalize_text(meta.get("lighting")),
        "style": normalize_text(meta.get("style")),
        "user_input": normalize_text(meta.get("user_input")),
        "lora": normalize_text(lora or meta.get("lora")),
        "width": int(width or meta.get("width") or 0),
        "height": int(height or meta.get("height") or 0),
    }
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


def ps_command(pid: int) -> str:
    try:
        out = subprocess.check_output(["ps", "-p", str(pid), "-o", "command="], text=True)
        return out.strip()
    except Exception:
        return ""


def pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def parse_worker_args(command: str) -> dict:
    args = {"lora": "", "width": 0, "height": 0}
    for flag in ("--lora", "--width", "--height"):
        m = re.search(rf"{re.escape(flag)}\s+(\S+)", command)
        if m:
            val = m.group(1)
            args[flag[2:]] = int(val) if flag in {"--width", "--height"} and str(val).isdigit() else val
    return args


def log_metadata(log_path: Path) -> dict:
    text = read_text(log_path)
    data = {}
    for key in ("PROMPT_FILE", "META_FILE", "DONE_FILE"):
        m = re.search(rf"^{key}=(.+)$", text, re.M)
        if m:
            data[key.lower()] = m.group(1).strip()
    return data


def active_worker_entries() -> list[dict]:
    paused_meta = str((safe_json_file(PAUSED_STATE).get("meta_file") or "")) if PAUSED_STATE.exists() else ""
    items = []
    for pid_file in sorted(WORK_DIR.glob(PID_GLOB), key=lambda p: p.stat().st_mtime, reverse=True):
        raw = read_text(pid_file).strip()
        if not raw.isdigit():
            try:
                pid_file.unlink(missing_ok=True)
            except Exception:
                pass
            continue
        pid = int(raw)
        if not pid_alive(pid):
            try:
                pid_file.unlink(missing_ok=True)
            except Exception:
                pass
            continue
        command = ps_command(pid)
        if "cu-worker.sh" not in command and "cu-draw-card.py" not in command:
            try:
                pid_file.unlink(missing_ok=True)
            except Exception:
                pass
            continue
        meta = log_metadata(pid_file.with_suffix(".log"))
        prompt_file = meta.get("prompt_file", "")
        meta_file = meta.get("meta_file", "")
        done_file = meta.get("done_file", "")
        if paused_meta and meta_file == paused_meta:
            continue
        args = parse_worker_args(command)
        if prompt_file and meta_file and Path(prompt_file).exists() and Path(meta_file).exists():
            fp = build_fingerprint(prompt_file, meta_file, args.get("lora"), args.get("width"), args.get("height"))
            summary = summarize_meta(safe_json_file(meta_file))
            items.append({
                "state": "running",
                "fingerprint": fp,
                "pid": pid,
                "prompt_file": prompt_file,
                "meta_file": meta_file,
                "done_file": done_file,
                "summary": summary,
            })
    return items


def queue_entries() -> list[dict]:
    queue = read_queue()
    items = []
    for idx, item in enumerate(queue, 1):
        prompt_file = item.get("prompt_file", "")
        meta_file = item.get("meta_file", "")
        if not prompt_file or not meta_file or not Path(prompt_file).exists() or not Path(meta_file).exists():
            continue
        fp = item.get("fingerprint") or build_fingerprint(prompt_file, meta_file, item.get("lora"), item.get("width"), item.get("height"))
        summary = summarize_meta(safe_json_file(meta_file))
        items.append({
            "state": "queued",
            "position": idx,
            "fingerprint": fp,
            "prompt_file": prompt_file,
            "meta_file": meta_file,
            "done_file": item.get("done_file", ""),
            "summary": summary,
        })
    return items


def paused_entry() -> Optional[dict]:
    if not PAUSED_STATE.exists():
        return None
    data = safe_json_file(PAUSED_STATE)
    prompt_file = data.get("prompt_file", "")
    meta_file = data.get("meta_file", "")
    if not prompt_file or not meta_file or not Path(prompt_file).exists() or not Path(meta_file).exists():
        return None
    args = data.get("args") or {}
    fp = data.get("fingerprint") or build_fingerprint(prompt_file, meta_file, args.get("lora"), args.get("width"), args.get("height"))
    summary = summarize_meta(data.get("meta") or safe_json_file(meta_file))
    return {
        "state": "paused",
        "fingerprint": fp,
        "prompt_file": prompt_file,
        "meta_file": meta_file,
        "done_file": data.get("done_file", ""),
        "summary": summary,
    }


def find_duplicate(prompt_file: str, meta_file: str, lora: str = None, width=None, height=None) -> dict:
    target = build_fingerprint(prompt_file, meta_file, lora, width, height)
    meta = safe_json_file(meta_file)
    card_id = str(meta.get("card_id") or "")
    snapshot = QUEUE_STORE.snapshot()
    waiting = [
        job for job in snapshot["jobs"] if job.get("state") in QueueStore.WAITING_STATES
    ]
    for job in snapshot["jobs"]:
        if (
            job.get("card_id") == card_id
            and job.get("idempotency_key") == target
        ):
            state = str(job.get("state") or "")
            legacy_state = {
                "pending": "queued",
                "retry_wait": "queued",
                "leased": "running",
                "running": "running",
            }.get(state, state)
            position = next(
                (
                    idx
                    for idx, queued in enumerate(waiting, 1)
                    if queued.get("job_id") == job.get("job_id")
                ),
                None,
            )
            return {
                **QueueStore.legacy_view(job),
                "state": legacy_state,
                "position": position,
                "summary": summarize_meta(meta),
            }
    return {"state": "none", "fingerprint": target}


def cmd_dedupe_check(prompt_file: str, meta_file: str, lora: str = None, width=None, height=None):
    hit = find_duplicate(prompt_file, meta_file, lora, width, height)
    summary = summarize_meta(safe_json_file(meta_file))
    payload = {
        "duplicate": hit.get("state") != "none",
        "fingerprint": hit.get("fingerprint"),
        "state": hit.get("state"),
        "position": hit.get("position"),
        "pid": hit.get("pid"),
        "summary": hit.get("summary") or summary,
    }
    print(json.dumps(payload, ensure_ascii=False))


def cmd_enqueue(
    prompt_file: str,
    meta_file: str,
    done_file: str,
    lora: str = None,
    width=None,
    height=None,
    *,
    card_id: str = "",
    idempotency_key: str = "",
    workflow: str = "",
    seed=None,
):
    prompt_path = Path(prompt_file)
    meta_path = Path(meta_file)
    done_path = Path(done_file)

    if not prompt_path.is_file():
        print(f"❌ prompt_file 不存在: {prompt_file}", file=sys.stderr)
        sys.exit(1)
    if not meta_path.is_file():
        print(f"❌ meta_file 不存在: {meta_file}", file=sys.stderr)
        sys.exit(1)

    meta_data = safe_json_file(meta_path)
    resolved_card_id = str(card_id or meta_data.get("card_id") or "")
    fingerprint = str(
        idempotency_key
        or build_fingerprint(str(prompt_path), str(meta_path), lora, width, height)
    )
    ack = QUEUE_STORE.enqueue(
        {
            "card_id": resolved_card_id,
            "idempotency_key": fingerprint,
            "workflow": workflow or "",
            "seed": seed,
            "lora": lora or "",
            "width": int(width or meta_data.get("width") or 0),
            "height": int(height or meta_data.get("height") or 0),
            "files": {
                "prompt": str(prompt_path),
                "meta": str(meta_path),
                "done": str(done_path),
            },
        }
    )
    ack["fingerprint"] = ack.get("idempotency_key") or fingerprint
    ack["summary"] = summarize_meta(meta_data)
    print(json.dumps(ack, ensure_ascii=False))
    return ack


def cmd_dequeue():
    ack = QUEUE_STORE.claim(owner=f"legacy-dequeue-{os.getpid()}")
    if ack.get("status") == "empty":
        print("EMPTY")
        return ack
    job = ack.get("job") or {}
    payload = QueueStore.legacy_view(job)
    payload.update(
        {
            "ok": True,
            "status": "claimed",
            "lease_token": ack.get("lease_token"),
        }
    )
    print(json.dumps(payload, ensure_ascii=False))
    return payload


def spawn_worker(task: dict) -> dict:
    files = task.get("files") or {}
    prompt_file = str(files.get("prompt") or task.get("prompt") or task.get("prompt_file") or "")
    meta_file = str(files.get("meta") or task.get("meta") or task.get("meta_file") or "")
    done_file = str(files.get("done") or task.get("done") or task.get("done_file") or "")
    job_id = str(task.get("job_id") or "")
    card_id = str(task.get("card_id") or "")
    lease_token = str((task.get("lease") or {}).get("token") or "")
    workflow = str(task.get("workflow") or "")
    seed = task.get("seed")
    lora = str(task.get("lora") or "")
    width = int(task.get("width") or 0)
    height = int(task.get("height") or 0)

    if not job_id or not lease_token:
        raise RuntimeError("task 缺少 job_id/lease token")
    if not prompt_file or not meta_file or not done_file:
        raise RuntimeError("task 缺少 prompt/meta/done 文件")
    if not Path(prompt_file).is_file() or not Path(meta_file).is_file():
        raise RuntimeError("task 文件不存在，无法启动 worker")

    if not acquire_gpu_lock():
        raise RuntimeError("GPU 锁已被占用，无法启动 worker")
    ts = f"{int(time.time())}_{os.getpid()}_{int(time.time_ns() % 100000)}"
    bg_log = str(WORK_DIR / f"cu-submit-bg_{ts}.log")
    pid_file = str(WORK_DIR / f"cu-submit-bg_{ts}.pid")
    cmd = [
        "python3", str(DETACHED_SPAWN),
        "--cwd", str(WORKSPACE),
        "--log", bg_log,
        "--pid-file", pid_file,
        "--env", f"CU_BG_LOG={bg_log}",
        "--env", f"CU_JOB_ID={job_id}",
        "--env", f"CU_CARD_ID={card_id}",
        "--env", f"CU_LEASE_TOKEN={lease_token}",
        "--env", f"CU_WORKFLOW={workflow}",
        "--env", f"CU_SEED={'' if seed is None else seed}",
        "--env", f"CU_WORK_DIR={WORK_DIR}",
        "--", str(WORKER_SCRIPT),
        "--job-id", job_id,
        "--card-id", card_id,
        "--lease-token", lease_token,
        "--prompt-file", prompt_file,
        "--meta-file", meta_file,
        "--done-file", done_file,
    ]
    if lora and lora != "null":
        cmd.extend(["--lora", lora])
    if width and height:
        cmd.extend(["--width", str(width), "--height", str(height)])
    if workflow:
        cmd.extend(["--workflow", workflow])
    if seed is not None:
        cmd.extend(["--seed", str(seed)])

    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        LOCK_FILE.unlink(missing_ok=True)
        raise RuntimeError((proc.stderr or proc.stdout or "spawn worker failed").strip())
    pid = (proc.stdout or "").strip()
    return {"pid": pid, "log": bg_log, "pid_file": pid_file}


def cmd_resume(job_id: Optional[str] = None):
    # A paused job is first returned to pending, then goes through the exact
    # same durable claim-before-spawn path as every other submission.
    resumed_paused = QUEUE_STORE.resume_paused(job_id=job_id)
    claim_job_id = resumed_paused.get("job_id") if resumed_paused.get("status") == "pending" else job_id

    # Smart GPU Lock Self-Healing: if lock exists but no worker process is active after 30 seconds, remove it
    if LOCK_FILE.exists():
        lock_age = time.time() - LOCK_FILE.stat().st_mtime
        if lock_age > 30 and not active_worker_entries():
            try:
                LOCK_FILE.unlink(missing_ok=True)
            except Exception:
                pass

    # 交付僵死：DONE 已落盘 + Comfy 空闲 + 超时 → 杀 worker 清锁再续跑
    heal = heal_deliver_stuck()
    if heal.get("healed"):
        print(json.dumps({
            "status": "healed_deliver_stuck",
            "killed": heal.get("killed") or [],
            "count": heal.get("count") or 0,
        }, ensure_ascii=False), file=sys.stderr)

    if LOCK_FILE.exists():
        ack = {"ok": True, "status": "busy", "reason": "gpu_lock_active"}
        print(json.dumps(ack, ensure_ascii=False))
        return ack
    if active_worker_entries():
        ack = {"ok": True, "status": "busy", "reason": "worker_running"}
        print(json.dumps(ack, ensure_ascii=False))
        return ack

    claimed = QUEUE_STORE.claim(owner=f"resume-{os.getpid()}", job_id=claim_job_id)
    if claimed.get("status") == "empty":
        ack = {"ok": True, "status": "empty"}
        print(json.dumps(ack, ensure_ascii=False))
        return ack

    item = claimed.get("job") or {}
    claimed_job_id = str(claimed.get("job_id") or item.get("job_id") or "")
    lease_token = str(claimed.get("lease_token") or "")
    try:
        result = spawn_worker(item)
    except Exception as e:
        LOCK_FILE.unlink(missing_ok=True)
        nack = QUEUE_STORE.nack(
            claimed_job_id,
            lease_token,
            f"spawn_failed: {e}",
            retry=True,
        )
        ack = {
            "ok": False,
            "status": "spawn_failed",
            "error": str(e),
            "job_id": claimed_job_id,
            "card_id": item.get("card_id") or "",
            "state": nack.get("state"),
            "nack": nack,
        }
        print(json.dumps(ack, ensure_ascii=False))
        return ack

    status = QUEUE_STORE.status()
    current = next(
        (
            job
            for job in status.get("jobs") or []
            if job.get("job_id") == claimed_job_id
        ),
        item,
    )
    meta_summary = summarize_meta(safe_json_file(item.get("meta", "")))
    ack = {
        "ok": True,
        "status": "started",
        "job_id": claimed_job_id,
        "card_id": item.get("card_id") or "",
        "lease_token": lease_token,
        "state": current.get("state") or "leased",
        "attempt": current.get("attempt"),
        "workflow": item.get("workflow") or "",
        "seed": item.get("seed"),
        "pid": result.get("pid"),
        "log": result.get("log"),
        "remaining": status.get("length", 0),
        "summary": meta_summary,
    }
    print(json.dumps(ack, ensure_ascii=False))
    return ack


def cmd_status():
    status = QUEUE_STORE.status()
    queue = status.get("queue") or []
    next_cap = ""
    next_lora = ""
    next_prompt_file = ""
    next_done_file = ""
    if queue:
        item = queue[0]
        next_lora = item.get("lora") or ""
        next_prompt_file = item.get("prompt_file") or ""
        next_done_file = item.get("done_file") or ""
        meta_file = item.get("meta_file")
        if meta_file and Path(meta_file).is_file():
            try:
                cap = json.loads(Path(meta_file).read_text(encoding="utf-8"))
                next_cap = cap.get("caption", "")[:80]
            except Exception:
                next_cap = ""
    status.update(
        {
            "next": next_cap,
            "next_lora": next_lora,
            "next_prompt_file": next_prompt_file,
            "next_done_file": next_done_file,
        }
    )
    print(json.dumps(status, ensure_ascii=False))
    return status


def cmd_clear(force=False):
    if force:
        ack = QUEUE_STORE.clear()
        print(json.dumps(ack, ensure_ascii=False))
        return ack

    queue = read_queue()
    if not queue:
        ack = {"ok": True, "status": "already_empty", "count": 0, "card_ids": []}
        print(json.dumps(ack, ensure_ascii=False))
        return ack
    if not force:
        # 展示内容，等确认
        items = []
        for i, item in enumerate(queue, 1):
            meta_file = item.get("meta_file", "")
            person = "?"
            if meta_file and Path(meta_file).is_file():
                try:
                    meta = json.loads(Path(meta_file).read_text(encoding="utf-8"))
                    person = meta.get("person", "?")
                except Exception:
                    pass
            items.append(f"  [{i}] {person}")
        print(f"⚠️  确认清空队列？（{len(queue)}张）")
        for item in items:
            print(item)
        print("\n请重新运行: cu-queue.py clear --yes  确认清空")
        print("           cu-queue.py clear --force  强制清空（不展示）")
        return {"ok": False, "status": "confirmation_required"}


def cmd_remove(position: int = None, fingerprint: str = None, job_id: str = None):
    """删除队列中指定位置的卡片。
    
    用法:
      python3 cu-queue.py remove --position 2       # 删第2张
      python3 cu-queue.py remove --fingerprint xxx   # 删指定指纹的卡
    """
    if job_id:
        ack = QUEUE_STORE.remove(job_id)
    elif position is not None:
        ack = QUEUE_STORE.remove_by_position(position)
    elif fingerprint is not None:
        ack = QUEUE_STORE.remove_by_idempotency(fingerprint)
    else:
        ack = {
            "ok": False,
            "status": "missing_arg",
            "usage": "remove --job-id ID, --position N, or --fingerprint KEY",
        }
    print(json.dumps(ack, ensure_ascii=False))
    return ack


def cmd_clean_stale():
    """清理队列中引用已删除文件的任务"""
    ack = QUEUE_STORE.clean_stale()
    print(json.dumps(ack, ensure_ascii=False))
    return ack


def cmd_drafts():
    """列出 / 清理孤儿草稿卡"""
    from datetime import datetime
    
    CARD_DIR = CARDS_DIR
    clean = "--clean" in sys.argv
    drafts = []
    
    for fp in sorted(CARD_DIR.glob("*.json")):
        try:
            card = json.loads(fp.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, IOError):
            continue
        
        if card.get("status") != "draft":
            continue
        
        cid = card.get("card_id", fp.stem)[-4:]
        scene = card.get("scene", {}).get("name", "?")
        mtime = datetime.fromtimestamp(fp.stat().st_mtime).strftime("%m-%d %H:%M")
        slots_filled = sum(1 for v in card.get("slots", {}).values() if v and v.strip())
        drafts.append({"cid": cid, "scene": scene, "mtime": mtime, "slots": slots_filled, "path": str(fp)})
    
    if not drafts:
        print("✅ 无孤儿草稿")
        return
    
    print(f"📋 孤儿草稿 ({len(drafts)} 张):")
    print(f"  {'ID':6s}  {'时间':12s}  {'场景':30s}  {'槽位'}")
    print(f"  {'-'*60}")
    for d in drafts:
        print(f"  {d['cid']:6s}  {d['mtime']:12s}  {d['scene']:30s}  {d['slots']}/14")
    
    if clean:
        for d in drafts:
            Path(d["path"]).unlink(missing_ok=True)
        print(f"\n🧹 已清理 {len(drafts)} 张草稿")
    else:
        print(f"\n→ 加 --clean 参数执行清理")


def send_zombie_alert(lock_age: int, queue: list, old_done: list):
    """僵尸锁检测：仅记录状态，不主动通知 Telegram。"""
    if not LOCK_FILE.is_file() or lock_age <= ZOMBIE_LOCK_THRESHOLD:
        ZOMBIE_ALERT_FILE.unlink(missing_ok=True)
        return

    next_person = ""
    if queue:
        meta_file = queue[0].get("meta_file")
        if meta_file and Path(meta_file).is_file():
            try:
                meta = json.loads(Path(meta_file).read_text(encoding="utf-8"))
                next_person = meta.get("person", "")
            except Exception:
                next_person = ""

    ZOMBIE_ALERT_FILE.write_text(json.dumps({
        "lock_mtime": int(LOCK_FILE.stat().st_mtime),
        "notified": False,
        "detected_at": int(time.time()),
        "lock_age": lock_age,
        "queue_depth": len(queue),
        "next_person": next_person,
        "old_done_count": len(old_done),
    }, ensure_ascii=False, indent=2), encoding="utf-8")


def cmd_health():
    """健康检查：每张卡状态 + 文件完整性 + 僵尸锁检测"""
    import os
    result = {
        "queue_depth": 0,
        "items": [],
        "issues": []
    }

    # ── 队列完整性 ──
    queue = read_queue()
    result["queue_depth"] = len(queue)
    for i, item in enumerate(queue):
        entry = {
            "position": i + 1,
            "status": "ok",
            "person": "?",
            "warnings": []
        }
        # 读 meta 取人物名
        meta_file = item.get("meta_file")
        if meta_file and Path(meta_file).is_file():
            try:
                m = json.loads(Path(meta_file).read_text(encoding="utf-8"))
                entry["person"] = m.get("person", "?")
            except Exception:
                entry["warnings"].append("meta 不可读")
        else:
            entry["warnings"].append("meta 文件缺失")
            entry["status"] = "broken"

        # 检查 prompt 文件
        pf = item.get("prompt_file")
        if pf and not Path(pf).is_file():
            entry["warnings"].append("prompt 文件缺失")
            entry["status"] = "broken"

        # 检查 done 文件（如果已存在说明已跑完但未交付）
        df = item.get("done_file")
        if df and Path(df).is_file():
            entry["status"] = "done_waiting_deliver"
            entry["warnings"].append("done 文件已存在，可能在等待交付")

        result["items"].append(entry)

    # ── GPU 锁检测 ──
    lock_file = LOCK_FILE
    if lock_file.is_file():
        age = int(time.time() - lock_file.stat().st_mtime)
        result["gpu_lock"] = {"active": True, "age_seconds": age}
        if age > ZOMBIE_LOCK_THRESHOLD:
            result["gpu_lock"]["zombie"] = True
            result["issues"].append(f"🧟 GPU锁僵尸: {age}s (>{ZOMBIE_LOCK_THRESHOLD}s)")
        else:
            result["gpu_lock"]["zombie"] = False
            # ── 查询 ComfyUI 获取当前卡详情 ──
            try:
                import urllib.request
                host = (load_config().get("comfyui_host") or "http://127.0.0.1:8188").rstrip("/")
                resp = urllib.request.urlopen(f"{host}/queue", timeout=3)
                qdata = json.loads(resp.read())
                running = qdata.get("queue_running", [])
                if running:
                    item = running[0]
                    pid = item[1][:12] if len(item) > 1 else "?"
                    pdata = item[2] if len(item) > 2 else {}
                    # 找 prompt 预览
                    prompt_preview = ""
                    for nid, node in pdata.items():
                        if isinstance(node, dict) and node.get("class_type") == "CLIPTextEncode":
                            txt = node.get("inputs",{}).get("text","")
                            if len(txt) > 10:
                                prompt_preview = txt[:60]
                                break
                    # 找 KSampler 参数
                    steps_list = []
                    for nid, node in pdata.items():
                        if isinstance(node, dict) and node.get("class_type","").startswith("KSampler"):
                            steps_list.append(node.get("inputs",{}).get("steps",0))
                    total_steps = sum(steps_list) if steps_list else 18  # 默认估计
                    # 估算剩余：与 cu-submit 相同，取最近成功交付均时（无记录则不伪造固定分钟）
                    elapsed_m = age / 60
                    eta_info = avg_recent_delivery_elapsed_info()
                    typical_m = eta_info.get("avg_min")
                    comfyui = {
                        "pid": pid,
                        "prompt_preview": prompt_preview,
                        "steps": total_steps,
                        "elapsed_min": round(elapsed_m, 1),
                        "eta_source": eta_info.get("source"),
                        "eta_sample_count": eta_info.get("sample_count"),
                        "typical_min": typical_m,
                    }
                    if typical_m and typical_m > 0:
                        eta_s = max(0, int((typical_m * 60) - age))
                        comfyui["eta_seconds"] = eta_s
                        comfyui["eta_min"] = round(eta_s / 60, 1)
                        comfyui["progress_pct"] = min(95, round(elapsed_m / typical_m * 100))
                    else:
                        comfyui["eta_seconds"] = None
                        comfyui["eta_min"] = None
                        comfyui["progress_pct"] = None
                    result["comfyui"] = comfyui
            except Exception as e:
                result["comfyui"] = {"error": str(e)}
            result["issues"].append(f"🔒 GPU 忙碌中: {age}s")
            stuck = deliver_stuck_entries()
            if stuck:
                result["gpu_lock"]["deliver_stuck"] = True
                result["issues"].append(
                    f"🧟 交付僵死: DONE 已存在 {stuck[0].get('done_age')}s 且 Comfy 空闲（>{DELIVER_STUCK_THRESHOLD}s）"
                )
    else:
        result["gpu_lock"] = {"active": False}
        # 队列非空但无锁 = 可能卡住了
        if queue:
            result["issues"].append("⚠️  队列非空但 GPU 空闲——可能上一张交付失败导致队列停住")

    # ── 僵尸 done 文件 ──
    done_dir = WORK_DIR
    old_done = []
    for f in done_dir.glob("cu-draw-card-done_*.json"):
        if time.time() - f.stat().st_mtime > 3600:
            old_done.append(str(f.name))
    if old_done:
        result["issues"].append(f"🗑️  {len(old_done)} 个僵尸 done 文件（>1h）: {old_done[:3]}...")

    # ── 主动通知 ──
    try:
        send_zombie_alert(result.get("gpu_lock", {}).get("age_seconds", 0), queue, old_done)
    except Exception as e:
        result["issues"].append(f"⚠️ 僵尸锁通知失败: {e}")

    # ── 汇总 ──
    broken = sum(1 for i in result["items"] if i["status"] == "broken")
    ok = sum(1 for i in result["items"] if i["status"] == "ok")
    result["summary"] = f"{ok} 正常 / {broken} 损坏 / {result['queue_depth']} 队列"
    if not result["issues"]:
        result["issues"].append("✅ 全部正常")

    print(json.dumps(result, ensure_ascii=False, indent=2))


def _cli_option(name: str, default=None):
    try:
        idx = sys.argv.index(name)
    except ValueError:
        return default
    if idx + 1 >= len(sys.argv):
        return default
    return sys.argv[idx + 1]


def _print_ack(payload: dict) -> int:
    print(json.dumps(payload, ensure_ascii=False))
    return 0 if payload.get("ok", True) else 1


def main() -> int:
    if len(sys.argv) < 2 or sys.argv[1] in {"-h", "--help", "help"}:
        print("""🎨 GPU 渲染队列管理器 (JSON v2)
=========================================
核心:
  status | health | avg-eta
  enqueue <prompt> <meta> <done> [--card-id ID] [--idempotency-key KEY]
          [--workflow NAME] [--seed N] [--lora X] [--width W] [--height H]
  resume [--job-id ID]       持久化 lease 后启动 worker
  claim [--job-id ID]        仅 claim，不启动 worker
  ready|heartbeat|ack|nack|pause --job-id ID --lease-token TOKEN
  reap                       回收过期 lease
  remove --job-id ID         推荐；兼容 --position/--fingerprint
  clear --force

兼容:
  dedupe-check <prompt> <meta> [...]
  dequeue | clean-stale | drafts | heal-deliver | free-memory [--if-queued]

所有写操作均使用 cu-queue.lock + temp/fsync/os.replace；坏 JSON 拒绝读写。""")
        return 0

    cmd = sys.argv[1]
    try:
        if cmd == "avg-eta":
            print(json.dumps(avg_recent_delivery_elapsed_info(), ensure_ascii=False))
            return 0

        if cmd == "free-memory":
            return _print_ack(cmd_free_memory(if_queued="--if-queued" in sys.argv))

        if cmd == "enqueue":
            if len(sys.argv) < 5:
                print(
                    "Usage: cu-queue.py enqueue <prompt> <meta> <done> [options]",
                    file=sys.stderr,
                )
                return 2
            ack = cmd_enqueue(
                sys.argv[2],
                sys.argv[3],
                sys.argv[4],
                _cli_option("--lora"),
                _cli_option("--width"),
                _cli_option("--height"),
                card_id=str(_cli_option("--card-id", "") or ""),
                idempotency_key=str(_cli_option("--idempotency-key", "") or ""),
                workflow=str(_cli_option("--workflow", "") or ""),
                seed=_cli_option("--seed"),
            )
            return 0 if ack.get("ok") else 1

        if cmd == "dedupe-check":
            if len(sys.argv) < 4:
                print("Usage: cu-queue.py dedupe-check <prompt> <meta> [options]", file=sys.stderr)
                return 2
            cmd_dedupe_check(
                sys.argv[2],
                sys.argv[3],
                _cli_option("--lora"),
                _cli_option("--width"),
                _cli_option("--height"),
            )
            return 0

        if cmd == "dequeue":
            cmd_dequeue()
            return 0

        if cmd == "claim":
            return _print_ack(
                QUEUE_STORE.claim(
                    owner=str(_cli_option("--owner", f"cli-{os.getpid()}")),
                    job_id=_cli_option("--job-id"),
                )
            )

        if cmd == "resume":
            ack = cmd_resume(job_id=_cli_option("--job-id"))
            return 0 if ack.get("ok") else 1

        if cmd in {"ready", "heartbeat", "ack", "nack", "pause"}:
            job_id = str(_cli_option("--job-id", "") or "")
            token = str(_cli_option("--lease-token", "") or "")
            if not job_id or not token:
                return _print_ack(
                    {
                        "ok": False,
                        "status": "missing_arg",
                        "command": cmd,
                        "error": "--job-id and --lease-token are required",
                    }
                )
            if cmd == "ready":
                ack = QUEUE_STORE.ready(job_id, token)
            elif cmd == "heartbeat":
                ack = QUEUE_STORE.heartbeat(job_id, token)
            elif cmd == "ack":
                result = None
                result_file = _cli_option("--result-file")
                if result_file:
                    result = safe_json_file(result_file)
                ack = QUEUE_STORE.ack(job_id, token, result=result)
            elif cmd == "nack":
                ack = QUEUE_STORE.nack(
                    job_id,
                    token,
                    str(_cli_option("--error", "worker_nack")),
                    retry="--no-retry" not in sys.argv,
                )
            else:
                ack = QUEUE_STORE.pause(job_id, token)
            return _print_ack(ack)

        if cmd == "reap":
            return _print_ack(QUEUE_STORE.reap_expired())

        if cmd == "get":
            job_id = str(_cli_option("--job-id", "") or "")
            job = QUEUE_STORE.get(job_id) if job_id else None
            return _print_ack(
                {"ok": bool(job), "status": "ok" if job else "not_found", "job": job}
            )

        if cmd == "status":
            cmd_status()
            return 0

        if cmd == "clear":
            ack = cmd_clear(force=("--force" in sys.argv or "--yes" in sys.argv))
            return 0 if ack.get("ok") else 1

        if cmd == "health":
            cmd_health()
            return 0

        if cmd == "heal-deliver":
            return _print_ack({"ok": True, "status": "ok", **heal_deliver_stuck()})

        if cmd == "clean-stale":
            ack = cmd_clean_stale()
            return 0 if ack.get("ok") else 1

        if cmd == "drafts":
            cmd_drafts()
            return 0

        if cmd == "remove":
            raw_position = _cli_option("--position")
            try:
                position = int(raw_position) if raw_position is not None else None
            except ValueError:
                return _print_ack(
                    {"ok": False, "status": "invalid_position", "position": raw_position}
                )
            ack = cmd_remove(
                position=position,
                fingerprint=_cli_option("--fingerprint"),
                job_id=_cli_option("--job-id"),
            )
            return 0 if ack.get("ok") else 1

        print(f"❌ 未知命令: {cmd}", file=sys.stderr)
        return 2
    except QueueLockBusy as exc:
        return_code = 75
        print(
            json.dumps(
                {
                    "ok": False,
                    "status": "lock_busy",
                    "error": str(exc),
                    "command": cmd,
                },
                ensure_ascii=False,
            )
        )
        return return_code
    except QueueCorruptError as exc:
        print(
            json.dumps(
                {
                    "ok": False,
                    "status": "corrupt_queue",
                    "error": str(exc),
                    "command": cmd,
                    "last_good_file": str(QUEUE_STORE.last_good_path),
                },
                ensure_ascii=False,
            )
        )
        return 65
    except QueueError as exc:
        return _print_ack(
            {"ok": False, "status": "queue_error", "error": str(exc), "command": cmd}
        )


if __name__ == "__main__":
    raise SystemExit(main())
