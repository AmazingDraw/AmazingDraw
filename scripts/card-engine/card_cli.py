#!/usr/bin/env python3
"""
统一 CLI 入口。

说明：
- single 独有命令：create / patch / options / present
- chain 独有命令：chain (带子选项 --resume / --count) / mend
- 共用命令：fill / render / check / submit / direct / featured / archive / record / search / progress / resolve / queue / doc

这里只合并入口层，不混淆 single / chain 的业务流程；
真实逻辑仍由 card_core.py 中各命令处理。

"""
import _path_bootstrap  # dist: native sys.path
import argparse
import sys
from pathlib import Path

from card_core import (
    CARDS_DIR,
    SLOT_RENDER_ORDER,
)
from card_config import load_validation_rules
from card_cli_commands import (
    cmd_archive,
    cmd_chain,
    cmd_check,
    cmd_create,
    cmd_direct,
    cmd_doc,
    cmd_featured,
    cmd_fill,
    cmd_mend,
    cmd_options,
    cmd_patch,
    cmd_present,
    cmd_progress,
    cmd_queue,
    cmd_record,
    cmd_render,
    cmd_resolve,
    cmd_search,
    cmd_submit,
)

SCRIPT_DIR = Path(__file__).resolve().parent
PROMPT_TEMPLATE_PATH = SCRIPT_DIR.parent.parent / "doc" / "PROMPT_TEMPLATE.md"
DRAW_GUIDE_PATH = SCRIPT_DIR.parent.parent / "doc" / "DRAW_GUIDE.md"

DOC_WARNING_TEXT = """
⚠️ [AI 必读契约]：
  在进行导演策划与槽位填充前，必须查阅相对路径下的核心文档（或使用 python3 card_cli.py doc <名称>）：
  1) 提示词装配手册: doc/PROMPT_TEMPLATE.md
  2) 绘图修改指南: doc/DRAW_GUIDE.md
  3) 高频报错避坑指南: doc/CHECK_PITFALLS.md
"""

CHAIN_DOC_WARNING_TEXT = """
⚠️ [AI 必读契约]：
  在进行导演策划与槽位填充前，必须查阅相对路径下的核心文档（或使用 python3 card_cli.py doc <名称>）：
  1) 提示词装配手册: doc/PROMPT_TEMPLATE.md
  2) 高频报错避坑指南: doc/CHECK_PITFALLS.md
"""


# ── single-only commands ──────────────────────────────────────────────────────
SINGLE_COMMANDS = {
    "create", "patch", "options", "present", "featured", "direct",
}

# ── chain-only commands ───────────────────────────────────────────────────────
def _get_aspect_help_text():
    from card_config import load_system_config
    cfg = load_system_config()
    presets = cfg.get("resolution_presets", {})
    v_w = presets.get("vertical", {}).get("width", 512)
    v_h = presets.get("vertical", {}).get("height", 768)
    h_w = presets.get("horizontal", {}).get("width", 768)
    h_h = presets.get("horizontal", {}).get("height", 512)
    sq = presets.get("square", {}).get("width", 640)
    w_w = presets.get("widescreen", {}).get("width", 1088)
    w_h = presets.get("widescreen", {}).get("height", 464)
    return f"常用画幅预设(当前配置)：portrait={v_w}x{v_h} landscape={h_w}x{h_h} square={sq}x{sq} widescreen={w_w}x{w_h}"

CHAIN_COMMANDS = {"chain"}

# ── shared commands ───────────────────────────────────────────────────────────
SHARED_COMMANDS = {
    "fill", "render", "check", "submit", "archive", "record",
    "search", "progress", "resolve", "queue", "doc", "mend",
}


# ── parser builders: shared ───────────────────────────────────────────────────
def add_shared_parsers(sub):
    """共用命令：single / chain 都可复用。"""
    sub.add_parser("progress", help="查看当前进度/健康状态")
    c_doc = sub.add_parser("doc", help="查阅提示词、绘图、避坑、命令速查或配置指南")
    c_doc.add_argument(
        "name",
        nargs="?",
        choices=["prompt", "draw", "pitfalls", "commands", "config"],
        default="prompt",
        help="文档类型：prompt / draw / pitfalls / commands / config（默认 prompt）",
    )

    c_search = sub.add_parser(
        "search",
        help="模糊搜索场景库/角色库中的预设 label 或 key",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
🚀 搜索预设命令 (Search Presets):
  - 搜索场景：python3 card_cli.py search --scene "教室"
  - 搜索角色：python3 card_cli.py search --person "jk"
  - 混合搜索：python3 card_cli.py search --scene "走廊" --person "ol"
"""
    )
    c_search.add_argument("--scene", help="按关键字搜索场景库 (如 '教室', '走廊')")
    c_search.add_argument("--person", help="按关键字搜索角色库/身份库 (如 '孕妇', 'jk')")

    c_resolve = sub.add_parser("resolve", help="resolver 联合解析，输出 fill-ready 字段")
    c_resolve.add_argument("--scene-library", default="general_scenes", help="场景库名")
    c_resolve.add_argument("--scene-id", default="", help="指定场景 id（精确查找）")
    c_resolve.add_argument("--include-tags", default="", help="必须包含的 tags")
    c_resolve.add_argument("--exclude-tags", default="", help="排除的 tags")
    c_resolve.add_argument("--exposure-focus", default="auto", help="裸露模式 upper/lower/both/half_nude/half_covered/none/auto")
    c_resolve.add_argument("--mood", default="", help="情绪关键词")

    c_queue = sub.add_parser(
        "queue",
        help="队列管理：查看状态/清空队列/健康检查/删除任务",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
🚀 队列管理命令 (Queue Management):
  - 查看状态：python3 card_cli.py queue status
  - 健康检查：python3 card_cli.py queue health
  - 清空队列：python3 card_cli.py queue clear [--force]
  - 按稳定任务 ID 删除：python3 card_cli.py queue remove --job-id JOB_ID
  - 删除指定排位任务：python3 card_cli.py queue remove --position N
  - 按唯一指纹删除任务：python3 card_cli.py queue remove --fingerprint HASH
"""
    )
    c_queue.add_argument("action", choices=["status", "health", "clear", "remove"], help="队列操作")
    c_queue.add_argument("--force", action="store_true", help="强制执行（用于 clear 命令，请极其谨慎使用且需二次确认）")
    c_queue.add_argument("--position", type=int, help="要删除的任务排队位置 (1-indexed)")
    c_queue.add_argument("--job-id", help="要删除的 QueueStore v2 稳定任务 ID（推荐）")
    c_queue.add_argument("--fingerprint", help="要删除的任务 SHA1 唯一指纹")

    # ── mend: 连抽手动修复 ──
    c_mend = sub.add_parser(
        "mend",
        help="连抽模式手动修复：单卡单字段修改 + 自动 recheck",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
🔧 连抽手动修复 (Manual Fix):
  - 修改字段：python3 card_cli.py mend --card <id> --set slots.clothing --value "xxx"
  - 预览修改：python3 card_cli.py mend --card <id> --set slots.clothing --value "xxx" --dry-run
  - 读取当前值：python3 card_cli.py mend --card <id> --get slots.clothing
  - 撤销上一步：python3 card_cli.py mend --card <id> --undo
  - 查看历史：python3 card_cli.py mend --card <id> --history
"""
    )
    c_mend.add_argument("--card", required=True, help="卡片 ID")
    c_mend.add_argument("--set", dest="field", help="字段路径，如 slots.clothing")
    c_mend.add_argument("--value", help="新值")
    c_mend.add_argument("--get", dest="get_field", help="读取字段当前值")
    c_mend.add_argument("--undo", action="store_true", help="撤销上一步修改")
    c_mend.add_argument("--history", action="store_true", help="查看最近修改记录")
    c_mend.add_argument("--dry-run", action="store_true", help="预览 diff，不写入")


PRIORITY_RULE_TEXT = """🎯 优先级规则：用户指定 > 库内命中 > 随机补全
* 基础属性（身份 / 体型 / 明星 / 场景 / 主题 / 视角 / 比例等）：用户指定则锁定（优先使用库项），未指定才随机。"""

PERSPECTIVE_TIPS_TEXT = """💡 技巧：自带视角特定场景精准命中
在 --scene 中包含以下关键词，可直接抽中全库原生视角特定机位：
  --scene "颜射视角"  -> 命中：诊室医生椅旁(颜射视角)、教室课桌旁(颜射视角)等
  --scene "后入视角"  -> 命中：器材室软垫(后入视角)、更衣室长凳旁(后入视角)等
  --scene "丝袜视角"  -> 命中：闺房床沿(丝袜视角)、浴室地砖(丝袜视角)等"""

CREATE_EPILOG = f"""
{DOC_WARNING_TEXT}

🏃 常规单卡交互流 (Normal Mode Workflow):
  R0. [可选检索] search   -> 模糊搜索场景库/角色库 (如 python3 card_cli.py search --scene 走廊)
  R1. create --user-input "用户原始要求"  -> 创建卡面骨架（--user-input 必传，落卡供约束解析）
  R2. 导演决策            -> AI 先深读骨架信息，再进行 8 维创意决策
  R3. fill+options      -> AI 用 fill 填导演及槽位字段 + options --auto 映射动态方向位
  R4. 渲染与展示          -> render 渲染生成 -> present --json 取结构化数据，AI 严格按 DRAW_GUIDE.md 格式输出
  R5. 交互修改循环        -> 依据用户指令进行 AI 动作响应（注：精修中统一使用 text_template 输出选项，出图时才使用 compact_template）：
      * 说「画」或「1」      => 先单独发骚话 → 再提交画图（使用 compact_template 终结展示）
      * 说「数字 2-8 / 9」   => 2-8 动态方向或 9 纹身固定位应用修改，随后 options --auto 轮转动态位并重新设计选项（使用 text_template）
      * 说「修改内容+数字」  => 先按文字优化，再应用数字方向并 options 轮转重新设计（使用 text_template）
      * 说「6」              => 检查：脚本检查 → AI检查 → 输出修正提示词
      * 说「61」             => 一键生成：检查 → 阻断则修正 / 全通则自动画
      * 数字组合 (如 27961) => 顺序执行多项修改并轮转（使用 text_template，除非含1则提交）
      * 说「换」或「0」      => 随机换全新场景重抽（使用 text_template）
  R6. 提交生成            -> check -> submit --confirm 确认提交 GPU 队列

"""


CHAIN_EPILOG = f"""
{CHAIN_DOC_WARNING_TEXT}

🏃 批量连抽导演流 (Chain Mode Workflow):
  C0. [可选检索] search   -> 模糊搜索场景库/角色库 (如 python3 card_cli.py search --person jk)
  C1. chain --count N --person 女初中生 --profile jc-shy --user-input "用户原始要求"  -> 创建 N 张卡骨架并返回 card_id（--person 锁身份，--profile 锁体型；--user-input 必传，落卡供约束解析）
  C2. 逐张决策             -> AI 先深读骨架信息，再逐张进行 8 维创意决策
  C3. 逐张一次 fill        -> 每张卡只用一次 fill（勿拆 --phase）：--json-file / --json 一次写齐 director+slots+elevation+theme_zh
  C4. 逐张 resume         -> 运行 python3 card_cli.py chain --resume <card_id> 自动进行 render -> check -> autofix -> submit --confirm
  C5. 修复 mend           -> check 失败时: python3 card_cli.py mend --card <id> --set <field> --value "<新值>" 修改字段，再回到 C4
  * 注：连抽模式为全自动连跑，中途不要停下来等待或询问指令。
  * 注：--phase 仅常规模式用；连抽一次 fill 完成，勿拆三次。
"""


def add_single_parsers(sub):
    """单卡模式独有命令。"""
    aspect_help = _get_aspect_help_text()

    c_create = sub.add_parser(
        "create",
        help="创建新卡面骨架",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=CREATE_EPILOG
    )
    c_create.add_argument("--mode", choices=["celebrity", "amateur"], default="amateur", help="默认为素人模式 amateur，没有明确要求禁止使用 celebrity 明星模式")
    c_create.add_argument("--scene", help="指定场景（跳过随机）")
    c_create.add_argument("--person", help="指定人物（明星中文名 / 身份职业如 OL、护士、大学生）。注意：严禁使用通用词「素人」，必须具体到职业/身份。")
    c_create.add_argument("--workflow", help="指定 workflow config")
    c_create.add_argument("--size", help="画幅，如 768x1024（优先级高于 --aspect）")
    c_create.add_argument("--aspect", choices=["portrait", "landscape", "square", "widescreen"], help=aspect_help)
    c_create.add_argument("--seed", type=int, help="固定 seed")
    c_create.add_argument("--profile", default="default", help="预设配置名（见 amateurs.json profiles；用户指定优先，未指定才随机）")
    c_create.add_argument("--user-input", help="用户原始要求（必传，落卡供约束解析）")
    c_create.add_argument("--bundle", nargs="?", const="auto", default=None, metavar="SECTIONS", help="启用场景词库参考（默认关闭）。不带值：智能加载纹身/宠物/道具/饰品四类词库常用章节；带值：按指定章节加载，格式同 cu-template-bundle.py --sections，如 --bundle \"tattoo:图案速查|皮肤融合,props:振动棒\"")

    c_fill = sub.add_parser(
        "fill",
        help="填充卡面槽位",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    c_fill.add_argument("--card", required=True, help="卡面 ID")
    c_fill.add_argument("--phase", choices=["director", "slots", "elevation"], default=None,
                        help="可选分阶段填（常规模式精细打磨）。连抽请勿使用：一次 --json/--json-file 写齐即可")
    c_fill.add_argument("--json-file", dest="json_file", help="结构化 fill JSON 文件")
    for slot in SLOT_RENDER_ORDER:
        c_fill.add_argument(f"--{slot.replace('_', '-')}", dest=slot, default=None)
    for d in [
        "intent", "exposure_mode", "style_recipe", "lighting_palette",
        "pose_direction", "makeup_direction", "expression_gaze",
        "focus_detail", "story_elevation",
    ]:
        c_fill.add_argument(f"--dir-{d.replace('_', '-')}", dest=f"dir_{d}", default=None)
    for d_zh in [
        "intent_zh", "pose_direction_zh", "makeup_direction_zh",
        "expression_gaze_zh", "focus_detail_zh",
    ]:
        c_fill.add_argument(f"--dir-{d_zh.replace('_', '-')}", dest=f"dir_{d_zh}", default=None)
    c_fill.add_argument("--theme-zh", dest="theme_zh", default=None, help="顶部展示用的中文主题短标签")
    # 门禁真会因为长度/语种打回，help 里不写清楚 AI 只能靠报错试出来，白白多跑几轮。
    # 数字一律从校验规则实时取，避免 help 与门禁各说各话。
    _vr = load_validation_rules()
    _story_zh_help = (
        f"中文叙事（门禁校验：必须为中文，长度 {_vr['min_story_chars']}-{_vr['max_story_chars']} 字，"
        f"容错区间 {_vr['min_story_tolerance']}-{_vr['max_story_tolerance']} 字，越界会被 fill 打回）"
    )
    c_fill.add_argument("--story-elevation-zh", dest="story_elevation_zh", default=None, help=_story_zh_help)
    c_fill.add_argument("--story-elevation-file", dest="story_elevation_file", default=None,
                        help=f"从文件读取中文叙事写入 story_elevation_zh，约束同 --story-elevation-zh")
    c_fill.add_argument("--lighting-palette-zh", dest="lighting_palette_zh", default=None, help="光影的中文展示文本")
    c_fill.add_argument("--style-recipe-zh", dest="style_recipe_zh", default=None, help="风格胶片的中文展示文本")
    c_fill.add_argument("--json", dest="json_text", default=None, help="结构化 fill JSON 字符串。按优先级：half_nude(半裸，保留服装结构 + 露点词) > upper(露上，下身补 lower body fully covered) > lower(露下，上身补 chest covered) > both(全裸)。不露场景：half_covered(半遮，擦边) > none(全包)。")

    c_patch = sub.add_parser("patch", help="局部修改卡面")
    c_patch.add_argument("--card", required=True)
    c_patch.add_argument("--direction", help="方向编号 0/1/6/9 或动态位 2/3/4/5/7/8")
    c_patch.add_argument("--user-input", help="组合指令，如 51 / 5 1 / 加大尺度 5 1")
    c_patch.add_argument("--set", help="字段路径如 slots.tattoo")
    c_patch.add_argument("--value", help="修改值（同值写入所有 target）")
    c_patch.add_argument("--intent", help="修改意图描述")
    c_patch.add_argument(
        "--targets-json",
        help=(
            "按 target 分别赋值；「裸露」方向必须同时提供 "
            "slots.clothing 与 director.exposure_mode"
        ),
    )
    c_patch.add_argument("--targets-file", help="按 target 分别赋值的 JSON 文件")

    OPTIONS_EPILOG = """
[AI 必须执行] options --auto 之后的强制步骤：

--auto 只完成动态方向抽签（随机决定 2,3,4,5,7,8 填哪些方向，9 纹身固定保留），不会写描述内容。
AI 必须在 --auto 之后立刻为每个动态方向（2/3/4/5/7/8）补写具体中文改法描述：

  card_cli.py patch --card <id> --set direction_descriptions.N --value "<具体中文改法>"

描述要求（对标 DRAW_GUIDE.md 选项示例）：
  ✅ 正确: "从四分之三背身回眸改成被堵在走廊死角的全正面，双手慌乱护着胸口，书包带滑到肘部，身体紧贴墙壁退无可退"
  ❌ 错误: "调整姿势" / "修改姿势" / 任何通用占位词

方向 9（纹身）的必须步骤：
  → 必须为方向 9（纹身）设计具体的修改方案（严禁偷懒使用“已有纹身/保持现状/重新设计”等占位词）。
  → 如果是首次生成：先运行词库工具设计具体图案，填入 slots 并更新方向 9 描述：
    python3 scripts/gpu-pipeline/cu-template-bundle.py --sections "tattoo:图案速查|皮肤融合|锁定表"
    card_cli.py fill --card <id> --tattoo "<英文具体纹身描述>"
    card_cli.py patch --card <id> --set direction_descriptions.9 --value "<具体中文描述（如：在锁骨下方设计一个极简的黑线描小蝴蝶纹身，翅膀边缘带着微红，汗湿后显得特别妖艳）>"
  → 如果是多轮交互：必须基于当前纹身，设计具体的替换/改变建议：
    card_cli.py patch --card <id> --set direction_descriptions.9 --value "从[当前图案]换成[具体新图案、位置、颜色、风格]"
"""
    c_options = sub.add_parser(
        "options",
        help="写入当前卡动态 option_map",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=OPTIONS_EPILOG,
    )
    c_options.add_argument("--card", required=True)
    c_options.add_argument("--file", help="JSON 文件路径")
    c_options.add_argument("--json", help="JSON 字符串")
    c_options.add_argument("--auto", action="store_true", help="从 18 方向池随机抽 6 个，自动生成 option_map")

    c_render = sub.add_parser("render", help="渲染卡面 → prompt/caption")
    c_render.add_argument("--card", required=True)

    c_check = sub.add_parser("check", help="双重校验卡面")
    c_check.add_argument("--card", required=True)

    c_submit = sub.add_parser("submit", help="提交到 GPU 队列")
    c_submit.add_argument("--card", required=True)
    c_submit.add_argument("--user-input", help="用户原始输入 / 组合指令")
    c_submit.add_argument("--confirm", action="store_true", help="确认提交（必须传）")
    c_submit.add_argument("--dry-run", action="store_true", help="模拟提交，仅输出最终构建的命令行，不进行实际入队渲染")

    c_record = sub.add_parser("record", help="保存抽卡记录")
    c_record.add_argument("--card", required=True)
    c_record.add_argument("--user-input", help="用户原始输入 / 组合指令")

    c_archive = sub.add_parser("archive", help="选择性存档到 Obsidian 灵感库")
    c_archive.add_argument("--card", required=True)

    PRESENT_EPILOG = """
[AI 操作规范] present 命令的正确使用方式：

首次展示 (R4):
  card_cli.py present --card <id> --json
  -> 输出结构化 JSON，AI 按以下字段处理：

  text_template    : 已拼装好的完整展示文本（含 __dirtytalk__ 占位、🎬摘要、
                     代码块、分割线、所有引用选项）。
                     AI 只需将 __dirtytalk__ 替换为自己写的中文骚话，原样输出。
                     在微调精修交互中，必须一直使用该模板输出选项列表，严禁截断。

  compact_template : 终结出图提交时用（骚话+摘要+prompt，不含选项）。
                     只有主人发送「画/1/61」正式提交生图时，才使用该模板输出给主人。

  options[N]       : 每个方向包含：
                     - display        展示给主人的中文标签（直接体现在 text_template 里）
                     - description    AI 之前写下的改法意图（本次修改主目标）
                     - targets        本次 patch 要修改的字段路径列表
                     - current_values 各 target 字段 of 当前英文值

  interaction_guide.how_to_patch   : AI 收到数字 N 时的完整执行流程，含双场景示例。
  interaction_guide.tattoo_workflow: 选项 9 的专属强制执行链路（mandatory=true）。

主人发送数字 2-8（patch 方向）或口头指令后 (R5 交互循环):

  Step 1 - 读 options[N].description/current_values 了解本次修改意图与当前英文值
  Step 2 - 生成英文新值（写进 targets-json）与中文改法描述（写进 direction_descriptions[N]）
           若 options[N].meaning=裸露，director.exposure_mode 必须写 upper/lower/both/half_nude/half_covered/none，
           并与 slots.clothing 的新值一致。
  Step 3 - 执行内容 patch（通过 --targets-json 传入）：
    card_cli.py patch --card <id> --direction N --targets-json '{"<target字段>": "<AI生成的英文新值>", ...}'
  Step 4 - 触发类别轮转：
    card_cli.py options --card <id> --auto
  Step 5 - 重新设计所有新维度的修改建议与新纹身描述（重中之重）：
    · 根据 Step 4 轮转出的新维度，结合当前卡片最新状态，设计全新的选项 2-8 修改建议以及选项 9（纹身，结合情境重新设计）的中文描述。
    · 一键写入最新的 direction_descriptions 字段中：
      card_cli.py fill --card <id> --json '{"direction_descriptions": {"2": "<新建议2>", "3": "<新建议3>", "4": "<新建议4>", "5": "<新建议5>", "7": "<新建议7>", "8": "<新建议8>", "9": "<新纹身建议9>"}}'
  Step 6 - render 重新编译:  card_cli.py render --card <id>
  Step 7 - 读新JSON:        card_cli.py present --card <id> --json
  Step 8 - 输出:            用新的 text_template，替换 __dirtytalk__ 后直接输出给主人。

  注：数字+主人详细描述（如 "2 姿势改成跪在地毯上，双手撑住椅子扶手，头发凌乱
      披下来挡住脸，只从侧面能看到乳房垂下的弧度"）：
      主人的中文描述直接作为 Step 2 的核心约束，等长转译写入 targets-json。

主人发送数字 9（纹身）后 — 必须执行，严禁跳过:

  Step 1 - 加载纹身词库:
    python3 scripts/gpu-pipeline/cu-template-bundle.py --sections "tattoo:图案速查|皮肤融合|锁定表"
  Step 2 - 设计纹身:    根据词库返回内容，结合 context.person 和 context.scene，用英文设计纹身（图案/位置/颜色/风格）
  Step 3 - 写入 slot:   card_cli.py fill --card <id> --tattoo "<英文纹身描述>"
  Step 4 - 更新描述:    card_cli.py patch --card <id> --set direction_descriptions.9 --value "<中文：图案+位置+颜色+风格>"
"""
    c_present = sub.add_parser(
        "present",
        help="展示模板生成器（常规模式 R4）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=PRESENT_EPILOG,
    )
    c_present.add_argument("--card", required=True)
    c_present.add_argument("--json", action="store_true", help="输出结构化 JSON（含 text_template / compact_template / interaction_guide）")
    c_present.add_argument("--reply-id", type=int, default=None, help="写入 delivery.reply_id")
    c_present.add_argument("--compact", action="store_true", help="修改后重展示：只输出完整上半段（骚话+摘要+prompt），不含选项")

    from card_config import load_system_config
    cfg = load_system_config()
    current_vault = cfg.get("obsidian_vault_dir", "~/Documents/ObsidianVault")
    
    c_featured = sub.add_parser(
        "featured",
        help="精选模式：随机读取 Obsidian 灵感库提示词直接渲染",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=f"""
🏃 精选模式流程 (Featured Mode Workflow):
  1. 自动扫描配置的 Obsidian 库（当前配置: {current_vault}/灵感库）下所有 .md 笔记
  2. 提取带有 [## 提示词] (或 prompt) 英文代码块及 [## 中文描述] 的精选笔记
  3. 随机抽取一个笔记，自动从文件名（以 · 分隔）中智能解析出人物、场景和主题
  4. 自动绕过常规卡片引擎槽位填充，初始化 workflow_mode="featured" 卡片，并自动提交至 GPU 队列

💡 提示：笔记命名格式规范应为：`场景·人物·主题.md`，例如：`浴室地砖·学妹·禁忌仰望.md`
"""
    )
    c_featured.add_argument("--width", type=int, help="手动指定生图宽度")
    c_featured.add_argument("--height", type=int, help="手动指定生图高度")
    c_featured.add_argument("--workflow", help="指定 workflow 配置文件别名")

    c_direct = sub.add_parser(
        "direct",
        help="直投模式：绕过卡片引擎，直接投递 raw prompt 提交到 GPU 队列",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
🏃 直投模式流程 (Direct-Draw Mode Workflow):
  当您不需要卡片引擎约束，希望直接将英文 Prompt 投递给 ComfyUI 时，可以使用 `direct` 子命令。
  注意：`--prompt` 为唯一技术必填项。为能生成完整的归档文件名及美观展示，推荐提供所有 6 个中文元数据参数（`--person`, `--scene`, `--theme`, `--narrative`, `--lighting`, `--style`）；若省略，系统会自动调用 LLM 提取。

  示例:
  $ python3 card_cli.py direct --prompt "raw prompt" --person "女秘书" --scene "和风户外" --theme "竹林大风" --narrative "风吹乱浴衣衣摆..." --lighting "竹林斑驳碎光" --style "日系胶片"
"""
    )
    c_direct.add_argument("--prompt", required=True, help="完整英文 prompt (唯一技术必填)")
    c_direct.add_argument("--person", help="(推荐提供，中文) 角色身份或演员中文名 (入队时自动绑定 LoRA)；省略时由 LLM 提取。严禁使用「素人」。")
    c_direct.add_argument("--scene", help="(推荐提供，中文) 场景中文位置关键词；省略时由 LLM 提取。")
    c_direct.add_argument("--theme", help="(推荐提供，中文) 主题分类；省略时由 LLM 提取。")
    c_direct.add_argument("--narrative", help="(推荐提供，中文) 中文长标题或场景叙事 (展示于卡片正文)；省略时由 LLM 提取。严禁包含「素人」。")
    c_direct.add_argument("--lighting", help="(推荐提供，中文) 光影描述；省略时由 LLM 提取。")
    c_direct.add_argument("--style", help="(推荐提供，中文) 画面艺术风格或胶片质感；省略时由 LLM 提取。")
    c_direct.add_argument("--lora", help="人物 LoRA 名字")
    c_direct.add_argument("--width", type=int, help="强制输出图像宽度")
    c_direct.add_argument("--height", type=int, help="强制输出图像高度")
    c_direct.add_argument("--workflow", help="强制指定 ComfyUI 工作流")
    c_direct.add_argument("--reply-id", type=int, help="Telegram 引用回复消息 ID")
    c_direct.add_argument("--user-input", help="用户原始输入")
    c_direct.add_argument("--dry-run", action="store_true", help="模拟提交，仅输出最终构建 of 命令行，不进行实际入队渲染")


# ── parser builders: chain-only ───────────────────────────────────────────────
def add_chain_parsers(sub):
    """连抽模式独有命令。"""
    aspect_help = _get_aspect_help_text()

    c_chain = sub.add_parser(
        "chain",
        help="连抽模式：创建卡骨架 / resume 已 fill 的卡",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=CHAIN_EPILOG
    )
    c_chain.add_argument("--mode", choices=["celebrity", "amateur"], default="amateur", help="模式（默认为素人模式 amateur，没有明确要求禁止使用 celebrity 明星模式）")
    c_chain.add_argument("--scene", help="指定场景（可选）")
    c_chain.add_argument("--person", help="指定人物（可选）。注意：严禁使用通用词「素人」，必须具体到职业/身份。")
    c_chain.add_argument("--profile", default="default", help="指定体型预设（可选，见 amateurs.json profiles，如 jk-big / jc-shy；用户指定优先，未指定才在该身份组内随机）")
    c_chain.add_argument("--count", type=int, default=1, help="创建卡数量（默认模式）")
    c_chain.add_argument("--resume", metavar="CARD_ID", help="已 fill 的卡 ID，直接走 render→check→autofix→submit")
    c_chain.add_argument("--dry-run", action="store_true", help="配合 --resume 使用：仅跑 render→check→autofix 全流程校验，不提交 GPU 队列（测试/审查用）")

    c_chain.add_argument("--user-input", help="用户原始要求（必传，落卡供约束解析）")
    c_chain.add_argument("--bundle", nargs="?", const="auto", default=None, metavar="SECTIONS", help="启用场景词库参考（默认关闭）。不带值：智能加载纹身/宠物/道具/饰品四类词库常用章节；带值：按指定章节加载，格式同 cu-template-bundle.py --sections，如 --bundle \"tattoo:图案速查|皮肤融合,props:振动棒\"")


# ── command dispatch ──────────────────────────────────────────────────────────
COMMANDS = {
    # single-only
    "create": cmd_create,
    "fill": cmd_fill,
    "patch": cmd_patch,
    "options": cmd_options,
    "render": cmd_render,
    "check": cmd_check,
    "submit": cmd_submit,
    "record": cmd_record,
    "archive": cmd_archive,
    "present": cmd_present,
    "featured": cmd_featured,
    "direct": cmd_direct,
    # chain-only
    "chain": cmd_chain,
    # shared
    "mend": cmd_mend,
    "progress": cmd_progress,
    "resolve": cmd_resolve,
    "queue": cmd_queue,
    "doc": cmd_doc,
    "search": cmd_search,
}


def build_parser(command_set, description):
    """按命令集合构建 parser。command_set 只控制入口暴露范围，不改变底层业务实现。"""
    p = argparse.ArgumentParser(
        description=description,
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=PRIORITY_RULE_TEXT + "\n\n" + PERSPECTIVE_TIPS_TEXT + """

🎮 抽卡控制台四大运行模式工作流 (Console Four Workflows):

  ⭐ [AI 契约] 主人未指定特定模式时，AI 应默认执行②批量连抽模式（chain 流程）。

  ① 常规单抽模式 (Normal Single Mode):
    $ python3 card_cli.py create [--person <角色>] [--scene <场景>]
    → 根据建卡骨架，AI导演深读并进行 8 维创意决策 
    → $ python3 card_cli.py fill --card <id> --json '{"subject":..., "director":..., "slots":..., "direction_descriptions":...}'
    → $ python3 card_cli.py options --card <id> --auto
    → $ python3 card_cli.py render --card <id> && python3 card_cli.py present --card <id>
    → 通过快捷数字或口头指令进行交互式微调修改（输入「1」或「画」提交出图）

  ② 批量连抽模式 (Chain Batch Mode):
    $ python3 card_cli.py chain --count <数量> [--person <角色>]
    → AI 导演逐张深读骨架 JSON，做 8 维创意决策
    → 逐张一次 fill 导入槽位（--json-file 一次写齐，勿拆 --phase）
    → $ python3 card_cli.py chain --resume <id> (自动 render -> check -> autofix -> submit)
    → check 失败时: $ python3 card_cli.py mend --card <id> --set <field> --value "<值>" 修改后回到 resume

  ③ 灵感精选模式 (Featured Inspiration Mode):
    $ python3 card_cli.py featured [--workflow <工作流>] [--width <宽>] [--height <高>]
    → 自动扫描 Obsidian 灵感库所有优秀笔记，随机抽取并智能解析
    → 绕过常规卡片引擎槽位填充，初始化特色 featured 卡片并自动一键提交至 GPU 队列

  ④ 英文直投模式 (Direct Raw Mode):
    $ python3 card_cli.py direct --prompt "<英文提示词>" --person "<中文人物>" --scene "<中文场景>" --theme "<中文主题>" --narrative "<中文叙事>" --lighting "<中文光影>" --style "<中文风格>"
    → 绕过卡片引擎所有的繁复校验，直接以 raw prompt 形式投递至 GPU 生图管道。`--prompt` 为唯一技术必填，但必须提供 6 个中文元数据参数以生成完整归档文件名。
"""
    )
    sub = p.add_subparsers(dest="command", required=True)

    if command_set & SINGLE_COMMANDS:
        add_single_parsers(sub)
    if command_set & CHAIN_COMMANDS:
        add_chain_parsers(sub)
    if command_set & SHARED_COMMANDS:
        add_shared_parsers(sub)
    return p


def build_unified_parser():
    return build_parser(
        SINGLE_COMMANDS | CHAIN_COMMANDS | SHARED_COMMANDS,
        "抽卡引擎统一 CLI（single / chain / shared）",
    )


def build_single_compat_parser():
    return build_parser(
        SINGLE_COMMANDS | SHARED_COMMANDS,
        "抽卡引擎 CLI（single 兼容入口）",
    )


def build_chain_compat_parser():
    return build_parser(
        CHAIN_COMMANDS | SHARED_COMMANDS,
        "抽卡引擎 CLI（chain 兼容入口）",
    )


def run_parsed_args(args, parser=None):
    CARDS_DIR.mkdir(parents=True, exist_ok=True)
    cmd = COMMANDS.get(args.command)
    if not cmd:
        if parser:
            parser.error(f"unknown command: {args.command}")
        raise SystemExit(f"unknown command: {args.command}")

    # ── 必传 --user-input 预检：仅 chain/create 且非 resume ──
    # 约束落卡依赖 user_constraints.raw（exposure override / 约束解析真相源）；
    # 不传则用户要求（如「只露逼」）无法生效。resume 走已 fill 卡，豁免。
    if args.command in ("chain", "create") and not getattr(args, "resume", None):
        user_input = str(getattr(args, "user_input", "") or "").strip()
        if not user_input:
            msg = "缺少 --user-input（用户原始要求必传，如「女高中生 3 张」「只露逼 户外」）"
            if parser:
                parser.error(msg)
            raise SystemExit(msg)

    return cmd(args)


def main(argv=None, parser_kind="unified"):
    argv = list(sys.argv[1:] if argv is None else argv)

    # 兼容旧写法：`card_cli.py single create ...`
    if parser_kind == "unified" and argv and argv[0] == "single":
        argv = argv[1:]

    if parser_kind == "single-compat":
        parser = build_single_compat_parser()
    elif parser_kind == "chain-compat":
        parser = build_chain_compat_parser()
    else:
        parser = build_unified_parser()

    args = parser.parse_args(argv)
    return run_parsed_args(args, parser=parser)


if __name__ == "__main__":
    main()
