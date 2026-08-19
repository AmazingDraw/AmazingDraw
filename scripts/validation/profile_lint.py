#!/usr/bin/env python3
"""
profile_lint.py — 扫描 amateurs.json 所有 profile body_shape，检查常见问题

用法: python3 profile_lint.py [--fix]

检查项：
1. 紧身布料 + 乳头/乳晕 = 穿透矛盾
2. pushed up / tight / fitted 与 nipple 描述同时出现
3. 输出有问题的 profile 列表
"""

import json, re, sys
from pathlib import Path

AMATEURS = Path(__file__).resolve().parent.parent / 'card-engine' / 'config' / 'amateurs.json'


def check_clothing_nipple_conflict(body: str) -> list[str]:
    """Check for clothing covering nipples while describing nipple details."""
    issues = []
    
    # Pattern: fitted/compression clothing + nipple/areola (but NOT "tight" when describing body parts)
    if re.search(r'\b(fitted|undershirt|camisole|tank.top|bra|pushed.up.by|contained.within)\b', body, re.I):
        if re.search(r'\b(nipple|areola|areolae)\b', body, re.I):
            # Check if clothing is actually removed/open
            if not re.search(r'\b(unbuttoned|lifted|open|removed|slipped.off|pushed.aside|fully.exposed|bare|completely.naked|uniform.open|shirt.open)\b', body, re.I):
                issues.append('cloth+nipple: 紧身布料 + 乳头细节，但无衣物移开词')
    
    # Pattern: clothing garment directly over nipple
    if re.search(r'\b(through|visible.through|poking.through|showing.through).*(fabric|cloth|shirt|bra|undershirt)\b', body, re.I):
        issues.append('penetration: 乳头穿透布料描述')
    
    return issues


def lint(fix: bool = False) -> int:
    with open(AMATEURS) as f:
        p = json.load(f)
    
    total = len(p['profiles'])
    bad = 0
    fixed = 0
    
    print(f'🔍 扫描 {total} 个 profile…')
    print()
    
    for name, prof in sorted(p['profiles'].items()):
        body = prof.get('body_shape', '')
        issues = check_clothing_nipple_conflict(body)
        if not issues:
            continue
        
        bad += 1
        desc = prof.get('description', name)
        print(f'⚠️  {name}: {desc[:60]}')
        for iss in issues:
            print(f'    → {iss}')
        
        if fix:
            # Autofix: add "no nipple visible" and replace "pushed up by" with "contained within"
            body = re.sub(r'pushed.up.by\s+(\w+)', r'contained within \1', body, flags=re.I)
            body = re.sub(r'(breasts.*$)', r'\1, no nipple visible', body)
            prof['body_shape'] = body
            print(f'    ✅ autofixed')
            fixed += 1
        
        print()
    
    if fix and fixed > 0:
        with open(AMATEURS, 'w') as f:
            json.dump(p, f, indent=2, ensure_ascii=False)
        print(f'💾 已保存 {fixed} 处修改到 amateurs.json')
    
    if bad == 0:
        print('✅ 全部 profile 通过检查')
    
    return bad


if __name__ == '__main__':
    fix = '--fix' in sys.argv
    count = lint(fix=fix)
    sys.exit(min(count, 1))
