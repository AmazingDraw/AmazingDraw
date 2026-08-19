#!/usr/bin/env python3
"""
cu-template-bundle.py — 结构化 JSON 词库打包加载器（v3.0）
===========================================================
整合并过滤 AI 组装 Prompt 所需的各类组件模板（饰品、道具、宠物、纹身），
不包含具体的场景数据库（场景由卡片引擎前端/配置库主导）。

使用示例：
  ① 一键智能提取（自动加载四类词库的常用章节）：
     python3 cu-template-bundle.py --auto

  ② 精准定向提取（按需拉取指定文件的指定章节）：
     python3 cu-template-bundle.py --sections "props:振动棒|假阳具,tattoo:图案速查"
     → 返回：定向过滤后的章节内容

  ③ 仅返回词库索引（轻量化导航目录）：
     python3 cu-template-bundle.py --index-only
     → 返回：所有可用 JSON 组件的章节标题索引

# ═══════════════════════════════════════════════════════════════
# 🔧 维护注意事项（模板文件更新时必读）
# ═══════════════════════════════════════════════════════════════
#
# 词库真相源是 templates-jav/ 下的 markdown，JSON 由转换脚本生成：
#   python3 scripts/gpu-pipeline/md2json.py          # 重新生成全部
#   python3 scripts/gpu-pipeline/md2json.py tattoo   # 只转一个
#
# 以下变更 **不需要** 修改脚本：
#   ✅ 在 markdown 词库里增/删/改名任意章节和词条内容（重新跑 md2json.py 即可）
#
# 以下变更 **需要** 修改脚本：
#   ⚠️  词库目录位置变化 → 改 JSON_TEMPLATE_DIR
#   ⚠️  新增/删除注册的 JSON 词库文件 → 改 TEMPLATE_FILES 列表
#   ⚠️  --auto 默认章节匹配关键词变化 → 改 AUTO_SECTIONS 字典
# ═══════════════════════════════════════════════════════════════
"""

import json
import argparse
from pathlib import Path

# ─── 路径配置 ────────────────────────────────────────────────
SKILL_DIR = Path(__file__).resolve().parent.parent.parent
JSON_TEMPLATE_DIR = SKILL_DIR / "library" / "templates-json"

# ⚠️  只读 json 格式的文件，markdown 仅作查阅。未来若新增词库，在此注册 .json 即可。
TEMPLATE_FILES = [
    "accessories.json",
    "tattoo.json",
    "props.json",
    "pets.json",
]

# ⚠️  章节名匹配到以下模式时跳过（索引/导航/生成规则类，无实际词库）
SKIP_SECTION_PATTERNS = [
    r"^📋\s*索引",
    r"^🎲\s*.*(生成|选择)",
    r"^📐\s*.*原则",
    r"^⚠️",
    r"^常见问题",
    r"^正确写法",
    r"^翻车词",
    r"^组合公式",
]

# ⚠️  --auto 模式自动加载的章节（按文件前缀 → 章节名关键词列表）
# 这些是 AI 组装 prompt 时几乎必读的章节，自动返回可省第二步调用。
# 模板文件增删章节时，如果 AI 的「必读」范围变化，更新此字典。
AUTO_SECTIONS = {
    "accessories":   ["甜美", "性感情趣", "和风", "项链", "耳饰", "身体饰品"],
    "tattoo":        ["CJK", "书写模板", "所有权", "侮辱", "指令", "状态", "计数", "部位标注", "下贱短语", "位置×文字", "皮肤融合", "安全写法"],
    # props：氛围/日常章节优先；性玩具仅末尾低频保留 1 类（跳蛋），避免 --auto 满眼振动棒/假阳具
    # 风俗/SM/玩具主题可用 --sections "props:振动棒|假阳具|跳蛋|束缚" 按需拉全量
    "props":         ["使用原则", "道具×场景速查", "酒", "食物", "蜡烛", "花瓣", "枕头", "手机", "影像", "娱乐", "日用", "跳蛋"],
    "pets":          ["猫", "狗", "兽耳", "尾巴"],
}


def should_skip(section_name: str) -> bool:
    import re
    return any(re.search(p, section_name) for p in SKIP_SECTION_PATTERNS)


def _normalize_match_key(text: str) -> str:
    """去掉 /、空白与常见标点，便于「学院制服」命中「学院/制服」。"""
    import re
    return re.sub(r"[\s/\\|_·•\-—–,，.。:：;；()（）\[\]【】{}<>《》\"'`~～]+", "", str(text or ""))


def _section_key_matches(key: str, section_name: str) -> bool:
    """关键词匹配章节名：原文子串 或 规范化后子串。"""
    if not key:
        return False
    if key in section_name:
        return True
    nk, ns = _normalize_match_key(key), _normalize_match_key(section_name)
    return bool(nk) and nk in ns


def parse_sections(filepath: Path, content_only: bool = True) -> dict:
    """
    加载 JSON 词库（{章节名: [行数组]} 结构，由 md2json.py 生成）。
    索引/规则类章节按 SKIP_SECTION_PATTERNS 过滤。

    content_only=True  → {章节名: 内容字符串}
    content_only=False → {章节名: None}（仅索引）
    """
    if not filepath.exists() or filepath.suffix != ".json":
        return {}
    try:
        with open(filepath, encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return {}
        items = ((k, v) for k, v in data.items() if not should_skip(k))
        if content_only:
            return {k: "\n".join(v) if isinstance(v, list) else v for k, v in items}
        return {k: None for k, _ in items}
    except Exception:
        return {}


def filter_sections(all_sections: dict, spec: str) -> dict:
    """
    按需过滤章节。
    spec 格式: "文件前缀:关键词1|关键词2,文件前缀2:关键词3"
    关键词模糊匹配章节名。
    """
    if not spec:
        return all_sections

    filtered = {}
    for item in spec.split(","):
        item = item.strip()
        if ":" not in item:
            continue
        file_prefix, section_keys = item.split(":", 1)
        file_prefix = file_prefix.strip()
        section_keys = [s.strip() for s in section_keys.split("|")]

        matched_file = None
        for fname in all_sections:
            if fname.startswith(file_prefix):
                matched_file = fname
                break
        if not matched_file:
            continue

        for sname, content in all_sections[matched_file].items():
            for key in section_keys:
                if _section_key_matches(key, sname):
                    filtered.setdefault(matched_file, {})[sname] = content
                    break

    return filtered


def auto_pick_sections(all_sections: dict) -> dict:
    """
    --auto 模式：按 AUTO_SECTIONS 字典自动挑选常用章节。
    不在字典中的文件 → 跳过。
    ⚠️  AUTO_SECTIONS 需与模板章节保持同步。
    """
    result = {}
    notices = []
    for fname, sections in all_sections.items():
        keys = AUTO_SECTIONS.get(fname)
        if not keys:
            continue
        matched = 0
        for sname, content in sections.items():
            for key in keys:
                if _section_key_matches(key, sname):
                    result.setdefault(fname, {})[sname] = content
                    matched += 1
                    break
        if matched == 0 and sections:
            notices.append(f"⚠️ {fname} 的 --auto 关键词 {keys} 未匹配到任何章节，请检查 AUTO_SECTIONS 是否与词库同步。")
    if notices:
        result["_notices"] = notices
    return result


def main():
    p = argparse.ArgumentParser(description="词库一键加载")
    mode = p.add_mutually_exclusive_group()
    mode.add_argument("--auto", action="store_true",
                      help="智能模式：自动加载纹身/宠物/道具/饰品四类词库的常用章节（AUTO_SECTIONS 定义）")
    mode.add_argument("--sections", default=None,
                      help="按需加载章节: '文件前缀:关键词|关键词,...'")
    mode.add_argument("--index-only", action="store_true",
                      help="仅返回章节索引（标题），不含内容")
    args = p.parse_args()

    result = {}

    # ═══ 章节解析 ═══
    if args.sections or args.auto:
        # 有内容模式：解析完整内容
        all_sections = {}
        for filename in TEMPLATE_FILES:
            filepath = JSON_TEMPLATE_DIR / filename
            sections = parse_sections(filepath, content_only=True)
            if sections:
                all_sections[filename.replace(".json", "")] = sections
    else:
        # 索引模式：仅标题，无内容（轻量）
        all_sections = {}
        for filename in TEMPLATE_FILES:
            filepath = JSON_TEMPLATE_DIR / filename
            sections = parse_sections(filepath, content_only=False)
            if sections:
                all_sections[filename.replace(".json", "")] = list(sections.keys())

    # ═══ 按需过滤 ═══
    if args.auto:
        result["sections"] = auto_pick_sections(all_sections)
    elif args.sections:
        result["sections"] = filter_sections(all_sections, args.sections)
    else:
        result["sections"] = all_sections  # 仅索引

    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
