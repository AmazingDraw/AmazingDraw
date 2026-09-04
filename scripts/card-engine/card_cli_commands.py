#!/usr/bin/env python3
"""
card_cli_commands.py — CLI Commands implementation layer.
Defines all cmd_xxx CLI handlers to keep card_core.py clean and importable.
"""

import argparse
import copy
import json
import random
import re
import subprocess
import os
import sys
from datetime import datetime
from pathlib import Path

from card_autofix import CAMERA_MAP, SAFE_CUMS, SAFE_TATTOOS

# Import variables and helper APIs from card_core.py
from card_core import (
    build_user_constraints,
    auto_fix_card,
    auto_direction_patch_value,
    refresh_display_fields,
    safe_autofix_card_text_fields,
    explain_auto_fix_changes,
    robust_normalize_payload,
    run_single_chain,
    run_chain_resume,
    write_chain_fill_templates,
    CARDS_DIR,
    SLOT_RENDER_ORDER,
    SLOT_CLEAN_EXCEPT_TATTOO,
    DIRECTION_POOL,
)

# Sibling utility imports
from card_io import (
    ts_id, card_path as resolve_card_path, load_card, save_card,
    set_nested, get_nested, sync_scene_metadata_from_slots,
    set_scene_keywords_preserve_name, is_manual_custom_scene_card,
    invalidate_render_cache, card_lock,
)
from card_scene_router import (
    scene_requests_sm_theme, scene_requests_workplace_theme,
    scene_requests_school_theme, scene_requests_medical_theme, scene_requests_general_theme,
    scene_requests_contrast_theme, scene_requests_special_theme, scene_requests_perspective_theme,
    infer_semantic_route_flags,
    resolve_scene_by_label_from_libraries, resolve_library_fields, pick_scene_for_create,
    infer_multi_subject_layout,
)
from card_validation import (
    strip_ansi,
    summarize_check_output,
    _contains_any,
    has_cjk,
    validation_binding_mismatches,
)
from card_identity import (
    _get_identity_group, _normalize_manual_identity, _pick_identity_and_profile,
    infer_profile_constraint_from_text,
)
from card_config import (
    SCRIPT_DIR,
    get_default_workflow_name,
    load_workflow_config,
    load_workflow_defaults,
    load_system_config,
    load_direction_map,
    load_validation_rules,
)

def run_script(script_name, *args, **kwargs):
    """调用同目录脚本（当前解释器；强制子进程 UTF-8 输出后再按 utf-8 解码）"""
    script = SCRIPT_DIR.parent / script_name
    cmd = [sys.executable, str(script)] + list(args)
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=kwargs.get("timeout", 30),
        env=env,
    )
    if result.returncode != 0 and kwargs.get("check", True):
        err = result.stderr or ""
        print(f"⚠️  {script_name} 失败: {err[:200]}")
    return (result.stdout or "").strip()

def run_bash(script_name, *args, input_str=None):
    """调用同目录 bash 脚本"""
    script = SCRIPT_DIR.parent / script_name
    cmd = ["bash", str(script)] + list(args)
    result = subprocess.run(
        cmd,
        input=input_str or None,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=30,
    )
    return result

from card_record import (
    meaningful_card_name, auto_record_recommendations,
    remember_user_input, parse_patch_user_input, write_record,
)





def cmd_create(args):
    """创建新卡面骨架(解析 scene + subject + profile；旧词库仅作可选参考)"""
    print("🎴 创建卡面...\n")

    from card_core import initialize_new_card
    card, path, is_custom_person, is_custom_scene = initialize_new_card(args)

    # 输出摘要
    print(f"\n{'='*50}")
    print(f"  🎴 {card['card_id']}")
    print(f"  模式: {args.mode}")
    print(f"  场景: {card['scene']['name']}")
    print(f"  人物: {card['subject']['display_name']}")
    if card['subject'].get('lora'):
        print(f"  LoRA: {card['subject']['lora']}")
    if getattr(args, 'bundle', False):
        secs = card.get('_bundle_sections') or {}
        n_libs = len(secs)
        n_secs = sum(len(v) if isinstance(v, list) else 0 for v in secs.values())
        print(f"  词库参考: {n_libs} 库 / {n_secs} 章")
        for lib, names in secs.items():
            if isinstance(names, list) and names:
                print(f"    · {lib}: {', '.join(names[:6])}{'…' if len(names) > 6 else ''}")
        if card.get('_bundle_sidecar'):
            print(f"  词库旁路: {card['_bundle_sidecar']}")
        print("  → fill 模板将自动注入 guidance.library_bundle")
    else:
        print("  词库参考: 关闭")
    if is_custom_scene:
        print(f"\n  💡 [SYSTEM TIPS] 场景「{card['scene']['name']}」为库外自定义，请在 fill 写入英文 scene.keywords，自由大胆发明机位与环境，禁止留空。")
    if is_custom_person:
        print(f"\n  💡 [SYSTEM TIPS] 人物「{args.person}」为库外词，请根据角色特质，尽情发挥，自由大胆无下限。")
        # 多人角色提示：检测是否包含多人关键词
        multi_person_keywords = [
            # 家庭关系（明确包含两人）
            '母女', '父女', '母子', '姐妹', '兄妹', '姐弟',
            # 明确多人组合
            '双胞胎', '姐妹花', '三姐妹', '闺蜜', '合影', '合照',
            # 明确多人行为
            '双飞', '3p', '4p', '群P', '多人', '双人', '三人', '四人', '五人',
            '乱交', '轮奸', '群交', '后宫团',
        ]
        if any(kw in args.person for kw in multi_person_keywords):
            # 根据关键词动态生成格式示例
            # 有男有女的关键词
            mixed_gender_keywords = ['父女', '母子', '兄妹', '姐弟']
            # 三人场景
            three_person_keywords = ['三姐妹', '三人', '3p']
            
            if any(kw in args.person for kw in mixed_gender_keywords):
                # 有男有女场景
                print("  💡 [SYSTEM TIPS] 检测到多人角色（有男有女），请在 body_shape 中为每个人物分别描述体型、年龄、外貌特征（格式如：ONE MAN AND ONE GIRL: (1) 男性描述; (2) 女性描述）。")
            elif any(kw in args.person for kw in three_person_keywords):
                # 三人纯女性场景
                print("  💡 [SYSTEM TIPS] 检测到多人角色，请在 body_shape 中为每个人物分别描述体型、年龄、外貌特征（格式如：THREE GIRLS: (1) 角色A描述; (2) 角色B描述; (3) 角色C描述）。")
            else:
                # 双人纯女性场景
                print("  💡 [SYSTEM TIPS] 检测到多人角色，请在 body_shape 中为每个人物分别描述体型、年龄、外貌特征（格式如：TWO GIRLS: (1) 角色A描述; (2) 角色B描述）。")
    print(f"{'='*50}")

    # 返回 card_id 便于管道
    print(f"\ncard_id={card['card_id']}")
    return card['card_id']

def cmd_fill(args):
    """填充卡面槽位(AI 导演链输出 → card.json)"""

    def _is_blank(value):
        return value is None or str(value).strip() == ""

    def _missing_fields(mapping, fields):
        return [field for field in fields if _is_blank(mapping.get(field, ""))]

    with card_lock(args.card, owner='fill', timeout=20.0):
        card = load_card(args.card)
        card.setdefault("slots", {})
        card.setdefault("director", {})
        card.setdefault("subject", {})
        card.setdefault("history", [])

        payload = {}
        if getattr(args, 'json_file', None):
            try:
                payload = json.loads(Path(args.json_file).read_text(encoding='utf-8'))
            except Exception as e:
                print(f"❌ 读取 fill JSON 文件失败: {e}")
                sys.exit(1)
        elif getattr(args, 'json_text', None):
            try:
                payload = json.loads(args.json_text)
            except Exception as e:
                print(f"❌ 解析 fill JSON 字符串失败: {e}")
                sys.exit(1)

        # 支持批量模板文件:JSON list 中按 card_id / card 匹配当前卡
        if isinstance(payload, list):
            matched = None
            for item in payload:
                if not isinstance(item, dict):
                    continue
                item_card_id = str(item.get('card_id') or item.get('card') or '').strip()
                if item_card_id == str(args.card).strip():
                    matched = item
                    break
            if matched is None:
                print(f"❌ 批量 fill JSON 中未找到 card_id={args.card} 的条目")
                sys.exit(1)
            payload = matched

        if payload and not isinstance(payload, dict):
            print("❌ fill JSON 必须是对象,或按 card_id 匹配的对象数组")
            sys.exit(1)

        # 智能平移与归一化 payload，彻底阻断 AI 因格式漂移和拼写错误引起的填槽失败
        robust_normalize_payload(payload)

        payload_slots = payload.get('slots', {}) if isinstance(payload.get('slots', {}), dict) else {}
        payload_director = payload.get('director', {}) if isinstance(payload.get('director', {}), dict) else {}
        payload_subject = payload.get('subject', {}) if isinstance(payload.get('subject', {}), dict) else {}
        phase = getattr(args, 'phase', None)
        changed_targets = set()
        explicit_targets = set()
        progress = card.get('_fill_progress', {})
        if not isinstance(progress, dict):
            progress = {}
        progress = dict(progress)
        for phase_name in ('director', 'slots', 'elevation'):
            progress[phase_name] = bool(progress.get(phase_name))

        required_director = [
            "intent", "exposure_mode", "style_recipe", "lighting_palette",
            "pose_direction", "makeup_direction", "expression_gaze",
            "focus_detail",
        ]
        VALID_EXPOSURE_MODE = {"upper", "lower", "both", "half_nude", "half_covered", "none"}
        required_slots = []
        optional_slots = ['lighting', 'clothing', 'pose', 'expression_gaze', 'style_quality', 'makeup_hair', 'accessories', 'imperfections', 'tattoo', 'props', 'pet', 'liquids']
        required_elevation_director = ['story_elevation', 'story_elevation_zh', 'lighting_palette_zh', 'style_recipe_zh']

        def _validate_story_elevation_zh(story_zh, errors):
            if not has_cjk(story_zh):
                errors.append("❌ story_elevation_zh 必须为中文（当前非中文）")
            else:
                slen = len(story_zh)
                rules = load_validation_rules()
                min_limit = rules.get("min_story_chars", 80)
                min_tol = rules.get("min_story_tolerance", 70)
                max_limit = rules.get("max_story_chars", 200)
                max_tol = rules.get("max_story_tolerance", 210)
                if slen < min_tol:
                    errors.append(f"❌ story_elevation_zh 过短 (最少{min_limit}字，容错{min_tol}字，当前{slen}字)")
                elif slen > max_tol:
                    errors.append(f"❌ story_elevation_zh 过长 (最多{max_limit}字，容错{max_tol}字，当前{slen}字)")

        def _progress_line():
            return (
                f"📍 当前进度: "
                f"director={'✅' if progress.get('director') else '⬜'} · "
                f"slots={'✅' if progress.get('slots') else '⬜'} · "
                f"elevation={'✅' if progress.get('elevation') else '⬜'}"
            )

        def _next_step_line():
            if not progress.get('director'):
                return "💡 下一步: fill --phase director --card <id> ..."
            if not progress.get('slots'):
                return "💡 下一步: fill --phase slots --card <id> ..."
            if not progress.get('elevation'):
                return "💡 下一步: fill --phase elevation --card <id> ..."
            if card.get('workflow_mode') == 'chain':
                return f"💡 下一步: chain --resume {card.get('card_id', '<id>')}"
            return "💡 下一步: render → present → check → submit"

        if phase == 'slots' and not progress.get('director'):
            print("❌ slots 阶段前置未完成: 必须先执行 fill --phase director --card <id> ...")
            sys.exit(1)
        if phase == 'elevation':
            if not progress.get('director'):
                print("❌ elevation 阶段前置未完成: 必须先完成 director，然后再执行 slots。")
                sys.exit(1)
            if not progress.get('slots'):
                print("❌ elevation 阶段前置未完成: 必须先执行 fill --phase slots --card <id> ...")
                sys.exit(1)

        # 逐槽填充:JSON 先作为基础,显式 CLI 再覆盖
        slot_fields = {}
        slots_changed = False
        for k in SLOT_RENDER_ORDER:
            val = payload_slots.get(k, None)
            cli_val = getattr(args, k, None)
            slot_fields[k] = cli_val if cli_val is not None else val
        for slot, val in slot_fields.items():
            if val is not None and val != "":
                if card["slots"].get(slot) != val:
                    slots_changed = True
                    changed_targets.add(f"slots.{slot}")
                explicit_targets.add(f"slots.{slot}")
                card["slots"][slot] = val
                card["history"].append({
                    "timestamp": datetime.now().isoformat(),
                    "action": "fill_slot",
                    "changes": {slot: str(val)[:80] + ("..." if len(str(val)) > 80 else "")}
                })

        # body_shape：create 身份注入为默认；fill 显式提供则覆盖（不进 SLOT_RENDER_ORDER，避免 render 双重拼装）
        body_shape_val = payload_slots.get("body_shape", None)
        if body_shape_val is not None and str(body_shape_val).strip() != "":
            body_shape_val = str(body_shape_val).strip()
            if card["slots"].get("body_shape") != body_shape_val:
                slots_changed = True
                changed_targets.add("slots.body_shape")
            explicit_targets.add("slots.body_shape")
            card["slots"]["body_shape"] = body_shape_val
            card["history"].append({
                "timestamp": datetime.now().isoformat(),
                "action": "fill_slot",
                "changes": {"body_shape": body_shape_val[:80] + ("..." if len(body_shape_val) > 80 else "")}
            })

        # 场景真相源是 scene.keywords
        # 1) 优先写 payload.scene.keywords / scene_keywords（自定义场景主路径，保名）
        # 2) 兼容废弃 slots.scene_theme / scene_theme
        payload_scene = payload.get('scene') if isinstance(payload.get('scene'), dict) else {}
        explicit_keywords = str(
            (payload_scene or {}).get('keywords')
            or payload.get('scene_keywords')
            or ''
        ).strip()
        legacy_theme = str(payload_slots.get('scene_theme') or payload.get('scene_theme') or '').strip()
        keywords_to_write = explicit_keywords or legacy_theme
        if keywords_to_write:
            preserve = is_manual_custom_scene_card(card) or bool(explicit_keywords)
            if preserve:
                set_scene_keywords_preserve_name(card, keywords_to_write, source='manual-custom-fill' if is_manual_custom_scene_card(card) else 'manual-fill-keywords')
            else:
                sync_scene_metadata_from_slots(card, keywords_to_write)
            changed_targets.add('scene.keywords')
            explicit_targets.add('scene.keywords')
            card["history"].append({
                "timestamp": datetime.now().isoformat(),
                "action": "fill_scene_keywords",
                "changes": {"scene.keywords": keywords_to_write[:80] + ("..." if len(keywords_to_write) > 80 else "")}
            })

        director_fields = [
            "intent", "exposure_mode", "style_recipe", "lighting_palette",
            "pose_direction", "makeup_direction", "expression_gaze",
            "focus_detail",
        ]
        director_changed = False
        for f in director_fields:
            val = getattr(args, f"dir_{f}", None)
            if val is None:
                val = payload_director.get(f, None)
            if val:
                if card["director"].get(f) != val:
                    director_changed = True
                    changed_targets.add(f"director.{f}")
                explicit_targets.add(f"director.{f}")
                card["director"][f] = val
                card["history"].append({
                    "timestamp": datetime.now().isoformat(),
                    "action": "fill_director",
                    "changes": {f"director.{f}": str(val)[:80] + ("..." if len(str(val)) > 80 else "")}
                })

        subject_changed = False
        for subj_key in ["display_name", "trigger", "archetype"]:
            subj_val = payload_subject.get(subj_key, None)
            if subj_val is not None and str(subj_val).strip() != "":
                if card.setdefault("subject", {}).get(subj_key) != subj_val:
                    subject_changed = True
                    changed_targets.add(f"subject.{subj_key}")
                explicit_targets.add(f"subject.{subj_key}")
                card.setdefault("subject", {})[subj_key] = subj_val
                card["history"].append({
                    "timestamp": datetime.now().isoformat(),
                    "action": "fill_subject",
                    "changes": {f"subject.{subj_key}": str(subj_val)[:80] + ("..." if len(str(subj_val)) > 80 else "")}
                })

        elevation_changed = False
        theme_zh_val = payload.get('theme_zh') if isinstance(payload, dict) else None
        if getattr(args, 'theme_zh', None) is not None:
            theme_zh_val = args.theme_zh
        if theme_zh_val:
            if card.get("theme_zh") != theme_zh_val:
                elevation_changed = True
                changed_targets.add("theme_zh")
            explicit_targets.add("theme_zh")
            card["theme_zh"] = theme_zh_val

        story_elevation_val = payload_director.get('story_elevation')
        if getattr(args, 'dir_story_elevation', None) is not None:
            story_elevation_val = args.dir_story_elevation
        if story_elevation_val:
            if card["director"].get("story_elevation") != story_elevation_val:
                elevation_changed = True
                changed_targets.add("director.story_elevation")
            explicit_targets.add("director.story_elevation")
            card["director"]["story_elevation"] = story_elevation_val

        story_elevation_zh_val = payload_director.get('story_elevation_zh')
        if getattr(args, 'story_elevation_zh', None) is not None:
            story_elevation_zh_val = args.story_elevation_zh
        if getattr(args, 'story_elevation_file', None):
            try:
                story_elevation_zh_val = open(args.story_elevation_file, encoding="utf-8").read().strip()
            except Exception as e:
                print(f"❌ 读取 story_elevation 文件失败: {e}")
                sys.exit(1)
        if story_elevation_zh_val:
            if card["director"].get("story_elevation_zh") != story_elevation_zh_val:
                elevation_changed = True
                changed_targets.add("director.story_elevation_zh")
            explicit_targets.add("director.story_elevation_zh")
            card["director"]["story_elevation_zh"] = story_elevation_zh_val

        for zh_field in ["lighting_palette_zh", "style_recipe_zh"]:
            zh_val = payload_director.get(zh_field)
            cli_val = getattr(args, zh_field, None)
            zh_val = cli_val if cli_val is not None else zh_val
            if zh_val:
                if card["director"].get(zh_field) != zh_val:
                    elevation_changed = True
                    changed_targets.add(f"director.{zh_field}")
                explicit_targets.add(f"director.{zh_field}")
                card["director"][zh_field] = zh_val

        # 补充处理其余中文展示字段（pose_direction_zh / makeup_direction_zh / expression_gaze_zh / intent_zh / focus_detail_zh 等）
        _extra_zh_fields = [
            "intent_zh", "pose_direction_zh", "makeup_direction_zh",
            "expression_gaze_zh", "focus_detail_zh",
        ]
        for zh_field in _extra_zh_fields:
            zh_val = payload_director.get(zh_field)
            cli_val = getattr(args, f"dir_{zh_field}", None)
            zh_val = cli_val if cli_val is not None else zh_val
            if zh_val:
                if card["director"].get(zh_field) != zh_val:
                    director_changed = True
                    changed_targets.add(f"director.{zh_field}")
                explicit_targets.add(f"director.{zh_field}")
                card["director"][zh_field] = zh_val

        if phase == 'director':
            missing = _missing_fields(card["director"], required_director)
            if missing:
                print(f"❌ director 阶段必填字段为空: {', '.join(missing)}")
                sys.exit(1)
            # ── exposure_mode 合法性校验 / 视角绑定 / 全局 limit 钳制 ──
            from card_exposure import clamp_exposure_mode, resolve_perspective_exposure, apply_user_explicit_exposure_override
            ef = str(card["director"].get("exposure_mode", "")).strip().lower()
            if ef and ef not in VALID_EXPOSURE_MODE and ef != "auto":
                print(f"❌ exposure_mode 值非法: '{ef}'，可选值: {', '.join(sorted(VALID_EXPOSURE_MODE))}")
                sys.exit(1)
            ef_resolved, exp_meta = resolve_perspective_exposure(
                ef,
                scene=card.get("scene") or {},
                seed=card.get("card_id"),
                force_pick=False,
            )
            if exp_meta.get("source") == "invalid" or (
                ef_resolved and ef_resolved not in VALID_EXPOSURE_MODE
            ):
                print(f"❌ exposure_mode 值非法: '{ef}'，可选值: {', '.join(sorted(VALID_EXPOSURE_MODE))}")
                sys.exit(1)
            if not ef_resolved or ef_resolved == "auto":
                # 无视角绑定时仍要求显式合法值
                if not exp_meta.get("allowed"):
                    print(f"❌ exposure_mode 值非法: '{ef or '空'}'，可选值: {', '.join(sorted(VALID_EXPOSURE_MODE))}")
                    sys.exit(1)
                ef_resolved, exp_meta = resolve_perspective_exposure(
                    ef,
                    scene=card.get("scene") or {},
                    seed=card.get("card_id"),
                    force_pick=True,
                )
            limit_range = exp_meta.get("limit_range")
            ef_clamped = clamp_exposure_mode(
                ef_resolved, limit_range=limit_range,
                allowed_set=exp_meta.get("allowed_set"),
            )
            _user_over = apply_user_explicit_exposure_override(card, ef_clamped)
            if _user_over != ef_clamped:
                print(f"💡 用户指令裸露直通: {ef_clamped} -> {_user_over}")
                ef_clamped = _user_over
            if ef_clamped != ef:
                reasons = []
                if exp_meta.get("allowed") and exp_meta.get("source") in (
                    "perspective_binding", "explicit_clamped_to_binding"
                ):
                    key = exp_meta.get("perspective_key") or "视角"
                    reasons.append(f"视角绑定 {key}: {'/'.join(exp_meta.get('allowed') or [])}")
                if exp_meta.get("bypass"):
                    reasons.append("绑定场景绕过 exposure_limit")
                elif ef_clamped != ef_resolved or (
                    exp_meta.get("source") not in ("perspective_binding", "explicit_clamped_to_binding")
                    and ef_clamped != ef
                ):
                    reasons.append("exposure_limit 配置")
                reason_txt = "；".join(reasons) if reasons else "自动归一化"
                print(f"💡 自动钳制裸露模式: {ef or '空'} -> {ef_clamped} ({reason_txt})")
            card["director"]["exposure_mode"] = ef_clamped
            ef = ef_clamped
            progress['director'] = True
            if director_changed:
                progress['slots'] = False
                progress['elevation'] = False
            status_lines = [
                "✅ director 阶段完成 (7/7 导演字段 + exposure_mode)",
            ]
            status_lines.extend([_progress_line(), _next_step_line()])
        elif phase == 'slots':
            missing = _missing_fields(card["slots"], required_slots)
            if missing:
                print(f"❌ slots 阶段必填槽位为空: {', '.join(missing)}")
                sys.exit(1)
            progress['slots'] = True
            filled = sum(1 for s in SLOT_RENDER_ORDER if str(card["slots"].get(s, '')).strip())
            optional_filled = sum(1 for s in optional_slots if str(card["slots"].get(s, '')).strip())
            if slots_changed:
                progress['elevation'] = False
            status_lines = [
                f"✅ slots 阶段完成 (12 槽位全部选填 · 已填 {filled}/{len(SLOT_RENDER_ORDER)} · 可选 {optional_filled}/{len(optional_slots)})",
            ]
            # ── 统一取 render 同源裸露上下文（exposure_mode + context_text）──
            from card_exposure import get_exposure_context
            _ctx_exposure, _ctx_mode, _ctx_text = get_exposure_context(card, card["director"])
            ef_val = _ctx_mode or str(card["director"].get("exposure_mode", "auto")).strip().lower()
            # ── clothing 预过滤：让 AI 当场看到哪些词会被删/加 ──
            exposure_raw = card["slots"].get("clothing", "").strip()
            if exposure_raw and ef_val != "auto":
                from card_exposure import (
                    filter_clothing_by_focus,
                    lower_clothing_policy_for_card,
                )
                exposure_filtered = filter_clothing_by_focus(
                    exposure_raw,
                    exposure_mode=ef_val,
                    context_text=_ctx_text,
                    lower_policy=lower_clothing_policy_for_card(card),
                )
                if exposure_filtered != exposure_raw:
                    status_lines.append(f"📋 clothing 预过滤({ef_val}):")
                    status_lines.append(f"   原始: {exposure_raw}")
                    status_lines.append(f"   过滤: {exposure_filtered}")
                    status_lines.append(f"   💡 如需保留被移除的词，请将 exposure_mode 改为 both 或 half_nude")
                else:
                    status_lines.append(f"📋 clothing 预过滤({ef_val}): 无变动")
            # ── body_shape 预过滤：clothing 已填后展示真实过滤结果（与 render 一致）──
            body_shape_raw = card["slots"].get("body_shape", "").strip()
            if body_shape_raw:
                from card_exposure import (
                    filter_body_shape_by_exposure,
                    split_prompt_items,
                )
                # 复用上方统一解析的 _ctx_exposure/_ctx_mode/_ctx_text，再补 pose_text，
                # 确保展示与 render 过滤结果一致（auto 解析/后入视角均对齐）。
                filtered_bs = filter_body_shape_by_exposure(
                    body_shape_raw,
                    _ctx_exposure or exposure_raw,
                    exposure_mode=_ctx_mode,
                    context_text=_ctx_text,
                    pose_text=card["slots"].get("pose", "") or "",
                )
                removed = set(split_prompt_items(body_shape_raw)) - set(split_prompt_items(filtered_bs))
                if removed:
                    status_lines.append(f"📋 body_shape 预过滤({ef_val}): 移除 [{', '.join(sorted(removed))}]")
                    status_lines.append(f"   保留: {filtered_bs}")
                    status_lines.append(f"   💡 如需保留被移除的词，请将 exposure_mode 改为 both 或 half_nude")
                else:
                    status_lines.append(f"📋 body_shape 预过滤({ef_val}): 无变动")
            status_lines.extend([_progress_line(), _next_step_line()])
        elif phase == 'elevation':
            missing_zh = _missing_fields(card.get("director", {}), required_elevation_director)
            missing_theme = [] if not _is_blank(card.get('theme_zh', '')) else ['theme_zh']
            all_missing = missing_theme + missing_zh
            if all_missing:
                print(f"❌ elevation 阶段必填字段为空: {', '.join(all_missing)}")
                sys.exit(1)

            # ── 硬性中文校验 ──
            zh_errors = []
            for field in ('theme_zh', 'lighting_palette_zh', 'style_recipe_zh'):
                val = card.get(field, '') if field == 'theme_zh' else card.get("director", {}).get(field, '')
                if not has_cjk(str(val or '')):
                    zh_errors.append(f"❌ {field} 必须为中文（当前非中文）")
            story_zh = str(card.get("director", {}).get('story_elevation_zh', '') or '').strip()
            _validate_story_elevation_zh(story_zh, zh_errors)
            if zh_errors:
                for msg in zh_errors:
                    print(msg)
                sys.exit(1)

            progress['elevation'] = True
            status_lines = [
                "✅ elevation 阶段完成 (theme_zh + 3 个导演中文字段)",
                _progress_line(),
                _next_step_line(),
            ]
        else:
            missing_director = _missing_fields(card["director"], required_director)
            missing_slots = _missing_fields(card["slots"], required_slots)  # 12槽位全部选填，此列表为空
            missing_elevation = []
            if _is_blank(card.get('theme_zh', '')):
                missing_elevation.append('theme_zh')
            missing_elevation.extend(_missing_fields(card.get("director", {}), required_elevation_director))
            if missing_director or missing_slots or missing_elevation:
                print("❌ fill 必填字段为空:")
                if missing_director:
                    print(f"   - director: {', '.join(missing_director)}")
                if missing_slots:
                    print(f"   - slots: {', '.join(missing_slots)}")
                if missing_elevation:
                    print(f"   - elevation: {', '.join(missing_elevation)}")
                sys.exit(1)

            # ── exposure_mode 合法性校验 / 视角绑定 / 全局 limit 钳制 ──
            from card_exposure import clamp_exposure_mode, resolve_perspective_exposure, apply_user_explicit_exposure_override
            ef = str(card["director"].get("exposure_mode", "")).strip().lower()
            if ef and ef not in VALID_EXPOSURE_MODE and ef != "auto":
                print(f"❌ exposure_mode 值非法: '{ef}'，可选值: {', '.join(sorted(VALID_EXPOSURE_MODE))}")
                sys.exit(1)
            ef_resolved, exp_meta = resolve_perspective_exposure(
                ef,
                scene=card.get("scene") or {},
                seed=card.get("card_id"),
                force_pick=False,
            )
            if exp_meta.get("source") == "invalid" or (
                ef_resolved and ef_resolved not in VALID_EXPOSURE_MODE and ef_resolved != "auto"
            ):
                print(f"❌ exposure_mode 值非法: '{ef}'，可选值: {', '.join(sorted(VALID_EXPOSURE_MODE))}")
                sys.exit(1)
            if not ef_resolved or ef_resolved == "auto":
                if not exp_meta.get("allowed"):
                    print(f"❌ exposure_mode 值非法: '{ef or '空'}'，可选值: {', '.join(sorted(VALID_EXPOSURE_MODE))}")
                    sys.exit(1)
                ef_resolved, exp_meta = resolve_perspective_exposure(
                    ef,
                    scene=card.get("scene") or {},
                    seed=card.get("card_id"),
                    force_pick=True,
                )
            limit_range = exp_meta.get("limit_range")
            ef_clamped = clamp_exposure_mode(
                ef_resolved, limit_range=limit_range,
                allowed_set=exp_meta.get("allowed_set"),
            )
            _user_over = apply_user_explicit_exposure_override(card, ef_clamped)
            if _user_over != ef_clamped:
                print(f"💡 用户指令裸露直通: {ef_clamped} -> {_user_over}")
                ef_clamped = _user_over
            if ef_clamped != ef:
                reasons = []
                if exp_meta.get("allowed") and exp_meta.get("source") in (
                    "perspective_binding", "explicit_clamped_to_binding"
                ):
                    key = exp_meta.get("perspective_key") or "视角"
                    reasons.append(f"视角绑定 {key}: {'/'.join(exp_meta.get('allowed') or [])}")
                if exp_meta.get("bypass"):
                    reasons.append("绑定场景绕过 exposure_limit")
                elif ef_clamped != ef_resolved or (
                    exp_meta.get("source") not in ("perspective_binding", "explicit_clamped_to_binding")
                    and ef_clamped != ef
                ):
                    reasons.append("exposure_limit 配置")
                reason_txt = "；".join(reasons) if reasons else "自动归一化"
                print(f"💡 自动钳制裸露模式: {ef or '空'} -> {ef_clamped} ({reason_txt})")
            card["director"]["exposure_mode"] = ef_clamped

            # ── 硬性中文校验（elevation 字段） ──
            zh_errors = []
            for field in ('theme_zh', 'lighting_palette_zh', 'style_recipe_zh'):
                val = card.get(field, '') if field == 'theme_zh' else card.get("director", {}).get(field, '')
                if not has_cjk(str(val or '')):
                    zh_errors.append(f"❌ {field} 必须为中文（当前非中文）")
            story_zh = str(card.get("director", {}).get('story_elevation_zh', '') or '').strip()
            _validate_story_elevation_zh(story_zh, zh_errors)
            if zh_errors:
                for msg in zh_errors:
                    print(msg)
                sys.exit(1)

            progress = {'director': True, 'slots': True, 'elevation': True}
            filled = sum(1 for s in SLOT_RENDER_ORDER if str(card["slots"].get(s, '')).strip())
            status_lines = [
                f"✅ fill 完成 (一次性完成 director + slots + elevation, {filled}/{len(SLOT_RENDER_ORDER)} 槽位)",
                _progress_line(),
                _next_step_line(),
            ]

        card['_fill_progress'] = progress
        card["history"].append({
            "timestamp": datetime.now().isoformat(),
            "action": "fill_phase_commit",
            "phase": phase or "all",
            "changes": {
                "changed_targets": sorted(changed_targets),
                "explicit_targets": sorted(explicit_targets),
                "progress": {k: bool(progress.get(k)) for k in ('director', 'slots', 'elevation')},
                "subject_changed": subject_changed,
                "elevation_changed": elevation_changed,
            }
        })

        latest_card = load_card(args.card)
        latest_card.setdefault('slots', {}).update(card.get('slots', {}))
        latest_card.setdefault('director', {}).update(card.get('director', {}))
        if card.get('theme_zh'):
            latest_card['theme_zh'] = card['theme_zh']
        latest_card.setdefault('subject', {}).update(card.get('subject', {}))
        # scene.keywords 等在内存 card 上已写入；必须整块带回，否则 custom/fill keywords 会丢
        if card.get('scene') is not None:
            latest_card['scene'] = card['scene']
        # 合并 direction_descriptions 和 direction_patch_values（逐 key 深度合并，避免覆盖已有内容）
        if isinstance(payload, dict):
            if 'direction_descriptions' in payload and isinstance(payload['direction_descriptions'], dict):
                latest_card.setdefault('direction_descriptions', {}).update(payload['direction_descriptions'])
            if 'direction_patch_values' in payload and isinstance(payload['direction_patch_values'], dict):
                latest_card.setdefault('direction_patch_values', {}).update(payload['direction_patch_values'])
        latest_card['_fill_progress'] = card.get('_fill_progress', {})
        latest_card.setdefault('history', []).extend(card.get('history', [])[len(latest_card.get('history', [])):])
        invalidate_render_cache(latest_card, reason='fill-updated-card-source')
        latest_card["status"] = "filled" if all(bool(latest_card.get('_fill_progress', {}).get(k)) for k in ('director', 'slots', 'elevation')) else "draft"

        # ── 自动进行前置物理与格式自愈纠偏（仅内存；预检通过后再一次落盘）──
        latest_card, changed = auto_fix_card(latest_card, persist=False)

        # ── Fill Preflight 预检纯文本拦截门禁 ──
        from card_validation import run_preflight_check
        preflight_errors, preflight_details = run_preflight_check(latest_card)
        if preflight_errors:
            print("\n❌ fill 预检未通过，已拒绝保存卡片变更：")
            for err in preflight_errors:
                print(f"   - {err}")
            print("\n💡 请根据上述提示修复 JSON 或参数后重新 fill。")
            sys.exit(1)

        save_card(latest_card)

        for line in status_lines:
            print(line)

def _is_exposure_direction(info):
    info = info or {}
    name = str(info.get("name") or "").strip().lower()
    return (
        str(info.get("kind") or "").strip().lower() == "exposure"
        or "裸露" in name
        or name in {"exposure", "nudity"}
    )


def _normalize_direction_info(info):
    if not isinstance(info, dict):
        return info
    normalized = dict(info)
    normalized["targets"] = list(info.get("targets") or [])
    if _is_exposure_direction(normalized):
        normalized["kind"] = "exposure"
        optional_targets = [
            target
            for target in normalized["targets"]
            if target not in {"slots.clothing", "director.exposure_mode"}
        ]
        normalized["targets"] = [
            "slots.clothing",
            *optional_targets,
            "director.exposure_mode",
        ]
    return normalized


def _resolve_numeric_exposure_patch_mode(card, target_values, direction_hint):
    """Resolve the exposure mode selected by a numeric nudity option."""
    from card_exposure import (
        VALID_EXPOSURE_MODE,
        _has_lower_exposure_signal,
        _has_upper_exposure_signal,
        apply_exposure_directive,
        infer_exposure_mode,
        parse_user_exposure_directive,
    )

    explicit = str((target_values or {}).get("director.exposure_mode") or "").strip().lower()
    if explicit:
        if explicit not in VALID_EXPOSURE_MODE:
            raise ValueError(f"裸露选项给出了无效 exposure_mode: {explicit}")
        return explicit

    clothing = str((card.get("slots") or {}).get("clothing") or "").strip()
    has_upper = _has_upper_exposure_signal(clothing)
    has_lower = _has_lower_exposure_signal(clothing)
    if has_upper or has_lower:
        resolved = str(
            infer_exposure_mode(clothing, context_text="")
        ).strip().lower()
        if resolved in VALID_EXPOSURE_MODE:
            return resolved

    current = str((card.get("director") or {}).get("exposure_mode") or "auto").strip().lower()
    directive = parse_user_exposure_directive(direction_hint)
    if directive.get("kind") != "no_directive":
        resolved = str(apply_exposure_directive(current, directive) or "").strip().lower()
        if resolved in VALID_EXPOSURE_MODE:
            return resolved

    lowered = f"{clothing} {direction_hint}".lower()
    for token, mode in (
        ("half_nude", "half_nude"),
        ("half nude", "half_nude"),
        ("半裸", "half_nude"),
        ("half_covered", "half_covered"),
        ("half covered", "half_covered"),
        ("擦边", "half_covered"),
        ("fully clothed", "none"),
        ("全遮", "none"),
    ):
        if token in lowered:
            return mode
    return None


def cmd_patch(args):
    """局部修改卡面(方向patch / 字段patch)"""
    user_input = getattr(args, 'user_input', None)
    direction = getattr(args, 'direction', None)
    is_special_direction = direction in {"0", "1", "6"}
    if (
        not user_input
        and not is_special_direction
        and not getattr(args, '_patch_lock_held', False)
    ):
        with card_lock(args.card, owner=f"patch-{direction or 'field'}", timeout=20.0):
            locked_args = copy.copy(args)
            locked_args._patch_lock_held = True
            return cmd_patch(locked_args)

    card = load_card(args.card)

    if user_input:
        from card_exposure import persist_exposure_directive

        parsed = parse_patch_user_input(user_input)
        with card_lock(args.card, owner="patch-user-input", timeout=20.0):
            card = load_card(args.card)
            remember_user_input(card, parsed['raw'])
            exposure_mode = persist_exposure_directive(card, parsed['raw'])
            if exposure_mode:
                invalidate_render_cache(card, reason='patch-user-exposure-directive')
                card.setdefault('history', []).append({
                    'timestamp': datetime.now().isoformat(),
                    'action': 'patch_exposure_directive',
                    'changes': {
                        'input': parsed['raw'],
                        'exposure_mode': exposure_mode,
                        'directive': dict((card.get('creative') or {}).get('exposure_directive') or {}),
                    },
                })
            save_card(card)

        if parsed['text_intent']:
            print(f"📝 已记录文字意图: {parsed['text_intent']}")
            print("   文字意图交给上层 AI 自由发挥;引擎层这里只顺序执行数字方向。")

        if not parsed['directions']:
            print("i️ 当前输入不含数字方向;已仅记录原始输入。")
            return

        for direction in parsed['directions']:
            print(f"➡️ 执行方向 {direction}")
            # 若 direction_patch_values 存在，优先使用 AI 编写的具体值
            card = load_card(args.card)
            pv = (card.get('direction_patch_values') or {}).get(direction, '')
            if pv:
                # 从 option_map 找该方向的 primary target
                om = card.get('option_map', {}) or {}
                fixed_map = load_direction_map()["directions"]
                entry = _normalize_direction_info(
                    om.get(direction) or fixed_map.get(direction)
                )
                if entry and entry.get('targets'):
                    primary = entry['targets'][0]
                    tf = fstr(TMP_DIR) + "/patch_{card['card_id']}_{direction}.json"
                    with open(tf, 'w') as f:
                        if isinstance(pv, dict):
                            json.dump(pv, f)
                        else:
                            json.dump({primary: pv}, f)
                    cmd_patch(argparse.Namespace(
                        card=args.card,
                        direction=direction,
                        set=None,
                        value=None,
                        intent=None,
                        targets_file=tf,
                        targets_json=None,
                        user_input=None,
                    ))
                else:
                    cmd_patch(argparse.Namespace(
                        card=args.card,
                        direction=direction,
                        set=None,
                        value=None,
                        intent=None,
                        targets_json=None,
                        targets_file=None,
                        user_input=None,
                    ))
            else:
                cmd_patch(argparse.Namespace(
                    card=args.card,
                    direction=direction,
                    set=None,
                    value=None,
                    intent=None,
                    targets_json=None,
                    targets_file=None,
                    user_input=None,
                ))

        # R5 交互修改后自动重展示完整上半段(骚话→6维摘要→prompt)
        # 重新生成 render 缓存以保证 present 可直接读取最新 prompt。
        with card_lock(args.card, owner="patch-user-render", timeout=20.0):
            card = load_card(args.card)
            cmd_render_silent(card)
            save_card(card)

        # 判断用户指令中是否包含出图指示（"1" 或 "画"）
        has_draw = False
        if "1" in parsed['directions']:
            has_draw = True
        elif any(k in user_input for k in ["画", "出图", "submit"]):
            has_draw = True

        print()
        if has_draw:
            print("━━━ 修改并提交，当前卡片 ━━━")
            cmd_present(argparse.Namespace(
                card=args.card,
                json=False,
                compact=True,
                reply_id=None,
            ))
        else:
            print("━━━ 已更新，当前卡片 ━━━")
            cmd_present(argparse.Namespace(
                card=args.card,
                json=False,
                compact=True,
                reply_id=None,
            ))
        return

    if getattr(args, 'direction', None):
        fixed_map = load_direction_map()["directions"]
        dynamic_map = card.get("option_map", {}) or {}

        # 0/1/6/9 固定;2~8 从当前卡 option_map 里读
        if args.direction in fixed_map:
            info = fixed_map[args.direction]
        elif args.direction in dynamic_map:
            info = dynamic_map[args.direction]
        else:
            print(f"❌ 当前卡没有方向 {args.direction} 的映射。固定仅 0/1/6/9,2~8 必须先写入 option_map。")
            sys.exit(1)

        info = _normalize_direction_info(info)
        targets = info.get("targets", [])

        if args.direction == "0":
            print("🎲 方向 0 = 重新生成新卡")
            cmd_create(argparse.Namespace(
                mode=card.get("mode", "amateur"),
                scene=None,
                person=None,
                workflow=card.get("render", {}).get("workflow_config"),
                aspect=None,
                size=None,
                seed=None,
            ))
            return

        if args.direction == "1":
            print("✨ 方向 1 = render → check → submit")
            cmd_render(argparse.Namespace(card=args.card))
            cmd_check(argparse.Namespace(card=args.card))
            refreshed = load_card(args.card)
            if refreshed.get("status") != "validated":
                print("⚠️  校验未通过,停止提交")
                return
            cmd_submit(argparse.Namespace(card=args.card, confirm=True))
            return

        if args.direction == "6":
            print("🔍 方向 6 = 合理性检查,直接进入 check")
            cmd_check(argparse.Namespace(card=args.card))
            return

        if not targets:
            print(f"⏭️  方向 {args.direction} ({info.get('name','?')}) 无修改目标")
            return

        # 支持按 target 分别赋值:--targets-json / --targets-file
        target_values = {}
        if args.targets_file:
            target_values = json.loads(Path(args.targets_file).read_text(encoding='utf-8'))
        elif args.targets_json:
            target_values = json.loads(args.targets_json)

        fallback_val = args.value or args.intent or ""
        changed = []
        changes_detail = {}  # 用于 diff 输出
        # 从 direction_descriptions 取出该方向的展示描述，作为改法意图注入
        d_hint = (card.get('direction_descriptions') or {}).get(args.direction, '')

        for target in targets:
            if target in target_values:
                val = target_values[target]
            elif fallback_val:
                val = fallback_val
            else:
                current_val = get_nested(card, target, "")
                val = auto_direction_patch_value(
                    args.direction, target, current_val,
                    info=info, direction_hint=d_hint,
                )
                if str(val or '').strip() == str(current_val or '').strip():
                    continue
            old_val = get_nested(card, target, "")
            set_nested(card, target, val)
            changed.append(target)
            changes_detail[target] = {"from": str(old_val)[:50], "to": str(val)[:50]}
            card["history"].append({
                "timestamp": datetime.now().isoformat(),
                "action": f"patch_direction_{args.direction}",
                "changes": {target: str(val)[:80] + ("..." if len(str(val)) > 80 else "")}
            })

        is_exposure_direction = _is_exposure_direction(info)
        if is_exposure_direction:
            from card_exposure import persist_explicit_exposure_mode

            try:
                selected_mode = _resolve_numeric_exposure_patch_mode(
                    card,
                    target_values,
                    d_hint,
                )
            except ValueError as exc:
                print(f"❌ {exc}")
                sys.exit(1)
            if not selected_mode:
                print(
                    "❌ 裸露数字选项无法确定 exposure_mode；"
                    "请在 --targets-json 中显式提供 director.exposure_mode"
                )
                sys.exit(1)

            previous_mode = str(
                (
                    changes_detail.get("director.exposure_mode", {}).get("from")
                    or (card.get("director") or {}).get("exposure_mode")
                    or "auto"
                )
            ).strip().lower()
            persist_explicit_exposure_mode(card, selected_mode)
            if previous_mode != selected_mode:
                if "director.exposure_mode" not in changed:
                    changed.append("director.exposure_mode")
                changes_detail.setdefault(
                    "director.exposure_mode",
                    {"from": previous_mode, "to": selected_mode},
                )
            card.setdefault("history", []).append({
                "timestamp": datetime.now().isoformat(),
                "action": "patch_numeric_exposure_mode",
                "changes": {
                    "direction": args.direction,
                    "previous_mode": previous_mode,
                    "exposure_mode": selected_mode,
                    "directive": dict(
                        (card.get("creative") or {}).get("exposure_directive") or {}
                    ),
                },
            })

        refresh_display_fields(card, changed_targets=changed, explicit_targets=set(changed))

        if not changed:
            print(f"⚠️  方向 {args.direction} 没有实际更新任何 target")
            return

        # 输出 diff 摘要
        print(f"✅ 方向 {args.direction} ({info.get('name','?')}) → {', '.join(changed)}")
        if changes_detail:
            print("  📋 修改摘要:")
            for tgt, diff_data in changes_detail.items():
                print(f"    {tgt}: {diff_data['from']} → {diff_data['to']}")
        invalidate_render_cache(card, reason=f'patch-direction-{args.direction}')
        if is_exposure_direction:
            from card_validation import run_preflight_check
            from card_exposure import (
                lower_clothing_policy_for_card,
                validate_exposure_consistency,
            )

            _, preflight_details = run_preflight_check(card)
            exposure_errors = [
                str(detail.get("message") or "")
                for detail in preflight_details
                if str(detail.get("code") or "").startswith(
                    ("CHECK_PROMPT_EXPOSURE", "CHECK_CLOTHING")
                )
            ]
            consistency = validate_exposure_consistency(
                exposure_text=str((card.get("slots") or {}).get("clothing") or ""),
                body_shape=str((card.get("slots") or {}).get("body_shape") or ""),
                pose_text=str((card.get("slots") or {}).get("pose") or ""),
                exposure_mode=selected_mode,
                context_text=str(
                    (card.get("director") or {}).get("pose_direction") or ""
                ),
                lower_policy=lower_clothing_policy_for_card(card),
            )
            if consistency.get("missing_signals"):
                exposure_errors.append(
                    "裸露选项缺少模式所需信号: "
                    + ", ".join(consistency["missing_signals"])
                )
            if consistency.get("conflicts"):
                exposure_errors.append(
                    "裸露选项存在方向冲突: "
                    + ", ".join(consistency["conflicts"])
                )
            if exposure_errors:
                print("❌ 裸露 patch 预检未通过，未保存本次修改：")
                for error in exposure_errors:
                    print(f"   - {error}")
                sys.exit(1)

    elif args.set:
        old_val = get_nested(card, args.set, "")
        val = args.value or ""
        set_nested(card, args.set, val)
        card["history"].append({
            "timestamp": datetime.now().isoformat(),
            "action": "patch_field",
            "changes": {args.set: val[:80] + ("..." if len(val) > 80 else "")}
        })
        refresh_display_fields(card, changed_targets={args.set}, explicit_targets={args.set})
        invalidate_render_cache(card, reason=f'patch-set-{args.set}')
        print(f"✅ {args.set}")
        print(f"  📋 {str(old_val)[:50]} → {str(val)[:50]}")

    else:
        print("❌ 需要 --direction 或 --set 参数")
        return

    save_card(card)

def cmd_mend(args):
    """连抽模式手动修复：单卡单字段，修改即验证，可撤销。"""
    card_id = args.card
    field = getattr(args, 'field', None)
    value = getattr(args, 'value', None)
    get_field = getattr(args, 'get_field', None) or getattr(args, 'get', None)
    undo = getattr(args, 'undo', False)
    history = getattr(args, 'history', False)
    dry_run = getattr(args, 'dry_run', False)
    with card_lock(card_id, owner='mend', timeout=20.0):
        card = load_card(card_id, default=None)
        if not card:
            print(f"❌ 卡片不存在: {card_id}")
            return {'ok': False, 'reason': 'not_found'}

        # ── 查看当前值 ──
        if get_field:
            val = get_nested(card, get_field, "")
            print(f"📋 {get_field} = {val}")
            return {'ok': True, 'action': 'get', 'field': get_field, 'value': val}

        # ── 查看历史 ──
        if history:
            mend_history = [h for h in (card.get('history') or []) if h.get('action', '').startswith('mend')]
            if not mend_history:
                print("📝 暂无 mend 修改记录")
            else:
                print(f"📝 修改历史 (最近 {min(len(mend_history), 10)} 次):")
                for h in mend_history[-10:]:
                    ts = h.get('timestamp', '')[:16]
                    changes = h.get('changes', {})
                    for k, v in changes.items():
                        print(f"  [{ts}] {k}: → {v[:120]}")
            return {'ok': True, 'action': 'history'}

        # ── 撤销上一步 ──
        if undo:
            undo_data = card.get('_mend_undo')
            if not undo_data:
                print("❌ 没有可撤销的操作")
                return {'ok': False, 'reason': 'no_undo'}
            undo_field = undo_data.get('field', '')
            undo_value = undo_data.get('value', '')
            old_val = get_nested(card, undo_field, "")
            set_nested(card, undo_field, undo_value)
            card.setdefault('history', []).append({
                'timestamp': datetime.now().isoformat(),
                'action': 'mend_undo',
                'changes': {undo_field: str(undo_value)[:80]}
            })
            card.pop('_mend_undo', None)
            invalidate_render_cache(card, reason=f'mend-undo-{undo_field}')
            refresh_display_fields(card, changed_targets={undo_field}, explicit_targets={undo_field})
            save_card(card)
            print(f"↩️ 已撤销:")
            print(f"  {undo_field}:")
            print(f"    当前值: {str(old_val)[:120]}")
            print(f"    回退到: {str(undo_value)[:120]}")
            # 自动 recheck
            cmd_check(argparse.Namespace(card=card_id, chain_mode=True))
            refreshed = load_card(card_id)
            status = refreshed.get('status', '')
            if status == 'validated':
                print("✅ 校验通过!")
            else:
                print(f"⚠️ 校验状态: {status}")
            return {'ok': True, 'action': 'undo', 'field': undo_field, 'status': status}

        # ── 修改字段 ──
        if not field:
            print("❌ 需要 --field 或 --get 或 --undo 或 --history 参数")
            return {'ok': False, 'reason': 'missing_args'}

        if value is None:
            print(f"❌ 需要 --value 参数")
            return {'ok': False, 'reason': 'missing_value'}

        old_val = get_nested(card, field, "")

        # --dry-run: 只预览不写入
        if dry_run:
            print(f"📋 修改预览:")
            print(f"  {field}:")
            print(f"    旧值: {str(old_val)[:80]}")
            print(f"    新值: {str(value)[:80]}")
            print(f"⚠️  --dry-run 模式，未写入")
            return {'ok': True, 'action': 'dry_run'}

        # 保存 undo 快照
        card['_mend_undo'] = {
            'field': field,
            'value': old_val,
            'timestamp': datetime.now().isoformat(),
        }

        # 写入新值
        set_nested(card, field, value)
        card.setdefault('history', []).append({
            'timestamp': datetime.now().isoformat(),
            'action': 'mend',
            'changes': {field: str(value)[:80] + ('...' if len(str(value)) > 80 else '')}
        })
        invalidate_render_cache(card, reason=f'mend-{field}')
        refresh_display_fields(card, changed_targets={field}, explicit_targets={field})
        save_card(card)

        print(f"✅ 已修改 {field}")
        print(f"  📋 {str(old_val)[:120]} → {str(value)[:120]}")

        # 自动 recheck
        print("🔄 rechecking...")
        cmd_check(argparse.Namespace(card=card_id, chain_mode=True))
        refreshed = load_card(card_id)
        status = refreshed.get('status', '')
        if status == 'validated':
            print("✅ 校验通过! 可以 chain --resume 提交了")
        else:
            validation = refreshed.get('_validation', {}) or {}
            details = validation.get('error_details') or []
            if details:
                for item in details[:3]:
                    print(f"  ❌ [{item.get('code','CHECK_PROMPT_GENERIC')}] {item.get('message','')}")
            else:
                for err in (validation.get('errors') or [])[:3]:
                    pretty = summarize_check_output(err, max_lines=4) or strip_ansi(str(err))
                    print(f"  ❌ {pretty}")

        return {'ok': True, 'action': 'mend', 'field': field, 'status': status}


def cmd_options(args):
    """写入当前卡动态 option_map(仅允许 2/3/4/5/7/8)

    --auto: 从 18 方向池随机抽 6 个,自动生成 option_map
    --json / --file: 手动指定
    """
    card = load_card(args.card)

    # --- --auto 模式:从 18 方向池随机抽 6 个 ---
    if getattr(args, 'auto', False):
        import random
        picked = random.sample(DIRECTION_POOL, 6)
        random.shuffle(picked)  # 打乱后按顺序分配到 2/3/4/5/7/8
        ports = ["2", "3", "4", "5", "7", "8"]
        normalized = {}
        print("🎲 随机抽选 6 个方向:")
        for i, port in enumerate(ports):
            d = _normalize_direction_info(picked[i])
            normalized[port] = {
                "name": d["name"],
                "emoji": d["emoji"],
                "targets": d["targets"],
            }
            if d.get("kind"):
                normalized[port]["kind"] = d["kind"]
            print(f"  {port}. {d['emoji']} {d['name']}")
        latest_card = load_card(args.card)
        latest_card["option_map"] = normalized
        # 清除已存在的废旧方向描述与 patch 值以防止错位
        dd = latest_card.get("direction_descriptions") or {}
        dpv = latest_card.get("direction_patch_values") or {}
        for d in ["2", "3", "4", "5", "7", "8", "9"]:
            dd.pop(d, None)
            dpv.pop(d, None)
        latest_card["direction_descriptions"] = dd
        latest_card["direction_patch_values"] = dpv
        latest_card.pop("_present_cache", None)

        latest_card["history"].append({
            "timestamp": datetime.now().isoformat(),
            "action": "set_option_map",
            "changes": {"option_map_keys": sorted(list(normalized.keys())), "auto": True}
        })
        # option_map 只影响交互菜单，不改变最终 prompt；保留缓存、验证和卡片状态。
        save_card(latest_card)
        print(f"✅ 已写入 option_map: {sorted(list(normalized.keys()))}(固定保留 0/1/6/9)")
        print("💡 如果某个方向不合适,用 options --json 覆盖")
        return

    # --- --json / --file 模式 ---
    if args.file:
        data = json.loads(Path(args.file).read_text(encoding="utf-8"))
    elif args.json:
        data = json.loads(args.json)
    else:
        print("❌ 需要 --auto、--file 或 --json")
        sys.exit(1)

    allowed_dynamic = {"2", "3", "4", "5", "7", "8"}
    reserved_fixed = {"0", "1", "6", "9"}
    keys = set(str(k) for k in data.keys())

    bad_reserved = sorted(keys & reserved_fixed)
    bad_unknown = sorted(keys - allowed_dynamic - reserved_fixed)

    if bad_reserved:
        print(f"❌ option_map 不能写固定数字位: {', '.join(bad_reserved)}(固定保留给 0/1/6/9)")
        sys.exit(1)
    if bad_unknown:
        print(f"❌ option_map 只允许动态数字位 2/3/4/5/7/8,非法键: {', '.join(bad_unknown)}")
        sys.exit(1)

    normalized = {
        str(k): _normalize_direction_info(v)
        for k, v in data.items()
    }
    latest_card = load_card(args.card)
    latest_card["option_map"] = normalized
    # 清除已存在的废旧方向描述与 patch 值以防止错位
    dd = latest_card.get("direction_descriptions") or {}
    dpv = latest_card.get("direction_patch_values") or {}
    for d in ["2", "3", "4", "5", "7", "8", "9"]:
        dd.pop(d, None)
        dpv.pop(d, None)
    latest_card["direction_descriptions"] = dd
    latest_card["direction_patch_values"] = dpv
    latest_card.pop("_present_cache", None)

    latest_card["history"].append({
        "timestamp": datetime.now().isoformat(),
        "action": "set_option_map",
        "changes": {"option_map_keys": sorted(list(normalized.keys()))}
    })
    # option_map 只影响交互菜单，不改变最终 prompt；保留缓存、验证和卡片状态。
    save_card(latest_card)
    print(f"✅ 已写入 option_map: {sorted(list(normalized.keys()))}(固定保留 0/1/6/9)")

def cmd_render(args):
    """渲染 card.json → prompt / caption / meta"""
    from card_rendering import cmd_render as _cmd_render
    return _cmd_render(args)

def cmd_check(args):
    """卡面 check。tattoo 非必填；若填写 tattoo，则按纹身质量规则校验。"""
    from card_validation import check_card, run_preflight_check
    card = load_card(args.card)
    
    # 自动对低风险/高频规则（含纹身融合词、手势体液等）执行静默纠偏并就地存盘，确保单抽与连抽体验完全对齐。
    card, changed_flag = auto_fix_card(card)
    changed = bool(changed_flag)
    
    if changed:
        save_card(card)

    return check_card(
        card,
        chain_mode=getattr(args, 'chain_mode', False),
        render_silent=cmd_render_silent,
        run_bash=run_bash,
        slot_clean_except_tattoo=SLOT_CLEAN_EXCEPT_TATTOO,
    )

def cmd_render_silent(card):
    """内部渲染(不输出,不修改状态)"""
    from card_rendering import cmd_render_silent as _cmd_render_silent
    return _cmd_render_silent(card)

def _submit_card_unlocked(args):
    """提交核心逻辑；调用方自行决定是否已持有卡锁。"""
    card = load_card(args.card)
    remember_user_input(card, getattr(args, 'user_input', None))

    prev_status = card.get('status')
    trusted_requeue = bool(getattr(args, "trusted_requeue", False)) and prev_status in {
        "validated",
        "rendered",
        "delivered",
        "success",
    }
    if (
        getattr(args, "capture_restore", False)
        and not isinstance(card.get("_status_restore"), dict)
    ):
        card["_status_restore"] = {
            "schema_version": 1,
            "source": str(
                getattr(args, "restore_source", None) or "webui_checked_render"
            ),
            "status": str(prev_status or "validated"),
            "render_image": str(card.get("render_image") or ""),
            "captured_at": datetime.now().isoformat(),
        }
    if not trusted_requeue:
        cmd_render_silent(card)
        if prev_status == 'validated' and card.get('status') == 'rendered':
            card['status'] = 'validated'
    validation = card.get('_validation', {}) or {}
    validation_errors = validation.get('errors') or []
    trusted_featured = card.get('workflow_mode') == 'featured'

    if validation_errors:
        print("❌ check 未通过,禁止提交")
        details = validation.get('error_details') or []
        if details:
            for item in details[:3]:
                print(f"   - [{item.get('code','CHECK_PROMPT_GENERIC')}] {item.get('message','')[:200]}")
        else:
            for err in validation_errors[:3]:
                print(f"   - {str(err)[:200]}")
        print("   先修复问题后,再执行: python3 card_cli.py check --card <card_id>")
        sys.exit(1)

    if card.get('status') != 'validated' and not trusted_requeue:
        print("❌ 当前卡面未处于 validated 状态,禁止提交")
        print("   请先执行并通过: python3 card_cli.py check --card <card_id>")
        sys.exit(1)

    if not trusted_featured:
        binding_mismatches = validation_binding_mismatches(
            card,
            workflow_override=getattr(args, "workflow", None),
        )
        version_only_drift = (
            trusted_requeue
            and set(binding_mismatches) == {"card_version"}
        )
        if binding_mismatches and not version_only_drift:
            labels = {
                "prompt_hash": "最终 Prompt",
                "card_version": "卡片版本",
                "workflow": "工作流",
            }
            changed = "、".join(labels.get(item, item) for item in binding_mismatches)
            print(f"❌ 校验凭证已失效（不一致: {changed}）,禁止提交")
            print("   请重新执行: python3 card_cli.py check --card <card_id>")
            sys.exit(1)

    render = card.get("_render_output", {})
    prompt = render.get("prompt", "")
    director = card.get("director", {})
    subject = card.get("subject", {})
    scene_obj = card.get("scene", {})

    person = render.get("meta_person") or subject.get("display_name") or subject.get("archetype") or "亚洲女孩"
    scene = render.get("meta_scene") or scene_obj.get("name") or "未命名场景"
    theme = render.get("meta_theme") or card.get("theme_zh") or director.get("intent") or "神秘主题"
    focus_detail = render.get("meta_narrative") or director.get("story_elevation_zh") or render.get("meta_focus_detail") or " "
    lighting = render.get("meta_lighting_display") or render.get("meta_lighting") or director.get("lighting_palette") or card.get("slots", {}).get("lighting") or " "
    style = render.get("meta_style_display") or render.get("meta_style") or director.get("style_recipe") or card.get("slots", {}).get("style_quality") or " "

    if not prompt:
        print("❌ 无 prompt 可提交")
        sys.exit(1)

    render_cfg = card.setdefault("render", {})
    submit_workflow = getattr(args, "workflow", None) or render_cfg.get("workflow_config")
    submit_seed = (
        getattr(args, "seed", None)
        if getattr(args, "seed", None) is not None
        else render_cfg.get("seed")
    )
    submit_args = [
        str(SCRIPT_DIR.parent / "gpu-pipeline" / "cu-submit.sh"),
        "--prompt", prompt,
        "--person", person,
        "--scene", scene,
        "--theme", theme,
        "--narrative", focus_detail,
        "--lighting", lighting,
        "--style", style,
        "--card", str(card['card_id']),
    ]
    if submit_workflow:
        submit_args += ["--workflow", str(submit_workflow)]
    if submit_seed is not None:
        submit_args += ["--seed", str(submit_seed)]
    submit_idempotency_key = str(
        getattr(args, "idempotency_key", None) or ""
    ).strip()
    if submit_idempotency_key:
        submit_args += ["--idempotency-key", submit_idempotency_key]
    if render_cfg.get("width") and render_cfg.get("height"):
        submit_args += ["--width", str(render_cfg["width"]), "--height", str(render_cfg["height"])]
    reply_id = card.get("delivery", {}).get("reply_id")
    if card["subject"].get("lora"):
        submit_args += ["--lora", card["subject"]["lora"]]
    if reply_id not in (None, "", "null"):
        submit_args += ["--reply-id", str(reply_id)]
    user_input = (card.get('creative', {}) or {}).get('last_user_input')
    if user_input:
        submit_args += ["--user-input", str(user_input)]

    if getattr(args, "dry_run", False):
        import shlex
        print("✨ [DRY-RUN] Submit simulation successful.")
        print(f"  Command: bash {shlex.join(submit_args)}")
        return

    print(f"🚀 提交 {card['card_id']} ...")
    result = subprocess.run(["bash"] + submit_args, capture_output=True, text=True, timeout=30)
    print(result.stdout)
    ack = {}
    for line in reversed((result.stdout or "").splitlines()):
        try:
            candidate = json.loads(line)
        except (TypeError, ValueError, json.JSONDecodeError):
            continue
        if isinstance(candidate, dict):
            ack = candidate
            break

    accepted = bool(ack.get("accepted") and ack.get("job_id"))
    queue_status = str(ack.get("status") or "")
    queue_state = str(ack.get("state") or "")
    if accepted:
        state_map = {
            "pending": "queued",
            "retry_wait": "queued",
            "leased": "submitted",
            "running": "submitted",
            "completed": "rendered",
            "failed": "failed",
            "paused": "queued",
        }
        if queue_status == "started":
            card["status"] = "submitted"
        elif queue_status == "queued":
            card["status"] = "queued"
        elif queue_status == "duplicate":
            card["status"] = state_map.get(queue_state, "queued")
        elif queue_status == "spawn_failed":
            card["status"] = state_map.get(queue_state, "queued")
            card["render_error"] = (ack.get("resume") or {}).get("error") or "worker spawn failed"
        else:
            card["status"] = state_map.get(queue_state, "queued")
        render_cfg["queue_job_id"] = ack.get("job_id")
        render_cfg["queue_state"] = queue_state or queue_status
        render_cfg["queue_idempotency_key"] = ack.get("idempotency_key")
        render_cfg["queue_workflow"] = ack.get("workflow")
        render_cfg["queue_seed"] = ack.get("seed")
        restore_snapshot = card.get("_status_restore")
        if isinstance(restore_snapshot, dict):
            restore_snapshot["job_id"] = str(ack.get("job_id") or "")
            restore_snapshot["bound_at"] = datetime.now().isoformat()
        if ack.get("ok") and queue_status != "spawn_failed":
            card.pop("render_error", None)
    else:
        if result.stderr:
            print(result.stderr[:500])
        card["status"] = "failed"
        card["render_error"] = (
            ack.get("error")
            or (ack.get("resume") or {}).get("error")
            or result.stderr[:500]
            or "queue submit returned no structured acceptance ACK"
        )
    save_card(card)
    if card.get("status") in {"submitted", "queued"}:
        write_record(card, user_input=(card.get('creative', {}) or {}).get('last_user_input') or "", source="auto-submit")
    if not accepted:
        sys.exit(result.returncode or 1)
    return ack


def cmd_submit(args):
    """提交卡面到 GPU 队列"""
    if not getattr(args, 'confirm', False):
        print("❌ submit 需要 --confirm 参数确认")
        print("   用法: python3 card_cli.py submit --card <id> --confirm")
        print("   AI 必须先展示给用户,等用户说「画」后再加 --confirm 提交")
        sys.exit(1)

    with card_lock(args.card, owner='submit', timeout=20.0):
        return _submit_card_unlocked(args)




# ─── 从 card_present 导入（展示模板生成器）──────────────────
from card_present import _generate_direction_descriptions, cmd_present




def _extract_scene_series_key(label):
    """从场景中文名提取系列标记（通用，适用于所有场景库）。

    规则：扫描到第一个位置字符（包含），作为系列标记；
    若位置字符在第1位导致系列标记仅1字 → 跳过继续向下找；
    找不到位置字符 + 场景名≤3字 → 返回 None（不参与系列去重）；
    否则回退取前2字。
    """
    LOCATION_CHARS = set('门室棚台场廊梯道窗园堂房站间厅馆屋楼院吧店')
    if not label:
        return None
    for i, ch in enumerate(label):
        if ch in LOCATION_CHARS:
            key = label[:i+1]
            if len(key) >= 2:
                return key
    if len(label) <= 3:
        return None
    return label[:2]

def cmd_chain(args):
    """连抽模式:AI 自动跑完整流程,失败时报告问题并继续。"""
    # --resume 模式:已 fill 好的单卡走 render→check→submit
    if getattr(args, 'resume', None):
        result = run_chain_resume(
            args.resume,
            args.user_input or '',
            dry_run=getattr(args, 'dry_run', False),
        )
        reason = result.get('reason')
        if reason == 'needs_fill':
            print(f'\n⏸️ AI 需补填:{", ".join(result.get("missing", []))}')
            print(f'   card_id: {result.get("card_id", "")}')
            print('   AI 用 fill 命令补上后,再次 chain --resume <card_id>')
        elif not result.get('ok'):
            print(f"❌ resume 失败:{reason} | card_id={result.get('card_id','')}")
        return

    # 默认模式:create N 张卡骨架(不 auto-fill,等 AI 填充)
    total = max(1, int(args.count or 1))
    results = []
    used_scenes = set()
    used_series_keys = set()
    explicit_scene = bool(getattr(args, 'scene', None))
    for i in range(1, total + 1):
        max_retries = 3
        for attempt in range(max_retries):
            try:
                result = run_single_chain(args, i, total)
                scene_name = result.get('scene', '') if result.get('ok') else ''
                if not explicit_scene and scene_name:
                    dup_reason = None
                    if scene_name in used_scenes:
                        dup_reason = f'场景「{scene_name}」已用过'
                    else:
                        series_key = _extract_scene_series_key(scene_name)
                        if series_key and series_key in used_series_keys:
                            dup_reason = f'场景「{scene_name}」与已选系列「{series_key}」冲突'
                    if dup_reason:
                        cid = result.get('card_id', '')
                        if cid:
                            duplicate_card_path = resolve_card_path(cid)
                            if duplicate_card_path.exists():
                                duplicate_card_path.unlink()
                        print(f'  ⚠️ {dup_reason},重抽 ({attempt+1}/{max_retries})')
                        continue
                if scene_name:
                    used_scenes.add(scene_name)
                    series_key = _extract_scene_series_key(scene_name)
                    if series_key:
                        used_series_keys.add(series_key)
                results.append(result)
                break
            except Exception as e:
                print(f'❌ 第 {i} 张异常:{e}')
                results.append({'ok': False, 'reason': f'exception:{e}'})
                break
        else:
            # 3 次都重复,保留最后一次
            print(f'  ⚠️ 场景去重耗尽重试,保留「{scene_name}」')
            if scene_name:
                used_scenes.add(scene_name)
                series_key = _extract_scene_series_key(scene_name)
                if series_key:
                    used_series_keys.add(series_key)
            results.append(result)

    ok = sum(1 for r in results if r.get('ok'))
    bad = len(results) - ok
    print(f'\n📊 创建完成:成功 {ok} / 失败 {bad} / 总计 {len(results)}')
    if ok:
        ids = [r['card_id'] for r in results if r.get('ok')]
        print(f'📋 card_ids: {",".join(ids)}')
        template_info = write_chain_fill_templates(ids)
        print(f'🧩 fill 批量模板: {template_info["batch_path"]}')
        if template_info.get('per_card_paths'):
            print(f'🧾 单卡模板示例: {template_info["per_card_paths"][0]}')
        print('→ AI 可直接按模板填 theme_zh / director / slots / story_elevation*，再用 fill --json-file 一次导入（连抽勿拆 --phase）')
        print('→ 骨架不贴合时,可在 fill 阶段原地改造,或重抽;展示用场景名须与 scene.keywords 一致')
        print('→ fill 完成后,用 chain --resume <id> 逐个提交')
    if bad:
        for idx, r in enumerate(results, start=1):
            if not r.get('ok'):
                print(f"  - 第 {idx} 张失败:{r.get('reason')} {r.get('card_id','')}")

def cmd_record(args):
    """手动保存抽卡记录。"""
    card = load_card(args.card)
    remember_user_input(card, args.user_input or "")
    save_card(card)
    write_record(card, user_input=args.user_input or "", source="manual-record")

from card_featured import cmd_featured

# ─── 从 card_archive 导入(归档功能) ────────────────────────
from card_archive import find_metadata_in_draw_history, extract_prompt_from_png, cmd_archive

def cmd_resolve(args):
    """独立调用 resolver 联合解析,输出 fill-ready 字段。"""
    scene_library = args.scene_library or 'general_scenes'
    include_tags = [x.strip() for x in (args.include_tags or '').split(',') if x.strip()]
    exclude_tags = [x.strip() for x in (args.exclude_tags or '').split(',') if x.strip()]

    result = resolve_library_fields(
        scene_library=scene_library,
        scene_id=args.scene_id or '',
        include_tags=include_tags,
        exclude_tags=exclude_tags,
        exposure_mode=args.exposure_focus,
        mood=args.mood or '',
    )
    if not result:
        print('❌ resolver 返回为空,请检查场景库配置')
        sys.exit(1)

    print(json.dumps(result, ensure_ascii=False, indent=2))

    # 同时输出可直接用于 fill 的命令（场景走 scene.keywords）
    parts = []
    if result.get('lighting'):
        parts.append(f"--lighting '{result['lighting']}'")
    if result.get('pose'):
        parts.append(f"--pose '{result['pose']}'")
    if result.get('scene_theme'):
        print(f"\n📌 场景关键词（写入 create 的 scene.keywords，fill 无对应 CLI 参数）:")
        print(f"   {result['scene_theme']}")
    if parts:
        print(f"\n💡 fill 命令参考:")
        print(f"   python3 card_cli.py fill --card <CARD_ID> {' '.join(parts)}")

def cmd_progress(args):
    """查看当前进度/健康状态(progress 比 health 更贴近工作流语义)"""
    print("📊 Progress 面板\n")

    # 1. 基础 progress/health
    progress_script = SCRIPT_DIR.parent / "gpu-pipeline" / "cu-progress.sh"
    if progress_script.exists():
        result = subprocess.run(["bash", str(progress_script)], capture_output=True, text=True, timeout=5)
        print(result.stdout.strip())
    else:
        print("⚠️  cu-progress.sh 不存在")

    # 2. 最新 card.json
    latest_cards = sorted(CARDS_DIR.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    if latest_cards:
        latest = latest_cards[0]
        try:
            card = json.loads(latest.read_text(encoding="utf-8"))
            print("\n━━ 最新卡面 ━━")
            print(f"  card_id: {card.get('card_id')}")
            print(f"  status: {card.get('status')}")
            print(f"  mode: {card.get('mode')}")
            print(f"  scene: {card.get('scene', {}).get('name')}")
            print(f"  person: {card.get('subject', {}).get('display_name')}")
            print(f"  version: v{card.get('version')}")
            if card.get('_validation'):
                print(f"  validation: errors={len(card.get('_validation', {}).get('errors', []))} warnings={len(card.get('_validation', {}).get('warnings', []))}")
            if card.get('delivery', {}).get('reply_id') not in (None, '', 'null'):
                print(f"  reply_id: {card.get('delivery', {}).get('reply_id')}")
        except Exception as e:
            print(f"\n⚠️  最新卡面读取失败: {e}")
    else:
        print("\n━━ 最新卡面 ━━")
        print("  暂无 card.json")



def cmd_direct(args):
    """直投模式：绕过卡片引擎，直接投递 prompt 至 GPU 队列"""
    # 构造 submit_args，直投模式必须带 --raw
    submit_args = [
        str(SCRIPT_DIR.parent / "gpu-pipeline" / "cu-submit.sh"),
        "--raw",
        "--prompt", args.prompt,
    ]

    # 可选参数
    if getattr(args, "person", None):
        submit_args += ["--person", args.person]
    if getattr(args, "scene", None):
        submit_args += ["--scene", args.scene]
    if getattr(args, "theme", None):
        submit_args += ["--theme", args.theme]
    if getattr(args, "narrative", None):
        submit_args += ["--narrative", args.narrative]
    if getattr(args, "lighting", None):
        submit_args += ["--lighting", args.lighting]
    if getattr(args, "style", None):
        submit_args += ["--style", args.style]
    if getattr(args, "lora", None):
        submit_args += ["--lora", args.lora]
    if getattr(args, "width", None):
        submit_args += ["--width", str(args.width)]
    if getattr(args, "height", None):
        submit_args += ["--height", str(args.height)]
    if getattr(args, "workflow", None):
        submit_args += ["--workflow", args.workflow]
    if getattr(args, "reply_id", None) not in (None, "", "null"):
        submit_args += ["--reply-id", str(args.reply_id)]
    if getattr(args, "user_input", None):
        submit_args += ["--user-input", args.user_input]

    if getattr(args, "dry_run", False):
        import shlex
        print("✨ [DRY-RUN] Direct submit simulation successful.")
        print(f"  Command: bash {shlex.join(submit_args)}")
        return

    print("🚀 提交直投任务...")
    result = subprocess.run(["bash"] + submit_args, capture_output=True, text=True, timeout=30)
    print(result.stdout)
    if result.returncode != 0:
        print(result.stderr[:500])
        sys.exit(result.returncode)


def cmd_queue(args):
    """队列管理：调用 cu-queue.py 执行各种动作"""
    # 构造 cu-queue.py 的执行参数
    queue_script = SCRIPT_DIR.parent / "gpu-pipeline" / "cu-queue.py"

    cmd_args = [sys.executable, str(queue_script), args.action]

    if args.action == "clear":
        if getattr(args, "force", False):
            cmd_args.append("--force")
    elif args.action == "remove":
        if getattr(args, "job_id", None):
            cmd_args += ["--job-id", args.job_id]
        elif getattr(args, "position", None) is not None:
            cmd_args += ["--position", str(args.position)]
        elif getattr(args, "fingerprint", None) is not None:
            cmd_args += ["--fingerprint", args.fingerprint]
        else:
            print("❌ remove 操作需要指定 --job-id、--position 或 --fingerprint")
            sys.exit(1)

    result = subprocess.run(cmd_args)
    sys.exit(result.returncode)


DOC_MAP = {
    "prompt": "PROMPT_TEMPLATE.md",
    "draw": "DRAW_GUIDE.md",
    "pitfalls": "CHECK_PITFALLS.md",
    "commands": "CARD_ENGINE_COMMANDS.md",
    "config": "CONFIG_GUIDE.md",
}

def cmd_doc(args):
    """打印指定的设计与维护手册文档的全部内容。"""
    doc_name = getattr(args, "name", "prompt")
    filename = DOC_MAP.get(doc_name, "PROMPT_TEMPLATE.md")
        
    doc_path = SCRIPT_DIR.parent.parent / "doc" / filename
    if not doc_path.exists():
        print(f"❌ 未找到对应文档：{doc_path}")
        sys.exit(1)
    try:
        content = doc_path.read_text(encoding="utf-8")
        print(content)
    except Exception as e:
        print(f"❌ 读取文档失败：{e}")
        sys.exit(1)


def cmd_search(args):
    """搜索场景和角色预设，支持模糊和拼音匹配。"""
    has_query = False
    
    # 中文别名 → 英文 tag 映射（搜中文时自动扩展英文 tag）
    SCENE_ALIAS_MAP = {
        "生活": "daily", "日常": "daily", "生活感": "daily", "日常感": "daily",
        "生活化": "daily", "更日常": "daily", "市井": "daily",
        "反差": "contrast", "反差感": "contrast", "强反差": "contrast",
        "sm": "sm", "捆绑": "bondage", "调教": "discipline",
        "医院": "medical", "诊室": "medical",
        "学校": "school", "教室": "school", "校园": "school",
    }

    if getattr(args, "scene", None):
        has_query = True
        q = str(args.scene).strip().lower()
        # 展开中文别名
        extra_tags = [SCENE_ALIAS_MAP[k] for k in SCENE_ALIAS_MAP if k in q]
        if extra_tags:
            print(f"🔍 正在检索场景库，关键字: '{q}' (展开别名: {', '.join(extra_tags)}) ...\n")
        else:
            print(f"🔍 正在检索场景库，关键字: '{q}' ...\n")
        
        # 场景搜索：优先加密资产加载器，回退扫 libraries/ 明文
        matches = []
        try:
            from card_asset_loader import search_scenes as _search_scenes
            matches = _search_scenes(q, limit=15)
        except Exception:
            matches = []
        if not matches:
                    if lib_dir.exists():
                        for p in lib_dir.glob("*.json"):
                            if p.name == "registry.json":
                                continue
                            try:
                                data = json.loads(p.read_text(encoding="utf-8"))
                                items = data.get("items", []) if isinstance(data, dict) else (data if isinstance(data, list) else [])
                                for item in items:
                                    if not isinstance(item, dict):
                                        continue
                                    label = item.get("label") or item.get("scene") or ""
                                    theme = item.get("scene_theme") or item.get("prompt") or ""
                                    tags = item.get("tags", [])
                                    moods = item.get("moods", [])
                                    notes = item.get("notes") or ""
                                    contrast = item.get("contrast_anchor") or ""
                        
                                    # Match label, theme, tags, moods, notes, contrast_anchor
                                    match_text = " ".join([label, theme, notes, contrast] + tags + moods).lower()
                                    tag_match = extra_tags and any(t in tags or t in moods for t in extra_tags)
                                    if q in match_text or tag_match:
                                        matches.append({
                                            "label": label,
                                            "library": p.stem,
                                            "tags": tags,
                                            "theme": theme[:80] + "..." if len(theme) > 80 else theme
                                        })
                            except Exception:
                                pass
        

        # 去重
        seen = set()
        dedup_matches = []
        for m in matches:
            if m["label"] not in seen:
                seen.add(m["label"])
                dedup_matches.append(m)
                
        if dedup_matches:
            print(f"✨ 找到 {len(dedup_matches)} 个匹配场景 (最多展示前 15 条)：")
            print("-" * 80)
            for idx, m in enumerate(dedup_matches[:15], 1):
                tags_str = f" | 标签: {','.join(m['tags'])}" if m['tags'] else ""
                print(f"  {idx}. 🎬 \033[32m{m['label']}\033[0m ({m['library']}){tags_str}")
                print(f"     💡 描述: {m['theme']}")
            print("-" * 80)
        else:
            print("❌ 未在场景库中找到匹配场景")
        print()

    if getattr(args, "person", None):
        has_query = True
        q = str(args.person).strip().lower()
        print(f"🔍 正在检索角色库/身份库，关键字: '{q}' ...\n")
        
        presets_path = SCRIPT_DIR / "config" / "amateurs.json"
        matches = []
        try:
            from card_asset_loader import search_person as _search_person
            matches = _search_person(q, limit=15)
        except Exception:
            matches = []
        if not matches:
                    if presets_path.exists():
                        try:
                            data = json.loads(presets_path.read_text(encoding="utf-8"))
                            profiles = data.get("profiles", {}) or {}
                            for key, val in profiles.items():
                                disp = val.get("display_name") or ""
                                desc = val.get("description") or ""
                                body = val.get("body_shape") or ""
                    
                                match_text = " ".join([key, disp, desc, body]).lower()
                                if q in match_text:
                                    matches.append({
                                        "key": key,
                                        "display_name": disp,
                                        "description": desc
                                    })
                        except Exception:
                            pass
                

        if matches:
            print(f"✨ 找到 {len(matches)} 个匹配角色/身份 (最多展示前 15 条)：")
            print("-" * 80)
            for idx, m in enumerate(matches[:15], 1):
                print(f"  {idx}. 👥 \033[36m{m['display_name']}\033[0m (key: \033[33m{m['key']}\033[0m)")
                print(f"     💡 描述: {m['description']}")
            print("-" * 80)
        else:
            print("❌ 未在角色库中找到匹配角色")
        print()

    if not has_query:
        print("❌ 错误: 请指定 --scene 或 --person 关键字进行搜索。")
        print("  例: python3 card_cli.py search --scene 教室")
        print("  例: python3 card_cli.py search --person jk")
        sys.exit(1)
