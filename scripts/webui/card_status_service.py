#!/usr/bin/env python3
"""Safe card status snapshots, cancellation restore, and manual transitions."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, Optional

SCRIPT_DIR = Path(__file__).resolve().parent
CARD_ENGINE_DIR = SCRIPT_DIR.parent / "card-engine"
if str(CARD_ENGINE_DIR) not in sys.path:
    sys.path.insert(0, str(CARD_ENGINE_DIR))

from card_config import load_system_config
from card_io import card_lock, load_card, save_card
from card_validation import validation_binding_mismatches


RESTORE_FIELD = "_status_restore"
RESTORE_SCHEMA_VERSION = 1
COMPLETED_STATUSES = frozenset({"rendered", "delivered", "success"})
TRANSIENT_STATUSES = frozenset({"validated", "submitted", "queued", "rendering"})
RESTORABLE_STATUSES = (
    frozenset({"draft", "filled", "failed", "validated"}) | COMPLETED_STATUSES
)
MANUAL_TARGET_STATUSES = frozenset({"draft", "validated", "rendered"})
MANUAL_BLOCKED_STATUSES = frozenset({"submitted", "queued", "rendering"})


class CardStatusError(ValueError):
    """Base class for user-visible card status failures."""


class CardStatusConflict(CardStatusError):
    """The requested transition races with another card operation."""


class CardStatusImageMissing(CardStatusError):
    """A completed status was requested without a verifiable image."""


def _now_iso() -> str:
    return datetime.now().isoformat()


def _configured_image_roots() -> list[Path]:
    config = load_system_config()
    roots: list[Path] = []
    seen: set[str] = set()
    for key in ("output_dir_archive", "output_dir"):
        raw = str(config.get(key) or "").strip()
        if not raw:
            continue
        try:
            root = Path(raw).expanduser().resolve()
        except (OSError, RuntimeError):
            continue
        marker = str(root)
        if marker in seen:
            continue
        seen.add(marker)
        roots.append(root)
    return roots


def resolve_existing_card_image(
    card: Dict[str, Any],
    preferred_image: Optional[str] = None,
    *,
    strict_preferred: bool = False,
) -> Optional[Path]:
    """Resolve only exact image basenames under configured output roots."""

    names: list[str] = []
    raw_names = (
        (preferred_image,)
        if preferred_image and strict_preferred
        else (
            preferred_image,
            card.get("render_image"),
            f"{card.get('card_id')}.png" if card.get("card_id") else None,
        )
    )
    for raw in raw_names:
        if not raw:
            continue
        name = Path(str(raw)).name
        if name and name not in {".", ".."} and name not in names:
            names.append(name)

    for root in _configured_image_roots():
        for name in names:
            try:
                candidate = (root / name).resolve()
                candidate.relative_to(root)
            except (OSError, RuntimeError, ValueError):
                continue
            if candidate.is_file():
                return candidate
    return None


def capture_status_restore(
    card_id: str,
    *,
    source: str,
) -> Dict[str, Any]:
    """Capture the latest stable status before WebUI starts a new submission."""

    with card_lock(card_id, owner="status-restore-capture", timeout=20.0):
        card = load_card(card_id)
        current = str(card.get("status") or "draft")
        existing = card.get(RESTORE_FIELD)
        if current in TRANSIENT_STATUSES and isinstance(existing, dict):
            return dict(existing)
        if current not in RESTORABLE_STATUSES:
            current = "draft"
        snapshot = {
            "schema_version": RESTORE_SCHEMA_VERSION,
            "source": str(source or "webui_rerender"),
            "status": current,
            "render_image": str(card.get("render_image") or ""),
            "captured_at": _now_iso(),
        }
        card[RESTORE_FIELD] = snapshot
        save_card(card)
        return dict(snapshot)


def restore_card_after_cancel(
    card_id: str,
    *,
    reason: str,
    fallback_status: str,
    expected_job_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Restore the captured stable status after cancellation is confirmed."""

    fallback = (
        fallback_status
        if fallback_status in {"draft", "filled", "failed"}
        else "draft"
    )
    with card_lock(card_id, owner="status-restore-cancel", timeout=20.0):
        card = load_card(card_id, default=None)
        if not card:
            return {
                "ok": False,
                "status": "missing_card",
                "card_id": card_id,
            }

        temporary_status = str(card.get("status") or fallback)
        snapshot = card.get(RESTORE_FIELD)
        render_cfg = card.get("render") if isinstance(card.get("render"), dict) else {}
        if not isinstance(card.get("render"), dict):
            card["render"] = render_cfg
        current_job_id = str(render_cfg.get("queue_job_id") or "")
        snapshot_job_id = (
            str(snapshot.get("job_id") or "")
            if isinstance(snapshot, dict)
            else ""
        )
        expected = str(expected_job_id or "")
        if expected and (
            (current_job_id and current_job_id != expected)
            or (snapshot_job_id and snapshot_job_id != expected)
        ):
            return {
                "ok": False,
                "status": "stale_job",
                "card_id": card_id,
                "expected_job_id": expected,
                "current_job_id": current_job_id or None,
                "snapshot_job_id": snapshot_job_id or None,
                "unchanged": True,
            }
        if not isinstance(snapshot, dict) and temporary_status not in TRANSIENT_STATUSES:
            return {
                "ok": True,
                "card_id": card_id,
                "previous_status": temporary_status,
                "status": temporary_status,
                "version": card.get("version"),
                "unchanged": True,
            }
        card.pop(RESTORE_FIELD, None)
        previous_status = ""
        target = fallback
        image_path: Optional[Path] = None
        if isinstance(snapshot, dict):
            previous_status = str(snapshot.get("status") or "")
            if previous_status in COMPLETED_STATUSES:
                captured_image = str(snapshot.get("render_image") or "")
                image_path = resolve_existing_card_image(
                    card,
                    captured_image or None,
                    strict_preferred=bool(captured_image),
                )
                target = "rendered" if image_path is not None else "draft"
            elif previous_status in {"draft", "filled", "failed", "validated"}:
                target = previous_status

        card["status"] = target
        if expected:
            render_cfg["queue_job_id"] = expected
            render_cfg["queue_state"] = "cancelled"
        if target != "failed":
            card.pop("render_error", None)
        card.setdefault("history", []).append(
            {
                "timestamp": _now_iso(),
                "action": "restore_status_after_cancel",
                "changes": {
                    "reason": str(reason or "cancelled"),
                    "captured_status": previous_status or None,
                    "temporary_status": temporary_status,
                    "restored_status": target,
                    "image_verified": image_path is not None,
                },
            }
        )
        save_card(card)
        return {
            "ok": True,
            "card_id": card_id,
            "previous_status": temporary_status,
            "status": target,
            "version": card.get("version"),
            "image_verified": image_path is not None,
        }


def complete_render_job(
    card_id: str,
    *,
    job_id: str,
    render_image: str,
) -> Dict[str, Any]:
    """Commit a rendered image only when this job still owns the card."""

    expected = str(job_id or "").strip()
    image_name = Path(str(render_image or "")).name
    if not expected or not image_name:
        raise CardStatusError("完成渲染缺少 job_id 或图片文件名")

    with card_lock(card_id, owner="render-complete", timeout=20.0):
        card = load_card(card_id, default=None)
        if not card:
            raise CardStatusError("卡片不存在")

        render_cfg = card.setdefault("render", {})
        current_job_id = str(render_cfg.get("queue_job_id") or "")
        current_queue_state = str(render_cfg.get("queue_state") or "")
        snapshot = card.get(RESTORE_FIELD)
        snapshot_job_id = (
            str(snapshot.get("job_id") or "")
            if isinstance(snapshot, dict)
            else ""
        )
        if (
            (current_job_id and current_job_id != expected)
            or (snapshot_job_id and snapshot_job_id != expected)
        ):
            return {
                "ok": False,
                "status": "stale_job",
                "card_id": card_id,
                "expected_job_id": expected,
                "current_job_id": current_job_id or None,
                "snapshot_job_id": snapshot_job_id or None,
                "unchanged": True,
            }
        if current_job_id == expected and current_queue_state in {
            "cancelled",
            "failed",
            "removed",
        }:
            return {
                "ok": False,
                "status": "cancelled_job",
                "card_id": card_id,
                "expected_job_id": expected,
                "queue_state": current_queue_state,
                "unchanged": True,
            }
        if (
            not current_job_id
            and not snapshot_job_id
            and str(card.get("workflow_mode") or "") != "direct"
        ):
            return {
                "ok": False,
                "status": "unowned_job",
                "card_id": card_id,
                "expected_job_id": expected,
                "unchanged": True,
            }

        previous_status = str(card.get("status") or "")
        restore_snapshot = card.pop(RESTORE_FIELD, None)
        card["status"] = "rendered"
        card["render_image"] = image_name
        card.pop("render_error", None)
        render_cfg["queue_job_id"] = expected
        render_cfg["queue_state"] = "completed"
        card.setdefault("history", []).append(
            {
                "timestamp": _now_iso(),
                "action": "render_completed",
                "changes": {
                    "job_id": expected,
                    "previous_status": previous_status,
                    "status": "rendered",
                    "render_image": image_name,
                    "captured_status": (
                        restore_snapshot.get("status")
                        if isinstance(restore_snapshot, dict)
                        else None
                    ),
                },
            }
        )
        save_card(card)
        return {
            "ok": True,
            "status": "rendered",
            "card_id": card_id,
            "job_id": expected,
            "render_image": image_name,
            "version": card.get("version"),
        }


def set_manual_status(
    card_id: str,
    *,
    target_status: str,
    expected_version: int,
    has_nonterminal_queue_job: Optional[Callable[[], bool]] = None,
) -> Dict[str, Any]:
    """Apply one safe manual status transition under the card write lock."""

    if target_status not in MANUAL_TARGET_STATUSES:
        raise CardStatusError(
            "只允许手动设置为 draft、validated 或 rendered"
        )
    with card_lock(card_id, owner="manual-status-change", timeout=20.0):
        card = load_card(card_id, default=None)
        if not card:
            raise CardStatusError("卡片不存在")

        current_version = int(card.get("version") or 0)
        if int(expected_version) != current_version:
            raise CardStatusConflict(
                f"卡片版本已变化（当前 v{current_version}），请刷新后重试"
            )

        previous_status = str(card.get("status") or "draft")
        if previous_status in MANUAL_BLOCKED_STATUSES or card.get(RESTORE_FIELD):
            raise CardStatusConflict("卡片正在提交、排队或渲染，暂不能手动修改状态")
        if has_nonterminal_queue_job and has_nonterminal_queue_job():
            raise CardStatusConflict("该卡仍在队列或渲染中，请先完成取消")

        image_path: Optional[Path] = None
        validation_verified = False
        if target_status == "rendered":
            image_path = resolve_existing_card_image(card)
            if image_path is None:
                raise CardStatusImageMissing("未找到该卡原图，不能标记为完成")
        elif target_status == "validated":
            mismatches = validation_binding_mismatches(card)
            if set(mismatches) - {"card_version"}:
                raise CardStatusConflict("该卡缺少有效校验凭证，不能标记为定稿")
            validation_verified = True

        if previous_status == target_status:
            return {
                "ok": True,
                "card_id": card_id,
                "previous_status": previous_status,
                "status": target_status,
                "version": current_version,
                "unchanged": True,
            }

        card["status"] = target_status
        if target_status != "failed":
            card.pop("render_error", None)
        card.setdefault("history", []).append(
            {
                "timestamp": _now_iso(),
                "action": "manual_status_change",
                "changes": {
                    "previous_status": previous_status,
                    "status": target_status,
                    "image_verified": image_path is not None,
                    "validation_verified": validation_verified,
                    "source": "webui",
                },
            }
        )
        save_card(card)
        return {
            "ok": True,
            "card_id": card_id,
            "previous_status": previous_status,
            "status": target_status,
            "version": card.get("version"),
            "image_verified": image_path is not None,
            "validation_verified": validation_verified,
        }


def _main() -> int:
    parser = argparse.ArgumentParser(description="Card status service helper")
    subparsers = parser.add_subparsers(dest="command", required=True)
    complete = subparsers.add_parser("complete")
    complete.add_argument("--card", required=True)
    complete.add_argument("--job-id", required=True)
    complete.add_argument("--image", required=True)
    args = parser.parse_args()

    try:
        result = complete_render_job(
            args.card,
            job_id=args.job_id,
            render_image=args.image,
        )
    except (CardStatusError, OSError, ValueError) as exc:
        print(json.dumps({"ok": False, "status": "error", "error": str(exc)}, ensure_ascii=False))
        return 1
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result.get("ok") else 2


if __name__ == "__main__":
    raise SystemExit(_main())
