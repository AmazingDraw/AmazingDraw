"""
smart_nodes.py — Card Engine ComfyUI 桥接（对齐 8318 现行 API）
================================================================
节点无状态；服务地址 CARD_ENGINE_URL（默认 http://127.0.0.1:8318）。

现行 WebUI 路由（非旧 /api/v1/*）：
  GET  /api/cards/{card_id}
  POST /api/cards/{card_id}/render
  POST /api/cards/{card_id}/check
"""
from __future__ import annotations

import json
import logging
import os
import random
from pathlib import Path
from typing import Any, Optional

import requests

logger = logging.getLogger("card-engine-nodes")


def _service_url() -> str:
    return os.environ.get("CARD_ENGINE_URL", "http://127.0.0.1:8318").rstrip("/")


def _default_card_path() -> str:
    tmp = os.environ.get("CARD_ENGINE_TMP") or str(Path.home() / ".card-engine" / "tmp")
    cards = os.environ.get("CARD_ENGINE_CARDS") or str(Path.home() / ".card-engine" / "cards")
    # 优先 cards 目录示例；tmp 兜底
    return str(Path(cards) / "example.json")


def _load_card_json(path: str) -> Optional[dict]:
    p = Path(path)
    if not p.is_file():
        logger.error("卡片文件不存在: %s", path)
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception as e:
        logger.error("卡片 JSON 解析失败: %s", e)
        return None


def _call(method: str, endpoint: str, **kwargs) -> Optional[Any]:
    url = f"{_service_url()}{endpoint}"
    try:
        resp = getattr(requests, method)(url, timeout=60, **kwargs)
        resp.raise_for_status()
        if resp.content:
            return resp.json()
        return {}
    except requests.ConnectionError:
        logger.warning("Card Engine 服务未就绪 (%s)，降级", url)
        return None
    except Exception as e:
        logger.error("服务调用失败 %s %s: %s", method.upper(), url, e)
        return None


def _extract_prompt(card: dict) -> tuple[str, str]:
    """从 card / _render_output 取正负向。"""
    ro = card.get("_render_output") or {}
    prompt = (
        ro.get("prompt")
        or ro.get("positive_prompt")
        or card.get("prompt")
        or card.get("positive_prompt")
        or ""
    )
    negative = (
        ro.get("negative_prompt")
        or ro.get("negative")
        or card.get("negative_prompt")
        or ""
    )
    return str(prompt), str(negative)


class SmartCardLoader:
    """读取卡片 JSON，经 8318 render 后输出提示词与元数据。"""

    CATEGORY = "Card Engine"
    FUNCTION = "load_card"
    RETURN_TYPES = (
        "STRING",
        "STRING",
        "INT",
        "INT",
        "INT",
        "STRING",
        "FLOAT",
        "STRING",
        "STRING",
        "STRING",
        "STRING",
        "STRING",
    )
    RETURN_NAMES = (
        "PROMPT",
        "NEGATIVE",
        "SEED",
        "WIDTH",
        "HEIGHT",
        "LORA_NAME",
        "LORA_STRENGTH",
        "CARD_ID",
        "PERSON",
        "SCENE",
        "NARRATIVE",
        "THEME",
    )

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "card_json_path": (
                    "STRING",
                    {
                        "default": _default_card_path(),
                        "tooltip": "卡片 JSON 路径；也可仅含 card_id 文件名",
                    },
                ),
            },
            "optional": {
                "override_seed": ("INT", {"default": -1, "min": -1, "max": 0x7FFFFFFF}),
                "override_width": ("INT", {"default": 0, "min": 0, "max": 8192}),
                "override_height": ("INT", {"default": 0, "min": 0, "max": 8192}),
            },
        }

    def load_card(
        self,
        card_json_path: str,
        override_seed: int = -1,
        override_width: int = 0,
        override_height: int = 0,
    ):
        card = _load_card_json(card_json_path)
        if card is None:
            return self._defaults()

        card_id = str(card.get("card_id") or Path(card_json_path).stem)

        # 先尝试服务端 render（写回卡片并返回）
        rendered = _call("post", f"/api/cards/{card_id}/render", json={})
        if rendered is None:
            # 再尝试 GET 已有卡片
            remote = _call("get", f"/api/cards/{card_id}")
            if isinstance(remote, dict) and remote.get("card_id"):
                card = remote
            logger.warning("服务 render 不可用，使用本地 JSON 字段")
        else:
            # render API 可能只回 status；再 GET 全量
            remote = _call("get", f"/api/cards/{card_id}")
            if isinstance(remote, dict) and (remote.get("card_id") or remote.get("slots")):
                card = remote

        prompt, negative = _extract_prompt(card)
        person = str(
            card.get("person")
            or (card.get("subject") or {}).get("name")
            or (card.get("subject") or {}).get("person")
            or ""
        )
        scene_obj = card.get("scene") or {}
        scene = str(
            card.get("scene_label")
            or scene_obj.get("label")
            or scene_obj.get("name")
            or ""
        )
        narrative = str(card.get("narrative_zh") or card.get("narrative") or "")
        theme = str(card.get("theme_zh") or card.get("theme") or "")

        suggested = card.get("seed", -1)
        try:
            suggested = int(suggested)
        except Exception:
            suggested = -1
        seed = (
            override_seed
            if override_seed >= 0
            else (suggested if suggested >= 0 else random.randint(0, 2**31 - 1))
        )

        meta = card.get("render_meta") or card.get("_render_output") or {}
        width = override_width if override_width > 0 else int(meta.get("width") or card.get("width") or 832)
        height = override_height if override_height > 0 else int(meta.get("height") or card.get("height") or 1216)
        lora_name = str(meta.get("lora_name") or card.get("lora_name") or "")
        try:
            lora_strength = float(meta.get("lora_strength") or card.get("lora_strength") or 0.85)
        except Exception:
            lora_strength = 0.85

        logger.info("卡片加载 card_id=%s scene=%s", card_id, scene)
        return (
            prompt,
            negative,
            seed,
            width,
            height,
            lora_name,
            lora_strength,
            card_id,
            person,
            scene,
            narrative,
            theme,
        )

    @staticmethod
    def _defaults():
        return ("", "", 0, 832, 1216, "", 0.85, "", "", "", "", "")


class SmartCardAutofix:
    """调用 POST /api/cards/{id}/check；服务不可用时透传 WARN。"""

    CATEGORY = "Card Engine"
    FUNCTION = "autofix"
    RETURN_TYPES = ("STRING", "STRING", "STRING")
    RETURN_NAMES = ("CLEANED_PROMPT", "STATUS", "LOG")

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "prompt": ("STRING", {"forceInput": True}),
            },
            "optional": {
                "card_json_path": (
                    "STRING",
                    {
                        "default": "",
                        "tooltip": "可选；用于解析 card_id 调 check API",
                    },
                ),
                "card_id": ("STRING", {"default": ""}),
                "fail_on_error": ("BOOLEAN", {"default": False}),
            },
        }

    def autofix(
        self,
        prompt: str,
        card_json_path: str = "",
        card_id: str = "",
        fail_on_error: bool = False,
    ):
        if not str(prompt).strip():
            return ("", "FAIL", "输入 Prompt 为空")

        cid = (card_id or "").strip()
        if not cid and card_json_path:
            card = _load_card_json(card_json_path)
            if card:
                cid = str(card.get("card_id") or Path(card_json_path).stem)
            else:
                cid = Path(card_json_path).stem

        if not cid:
            log = "无 card_id，跳过服务校验（透传）"
            return (prompt, "WARN", log)

        result = _call("post", f"/api/cards/{cid}/check", json={})
        if result is None:
            log = "Card Engine 服务不可用，跳过校验（降级）"
            logger.warning(log)
            return (prompt, "WARN", log)

        errors = result.get("errors") or []
        warnings = result.get("warnings") or []
        status = "FAIL" if errors else ("WARN" if warnings else "PASS")
        # 现行 check 不改写 prompt；cleaned = 输入
        cleaned = prompt
        log_lines = [f"校验结果: {status}"]
        if errors:
            log_lines.append("错误:\n  " + "\n  ".join(str(e) for e in errors))
        if warnings:
            log_lines.append("警告:\n  " + "\n  ".join(str(w) for w in warnings))
        log = "\n".join(log_lines)

        if status == "FAIL" and fail_on_error:
            raise RuntimeError(f"Card Engine check 失败:\n{log}")

        return (cleaned, status, log)


class SmartCardNotifier:
    """渲染完成推送：Telegram（可选）+ WebUI webhook（可选）。"""

    CATEGORY = "Card Engine"
    FUNCTION = "notify"
    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("RESULT_JSON",)
    OUTPUT_NODE = True

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "images": ("IMAGE",),
            },
            "optional": {
                "card_id": ("STRING", {"default": ""}),
                "status": ("STRING", {"default": "PASS"}),
                "bot_token": ("STRING", {"default": ""}),
                "chat_id": ("STRING", {"default": ""}),
                "webhook_url": (
                    "STRING",
                    {
                        "default": "",
                        "tooltip": "可选回调，如 http://127.0.0.1:8318/api/...（按你的 WebUI 配置）",
                    },
                ),
                "caption": ("STRING", {"default": "", "multiline": True}),
            },
        }

    def notify(
        self,
        images,
        card_id: str = "",
        status: str = "PASS",
        bot_token: str = "",
        chat_id: str = "",
        webhook_url: str = "",
        caption: str = "",
    ):
        result = {"card_id": card_id, "status": status, "telegram": None, "webhook": None}
        # Telegram：仅当用户显式填 token/chat，绝不硬编码
        if bot_token.strip() and chat_id.strip():
            try:
                # 取第一张图保存临时再发较重；此处只记录意图，避免强依赖 torch 编码
                result["telegram"] = "configured_but_image_send_left_to_user_pipeline"
            except Exception as e:
                result["telegram"] = f"error: {e}"

        if webhook_url.strip():
            try:
                r = requests.post(
                    webhook_url.strip(),
                    json={"card_id": card_id, "status": status, "caption": caption},
                    timeout=15,
                )
                result["webhook"] = {"http": r.status_code}
            except Exception as e:
                result["webhook"] = f"error: {e}"

        return (json.dumps(result, ensure_ascii=False),)


NODE_CLASS_MAPPINGS = {
    "SmartCardLoader": SmartCardLoader,
    "SmartCardAutofix": SmartCardAutofix,
    "SmartCardNotifier": SmartCardNotifier,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "SmartCardLoader": "Smart Card Loader",
    "SmartCardAutofix": "Smart Card Autofix",
    "SmartCardNotifier": "Smart Card Notifier",
}
