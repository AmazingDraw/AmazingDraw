#!/usr/bin/env python3
"""
md2json.py — markdown 词库 → JSON 词库转换器
==============================================
templates-jav/ 下的 markdown 是词库真相源；templates-json/ 下的 JSON
由本脚本生成，供 cu-template-bundle.py 高速读取。

用法：
  python3 md2json.py            # 转换全部注册词库
  python3 md2json.py tattoo     # 只转指定词库（accessories/tattoo/props/pets）
  python3 md2json.py --check    # 只对比不写入，报告 md 与 JSON 是否漂移

转换规则：
  - ## / ### / #### 标题 → 章节 key（剥离前导 emoji/符号，折叠空白）
  - 标题之间的所有行原样保留为行数组（含 markdown 表格语法）
  - 首个标题之前的内容并入 "前言" 章节
"""

import json
import re
import sys
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent.parent.parent
MD_DIR = SKILL_DIR / "library" / "templates-jav"
JSON_DIR = SKILL_DIR / "library" / "templates-json"

# 注册表：JSON 名 → markdown 源文件
LIBRARIES = {
    "accessories": "10-发型饰品.md",
    "tattoo":      "12-纹身标记.md",
    "props":       "13-道具专项.md",
    "pets":        "14-宠物动物.md",
}

HEADER_RE = re.compile(r"^(#{1,4})\s+(.+?)\s*$")
# 标题前导的 emoji/符号/编号装饰（保留中文、英文、数字、常用分隔符）
DECOR_RE = re.compile(r"^[^\w\u4e00-\u9fff（(【-]+")


def clean_title(raw: str) -> str:
    """剥离标题前导 emoji/装饰符号，折叠内部空白。"""
    t = DECOR_RE.sub("", raw).strip()
    t = re.sub(r"\s+", " ", t)
    return t or raw.strip()


def convert(md_path: Path) -> dict:
    sections: dict[str, list[str]] = {}
    current = "前言"
    buf: list[str] = []

    def flush():
        nonlocal buf
        lines = buf
        buf = []
        # 去掉首尾空行
        while lines and not lines[0].strip():
            lines.pop(0)
        while lines and not lines[-1].strip():
            lines.pop()
        if not lines:
            return
        if current in sections:
            sections[current].extend(["", *lines])
        else:
            sections[current] = lines

    for line in md_path.read_text(encoding="utf-8").splitlines():
        m = HEADER_RE.match(line)
        if m:
            flush()
            current = clean_title(m.group(2))
        else:
            buf.append(line)
    flush()

    if "前言" in sections and not any(s.strip() for s in sections["前言"]):
        del sections["前言"]
    return sections


def main():
    check_only = "--check" in sys.argv
    targets = [a for a in sys.argv[1:] if not a.startswith("--")] or list(LIBRARIES)

    drift = False
    for name in targets:
        if name not in LIBRARIES:
            print(f"⚠️ 未知词库: {name}（可选: {', '.join(LIBRARIES)}）")
            continue
        md_path = MD_DIR / LIBRARIES[name]
        json_path = JSON_DIR / f"{name}.json"
        if not md_path.exists():
            print(f"❌ {name}: 找不到 md 源 {md_path}")
            drift = True
            continue

        sections = convert(md_path)
        if check_only:
            old = {}
            if json_path.exists():
                old = json.loads(json_path.read_text(encoding="utf-8"))
            if list(old.keys()) == list(sections.keys()) and all(
                old.get(k) == v for k, v in sections.items()
            ):
                print(f"✅ {name}: 无漂移（{len(sections)} 章节）")
            else:
                new_keys = [k for k in sections if k not in old]
                gone = [k for k in old if k not in sections]
                print(f"⚠️ {name}: 有漂移（新增 {len(new_keys)}、消失 {len(gone)}）")
                drift = True
            continue

        json_path.parent.mkdir(parents=True, exist_ok=True)
        json_path.write_text(
            json.dumps(sections, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        print(f"✅ {name}: {LIBRARIES[name]} → {json_path.name}（{len(sections)} 章节）")

    sys.exit(1 if drift and check_only else 0)


if __name__ == "__main__":
    main()
