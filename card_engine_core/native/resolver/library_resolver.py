#!/usr/bin/env python3
"""library_resolver.py — 统一库引擎（v2: 含 resolve 联合解析）

能力：
- list / sample / inspect：单库查询
- resolve：场景库解析，输出 fill-ready 字段（scene_theme）
"""
import argparse
import json
import random
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

ROOT = Path(__file__).resolve().parent.parent
LIB_DIR = ROOT / 'libraries'
REGISTRY_FILE = LIB_DIR / 'registry.json'

# 发行版：resolver 常以独立子进程运行，须把 native/（父目录）加进 sys.path，
# 否则 import card_config / card_asset_loader（.so）失败，回退明文 registry 报 FileNotFoundError。
_NATIVE_DIR = Path(__file__).resolve().parent.parent
if str(_NATIVE_DIR) not in sys.path:
    sys.path.insert(0, str(_NATIVE_DIR))


def load_json(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text())


def load_registry() -> Dict[str, Any]:
    try:
        import sys
        parent_dir = str(Path(__file__).resolve().parent.parent)
        if parent_dir not in sys.path:
            sys.path.insert(0, parent_dir)
        from card_config import load_system_config
        cfg = load_system_config()
        if "scene_registry" in cfg and isinstance(cfg["scene_registry"], dict):
            return cfg["scene_registry"]
    except Exception:
        pass
    return load_json(REGISTRY_FILE)


def resolve_library_file(registry: Dict[str, Any], library_name: str) -> Path:
    item = registry['libraries'][library_name]
    return (LIB_DIR / item['file']).resolve()


def load_library(registry: Dict[str, Any], library_name: str) -> Dict[str, Any]:
    item = registry['libraries'][library_name]
    if item.get('mode') == 'external_reference':
        return {
            'library': library_name,
            'mode': 'external_reference',
            'source_file': str(resolve_library_file(registry, library_name)),
            'description': item.get('description', '')
        }
    # 发布态：加密资产加载器优先（发行版无明文 libraries/ 文件）
    try:
        from card_asset_loader import load_library as _load_enc
        enc = _load_enc(library_name)
        if enc:
            return enc
    except Exception:
        pass
    return load_json(resolve_library_file(registry, library_name))


def _entry_terms(entry: Dict[str, Any]) -> set:
    terms = set(entry.get('tags', []))
    for key in ['category', 'privacy_level', 'intensity_level']:
        val = entry.get(key)
        if val:
            terms.add(str(val))
    for key in ['play_axis', 'dominance_axis', 'moods', 'body_focus']:
        vals = entry.get(key, []) or []
        for v in vals:
            if v:
                terms.add(str(v))
    return terms


def match_all_tags(entry: Dict[str, Any], include_tags: List[str]) -> bool:
    if not include_tags:
        return True
    entry_terms = _entry_terms(entry)
    return set(include_tags).issubset(entry_terms)


def match_none_tags(entry: Dict[str, Any], exclude_tags: List[str]) -> bool:
    if not exclude_tags:
        return True
    entry_terms = _entry_terms(entry)
    return entry_terms.isdisjoint(set(exclude_tags))


def sample_items(items: List[Dict[str, Any]], count: int) -> List[Dict[str, Any]]:
    if not items:
        return []
    weights = [max(1, int(item.get('weight', 1))) for item in items]
    chosen = []
    pool = items[:]
    pool_weights = weights[:]
    for _ in range(min(count, len(pool))):
        pick = random.choices(pool, weights=pool_weights, k=1)[0]
        idx = pool.index(pick)
        chosen.append(pick)
        pool.pop(idx)
        pool_weights.pop(idx)
    return chosen


# ═══════════════════════════════════════════════════════════
# resolve 联合解析
# ═══════════════════════════════════════════════════════════

def _pick_one(items: List[Dict], include_tags: List[str] = None, exclude_tags: List[str] = None) -> Optional[Dict]:
    """从 items 中按标签过滤后加权随机抽 1 个。"""
    filtered = [
        item for item in items
        if match_all_tags(item, include_tags or []) and match_none_tags(item, exclude_tags or [])
    ]
    if not filtered:
        return None
    return sample_items(filtered, 1)[0]


def resolve_multi(
    registry: Dict,
    scene_library: str = 'general_scenes',
    scene_id: str = '',
    scene_include_tags: List[str] = None,
    scene_exclude_tags: List[str] = None,
    exposure_mode: str = 'auto',
    mood: str = '',
) -> Dict[str, Any]:
    """场景库解析：从场景库中选出场景。

    scene_id 非空时直接按 id 查找场景（不随机选）；为空时按 tags 随机选。

    返回 fill-ready 字典：
      scene_theme, _meta
    """
    result = {}
    _meta = {'libraries_used': [], 'fallbacks': []}

    # ── 选/查场景 ──
    scene_data = load_library(registry, scene_library)
    scene_items = scene_data.get('items', []) if scene_data.get('mode') != 'external_reference' else []

    if scene_id:
        # 按 id 精确查找
        scene = next((s for s in scene_items if s.get('id') == scene_id), None)
        if not scene:
            _meta['fallbacks'].append(f'scene:{scene_id}=not_found')
            scene = {}
        else:
            _meta['libraries_used'].append(scene_library)
    else:
        # 按 tags 随机选
        scene = _pick_one(scene_items, include_tags=scene_include_tags, exclude_tags=scene_exclude_tags)
        if not scene:
            _meta['fallbacks'].append(f'scene:{scene_library}=empty')
            scene = {}
        else:
            _meta['libraries_used'].append(scene_library)

    # 场景 → scene_theme
    if scene.get('scene_theme'):
        result['scene_theme'] = scene['scene_theme']
    result['_scene'] = {
        'id': scene.get('id'),
        'label': scene.get('label'),
        'tags': scene.get('tags', []),
        'moods': scene.get('moods', []),
    }

    result['_meta'] = _meta
    return result


def main() -> None:
    p = argparse.ArgumentParser(description='统一库引擎（v2）')
    p.add_argument('--library', help='库名（list/sample/inspect 时必填）')
    p.add_argument('--action', choices=['list', 'sample', 'inspect', 'resolve'], default='list')
    p.add_argument('--include-tags', default='', help='必须同时包含的 tags，逗号分隔')
    p.add_argument('--exclude-tags', default='', help='不能包含的 tags，逗号分隔')
    p.add_argument('--count', type=int, default=3)
    # resolve 专用参数
    p.add_argument('--scene-library', default='general_scenes', help='resolve: 场景库名')
    p.add_argument('--scene-id', default='', help='resolve: 指定场景 id（精确查找，不随机）')
    p.add_argument('--exposure-focus', default='auto', help='resolve: 曝光模式 upper/lower/both/auto/none')
    p.add_argument('--mood', default='', help='resolve: 情绪关键词')

    args = p.parse_args()

    registry = load_registry()

    # ── resolve 模式 ──
    if args.action == 'resolve':
        include_tags = [x.strip() for x in args.include_tags.split(',') if x.strip()]
        exclude_tags = [x.strip() for x in args.exclude_tags.split(',') if x.strip()]
        result = resolve_multi(
            registry,
            scene_library=args.scene_library,
            scene_id=args.scene_id,
            scene_include_tags=include_tags,
            scene_exclude_tags=exclude_tags,
            exposure_mode=args.exposure_focus,
            mood=args.mood,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return

    # ── 其他模式需要 --library ──
    if not args.library:
        print('--library is required for list/sample/inspect', file=sys.stderr)
        sys.exit(1)

    include_tags = [x.strip() for x in args.include_tags.split(',') if x.strip()]
    exclude_tags = [x.strip() for x in args.exclude_tags.split(',') if x.strip()]

    data = load_library(registry, args.library)

    if data.get('mode') == 'external_reference':
        print(json.dumps(data, ensure_ascii=False, indent=2))
        return

    items = data.get('items', [])
    filtered = [
        item for item in items
        if match_all_tags(item, include_tags) and match_none_tags(item, exclude_tags)
    ]

    if args.action == 'inspect':
        print(json.dumps(data, ensure_ascii=False, indent=2))
    elif args.action == 'sample':
        print(json.dumps(sample_items(filtered, args.count), ensure_ascii=False, indent=2))
    else:
        brief = [
            {
                'id': item.get('id'),
                'label': item.get('label'),
                'tags': item.get('tags', []),
                'weight': item.get('weight', 1)
            }
            for item in filtered
        ]
        print(json.dumps(brief, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
