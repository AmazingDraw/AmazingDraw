#!/usr/bin/env python3
"""Cards / settings / poetry / pipeline / roles-scenes API routes."""

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
import base64
import contextlib
import io
import json
import os
import re
import time
from pathlib import Path
from typing import Any, Dict, Optional
from urllib.parse import quote as url_quote

from fastapi import APIRouter, HTTPException

from web_server import (
    CARDS_DIR,
    CONFIG_PATH,
    PRESETS_DIR,
    SCRIPT_DIR,
    load_system_config,
    save_system_config,
    update_images_mount,
    clear_chat_history,
    append_chat_history,
    safe_chat_id,
    webui_session_id,
)

from card_core import load_card, save_card
from card_io import (
    InvalidCardIdError,
    card_lock,
    card_path as resolve_card_path,
    new_card_id,
    validate_card_id,
)
from card_archive import (
    ArchiveError,
    ArchiveImageAmbiguous,
    ArchiveImageNotFound,
    archive_card,
)
from card_status_service import (
    CardStatusConflict,
    CardStatusError,
    CardStatusImageMissing,
    capture_status_restore,
    restore_card_after_cancel,
    set_manual_status,
)
# 卡片编辑链路（fill/patch/present/chain）已下放 CLI，WebUI 只保留建卡骨架、提交、归档、精选
from card_cli_commands import (
    cmd_create, cmd_options, cmd_render, cmd_check,
    cmd_submit, cmd_featured,
)
from resolver import role_resolver
from card_llm_client import chat_completion
from prompt_rules import (
    get_chat_rules,
    normalize_chat_mode,
    is_draw_mode,
    reset_rule_session,
)

router = APIRouter(tags=["cards"])


def _card_id_or_400(card_id: Any) -> str:
    try:
        return validate_card_id(card_id)
    except InvalidCardIdError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def _card_path_or_400(card_id: Any) -> Path:
    try:
        return resolve_card_path(card_id)
    except InvalidCardIdError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def _safe_join_under(base_dir: str | Path, rel_name: str) -> Optional[Path]:
    """Join base_dir / rel_name only if the resolved path stays under base_dir.

    Blocks absolute paths and `../` traversal in card.render_image.
    """
    if not base_dir or not rel_name:
        return None
    rel = Path(str(rel_name))
    if rel.is_absolute() or ".." in rel.parts:
        # Fast reject obvious traversal; still resolve+relative_to below for symlinks
        rel = Path(rel.name)
        if not rel.name or rel.name in (".", ".."):
            return None
    try:
        base = Path(os.path.expanduser(str(base_dir))).resolve()
        candidate = (base / rel).resolve()
        candidate.relative_to(base)
        return candidate
    except (OSError, ValueError, RuntimeError):
        return None


def _safe_image_url(prefix: str, rel_name: str) -> str:
    """Build /images/... URL using basename only (no path segments)."""
    name = Path(str(rel_name)).name
    return f"{prefix}/{url_quote(name)}"


def _norm_dir(raw: str | Path | None) -> Optional[str]:
    """Expanduser + strip; empty → None."""
    if not raw:
        return None
    s = str(raw).strip()
    if not s:
        return None
    return os.path.expanduser(s)


def _image_search_roots(config: dict) -> list[tuple[str, str]]:
    """Ordered image roots for WebUI: archive → local output.

    Both share ``/images`` (StaticFiles all_directories).
    Dedupes by resolved path so the same disk is not scanned twice.
    """
    roots: list[tuple[str, str]] = []
    seen: set[str] = set()

    def _add(raw: str | None, prefix: str) -> None:
        path = _norm_dir(raw)
        if not path:
            return
        try:
            key = str(Path(path).resolve())
        except (OSError, RuntimeError):
            key = path
        if key in seen:
            return
        seen.add(key)
        roots.append((path, prefix))

    _add(config.get("output_dir_archive"), "/images")
    _add(config.get("output_dir"), "/images")
    return roots


def _resolve_card_image(
    config: dict, render_image: str | None
) -> Optional[tuple[Path, str, str]]:
    """Find render_image on disk.

    Returns ``(abs_path, url_prefix, basename)`` or None.
    Priority: archive → local Comfy output.
    """
    if not render_image:
        return None
    name = Path(str(render_image)).name
    if not name or name in (".", ".."):
        return None
    for base, prefix in _image_search_roots(config):
        candidate = _safe_join_under(base, name)
        if candidate is not None and candidate.is_file():
            return candidate, prefix, name
    return None


def _attach_card_image_fields(card: dict, config: dict) -> Optional[Path]:
    """Align card.render_image / image_url / status hint with on-disk PNG.

    Mutates ``card`` in place. Returns resolved Path if found.
    """
    render_image = card.get("render_image")
    resolved = _resolve_card_image(config, render_image)
    if resolved is None and card.get("card_id"):
        # Fallback: card_id.png when render_image missing or stale
        resolved = _resolve_card_image(config, f"{card['card_id']}.png")
    if resolved is None:
        return None
    path, prefix, name = resolved
    card["render_image"] = name
    card["image_url"] = _safe_image_url(prefix, name)
    return path


def run_core_cmd(*args, **kwargs):
    """Delegate so tests can patch web_server.run_core_cmd."""
    import web_server as _ws
    return _ws.run_core_cmd(*args, **kwargs)


def _core_command_failed(result: Dict[str, Any]) -> bool:
    if not isinstance(result, dict):
        return True
    return bool(result.get("exited") and int(result.get("exit_code") or 0) != 0)


def _core_command_error(result: Dict[str, Any], fallback: str) -> str:
    if not isinstance(result, dict):
        return fallback
    return str(result.get("stderr") or result.get("stdout") or fallback).strip()


def _card_has_nonterminal_queue_job(card_id: str) -> bool:
    """Fail closed when QueueStore cannot prove that the card is idle."""

    from api_queue import _run_queue_cli

    try:
        proc, payload = _run_queue_cli("status", timeout=5)
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"队列状态查询失败: {exc}") from exc
    if proc.returncode != 0 or not payload.get("ok"):
        raise HTTPException(status_code=503, detail="暂时无法确认队列状态，请稍后重试")
    terminal_states = {"completed", "failed"}
    return any(
        str(job.get("card_id") or "") == card_id
        and str(job.get("state") or "") not in terminal_states
        for job in (payload.get("jobs") or [])
        if isinstance(job, dict)
    )


@router.get("/api/poetry")
def get_poetry():
    """对外发行版：离线诗词（白盒加密词库），无西窗烛 API/凭证。"""
    import random
    from pathlib import Path

    try:
        here = Path(__file__).resolve().parent
        db_path = None
        for p in [here] + list(here.parents):
            cand = p / "data" / "poetry_db.json"
            if cand.is_file():
                db_path = cand
                break
        if db_path is None:
            raise RuntimeError("poetry_db.json not found")
        import json
        db = json.loads(db_path.read_text(encoding="utf-8"))
        if db:
            item = random.choice(db)
            return {
                "status": "ok",
                "quote": item.get("quote", ""),
                "title": item.get("title", ""),
                "author": item.get("author", "佚名"),
                "dynasty": item.get("dynasty", ""),
                "audio": None,
            }
    except Exception:
        pass
    fb = random.choice(_OFFLINE_FALLBACK_POEMS)
    return {
        "status": "fallback",
        "quote": fb["quote"],
        "title": fb["title"],
        "author": fb["author"],
        "dynasty": fb["dynasty"],
        "audio": None,
    }


_OFFLINE_FALLBACK_POEMS = [
    {"quote": "春眠不觉晓，处处闻啼鸟。\n夜来风雨声，花落知多少。", "title": "春晓", "author": "孟浩然", "dynasty": "唐"},
    {"quote": "明月几时有？把酒问青天。\n不知天上宫阙，今夕是何年。", "title": "水调歌头·明月几时有", "author": "苏轼", "dynasty": "宋"},
    {"quote": "落霞与孤鹜齐飞，秋水共长天一色。\n渔舟唱晚，响穷彭蠡之滨。", "title": "滕王阁序", "author": "王勃", "dynasty": "唐"},
    {"quote": "君不见，黄河之水天上来，奔流到海不复回。", "title": "将进酒", "author": "李白", "dynasty": "唐"},
    {"quote": "红豆生南国，春来发几枝。\n愿君多采撷，此物最相思。", "title": "相思", "author": "王维", "dynasty": "唐"},
    {"quote": "结庐在人境，而无车马喧。\n问君何能尔？心远地自偏。", "title": "饮酒·其五", "author": "陶渊明", "dynasty": "东晋"},
]

@router.get("/api/settings")
def get_settings():
    return load_system_config()

@router.post("/api/settings")
def post_settings(settings: Dict[str, Any]):
    # 归一化 chat_mode：仅 cards | draw
    if "chat_mode" in settings:
        settings["chat_mode"] = normalize_chat_mode(settings.get("chat_mode"), "cards")
    save_system_config(settings)
    update_images_mount()
    return {"status": "ok", "settings": settings}

def parse_png_filename(filename: str):
    """从 PNG 文件名解析人物、场景和意图描述"""
    name_without_ext = os.path.splitext(filename)[0]
    
    # 检查文件名是否包含中文
    has_chinese = any('\u4e00' <= char <= '\u9fff' for char in name_without_ext)
    
    if has_chinese:
        parts = name_without_ext.split('-')
        if len(parts) >= 3:
            person = parts[0]
            scene = parts[1]
            intent = "-".join(parts[2:])
        elif len(parts) == 2:
            person = parts[0]
            scene = parts[1]
            intent = ""
        else:
            person = "ComfyUI"
            scene = "Raw Output"
            intent = name_without_ext
    else:
        # 英文 Prompt 构型的文件名，归类为 ComfyUI/Raw Output
        person = "ComfyUI"
        scene = "Raw Output"
        intent = name_without_ext
        
    return person, scene, intent


def extract_prompt_from_png(png_path: Path) -> str:
    """利用 Pillow 从 PNG 文件中提取嵌入的英文提示词"""
    try:
        from PIL import Image
        with Image.open(png_path) as img:
            # 1. 尝试 ComfyUI prompt 字段
            if "prompt" in img.info:
                try:
                    prompt_data = json.loads(img.info["prompt"])
                    texts = []
                    for k, v in prompt_data.items():
                        class_type = v.get("class_type", "")
                        inputs = v.get("inputs", {})
                        if "CLIPTextEncode" in class_type or "text" in inputs:
                            text_val = inputs.get("text", "")
                            if isinstance(text_val, str) and text_val.strip():
                                low_text = text_val.lower()
                                # 排除常见的负向提示词
                                if any(neg in low_text for neg in ["low quality", "worst quality", "bad anatomy", "deformed"]):
                                    continue
                                texts.append(text_val.strip())
                    if texts:
                        return max(texts, key=len)
                except Exception:
                    pass

            # 2. 尝试标准 SD parameters 字段
            if "parameters" in img.info:
                params_str = img.info["parameters"]
                if "Negative prompt:" in params_str:
                    return params_str.split("Negative prompt:")[0].strip()
                elif "Steps:" in params_str:
                    return params_str.split("Steps:")[0].strip()
                else:
                    return params_str.strip()
    except Exception as e:
        print(f"Failed to extract prompt metadata from {png_path}: {e}")
    return ""


@router.get("/api/cards")
def list_cards():
    """获取所有卡片摘要"""
    cards = []
    matched_pngs = set()
    
    config = load_system_config()
    
    # 1. 加载所有物理 JSON 卡片
    if CARDS_DIR.exists():
        for f in CARDS_DIR.glob("*.json"):
            try:
                card = json.loads(f.read_text(encoding="utf-8"))
                card_id = card.get("card_id")
                if not card_id:
                    continue
                
                # 默认使用 JSON 的 mtime；有图则以图为准并对齐 render_image/image_url
                mtime = f.stat().st_mtime
                image_url = None
                img_path = _attach_card_image_fields(card, config)
                if img_path is not None:
                    mtime = img_path.stat().st_mtime
                    image_url = card.get("image_url")
                    matched_pngs.add(card.get("render_image") or img_path.name)
                elif card.get("render_image"):
                    matched_pngs.add(os.path.basename(str(card["render_image"])))

                # 列表摘要：人物/场景优先 JSON；若空且文件名可解析则补齐（交付本地 rename 后仍可读）
                person = card.get("subject", {}).get("display_name", "") or ""
                scene = card.get("scene", {}).get("name", "") or ""
                if (not person or not scene) and card.get("render_image"):
                    p2, s2, _ = parse_png_filename(str(card["render_image"]))
                    person = person or p2
                    scene = scene or s2
                try:
                    card_version = int(card.get("version") or 0)
                except (TypeError, ValueError):
                    card_version = 0
                    
                cards.append({
                    "card_id": card_id,
                    "version": card_version,
                    "status": card.get("status", "draft"),
                    "mode": card.get("mode", "amateur"),
                    "person": person,
                    "scene": scene,
                    "narrative": card.get("director", {}).get("story_elevation_zh", "") or card.get("narrative_zh", "") or (card.get("creative", {}) or {}).get("ai_notes", ""),
                    "workflow_mode": card.get("workflow_mode", "single"),
                    "mtime": mtime,
                    "is_virtual": False,
                    "render_image": card.get("render_image"),
                    "image_url": image_url
                })
            except Exception:
                pass

    # 2. 扫描输出目录并查找孤儿 PNG 文件，混合动态合成虚拟卡片
    def _scan_dir_for_orphan_pngs(scan_dir: str, url_prefix: str, cache: dict, cache_ref: list):
        if not scan_dir or not os.path.exists(scan_dir):
            return
        scan_path = Path(scan_dir)
        for entry in os.scandir(scan_path):
            if entry.is_file() and entry.name.lower().endswith(".png"):
                filename = entry.name
                has_chinese = any('\u4e00' <= char <= '\u9fff' for char in filename)
                is_card_prefix = any(filename.startswith(pfx) for pfx in [
                    "Moody_", "Chroma_", "Classic_", "Pure_", "Hentai_", "Sexy_", "Amateur_", 
                    "Cyber_", "Lomo_", "Zimage_", "Flux_", "Nude_"
                ])
                if not (has_chinese or is_card_prefix):
                    continue

                if filename in matched_pngs:
                    continue
                    
                stat = entry.stat()
                mtime = stat.st_mtime
                size = stat.st_size
                
                cached_item = cache.get(filename)
                if cached_item and cached_item.get("mtime") == mtime and cached_item.get("size") == size:
                    person = cached_item.get("person", "")
                    scene = cached_item.get("scene", "")
                    intent = cached_item.get("intent", "")
                    prompt = cached_item.get("prompt", "")
                else:
                    person, scene, intent = parse_png_filename(filename)
                    prompt = extract_prompt_from_png(entry.path)
                    cache[filename] = {
                        "mtime": mtime,
                        "size": size,
                        "person": person,
                        "scene": scene,
                        "intent": intent,
                        "prompt": prompt
                    }
                    cache_ref[0] = True
                    
                card_id_virtual = os.path.splitext(filename)[0]
                cards.append({
                    "card_id": card_id_virtual,
                    "version": None,
                    "status": "rendered",
                    "mode": "amateur",
                    "person": person,
                    "scene": scene,
                    "narrative": intent or prompt[:100],
                    "workflow_mode": "single",
                    "mtime": mtime,
                    "is_virtual": True,
                    "render_image": filename,
                    "image_url": f"{url_prefix}/{url_quote(filename)}"
                })

    try:
        cache_path = CARDS_DIR.parent / "png_metadata_cache.json"
        cache = {}
        if cache_path.exists():
            try:
                cache = json.loads(cache_path.read_text(encoding="utf-8"))
            except Exception:
                pass
                
        cache_updated = [False]
        # archive → local Comfy output（与 /images 双挂载一致）
        for scan_dir, url_prefix in _image_search_roots(config):
            _scan_dir_for_orphan_pngs(scan_dir, url_prefix, cache, cache_updated)
            
        if cache_updated[0]:
            try:
                CARDS_DIR.parent.mkdir(parents=True, exist_ok=True)
                cache_path.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")
            except Exception:
                pass
    except Exception as scan_err:
        print(f"⚠️ Warning: list_cards scanning orphan images failed: {scan_err}")

    # 按 mtime 降序排列
    cards.sort(key=lambda x: x["mtime"], reverse=True)
    return cards


@router.get("/api/cards/{card_id}")
def get_card(card_id: str):
    card_path = _card_path_or_400(card_id)
    if not card_path.exists():
        # 1. 优先：检查是否是按图片名（文件名 stem）查找，尝试反查 render_image 相同的真实卡片 JSON
        try:
            for jf in CARDS_DIR.glob("*.json"):
                try:
                    jdata = json.loads(jf.read_text(encoding="utf-8"))
                    if jdata.get("render_image") == f"{card_id}.png":
                        config = load_system_config()
                        _attach_card_image_fields(jdata, config)
                        return jdata
                except Exception:
                    continue
        except Exception:
            pass

        # 2. 降级：检查是否存在与该 card_id 对应的孤儿 PNG 图片并合成
        config = load_system_config()
        resolved = _resolve_card_image(config, f"{card_id}.png")
        png_path = None
        img_prefix = "/images"
        if resolved is not None:
            png_path, img_prefix, _ = resolved
                
        if png_path:
            # 触发 Option B：动态合成 JSON 卡片并写入 CARDS_DIR
            person, scene, intent = parse_png_filename(png_path.name)
            prompt = extract_prompt_from_png(png_path)
            
            card = {
                "card_id": card_id,
                "version": 1,
                "status": "rendered",
                "validation_mode": "normal",
                "mode": "amateur",
                "workflow_mode": "single",
                "scene": {
                    "name": scene,
                    "keywords": "",
                    "tags": [],
                    "moods": [],
                    "optional_details": [],
                    "directives": None
                },
                "subject": {
                    "mode": "amateur",
                    "display_name": person,
                    "trigger": "girl",
                    "lora": None,
                    "archetype": None,
                    "model_type": "z"
                },
                "creative": {
                    "freedom": "guided",
                    "source": {
                        "scene": "manual-library",
                        "person": "manual"
                    },
                    "workflow_override": None,
                    "ai_notes": intent or "",
                    "last_user_input": ""
                },
                "director": {
                    "intent": intent or "",
                    "exposure_mode": "upper",
                    "pose_direction": "",
                    "focus_detail": ""
                },
                "slots": {
                    "lighting": "",
                    "clothing": prompt,
                    "pose": "",
                    "expression_gaze": "",
                    "style_quality": "",
                    "makeup_hair": "",
                    "accessories": "",
                    "imperfections": "",
                    "tattoo": "",
                    "props": "",
                    "pet": "",
                    "liquids": "",
                    "body_shape": ""
                },
                "narrative_zh": intent or "",
                "render": {
                    "width": 512,
                    "height": 768,
                    "seed": None,
                    "workflow_config": "moody"
                },
                "delivery": {
                    "reply_id": None
                },
                "option_map": {},
                "user_constraints": {
                    "raw": "",
                    "identity": person,
                    "profile": "",
                    "celebrity": "",
                    "scene": scene,
                    "theme": "",
                    "view": "",
                    "exposure": "",
                    "style": "",
                    "aspect": "",
                    "locked": ["identity", "scene"],
                    "resolved": {
                        "person": person,
                        "profile": "default",
                        "scene": scene,
                        "scene_source": "manual-library"
                    }
                },
                "history": [],
                "_render_output": {
                    "prompt": prompt,
                    "narrative": intent or "",
                    "meta_person": person,
                    "meta_scene": scene,
                    "meta_theme": intent or "",
                    "meta_narrative": intent or "",
                    "meta_focus_detail": "",
                    "meta_story_elevation": "",
                    "meta_lighting": "",
                    "meta_style": "",
                    "meta_lighting_display": "",
                    "meta_style_display": "",
                    "meta_lighting_source": "",
                    "meta_style_source": ""
                },
                "render_image": png_path.name,
                "image_url": f"{img_prefix}/{url_quote(png_path.name)}"
            }
            
            try:
                CARDS_DIR.mkdir(parents=True, exist_ok=True)
                card_path.write_text(json.dumps(card, ensure_ascii=False, indent=2), encoding="utf-8")
                # 保持文件修改时间与原图一致，防止点击卡片后时间错乱
                png_mtime = png_path.stat().st_mtime
                os.utime(str(card_path), (png_mtime, png_mtime))
            except Exception as ex:
                raise HTTPException(status_code=500, detail=f"Failed to save synthesized card JSON: {ex}")
            return card
        raise HTTPException(status_code=404, detail="Card not found")
        
    try:
        card = json.loads(card_path.read_text(encoding="utf-8"))
        config = load_system_config()
        img_path = _attach_card_image_fields(card, config)
        # 人物/场景空时，用文件名补齐（与列表摘要一致）
        if img_path is not None:
            person = (card.get("subject") or {}).get("display_name", "") or ""
            scene = (card.get("scene") or {}).get("name", "") or ""
            if (not person or not scene) and card.get("render_image"):
                p2, s2, intent = parse_png_filename(str(card["render_image"]))
                if card.get("subject") is None:
                    card["subject"] = {}
                if card.get("scene") is None:
                    card["scene"] = {}
                if not person and p2:
                    card["subject"]["display_name"] = p2
                if not scene and s2:
                    card["scene"]["name"] = s2
                if intent and not (card.get("narrative_zh") or (card.get("director") or {}).get("intent")):
                    card.setdefault("director", {})
                    if not card["director"].get("intent"):
                        card["director"]["intent"] = intent
        return card
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.patch("/api/cards/{card_id}/status")
def update_card_status_api(card_id: str, req: Dict[str, Any]):
    """Safely change one stable card status from the sidebar badge menu."""

    card_id = _card_id_or_400(card_id)
    req = req or {}
    target_status = str(req.get("status") or "").strip()
    raw_version = req.get("expected_version")
    try:
        expected_version = int(raw_version)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="expected_version 必须是整数")

    try:
        return set_manual_status(
            card_id,
            target_status=target_status,
            expected_version=expected_version,
            has_nonterminal_queue_job=lambda: _card_has_nonterminal_queue_job(card_id),
        )
    except (CardStatusConflict, CardStatusImageMissing) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except CardStatusError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.delete("/api/cards/{card_id}")
async def delete_card(card_id: str):
    card_path = _card_path_or_400(card_id)
    config = load_system_config()
    
    png_filename = None
    
    # 1. 尝试从已存在的 JSON 卡片中提取图片名称
    if card_path.exists():
        try:
            card = json.loads(card_path.read_text(encoding="utf-8"))
            render_image = card.get("render_image")
            if render_image:
                png_filename = os.path.basename(render_image)
        except Exception:
            pass
            
        try:
            card_path.unlink()
        except Exception:
            pass
            
    # 2. 如果未在 JSON 中提取到，或者它是虚拟卡片，使用 card_id.png 作为默认值
    if not png_filename:
        png_filename = f"{card_id}.png"
        
    # 3. 物理删除 PNG：archive / 本地 output / config fallback 全扫
    for base, _prefix in _image_search_roots(config):
        img_path = _safe_join_under(base, png_filename)
        if img_path is not None and img_path.exists():
            try:
                img_path.unlink()
            except Exception as e:
                print(f"Failed to delete PNG file {img_path}: {e}")
                
    # 4. 从元数据缓存中剔除对应的文件名记录
    if png_filename:
        cache_path = CARDS_DIR.parent / "png_metadata_cache.json"
        if cache_path.exists():
            try:
                cache = json.loads(cache_path.read_text(encoding="utf-8"))
                if png_filename in cache:
                    cache.pop(png_filename)
                    cache_path.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")
            except Exception:
                pass
                
    # 5. 清理聊天历史和规则缓存
    clear_chat_history(card_id)
    reset_rule_session(webui_session_id(card_id))
        
    return {"status": "deleted"}

# 状态集合必须与前端 CARD_FILTERS 一一对应，否则弹窗预告的数量会与实际删除量不符
CLEANUP_STATUS_GROUPS = {
    "drafts": ("draft", "filled"),
    "queued": ("validated", "submitted", "queued", "rendering"),
    "failed": ("failed",),
    "missing_images": ("rendered", "success"),
}


def _is_cleanup_eligible_card_id(card_id: str) -> bool:
    """只清理时间戳卡与 featured_ 临时卡，避免误删开发测试卡。"""
    if len(card_id) > 15 and card_id[0].isdigit():
        return True
    return card_id.startswith("featured_") and len(card_id) > 15


def _purge_card(path, card_id: str) -> None:
    """物理删除卡片及其对话痕迹。"""
    path.unlink()
    clear_chat_history(card_id)
    reset_rule_session(webui_session_id(card_id))


def _card_has_local_image(config: dict, card: dict, card_id: str) -> bool:
    """任一精确关联图片仍在配置的本地目录中，就保护该卡不被批量删除。"""
    if _resolve_card_image(config, card.get("render_image")) is not None:
        return True
    return bool(card_id and _resolve_card_image(config, f"{card_id}.png") is not None)


def _cleanup_cards(
    group: str,
    extra_predicate=None,
    *,
    config: Optional[dict] = None,
) -> Dict[str, Any]:
    """按状态批量清理；任何仍有本地图片的卡片一律跳过。"""
    statuses = CLEANUP_STATUS_GROUPS[group]
    deleted_ids = []
    skipped_image_ids = []
    config = config or load_system_config()
    if not CARDS_DIR.exists():
        return {
            "status": "ok",
            "cleaned_count": 0,
            "deleted_ids": [],
            "skipped_image_count": 0,
            "skipped_image_ids": [],
        }

    for f in CARDS_DIR.glob("*.json"):
        card_id = f.stem
        if not _is_cleanup_eligible_card_id(card_id):
            continue
        try:
            card = json.loads(f.read_text(encoding="utf-8"))
            if card.get("status", "") not in statuses:
                continue
            if _card_has_local_image(config, card, card_id):
                skipped_image_ids.append(card_id)
                continue
            if extra_predicate and not extra_predicate(card, card_id):
                continue
            _purge_card(f, card_id)
            deleted_ids.append(card_id)
        except Exception as e:
            print(f"Cleanup card {card_id} ({group}) failed: {e}")

    return {
        "status": "ok",
        "cleaned_count": len(deleted_ids),
        "deleted_ids": deleted_ids,
        "skipped_image_count": len(skipped_image_ids),
        "skipped_image_ids": skipped_image_ids,
    }


@router.post("/api/cards/cleanup-missing-images")
def cleanup_missing_images():
    """一键清理：删除已渲染完成但物理图片已不存在/被清理的卡片"""
    config = load_system_config()
    if not _image_search_roots(config):
        return {
            "status": "ok",
            "cleaned_count": 0,
            "deleted_ids": [],
            "skipped_image_count": 0,
            "skipped_image_ids": [],
        }

    def image_gone(card, card_id):
        # archive / 本地 output / config fallback 任一存在即保留
        if _resolve_card_image(config, card.get("render_image")) is not None:
            return False
        return not card_id or _resolve_card_image(config, f"{card_id}.png") is None

    return _cleanup_cards("missing_images", image_gone, config=config)


@router.post("/api/cards/cleanup-drafts")
def cleanup_drafts():
    """一键清理无本地图的草稿分类（draft / filled）卡片。"""
    return _cleanup_cards("drafts")


@router.post("/api/cards/cleanup-queued")
def cleanup_queued():
    """一键清理无本地图的定稿分类卡片。"""
    return _cleanup_cards("queued")


@router.post("/api/cards/cleanup-failed")
def cleanup_failed():
    """一键清理无本地图的失败卡片。"""
    return _cleanup_cards("failed")

@router.post("/api/cards/create")
def create_card(req: Dict[str, Any]):
    """创建新卡面骨架"""
    # 构造 Namespace
    # user_input 是引擎构建 user_constraints 的唯一来源，缺失会导致整张卡没有任何用户锁定项
    user_input = str(req.get("user_input") or "").strip()
    if not user_input:
        raise HTTPException(status_code=400, detail="user_input 不能为空：引擎需要它解析人物/场景/裸露等用户约束")

    bundle = req.get("bundle")
    if bundle is True:
        bundle = "auto"

    args = argparse.Namespace(
        mode=req.get("mode", "amateur"),
        scene=req.get("scene"),
        person=req.get("person"),
        workflow=req.get("workflow"),
        size=req.get("size"),
        aspect=req.get("aspect", "portrait"),
        seed=req.get("seed"),
        profile=req.get("profile", "default"),
        user_input=user_input,
        bundle=bundle or None,
    )
    
    res = run_core_cmd(cmd_create, args)
    
    card_id = res.get("return_value")
    if not card_id:
        match = re.search(r"card_id=([0-9a-zA-Z_]+)", res["stdout"])
        if match:
            card_id = match.group(1)
        else:
            raise HTTPException(status_code=500, detail=f"Create failed: {res['stdout']}\n{res['stderr']}")
    
    # 自动执行 options-auto 初始化动态方向映射，保证新卡可以直接 present
    try:
        opt_args = argparse.Namespace(card=card_id, auto=True, file=None, json=None)
        run_core_cmd(cmd_options, opt_args)
    except Exception as ex_opt:
        print(f"Auto option_map generation failed for card {card_id}: {ex_opt}")


    return {
        "status": "created",
        "card_id": card_id,
        "stdout": res["stdout"]
    }

@router.post("/api/featured")
def featured_api(req: Dict[str, Any] = None):
    """精选模式: 随机灵感库笔记 → 建 featured 卡并提交 GPU 队列"""
    req = req or {}
    args = argparse.Namespace(
        width=req.get("width"),
        height=req.get("height"),
        workflow=req.get("workflow"),
    )
    res = run_core_cmd(cmd_featured, args)
    if res["exited"] and res["exit_code"] not in (0, None):
        raise HTTPException(
            status_code=500,
            detail=f"Featured failed:\n{res['stdout']}\n{res['stderr']}",
        )

    card_id = res.get("return_value")
    if not card_id:
        m_featured = re.search(r"featured_\d+_\d+", res.get("stdout") or "")
        m_generic = re.search(r"card_id[=: ]([0-9a-zA-Z_]+)", res.get("stdout") or "")
        if m_featured:
            card_id = m_featured.group(0)
        elif m_generic:
            card_id = m_generic.group(1)
        else:
            newest_id, newest_mtime = None, 0.0
            if CARDS_DIR.exists():
                for f in CARDS_DIR.glob("featured_*.json"):
                    mtime = f.stat().st_mtime
                    if mtime > newest_mtime:
                        newest_mtime = mtime
                        newest_id = f.stem
            card_id = newest_id

    if not card_id:
        raise HTTPException(
            status_code=500,
            detail=f"Featured succeeded but card_id missing:\n{res['stdout']}\n{res['stderr']}",
        )

    return {
        "status": "ok",
        "card_id": card_id,
        "stdout": res["stdout"],
        "stderr": res["stderr"],
    }

def extract_card_info_via_llm(prompt: str) -> dict:
    # 🌟 正则/切片 fallback 兜底（禁止「素人」——会撞 cu-submit.sh 硬拦）
    def _scrub_banned(text: str, fallback: str) -> str:
        t = str(text or "").strip()
        if not t or "素人" in t:
            return fallback
        return t

    fallback_data = {
        "person": "直投模式",
        "scene": "Raw Prompt",
        "narrative_zh": _scrub_banned(prompt, "用户英文 Prompt 直投生图"),
    }
    
    try:
        from card_llm_client import chat_completion
        system_msg = (
            "You are a prompt analyzer. Given a Stable Diffusion English prompt, extract the main subject (person), the core scene, "
            "and provide a short, natural Chinese translation/description of the scene.\n"
            "Respond ONLY with a valid JSON object matching this schema, no markdown blocks, no other text:\n"
            "{\"person\": \"Subject name/description\", \"scene\": \"Scene name/description\", \"narrative_zh\": \"Short Chinese translation of the prompt\"}\n"
            "Never use the Chinese word 素人 for person/scene/narrative."
        )
        messages = [
            {"role": "system", "content": system_msg},
            {"role": "user", "content": f"Prompt: {prompt}"}
        ]
        
        # 设为 8s 超时，防止网络阻塞且留有充足代理重试时间
        res_text = chat_completion(
            messages=messages,
            max_tokens=150,
            temperature=0.1,
            timeout=30
        )
        
        if res_text:
            cleaned_text = res_text.strip()
            if cleaned_text.startswith("```json"):
                cleaned_text = cleaned_text[7:]
            if cleaned_text.endswith("```"):
                cleaned_text = cleaned_text[:-3]
            cleaned_text = cleaned_text.strip()
            
            data = json.loads(cleaned_text)
            person = _scrub_banned(data.get("person", ""), fallback_data["person"])
            scene = _scrub_banned(data.get("scene", ""), fallback_data["scene"])
            narrative_zh = _scrub_banned(data.get("narrative_zh", ""), fallback_data["narrative_zh"])
            
            if len(person) > 25:
                person = person[:25] + "..."
            if len(scene) > 25:
                scene = scene[:25] + "..."
                
            return {
                "person": person,
                "scene": scene,
                "narrative_zh": narrative_zh
            }
    except Exception as e:
        print(f"⚠️ LLM direct submit prompt analysis failed, using fallback: {e}")
        
    return fallback_data

@router.post("/api/direct/submit")
def direct_submit_api(req: Dict[str, Any]):
    """直投模式: 直接提交裸 English Prompt 到 ComfyUI 渲染队列"""
    import subprocess
    from card_io import save_card

    prompt = req.get("prompt", "").strip()
    if not prompt:
        raise HTTPException(status_code=400, detail="Prompt is empty")

    requested_card_id = req.get("card_id") or None
    if requested_card_id is not None:
        requested_card_id = _card_id_or_400(requested_card_id)

    # 用 LLM 或者是切片 fallback 提取优雅的卡片元数据
    info = extract_card_info_via_llm(prompt)

    def _scrub_req(val, fallback):
        t = str(val or "").strip()
        if not t or "素人" in t:
            return fallback
        return t

    display_name = _scrub_req(req.get("person"), info["person"])
    scene_name = _scrub_req(req.get("scene"), info["scene"])
    narrative_zh = _scrub_req(req.get("narrative"), info["narrative_zh"])
    theme_val = req.get("theme", "")
    lighting_val = req.get("lighting", "")
    style_val = req.get("style", "")

    # 自动生成卡片
    card_id = requested_card_id or new_card_id("direct")
    card = {
        "card_id": card_id,
        "version": 1,
        "status": "draft",
        "workflow_mode": "direct",
        "narrative_zh": narrative_zh,
        "subject": {"display_name": display_name, "trigger": "girl", "lora": None},
        "scene": {"name": scene_name, "keywords": ""},
        "director": {
            "intent": theme_val,
            "lighting_palette_zh": lighting_val,
            "style_recipe_zh": style_val,
            "story_elevation_zh": narrative_zh
        },
        "slots": {
            "scene_theme": "", "lighting": "", "clothing": prompt,
            "pose": "", "expression_gaze": "", "style_quality": "",
            "makeup_hair": "", "accessories": "", "imperfections": "",
            "tattoo": "", "props": "", "pet": "", "liquids": "",
            "body_shape": ""
        },
        "_render_output": {
            "prompt": prompt,
            "meta_person": display_name,
            "meta_scene": scene_name,
            "meta_narrative": prompt,
            "meta_theme": theme_val,
            "meta_lighting_display": lighting_val,
            "meta_style_display": style_val
        }
    }
    save_card(card)

    # 用户输入可以先落历史；成功提示必须等队列返回结构化 acceptance ACK。
    try:
        append_chat_history(card_id, "user", prompt)
    except Exception as ex_chat:
        print(f"Pre-pending chat history failed for card {card_id}: {ex_chat}")

    cmd = [
        "bash",
        str(SCRIPT_DIR.parent / "gpu-pipeline" / "cu-submit.sh"),
        "--raw",
        "--prompt", prompt,
        "--card", card_id
    ]
    # Optionally append extra properties if provided
    if req.get("width"):
        cmd += ["--width", str(req["width"])]
    if req.get("height"):
        cmd += ["--height", str(req["height"])]
    if req.get("workflow"):
        cmd += ["--workflow", str(req["workflow"])]
    if display_name:
        cmd += ["--person", str(display_name)]
    if scene_name:
        cmd += ["--scene", str(scene_name)]
    if theme_val:
        cmd += ["--theme", str(theme_val)]
    if narrative_zh:
        cmd += ["--narrative", str(narrative_zh)]
    if lighting_val:
        cmd += ["--lighting", str(lighting_val)]
    if style_val:
        cmd += ["--style", str(style_val)]
        
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if res.returncode != 0:
            raise Exception(res.stderr.strip() or res.stdout.strip())
        ack: Dict[str, Any] = {}
        for line in reversed((res.stdout or "").splitlines()):
            try:
                candidate = json.loads(line)
            except (TypeError, ValueError, json.JSONDecodeError):
                continue
            if isinstance(candidate, dict):
                ack = candidate
                break
        job_id = str(ack.get("job_id") or "")
        if not ack.get("accepted") or not job_id:
            raise Exception(
                ack.get("error")
                or res.stderr.strip()
                or "Queue submit returned no structured acceptance ACK"
            )

        with card_lock(card_id, owner="direct-submit-ack", timeout=20.0):
            submitted_card = load_card(card_id)
            render_cfg = submitted_card.setdefault("render", {})
            current_job_id = str(render_cfg.get("queue_job_id") or "")
            current_queue_state = str(render_cfg.get("queue_state") or "")
            current_status = str(submitted_card.get("status") or "")
            if current_status in {"draft", "rendering", "submitted", "queued"} and not (
                current_job_id == job_id
                and current_queue_state in {"cancelled", "failed"}
            ):
                render_cfg["queue_job_id"] = job_id
                render_cfg["queue_state"] = str(
                    ack.get("state") or ack.get("status") or "pending"
                )
                submitted_card["status"] = (
                    "submitted"
                    if ack.get("status") == "started"
                    else "queued"
                )
                save_card(submitted_card)
        try:
            append_chat_history(
                card_id,
                "assistant",
                f"🚀 直投任务已提交渲染队列！\n\n提示词: `{prompt}`",
            )
        except Exception as ex_chat:
            print(f"Post-accept chat history failed for card {card_id}: {ex_chat}")
        return {
            "status": str(submitted_card.get("status") or "queued"),
            "card_id": card_id,
            "job_id": job_id,
            "stdout": res.stdout,
            "stderr": res.stderr
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Direct submit failed: {str(e)}")

@router.post("/api/cards/{card_id}/submit")
def submit_card_api(card_id: str, req: Dict[str, Any]):
    """提交队列：定稿/完成卡直接 submit；其他卡执行 render → check → submit。"""
    card_id = _card_id_or_400(card_id)
    req = req or {}
    initial_card = load_card(card_id)
    direct_checked_submit = initial_card.get("status") in {
        "validated",
        "rendered",
        "delivered",
        "success",
    }

    if not direct_checked_submit:
        capture_status_restore(card_id, source="webui_rerender")
        render_res = run_core_cmd(cmd_render, argparse.Namespace(card=card_id))
        if _core_command_failed(render_res):
            with contextlib.suppress(Exception, SystemExit):
                restore_card_after_cancel(
                    card_id,
                    reason="render_preflight_failed",
                    fallback_status="draft",
                )
            raise HTTPException(
                status_code=400,
                detail=_core_command_error(render_res, "Render failed; submit blocked."),
            )

        card = load_card(card_id)
        check_res = run_core_cmd(
            cmd_check,
            argparse.Namespace(
                card=card_id,
                chain_mode=(card.get("workflow_mode") == "chain"),
            ),
        )
        if _core_command_failed(check_res):
            with contextlib.suppress(Exception, SystemExit):
                restore_card_after_cancel(
                    card_id,
                    reason="validation_preflight_error",
                    fallback_status="draft",
                )
            raise HTTPException(
                status_code=400,
                detail=_core_command_error(check_res, "Check failed; submit blocked."),
            )

        card = load_card(card_id)
        validation = card.get("_validation", {}) or {}
        if validation.get("errors") or card.get("status") != "validated":
            with contextlib.suppress(Exception, SystemExit):
                restore_card_after_cancel(
                    card_id,
                    reason="validation_preflight_failed",
                    fallback_status="draft",
                )
            raise HTTPException(status_code=400, detail={
                "message": "Check failed; submit blocked.",
                "errors": validation.get("errors", []),
                "warnings": validation.get("warnings", []),
                "error_details": validation.get("error_details", []),
                "stdout": check_res["stdout"],
                "stderr": check_res["stderr"],
            })
    user_input = req.get("user_input")
    idempotency_key = None
    if direct_checked_submit:
        request_id = re.sub(
            r"[^A-Za-z0-9_.-]",
            "",
            str(req.get("request_id") or ""),
        )[:80]
        if not request_id:
            request_id = new_card_id("render")
        idempotency_key = f"webui-render:{card_id}:{request_id}"
    res = run_core_cmd(
        cmd_submit,
        argparse.Namespace(
            card=card_id,
            user_input=user_input,
            confirm=True,
            capture_restore=direct_checked_submit,
            restore_source="webui_checked_render",
            trusted_requeue=direct_checked_submit,
            idempotency_key=idempotency_key,
        ),
    )
    card = load_card(card_id)
    ack = res.get("return_value") if isinstance(res, dict) else None
    ack = ack if isinstance(ack, dict) else {}
    card_status = str(card.get("status") or "")
    job_id = str(
        ack.get("job_id")
        or ((card.get("render") or {}).get("queue_job_id"))
        or ""
    )
    accepted = bool(
        not _core_command_failed(res)
        and ack.get("accepted")
        and job_id
        and card_status in {"queued", "submitted", "rendering", "rendered"}
    )
    if not accepted:
        with contextlib.suppress(Exception, SystemExit):
            if not _card_has_nonterminal_queue_job(card_id):
                current = load_card(card_id)
                if (
                    not direct_checked_submit
                    or isinstance(current.get("_status_restore"), dict)
                ):
                    restore_card_after_cancel(
                        card_id,
                        reason="submit_rejected_before_queue",
                        fallback_status="draft",
                    )
        raise HTTPException(
            status_code=400,
            detail=_core_command_error(res, "Submit rejected before queue acceptance."),
        )
    return {
        "status": card_status,
        "job_id": job_id,
        "queue_status": ack.get("status"),
        "queue_state": ack.get("state"),
        "stdout": res.get("stdout", ""),
        "stderr": res.get("stderr", ""),
    }

@router.post("/api/cards/{card_id}/archive")
def archive_card_api(card_id: str):
    """将卡片安全且幂等地归档到 Obsidian。"""
    card_id = _card_id_or_400(card_id)
    try:
        result = archive_card(card_id)
    except ArchiveImageNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ArchiveImageAmbiguous as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except (ArchiveError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    status = result.get("status")
    return {
        **result,
        "archived": status == "archived",
        "already_archived": status == "already_archived",
        "message": (
            "该卡已保存过，无需重复保存。"
            if status == "already_archived"
            else "归档成功"
        ),
    }

# 预设与系统 API

try:
    from pypinyin import lazy_pinyin, Style as _PinyinStyle
except Exception:  # 没装 pypinyin 也要能用，只是退化成不支持拼音搜索
    lazy_pinyin = None
    _PinyinStyle = None


def _pinyin_initial(name: str) -> str:
    """首字母分组键；非中文或取不到时归入 # 组。"""
    if not name:
        return "#"
    if lazy_pinyin is None:
        c = name[0].upper()
        return c if c.isascii() and c.isalpha() else "#"
    parts = lazy_pinyin(name[0], style=_PinyinStyle.FIRST_LETTER)
    c = (parts[0][:1] if parts else "").upper()
    return c if c.isalpha() else "#"


def _pinyin_full(name: str) -> str:
    """全拼，供「liuyifei」式搜索。"""
    if not name or lazy_pinyin is None:
        return ""
    return "".join(lazy_pinyin(name)).lower()


def _pinyin_abbr(name: str) -> str:
    """首字母缩写，供「lyf」式搜索。"""
    if not name or lazy_pinyin is None:
        return ""
    return "".join(p[:1] for p in lazy_pinyin(name, style=_PinyinStyle.FIRST_LETTER)).lower()


@router.get("/api/config/roles")
def get_roles():
    """获取所有内置与第三方角色 Profiles（与抽卡 load_amateurs 同源：amateurs.json + amateurs/ + roles/）。"""
    builtin_path = SCRIPT_DIR.parent / "card-engine" / "config" / "amateurs.json"
    try:
        builtin_data = json.loads(builtin_path.read_text(encoding="utf-8"))
    except Exception:
        builtin_data = {"profiles": {}, "identity_pool": []}
    builtin_profile_keys = set((builtin_data.get("profiles") or {}).keys())
    builtin_pool = list(builtin_data.get("identity_pool") or [])

    # 与抽卡同一合并逻辑
    try:
        merged = role_resolver.load_amateurs()
    except Exception:
        merged = builtin_data

    profiles = {}
    for k, v in (merged.get("profiles") or {}).items():
        if not isinstance(v, dict):
            continue
        src = "builtin" if k in builtin_profile_keys else "third-party"
        profiles[k] = {**v, "source": src}

    # 兼容旧路径：custom_presets_dir/profiles/*.json（扁平 {key: profile}）
    config = load_system_config()
    presets_dir = Path(config.get("custom_presets_dir", str(PRESETS_DIR)))
    profiles_dir = presets_dir / "profiles"
    if profiles_dir.exists():
        for f in profiles_dir.glob("*.json"):
            if f.name == "template.json":
                continue
            try:
                custom_data = json.loads(f.read_text(encoding="utf-8"))
                if isinstance(custom_data, dict):
                    for k, v in custom_data.items():
                        if k.startswith("_") or not isinstance(v, dict):
                            continue
                        profiles[k] = {**v, "source": "third-party", "file": f.name}
            except Exception:
                pass

    celebrities = []
    try:
        celebs_map = role_resolver.load_celebrities()
        for mode_key in ["z", "flux"]:
            for lora_key, item in celebs_map.get(mode_key, {}).items():
                # celebrities.json 形如 {"girlslike_zi_ayx": ["安悦溪", "触发词"]}：
                # 键是 lora 名，中文名在值里。早先把值当 dict 取 .get("lora") 会抛异常，
                # 又被空的 except 吞掉，导致这个列表长期恒为空，前端的明星补全从未生效。
                if isinstance(item, list) and item:
                    display = str(item[0]).strip()
                    trigger = str(item[1]).strip() if len(item) > 1 else display
                elif isinstance(item, dict):
                    display = str(item.get("name") or lora_key).strip()
                    trigger = item.get("trigger") or display
                else:
                    display = str(item).strip()
                    trigger = display
                if not display:
                    continue
                celebrities.append({
                    "name": display,
                    "model_type": mode_key,
                    "lora": lora_key,
                    "trigger": trigger,
                    "initial": _pinyin_initial(display),
                    "pinyin": _pinyin_full(display),
                    "abbr": _pinyin_abbr(display),
                    "source": "celebrity",
                })
    except Exception as e:
        # 再出问题要看得见，不能又变成一个静默的空列表
        print(f"⚠️ 明星列表解析失败: {type(e).__name__}: {e}", flush=True)

    identity_pool = list(merged.get("identity_pool") or builtin_pool)
    try:
        from card_identity import (
            RESTRICTED_IDENTITIES,
            is_restricted_profile,
            role_restrictions_enabled,
        )
        if role_restrictions_enabled():
            profiles = {
                k: v for k, v in profiles.items()
                if not is_restricted_profile(k, v if isinstance(v, dict) else None)
            }
            identity_pool = [i for i in identity_pool if i not in RESTRICTED_IDENTITIES]
    except Exception:
        pass

    return {
        "profiles": profiles,
        "identity_pool": identity_pool,
        "celebrities": celebrities
    }

@router.get("/api/config/scenes")
def get_scenes():
    """获取内置 special_scenes + 第三方 scenes/（支持 {library,items} 与纯数组两种格式）。"""
    builtin_path = SCRIPT_DIR.parent / "card-engine" / "libraries" / "special_scenes.json"
    try:
        builtin_scenes_data = json.loads(builtin_path.read_text(encoding="utf-8"))
        builtin_scenes = list(builtin_scenes_data.get("items", []) or [])
    except Exception:
        builtin_scenes = []

    for s in builtin_scenes:
        if isinstance(s, dict):
            s["source"] = "builtin"
            s.setdefault("library", "special_scenes")

    config = load_system_config()
    presets_dir = Path(config.get("custom_presets_dir", str(PRESETS_DIR)))
    scenes_dir = presets_dir / "scenes"
    if scenes_dir.exists():
        for f in scenes_dir.glob("*.json"):
            if f.name == "template.json":
                continue
            try:
                custom_scenes = json.loads(f.read_text(encoding="utf-8"))
                items = []
                library = "general_scenes"
                if isinstance(custom_scenes, list):
                    items = custom_scenes
                elif isinstance(custom_scenes, dict):
                    library = str(custom_scenes.get("library") or "general_scenes")
                    raw_items = custom_scenes.get("items", [])
                    if isinstance(raw_items, list):
                        items = raw_items
                for s in items:
                    if not isinstance(s, dict) or not s.get("label"):
                        continue
                    entry = dict(s)
                    entry["source"] = "third-party"
                    entry["file"] = f.name
                    entry.setdefault("library", library)
                    builtin_scenes.append(entry)
            except Exception:
                pass

    return builtin_scenes
