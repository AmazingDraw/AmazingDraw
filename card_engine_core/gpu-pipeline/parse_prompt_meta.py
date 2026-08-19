#!/usr/bin/env python3
import sys
import os
import json
from pathlib import Path

# Add card-engine directory to path
SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR.parent / 'card-engine'))

from card_llm_client import chat_completion, extract_json_object
from card_validation import has_cjk

SYSTEM_PROMPT = """You are a Stable Diffusion / Midjourney metadata parser.
Given an English prompt, extract or infer the scene metadata and translate them to Chinese.

Format your response STRICTLY as a single JSON object.
Do NOT output any thinking, reasoning, chain-of-thought, or explanation.
Start your response immediately with the opening curly brace '{' and end with the closing curly brace '}'.

JSON format:
{
  "person": "Chinese subject identity, e.g. '女孩', 'OL', '学姐' (max 6 chars)",
  "scene": "Chinese scene location, e.g. '教室', '阳台', '雨中街道' (max 8 chars)",
  "theme": "Chinese theme or vibe, e.g. '慵懒日常', '监控偷窥', '逆光夕阳' (max 8 chars)",
  "narrative": "A descriptive, narrative Chinese sentence translating/expanding the prompt (max 100 chars)",
  "lighting": "Chinese lighting description, e.g. '柔和光线', '夕阳余晖' (max 8 chars)",
  "style": "Chinese style description, e.g. '胶片人像', '监控纪实' (max 8 chars)"
}"""

def main():
    if len(sys.argv) > 1 and sys.argv[1] in {"-h", "--help", "help"}:
        print("""🧠 直投提示词元数据 AI 补全工具 (parse_prompt_meta.py)
=========================================
用法:
  通过环境变量控制：
    export CU_PROMPT="英文提示词"
    export CU_META_FILE="/tmp/test_meta.json"
    [export CU_PERSON="人物名"] [export CU_SCENE="场景名"] ...
    python3 parse_prompt_meta.py

环境变量说明:
  CU_META_FILE  (必填) 输出元数据 JSON 文件的写入物理路径
  CU_PROMPT     (必填) 待解析的英文 Prompt 文本
  CU_PERSON     (可选) 已知的人物中文名/职业
  CU_SCENE      (可选) 已知的场景中文名
  CU_THEME      (可选) 已知的主题中文名
  CU_NARRATIVE  (可选) 已知的中文叙事
  CU_LIGHTING   (可选) 已知的光影
  CU_STYLE      (可选) 已知的风格
  CU_WIDTH/HEIGHT  (可选) 图像宽高
  CU_USER_INPUT    (可选) 用户原始输入

逻辑：
  如果任一可选元数据为空，本脚本将利用本地 LLM 代理自动解析并生成最贴切的中文元数据和故事叙事，
  并以单张渲染 meta 格式写回 JSON，支持动态 Caption 格式组装输出。""")
        sys.exit(0)

    meta_file = os.environ.get('CU_META_FILE', '').strip()
    if not meta_file:
        print("Error: CU_META_FILE environment variable not set", file=sys.stderr)
        sys.exit(1)

    prompt = os.environ.get('CU_PROMPT', '').strip()
    reply_id = os.environ.get('CU_REPLY_ID', '').strip()
    if reply_id.lower() in {'', 'none', 'null'}:
        reply_id = None

    provided = {
        "person": os.environ.get('CU_PERSON', '').strip(),
        "scene": os.environ.get('CU_SCENE', '').strip(),
        "theme": os.environ.get('CU_THEME', '').strip(),
        "narrative": os.environ.get('CU_NARRATIVE', '').strip(),
        "lighting": os.environ.get('CU_LIGHTING', '').strip(),
        "style": os.environ.get('CU_STYLE', '').strip()
    }

    # If any fields are missing, call LLM to infer
    missing_any = any(not val for val in provided.values())
    inferred = {}

    if missing_any and prompt:
        try:
            # Query LLM to parse/infer
            user_msg = f"Prompt to parse:\n{prompt}"
            messages = [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_msg}
            ]
            response_text = chat_completion(messages, max_tokens=1024)
            inferred = extract_json_object(response_text) or {}
        except Exception as e:
            print(f"LLM metadata parsing failed: {e}", file=sys.stderr)

    # Merge: provided values take absolute priority
    final = {}
    for key in ["person", "scene", "theme", "narrative", "lighting", "style"]:
        final[key] = provided[key] if provided[key] else inferred.get(key, "").strip()

    # Enforce CJK fallbacks to guarantee 100% Chinese caption and meta
    final["person"] = final["person"].strip()
    if not has_cjk(final["person"]):
        final["person"] = "神秘女孩"

    final["scene"] = final["scene"].strip()
    if not has_cjk(final["scene"]):
        final["scene"] = "神秘情境"

    final["theme"] = final["theme"].strip()
    if not has_cjk(final["theme"]):
        final["theme"] = "灵感直投"

    final["narrative"] = final["narrative"].strip()
    if not has_cjk(final["narrative"]):
        final["narrative"] = f"{final['person']}在{final['scene']}的魅力瞬间"

    final["lighting"] = final["lighting"].strip()
    if not has_cjk(final["lighting"]):
        final["lighting"] = "自然光影"

    final["style"] = final["style"].strip()
    if not has_cjk(final["style"]):
        final["style"] = "写实人像"

    # Build caption dynamically
    title_parts = [x for x in [final["person"], final["scene"], final["theme"]] if x]
    title = '🎬 ' + ' · '.join(title_parts) if title_parts else '🎬 灵感直投'

    quote_parts = [x for x in [final["narrative"], final["lighting"], final["style"]] if x]
    quote = '<blockquote>' + ' | '.join(quote_parts) + '</blockquote>' if quote_parts else ''

    caption = title
    if quote:
        caption += '\n\n' + quote
    caption += '\n\nSeed: {SEED} | {ELAPSED}分钟'

    # Build meta dict
    meta = {
        'card_id': os.environ.get('CU_CARD_ID', ''),
        'reply_id': reply_id,
        'person': final["person"],
        'scene': final["scene"],
        'theme': final["theme"],
        'narrative': final["narrative"],
        'lighting': final["lighting"],
        'style': final["style"],
        'width': int(os.environ.get('CU_WIDTH', '0') or '0') or None,
        'height': int(os.environ.get('CU_HEIGHT', '0') or '0') or None,
        'user_input': os.environ.get('CU_USER_INPUT', ''),
        'caption': caption
    }

    with open(meta_file, 'w', encoding='utf-8') as f:
        json.dump(meta, f, ensure_ascii=False)

if __name__ == "__main__":
    main()
