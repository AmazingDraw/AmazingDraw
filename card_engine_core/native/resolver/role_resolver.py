import json
import random
import logging
import re
from pathlib import Path
from typing import Optional

RESOLVER_DIR = Path(__file__).resolve().parent
ROOT_DIR = RESOLVER_DIR.parent
CONFIG_DIR = ROOT_DIR / 'config'

logger = logging.getLogger("role_resolver")

from card_config import TMP_DIR
RANDOM_HISTORY_FILE = TMP_DIR / "random-history.json"
RECENT_CELEBRITY_WINDOW = 10


def _compact(text: str) -> str:
    return re.sub(r'[^a-z0-9\u4e00-\u9fff]+', '', str(text or '').lower())


def _find_profile_key_by_person(person: str, profiles: dict) -> Optional[str]:
    raw = str(person or '').strip()
    if not raw:
        return None
    compact = _compact(raw)
    try:
        from card_identity import is_restricted_profile, role_restrictions_enabled
        restrict_on = role_restrictions_enabled()
    except Exception:
        restrict_on = False
        is_restricted_profile = lambda *a, **k: False  # noqa: E731
    for key, profile in profiles.items():
        if restrict_on and is_restricted_profile(key, profile if isinstance(profile, dict) else None):
            continue
        display_name = str((profile or {}).get('display_name') or '').strip()
        description = str((profile or {}).get('description') or '').strip()
        candidates = [key, display_name, description]
        if any(raw == c or compact == _compact(c) for c in candidates if c):
            return key
    return None


def _find_identity_by_profile_key(profile_key: str, presets: dict) -> Optional[str]:
    profiles = presets.get('profiles', {}) or {}
    profile = profiles.get(profile_key) or {}
    display_name = str(profile.get('display_name') or '').strip()
    if display_name and display_name != 'random':
        return display_name
    return None


def load_amateurs() -> dict:
    # 发布态：加密资产加载器优先；失败回退开发态明文
    try:
        from card_asset_loader import load_amateurs as _load_enc
        enc = _load_enc()
        if enc:
            return _merge_custom_presets(enc)
    except Exception:
        pass
    presets_path = CONFIG_DIR / "amateurs.json"
    presets = {}
    if presets_path.exists():
        try:
            presets = json.loads(presets_path.read_text(encoding="utf-8"))
        except Exception:
            pass
    return _merge_custom_presets(presets)


def _merge_custom_presets(presets: dict) -> dict:
    """合并第三方自定义角色（发布态与开发态共用）。"""
    presets = dict(presets or {})
    # 合并第三方自定义角色
    try:
        from card_config import load_system_config
        from pathlib import Path
        config = load_system_config()
        custom_dir = config.get("custom_presets_dir", "")
        if custom_dir:
            # 兼容 amateurs / roles 子文件夹命名
            for folder_name in ["amateurs", "roles"]:
                subjects_dir = Path(custom_dir) / folder_name
                if subjects_dir.exists() and subjects_dir.is_dir():
                    for f in subjects_dir.glob("*.json"):
                        if f.name == "template.json":
                            continue
                        try:
                            custom_presets = json.loads(f.read_text(encoding="utf-8"))
                            if "identity_pool" in custom_presets and isinstance(custom_presets["identity_pool"], list):
                                pool = presets.setdefault("identity_pool", [])
                                for item in custom_presets["identity_pool"]:
                                    if item not in pool:
                                        pool.append(item)
                            if "profiles" in custom_presets and isinstance(custom_presets["profiles"], dict):
                                profiles = presets.setdefault("profiles", {})
                                for k, v in custom_presets["profiles"].items():
                                    profiles[k] = v
                        except Exception:
                            pass
    except Exception:
        pass
    return presets


def get_disabled_celebrity_candidates() -> set:
    """获取当前配置中所有被禁用的明星标识集合（含中文名/触发词/lora键及归一化形式）。"""
    disabled_set = set()
    try:
        cfg_path = ROOT_DIR.parent / "config.json"
        if cfg_path.exists():
            cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
            disabled_raw = cfg.get("disabled_celebrities") or []
            if isinstance(disabled_raw, (list, tuple, set)):
                for d in disabled_raw:
                    s = str(d or "").strip()
                    if s:
                        disabled_set.add(s)
                        disabled_set.add(_compact(s))
    except Exception:
        pass
    return disabled_set


def is_celebrity_disabled(identifier: str) -> bool:
    """判定指定的明星姓名/触发词/LoRA键名是否属于当前被禁用的明星。"""
    raw = str(identifier or "").strip()
    if not raw:
        return False
    disabled_set = get_disabled_celebrity_candidates()
    if not disabled_set:
        return False
    candidates = {raw, _compact(raw)}
    if any(c in disabled_set for c in candidates if c):
        return True
    # 进一步在原始完整未过滤的 celebrities.json 中逆查其名字与触发词
    celebs_path = CONFIG_DIR / "celebrities.json"
    if celebs_path.exists():
        try:
            raw_data = json.loads(celebs_path.read_text(encoding="utf-8"))
            for pool in raw_data.values():
                if not isinstance(pool, dict):
                    continue
                for lora_key, val in pool.items():
                    name = val[0] if isinstance(val, (list, tuple)) and val else str(val)
                    trig = val[1] if isinstance(val, (list, tuple)) and len(val) > 1 else name
                    item_tokens = {lora_key, _compact(lora_key), name, _compact(name), trig, _compact(trig)}
                    if raw in item_tokens or _compact(raw) in item_tokens:
                        if any(tok in disabled_set for tok in item_tokens if tok):
                            return True
        except Exception:
            pass
    return False


def load_celebrities() -> dict:
    celebs_path = CONFIG_DIR / "celebrities.json"
    if not celebs_path.exists():
        return {"z": {}, "flux": {}}
    try:
        data = json.loads(celebs_path.read_text(encoding="utf-8"))
    except Exception:
        return {"z": {}, "flux": {}}

    # 支持从 config.json 读取 disabled_celebrities 黑名单（可填中文名、触发词或 lora 键名）
    disabled_set = get_disabled_celebrity_candidates()
    if not disabled_set:
        return data

    filtered = {}
    for pool_name, pool in data.items():
        if not isinstance(pool, dict):
            filtered[pool_name] = pool
            continue
        filtered_pool = {}
        for lora_key, val in pool.items():
            name = val[0] if isinstance(val, (list, tuple)) and val else str(val)
            trigger = val[1] if isinstance(val, (list, tuple)) and len(val) > 1 else name
            # 匹配 lora_key / 姓名 / 触发词 / 紧凑归一化
            match_candidates = {
                lora_key,
                _compact(lora_key),
                name,
                _compact(name),
                trigger,
                _compact(trigger),
            }
            if any(c in disabled_set for c in match_candidates if c):
                continue
            filtered_pool[lora_key] = val
        filtered[pool_name] = filtered_pool
    return filtered


def load_random_history() -> dict:
    if RANDOM_HISTORY_FILE.exists():
        try:
            with open(RANDOM_HISTORY_FILE) as f:
                data = json.load(f)
            if isinstance(data, dict):
                return data
        except Exception:
            pass
    return {"recent_celebrities": []}


def save_random_history(data: dict):
    RANDOM_HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(RANDOM_HISTORY_FILE, "w") as f:
        json.dump(data, f, ensure_ascii=False)


def load_recent_celebrities(limit: int = RECENT_CELEBRITY_WINDOW) -> list[str]:
    history = load_random_history().get("recent_celebrities", [])
    return history[-limit:]


def save_recent_celebrity(name: str, limit: int = RECENT_CELEBRITY_WINDOW):
    data = load_random_history()
    history = data.get("recent_celebrities", [])
    history.append(name)
    data["recent_celebrities"] = history[-limit:]
    save_random_history(data)


def pick_non_repeating_celebrity(pool: dict, model_name: str):
    recent_names = set(load_recent_celebrities())
    available_keys = [key for key, val in pool.items() if val[0] not in recent_names]
    if not available_keys:
        available_keys = list(pool.keys())
    key = random.choice(available_keys)
    name, trigger = pool[key]
    save_recent_celebrity(name)
    logger.info(f"CELEBRITY_PICK | model={model_name} name={name} recent={list(recent_names)}")
    return key, name, trigger, model_name


def pick_non_repeating_celebrity_auto(celebs: dict):
    recent_names = set(load_recent_celebrities())
    # 目前仅接入并支持 Z-Image，Flux 预留为空
    candidates = [(key, val[0], val[1], 'z') for key, val in celebs.get("z", {}).items()]

    available = [item for item in candidates if item[1] not in recent_names]
    if not available:
        available = candidates

    if not available:
        logger.error("CELEBRITY_PICK_ERROR | Z-Image celebrity pool is empty")
        raise RuntimeError("zimage_celebrity_pool_empty")

    key, name, trigger, model_name = random.choice(available)
    save_recent_celebrity(name)
    logger.info(f"CELEBRITY_PICK | model={model_name} name={name} recent={list(recent_names)} mode=auto-global")
    return key, name, trigger, model_name


def pick_celebrity_role(person: str = None, trigger: str = None, lora: str = None, model_type: str = "auto") -> dict:
    """解析或随机抽选明星角色"""
    # 0. 显式指定检测：若显式指定的 person/trigger/lora 属于被禁用的明星，Fail-Fast 强拦截
    explicit_target = str(person or trigger or lora or "").strip()
    if explicit_target and is_celebrity_disabled(explicit_target):
        raise ValueError(
            f"明星「{explicit_target}」已被配置禁用 (disabled_celebrities)，"
            "禁止显式指定创卡。如需使用请先在 config.json 中解除屏蔽或更换人选！"
        )

    celebs = load_celebrities()
    z_pool = celebs.get("z", {})
    flux_pool = celebs.get("flux", {})

    # 1. 如果指定了 LoRA，直接解析
    if lora:
        if lora in z_pool:
            return {"celebrity": z_pool[lora][0], "lora": lora, "trigger": z_pool[lora][1], "model_type": "z"}
        if lora in flux_pool:
            return {"celebrity": flux_pool[lora][0], "lora": lora, "trigger": flux_pool[lora][1], "model_type": "flux"}
        # 兼容不带后缀和路径的 LoRA 键
        for pool_name, pool in [("z", z_pool), ("flux", flux_pool)]:
            for k, val in pool.items():
                if lora in k:
                    return {"celebrity": val[0], "lora": k, "trigger": val[1], "model_type": pool_name}

    # 2. 如果指定了 trigger 词或姓名，进行模糊查找
    search_term = trigger or person
    if search_term:
        for pool_name, pool in [("z", z_pool), ("flux", flux_pool)]:
            for k, (name, trig) in pool.items():
                if (trig and search_term in trig) or (name and search_term in name):
                    return {"celebrity": name, "lora": k, "trigger": trig, "model_type": pool_name}

    # 3. 随机抽取
    if model_type == 'z':
        lora_key, name, trig, mtype = pick_non_repeating_celebrity(z_pool, 'z')
    elif model_type == 'flux':
        lora_key, name, trig, mtype = pick_non_repeating_celebrity(flux_pool, 'flux')
    else:
        lora_key, name, trig, mtype = pick_non_repeating_celebrity_auto(celebs)

    return {"celebrity": name, "lora": lora_key, "trigger": trig, "model_type": mtype}


def pick_amateur_role(person: str = None, profile_name: str = "default") -> dict:
    """解析素人角色。

    优先级：
      1. 用户指定 person + 命中 profile/display_name/description/identity → 锁定对应 identity/profile
      2. 用户指定 person 但仅是身份词 → 锁定 identity，profile 留给上层关联逻辑挑选
      3. 用户指定 profile → 锁定 profile，并尽量反推出 identity
      4. 都没指定 → identity/profile 随机
    """
    from card_identity import apply_role_restrictions, is_restricted_profile, role_restrictions_enabled

    presets = apply_role_restrictions(load_amateurs())
    all_profiles = presets.get("profiles", {})

    raw_person = str(person or "").strip()
    requested_profile = str(profile_name or 'default').strip() or 'default'
    if role_restrictions_enabled() and requested_profile not in ("default", "random", "") and is_restricted_profile(requested_profile):
        requested_profile = "default"

    matched_profile_key = _find_profile_key_by_person(raw_person, all_profiles) if raw_person else None
    if matched_profile_key:
        profile_data = all_profiles.get(matched_profile_key, {})
        identity = _find_identity_by_profile_key(matched_profile_key, presets) or raw_person
        body_shape = profile_data.get("body_shape", "young East Asian girl, slim figure")
        logger.info(f"AMATEUR_PICK | source=person-profile-match person={raw_person} profile={matched_profile_key} identity={identity}")
        return {
            "celebrity": identity,
            "trigger": identity,
            "lora": None,
            "model_type": "z",
            "profile": matched_profile_key,
            "body_shape": body_shape,
        }

    if raw_person:
        logger.info(f"AMATEUR_PICK | source=manual-person person={raw_person} profile={requested_profile}")
        return {
            "celebrity": raw_person,
            "trigger": raw_person,
            "lora": None,
            "model_type": "z",
            "profile": requested_profile,
            "body_shape": "",
        }

    p_name = requested_profile
    if p_name == 'default':
        p_name = random.choice(list(all_profiles.keys())) if all_profiles else 'default'

    profile_data = all_profiles.get(p_name, {})
    body_shape = profile_data.get("body_shape", "young East Asian girl, slim figure")
    identity = _find_identity_by_profile_key(p_name, presets)
    if not identity:
        pool = presets.get("identity_pool", ["女大学生"])
        identity = random.choice(pool) if pool else "亚洲女孩"

    logger.info(f"AMATEUR_PICK | source=random identity={identity} profile={p_name}")
    return {
        "celebrity": identity,
        "trigger": identity,
        "lora": None,
        "model_type": "z",  # 素人默认采用 z 采样工作流
        "profile": p_name,
        "body_shape": body_shape
    }


def resolve_role(mode: str, person: str = None, trigger: str = None, lora: str = None, model_type: str = "auto", profile: str = "default") -> dict:
    """统一解析角色入口"""
    if mode == "celebrity":
        return pick_celebrity_role(person=person, trigger=trigger, lora=lora, model_type=model_type)
    else:
        return pick_amateur_role(person=person, profile_name=profile)
