#!/bin/bash
# ============================================
# 画面合理性检查脚本 - 输入数字6时自动运行
# 功能：检查提示词中的常见错误，确保不会犯物理/逻辑矛盾
# ============================================
#
# ⚠️  警告 ⚠️
# 禁止在检查的过程中修改脚本！！！
# 如发现误判，请先记录问题并向主人反馈，检查完成后再统一修复。
#
# 📋 文档同步（三处必须同时更新）：
#   1) CHECK_SCRIPT_GUIDE.md（完整规则说明）
#   2) CHECK_PITFALLS.md（高频避坑速查）
#   3) check_prompt.sh 脚本本身
# ⚠️ 任何规则的新增 / 删除 / 调整 / 编号变化，都必须三处同步；禁止只改脚本不改文档。
#
# ─── 扩展/修改规则（给 AI / 维护者）───────────────────────────
#
# 🔧 新增检查的三种模式：
#
#   【模式A：简单匹配】话题明确、单步 grep 即够
#     → 用 check_error()，插入对应章节最接近的位置
#     → 参数: pattern, description, fix, severity(ERROR|WARNING)
#
#   【模式B：复杂判断】需要多步逻辑（豁免 / 互斥 / 先排除后判断）
#     → 写裸 if-else，放到最相关章节内部，不要甩到文件末尾
#     → 变量名优先用 HAS_/NEEDS_/ALLOW_/BLOCK_ 前缀，注释写清判定目的
#     → ERRORS/WARNINGS 手动 ++，记得 echo "" 换行
#
#   【模式C：缺失检测】“有 A 但没有 B → 警告/错误”
#     → 写 if [ HAS_A ] && ! [ HAS_B ] 块
#     → 示例：§1 的乳房细节缺自然纹理词
#
# 🧭 新规则放置原则（强制）：
#   1. 先判断它属于哪类矛盾，再决定章节；禁止因为“懒得分类”就放到后面新开小节。
#   2. 现有 19 章优先复用；只有在无法归入任何现有章节时，才允许新增章节。
#   3. 新规则必须插入“语义最接近”的章节内部，而不是统一堆在章节末尾。
#   4. 改完脚本后，必须同步更新 CHECK_SCRIPT_GUIDE.md；高频/普遍坑再同步到 CHECK_PITFALLS.md。
#
# 🩹 跨段误杀修复指南：
#   ──────────────────────────────────────────────
#   问题：整段 prompt 由多个槽位拼接而成（场景+光影+着装+姿势+...），
#        宽泛的 .* 正则可能跨数百字匹配到不同槽位的词，造成误杀。
#
#   示例：prompt 开头 "pure white lace" + 中间 "no liquids" + 末尾 "pussy"
#         → white.*liquid.*pussy 跨整段匹配，误报「爱液呈白色」
#
#   解法：把 .* 替换为有限距离 {0,N}，限定匹配范围：
#     ❌ white.*liquid.*pussy
#     ✅ white.{0,40}liquid.{0,40}pussy
#
#   距离建议：
#   • 同槽位内词对 → {0,40}（如 sheer shirt → 40字内有 nipple）
#   • 相邻槽位内词对 → {0,80}（如 transparent → 80字内有 revealing）
#   • 否定表达 "no X" 里的 X 被误匹配 → 直接去掉否定词或用近义词（如 no wetness → no dampness）
#
#   过往修复记录：
#   • 2026-05-29 §2 透明布料: transparent.*revealing.*body → transparent.{0,80}revealing.{0,30}body
#   • 2026-05-29 §4 液体物理:  body_shape 改用 vulva + liquids 改 no dampness 规避 white.*liquid.*pussy
#   • 2026-05-29 §17 干湿发:  liquids 改 no dampness 规避 wet.*hair 跨段匹配
#   ──────────────────────────────────────────────

# 📦 章节职责速查：
#   §1   服装/裸露状态（含 1b 阴毛合理性）
#   §2   透明/穿透布料
#   §3   身体朝向/可见性
#   §4   液体物理
#   §5   光源一致性
#   §6   动作协调
#   §7   布料物理/穿着状态
#   §8   情绪与姿态一致性
#   §9   场景光源/时间
#   §10  镜子与反射物理一致性
#   §11  负面词 / 嘴部风险 / 面部高风险细节
#   §12  支撑与平衡
#   §13  肢体数量 / 归属 / 人数匹配
#   §14  动态与静态描述冲突（预留，不要乱塞别的规则）
#   §15  光影-形体一致性
#   §16  空间占位 / 尺寸比例
#   §17  姿势 + 服装/遮挡 + 构图机位的组合矛盾
#   §18  特写解剖 / 局部真实感
#   §19  纹身质量（融合词 / 颜色 / CJK 文字纹身手写）
#
# 🏷️ 规则编号规范：
#   统一使用“§章节-序号”，例如：§17-2、§11-1。
#   - 章节号 = 所属大章
#   - 序号 = 该章内的扩展规则序号
#   - 禁止重复占用编号，禁止继续使用旧的 Bxx / Wxx 漂移编号
#   - 若规则从一章迁到另一章，编号也必须一起改，并同步文档
#
# 🧪 测试：
#   修改后至少用一个正例 + 一个反例验证，再同步文档说明
#
# ============================================

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# 检查是否请求帮助
if [[ "${1:-}" == "-h" || "${1:-}" == "--help" || "${1:-}" == "help" ]]; then
    echo "🔍 画面物理/安全合理性门禁检查脚本 (check_prompt.sh)"
    echo "========================================="
    echo "用法:"
    echo "  $0 '<提示词内容>'"
    echo "  $0 <提示词文件路径>"
    echo ""
    echo "功能说明:"
    echo "  对 Stable Diffusion 提示词进行多达 19 个章节的物理、逻辑、透视、朝向及安全词冲突校验门禁。"
    echo "  如果提示词中含有低级物理冲突或违禁词，脚本会输出错误并以 exit code 1 拦截提交。"
    exit 0
fi

# 检查参数
if [ -z "$1" ]; then
    echo -e "${RED}错误：请提供提示词文件路径或直接输入提示词${NC}"
    echo "用法：$0 <提示词文件> 或 $0 '<提示词内容>'"
    exit 1
fi

# 读取输入
if [ -f "$1" ]; then
    PROMPT=$(cat "$1")
    INPUT_SOURCE="文件: $1"
else
    PROMPT="$1"
    INPUT_SOURCE="直接输入"
fi

echo "============================================"
echo "  🔍 画面合理性检查 (数字 6 触发)"
echo "============================================"
echo "输入来源: $INPUT_SOURCE"
echo "检查时间: $(date '+%Y-%m-%d %H:%M:%S')"
echo ""

# 初始化错误计数器
ERRORS=0
WARNINGS=0

# 检查函数
check_error() {
    local pattern="$1"
    local description="$2"
    local fix="$3"
    local severity="$4"  # ERROR 或 WARNING
    
    if echo "$PROMPT" | grep -qiE "$pattern"; then
        if [ "$severity" = "ERROR" ]; then
            echo -e "${RED}❌ [严重] $description${NC}"
            echo -e "${YELLOW}   发现: $(echo "$PROMPT" | grep -oiE "$pattern" | head -1)${NC}"
            echo -e "${GREEN}   修正: $fix${NC}"
            ERRORS=$((ERRORS + 1))
        else
            echo -e "${YELLOW}⚠️  [警告] $description${NC}"
            echo -e "${BLUE}   建议: $fix${NC}"
            WARNINGS=$((WARNINGS + 1))
        fi
        echo ""
    fi
}

# ── 视角矛盾检查（带误杀排除） ───────────────────
# check_angle_contradiction <角度关键词> <人脸方向> <误杀排除词> <错误描述> <修正建议>
# 逻辑：先检查角度关键词是否存在 → 再检查人脸方向是否存在 → 最后排除已知误杀模式
check_angle_contradiction() {
    local angle_pattern="$1"
    local face_pattern="$2"
    local false_positive="$3"
    local description="$4"
    local fix="$5"

    # Step 1: 角度关键词不存在 → 跳过
    if ! echo "$PROMPT" | grep -qiE "$angle_pattern"; then
        return
    fi
    # Step 2: 人脸方向不存在 → 跳过
    if ! echo "$PROMPT" | grep -qiE "$face_pattern"; then
        return
    fi
    # Step 3: 命中误杀排除词 → 跳过（如 overhead light / looking at lens）
    if echo "$PROMPT" | grep -qiE "$false_positive"; then
        return
    fi
    # Step 4: 真正的视角矛盾
    echo -e "${RED}❌ [严重] $description${NC}"
    echo -e "${GREEN}   修正: $fix${NC}"
    ERRORS=$((ERRORS + 1))
    echo ""
}

# ── 特殊空间/失重/水下流体环境豁免判定 ─────────────
# 判定是否为“失重/时间静止/奇幻空间/水下流体环境”等非自然物理或流体物理设定场景
# 如果是，将豁免部分“液体浮空”、“肢体无支撑悬空”、“衣物悬浮”等刚性物理规则。
# 注：水下场景（泳池/浴缸/温泉等）中气泡悬浮、液体悬浮、衣物漂浮、身体无支撑漂浮均为物理常态。
IS_SPECIAL_PHYSICS=0
if echo "$PROMPT" | grep -qiE "zero-gravity|zero gravity|weightless|microgravity|zero-g|time-space|special-time-space|honey-mist-space|special-honey-mist-space|silk-drape-space|special-silk-drape-space|cloud-space|special-cloud-space|prism-space|special-prism-space|space station|outer space|frozen in mid-air|frozen splash|frozen in time|amber mist|honey-colored|honey mist|viscous liquid|liquid mercury texture|translucent gel|crystalline abyss|giant floating bubbles|floating on.*cloud|hanging silk|silk drape|underwater|under water|submerged|pool water|swimming pool|hot spring|bath water|bathtub" ; then
    IS_SPECIAL_PHYSICS=1
fi

# 判定是否属于场景道具半透明背景（例如 special-silk-drape-space / 站在纱帘后）
IS_BACKGROUND_DRAPE_EXEMPT=0
if echo "$PROMPT" | grep -qiE "silk-drape-space|special-silk-drape-space|standing behind.*silk|translucent silk.*background|translucent silk drape|sheer curtain" ; then
    IS_BACKGROUND_DRAPE_EXEMPT=1
fi

# 判定是否为脚部特写/丝袜视角 feet-first POV 构图（低角度脚前透视，非后入视角）
IS_FEET_FIRST_POV=0
if echo "$PROMPT" | grep -qiE "feet-first POV|feet-first low-angle|feet in foreground|foot focus|feet\.first" ; then
    IS_FEET_FIRST_POV=1
fi

echo "📋 开始检查常见错误..."
echo ""

# ── 全局占位符残留检查（防裸 {clothing}/{liquids} 泄漏进 GPU prompt） ──
# perspective_scenes 等场景库的 scene_theme 会带 {clothing}/{liquids} 占位符，
# 渲染时必须被替换；若残留说明渲染链路有 bug，必须阻断，否则占位符会原样喂给生图模型。
if echo "$PROMPT" | grep -qE '\{[a-zA-Z_]+\}'; then
    LEFTOVER_PLACEHOLDERS=$(echo "$PROMPT" | grep -oE '\{[a-zA-Z_]+\}' | sort -u | tr '\n' ' ')
    echo -e "${RED}❌ [严重] 提示词残留未替换占位符: $LEFTOVER_PLACEHOLDERS${NC}"
    echo -e "${YELLOW}   发现: 场景模板占位符未在渲染时替换（如 {clothing}/{liquids}）${NC}"
    echo -e "${GREEN}   修正: 检查 card_rendering.py 的占位符替换逻辑（{clothing}/{liquids} 应全局替换）；确认 render 后无裸占位符${NC}"
    ERRORS=$((ERRORS + 1))
    echo ""
fi

# ============================================
# 1. 私处与内裤互斥性检查（严格规则）
# 本章处理“裸露状态是否自洽”：
# - 内裤/underwear 与 pussy/vulva 是否矛盾
# - 明确无内裤词是否可触发豁免
# - 裸露后乳房细节是否过于塑料感
# 新增规则示例：
# - 有 no bra + nipples visible，但又写 fully buttoned shirt → 放本章或 §7，优先看是否属于裸露状态矛盾
# - 有 bottomless + panties visible → 放本章
# ============================================
echo -e "${BLUE}━━ 1. 服装与裸露状态检查 ━━${NC}"
echo ""

# ── 豁免检查（优先级最高）───────────────────
# 方案2：明确无内裤的全局词出现 → 跳过整个检查
if echo "$PROMPT" | grep -qiE "bare from waist|bottomless|completely bare|nothing on from waist|no underwear|naked from waist|bare from neck to floor|lower half fully nude|fully exposed below the waist" ; then
    echo -e "${GREEN}✅ 豁免：明确无内裤词出现（bottomless/bare from waist/bare from neck to floor），跳过 panties 检查${NC}"
    echo ""
else
    # 方案1：扩大 sed 排除（兜底排除各种"内裤已移除"的变体）
    PROMPT_PANTIES_FIXED=$(echo "$PROMPT" | sed \
        -e 's/no panties//gi' \
        -e 's/without panties//gi' \
        -e 's/panties pulled//gi' \
        -e 's/panties removed//gi' \
        -e 's/panties aside//gi' \
        -e 's/panties down//gi' \
        -e 's/panties open//gi' \
        -e 's/panties rolled//gi' \
        -e 's/panties to one side//gi' \
        -e 's/panties slipped//gi' \
        -e 's/panties at the ankle//gi' \
        -e 's/panties around ankle//gi' \
        -e 's/panties around leg//gi' \
        -e 's/panties on one leg//gi' \
        -e 's/panties at knee//gi' \
        -e 's/panties tangled//gi' \
        -e 's/panties half off//gi' \
        -e 's/panties off body//gi' \
        -e 's/panties falling//gi' \
        -e 's/panties hanging//gi' \
        -e 's/panties bunched//gi' \
        -e 's/underwear off body//gi' \
    )

    if echo "$PROMPT_PANTIES_FIXED" | grep -qiE "\bpanties\b|\bunderwear\b" ; then
        if echo "$PROMPT_PANTIES_FIXED" | grep -qiE "\bpussy\b|\bvulva\b" ; then
            echo -e "${RED}❌ [严重] 内裤与私处同时出现（排除已移除词后） - AI会产生矛盾理解${NC}"
            echo -e "${YELLOW}   发现: $(echo "$PROMPT_PANTIES_FIXED" | grep -oiE "\bpanties\b|\bunderwear\b" | head -1) + $(echo "$PROMPT" | grep -oiE "\bpussy\b|\bvulva\b" | head -1)${NC}"
            echo -e "${GREEN}   修正方案1: 删除内裤描述，使用 'no panties, bottomless, pussy visible'${NC}"
            echo -e "${GREEN}   修正方案2: 删除私处描述，只保留内裤状态${NC}"
            ERRORS=$((ERRORS + 1))
            echo ""
        fi
    fi
fi

# 身体裸露细节要求：有乳头/乳晕暴露时必须搭配自然瑕疵词，否则 AI 画出塑料感乳房
HAS_BREAST_DETAIL=$(echo "$PROMPT" | grep -qiE "\b(nipple|areola|bare breast|exposed breast|bare nipples)\b" && echo 1 || echo 0)
if [ "$HAS_BREAST_DETAIL" = "1" ]; then
    if ! echo "$PROMPT" | grep -qiE "\b(areola texture|montgomery glands|montgomery|skin pores|visible pores|areola detail|natural areola|natural nipple|natural skin texture|slight asymmetry|asymmetrical areola|uneven areola|natural pigmentation|skin detail|realistic skin|bumpy areola|puffy areola|puffy nipple|small areola|large areola|wide areola|pale areola|dark areola|brown areola|pink-brown gradient|wrinkled areola|wrinkled nipple|inverted nipple|flat nipple|nipple pointing|nipple slightly higher|nipple slightly darker|freckle on areola|mole near nipple|underboob crease|natural gravity pull|breast with natural|asymmetrical breast|slightly sagging|skin fold|perky nipple|nipple with|tan areola|purplish-pink|light pink nipple|one nipple|color gradient|brown nipple|areola bump|areola edge|bumpy texture around)" ; then
        echo -e "${YELLOW}⚠️  [警告] §1-1 乳房/乳晕/乳头缺少自然瑕疵描写${NC}"
        echo -e "${BLUE}   当前乳房描写过于干净，AI 容易画出完美但缺乏真实感的乳房${NC}"
        echo -e "${BLUE}   建议：加 areola texture / montgomery glands / visible pores / slight areola asymmetry / natural skin texture${NC}"
        WARNINGS=$((WARNINGS + 1))
        echo ""
    fi
fi

# ============================================
# 1-2. 血管/静脉词检测
# 模型无法正确渲染裸血管词（veins），通常会变成蓝色染料状涂抹。
# 但 faint + translucent skin 上下文下可以自然呈现微血管纹理。
# 策略：先剔除安全血管模式（faint + translucent），再检测残余裸血管词。
# 同时检测 CJK 血管相关词（血管、静脉、青筋 等）。
# ============================================
echo -e "${BLUE}━━ 1-2. 血管/静脉词检测 ━━${NC}"
echo ""

# ── 先剔除安全血管模式：faint veins + translucent/thin skin 上下文 ──
# 这类写法能正确渲染为皮肤下微血管，不属于蓝色染料问题
PROMPT_VEIN_CHECK=$(echo "$PROMPT" | sed -E '
    s/faint (blue )?veins? (barely |subtly )?visible through (thin |soft |stretched |delicate |luminous |flawless |warm |dewy )?(translucent|porcelain|luminous|milky-white) skin across [a-zA-Z -]+//g
')

HAS_VEIN=$(echo "$PROMPT_VEIN_CHECK" | grep -qiE "\b(vein|veins|veiny|venous|vascular|blue vein|milk vein|milk veins|breast vein|chest vein|visible vein|prominent vein|vein network|veiny breast|veiny boob|veiny chest|veiny belly|veiny skin|veiny texture|surface vein|superficial vein|vein detail|vein detail breast|vein detail belly|vein map|vein tracing|vein visible on|blue vein network|greenish vein|blueish vein|vein through skin|vein under skin|subcutaneous vein|dilated vein|blue vein visible|blue veins)($|[^a-zA-Z]\b)" && echo 1 || echo 0)
HAS_VEIN_CJK=$(echo "$PROMPT" | grep -qiE "(血管|静脉|青筋|乳脉|孕脉|孕静脉)" && echo 1 || echo 0)

if [ "$HAS_VEIN" = "1" ] || [ "$HAS_VEIN_CJK" = "1" ]; then
    # 尝试定位具体问题词
    VEIN_MATCH=$(echo "$PROMPT" | grep -oiE "\b[^ ,.]*vein[^ ,.]*\b" 2>/dev/null | head -3 | tr '\n' ' ')
    VEIN_MATCH_CJK=$(echo "$PROMPT" | grep -oiE "(血管|静脉|青筋|乳脉|孕脉|孕静脉)" 2>/dev/null | head -3 | tr '\n' ' ')
    echo -e "${RED}❌ [严重] §1-2 血管/静脉词 — 裸血管词会导致蓝色染料涂抹${NC}"
    if [ -n "$VEIN_MATCH" ]; then
        echo -e "${RED}   发现血管词: $VEIN_MATCH${NC}"
    fi
    if [ -n "$VEIN_MATCH_CJK" ]; then
        echo -e "${RED}   发现血管词: $VEIN_MATCH_CJK${NC}"
    fi
    echo -e "${YELLOW}   后果：缺少 faint + translucent 上下文的血管词会被 AI 画成皮肤上涂抹蓝色颜料${NC}"
    echo -e "${GREEN}   修正：删除裸血管词，或改为 faint blue veins visible through translucent skin across breasts 安全模式${NC}"
    ERRORS=$((ERRORS + 1))
    echo ""
fi

# ============================================
# 1-3. 女警警服颜色样式检查
# 拒绝很土很丑的深蓝色警服，直接报错，并建议使用浅蓝色警服或其它性感款式。
# ============================================
HAS_COP=$(echo "$PROMPT" | grep -qiE "\b(police|cop|policewoman)\b|警服|女警" && echo 1 || echo 0)
HAS_DARK_BLUE_UNIFORM=$(echo "$PROMPT" | grep -qiE "\b(dark\s+blue|navy\s+blue|navy)\b.*\b(uniform|costume|shirt|attire|outfit|skirt)\b|\b(uniform|costume|shirt|attire|outfit|skirt)\b.*\b(dark\s+blue|navy\s+blue|navy)\b|深蓝色警服|深蓝警服|藏青色警服|藏青警服" && echo 1 || echo 0)

if [ "$HAS_COP" = "1" ] && [ "$HAS_DARK_BLUE_UNIFORM" = "1" ]; then
    echo -e "${RED}❌ [严重] §1-3 警服颜色校验失败 — 拒绝土气的深蓝色警服${NC}"
    echo -e "${YELLOW}   发现: $(echo "$PROMPT" | grep -oiE "\b(dark\s+blue|navy\s+blue|navy)\b.*\b(uniform|costume|shirt|attire|outfit|skirt)\b|\b(uniform|costume|shirt|attire|outfit|skirt)\b.*\b(dark\s+blue|navy\s+blue|navy)\b|深蓝色警服|深蓝警服|藏青色警服|藏青警服" | head -1)${NC}"
    echo -e "${GREEN}   修正: 建议使用：浅蓝色警服（例如 \"tight low-cut light blue police shirt and sexy white bodycon police skirt\" 即 紧身低胸浅蓝警服与白色包臀警裙，或者 \"sexy black latex cop bodysuit\" 即 性感乳胶黑色警服）。${NC}"
    ERRORS=$((ERRORS + 1))
    echo ""
else
    # ── 未指定颜色样式的普通警服检测 ──
    HAS_GENERIC_COP_UNIFORM=$(python3 - "$PROMPT" <<'PY'
import re, sys
prompt = sys.argv[1]
text = prompt.lower()

is_cop = any(w in text for w in ['police', 'cop', 'policewoman', '警服', '女警'])
if not is_cop:
    print(0)
    sys.exit(0)

has_generic = False
for m in re.finditer(r'\b(police|cop)\s+(uniform|costume|shirt|attire|outfit|skirt)\b', text):
    start = m.start()
    prefix = text[max(0, start-30):start]
    approved_en = ['light blue', 'light-blue', 'baby blue', 'sky blue', 'white', 'latex', 'vinyl', 'leather', 'shiny', 'pink', 'low-cut', 'tight', 'sexy', 'bodycon', 'form-fitting', 'open']
    if not any(w in prefix for w in approved_en):
        has_generic = True
        break

if not has_generic:
    for m in re.finditer(r'警服|警裙|警衣', prompt):
        start = m.start()
        prefix = prompt[max(0, start-10):start]
        approved_zh = ['浅蓝', '白色', '乳胶', '漆皮', '粉色', '低胸', '紧身', '包臀']
        if not any(w in prefix for w in approved_zh):
            has_generic = True
            break

print(1 if has_generic else 0)
PY
)

    if [ "$HAS_GENERIC_COP_UNIFORM" = "1" ]; then
        echo -e "${RED}❌ [严重] §1-3 警服颜色校验失败 — 必须显式指定好看的警服颜色/样式${NC}"
        echo -e "${YELLOW}   提示：警服没有显示指定颜色样式时，模型默认会画出很土很丑的深蓝色警服${NC}"
        echo -e "${GREEN}   修正: 建议使用：浅蓝色警服（例如 \"tight low-cut light blue police shirt and sexy white bodycon police skirt\" 即 紧身低胸浅蓝警服与白色包臀警裙，或者 \"sexy black latex cop bodysuit\" 即 性感乳胶黑色警服）。${NC}"
        ERRORS=$((ERRORS + 1))
        echo ""
    fi
fi

# ============================================
# 1b. 阴毛合理性检查
# 本子章只处理“阴毛是否在合理位置、是否能在当前姿势下被看见”：
# - 阴毛 + 闭腿/趴卧的可见性冲突
# - 阴毛与 stomach/belly/abdomen 的跨段误配
# - 私处特写时是否缺少位置限定词
# 新增规则示例：
# - 有 pubic hair + knees pressed together → 放这里
# - 有 bush + macro close-up 但没有 on mons pubis → 放这里
# ============================================
echo -e "${BLUE}━━ 1b. 阴毛合理性检查 ━━${NC}"
echo ""

# 阴毛关键词
HAS_PUBIC=$(echo "$PROMPT" | grep -qiE "\b(pubic hair|pubic|bush|bushy|mound|mons pubis|mons)\b" && echo 1 || echo 0)

if [ "$HAS_PUBIC" = "1" ]; then
    # 检查1：姿势是否可能遮挡私处（浓密阴毛可能仍可见，降为警告）
    POSE_COVERS=$(echo "$PROMPT" | grep -qiE "(thighs pressed together|legs squeezed tight|knees pressed together|sitting with legs fully crossed|modest closed posture|legs firmly closed|lying on stomach|lying face down|prone position|face down on)" && echo 1 || echo 0)
    if [ "$POSE_COVERS" = "1" ]; then
        # 如果阴毛描述含浓密词，降级为提示（浓密阴毛夹住也可见）
        THICK_BUSH=$(echo "$PROMPT" | grep -qiE "(thick|bushy|full bush|dense|abundant|wild|untrimmed|thick pubic|full dark)" && echo 1 || echo 0)
        if [ "$THICK_BUSH" = "1" ]; then
            echo -e "${YELLOW}⚠️  [警告] 姿势遮挡+浓密阴毛 — 浓密毛发夹住可能仍可见，但模型容易画错位置${NC}"
            echo -e "${BLUE}   建议：加 'on mons pubis' 明确位置，或确认姿势确实能露出阴毛${NC}"
            WARNINGS=$((WARNINGS + 1))
        else
            echo -e "${RED}❌ [严重] 姿势遮挡私处但描述了阴毛 — 模型会强行画出位置错误的阴毛${NC}"
            echo -e "${YELLOW}   阴毛在私处，如果姿势完全遮挡（闭腿/交叉），阴毛不可见，不该写入 prompt${NC}"
            echo -e "${GREEN}   修正：删除阴毛描述，或直接换姿势${NC}"
            ERRORS=$((ERRORS + 1))
        fi
        echo ""
    fi

    # 检查2：阴毛位置描述（stomach/belly 不是阴毛区域）
    WRONG_POS=$(python3 - "$PROMPT" <<'PY'
import re, sys
prompt = sys.argv[1].lower()
segments = [s.strip() for s in re.split(r',|\|', prompt) if s.strip()]
wrong = 0
for seg in segments:
    has_pubic = re.search(r'\b(pubic hair|bush|bushy)\b', seg)
    bad_pos = re.search(r'\b(stomach|belly|abdomen)\b', seg)
    safe_anchor = re.search(r'\bmons pubis\b|above pussy|pubic area|above vulva|on mound', seg)
    if has_pubic and bad_pos and not safe_anchor:
        # 豁免形如 "no pubic hair on belly" 的否定表达
        if re.search(r'\b(no|without|none|free of)\s+pubic\s+hair\b', seg):
            continue
        wrong = 1
        break
print(1 if wrong else 0)
PY
)
    if [ "$WRONG_POS" = "1" ]; then
        echo -e "${RED}❌ [严重] 阴毛位置描述错误 — stomach/belly 不是阴毛区域${NC}"
        echo -e "${YELLOW}   阴毛在 mons pubis（耻骨上方），不在 stomach/belly/abdomen${NC}"
        echo -e "${GREEN}   修正：阴毛用 'on mons pubis' 或 'above pussy' 描述位置${NC}"
        ERRORS=$((ERRORS + 1))
        echo ""
    fi

    # 检查3：阴毛 + 特写时必须有位置限定词
    HAS_MACRO=$(echo "$PROMPT" | grep -qiE "\b(macro|close.up|extreme close|detail shot|gynecological)\b" && echo 1 || echo 0)
    if [ "$HAS_MACRO" = "1" ]; then
        if ! echo "$PROMPT" | grep -qiE "mons pubis|above pussy|on mound|lower belly|above vulva|pubic area" ; then
            echo -e "${YELLOW}⚠️  [警告] 特写镜头下阴毛缺少位置限定 — 模型可能画错位置${NC}"
            echo -e "${BLUE}   建议：加 'on mons pubis' 或 'above pussy' 明确位置${NC}"
            WARNINGS=$((WARNINGS + 1))
            echo ""
        fi
    fi

    # 检查4：后入/背后视角+阴毛 → 必须有 on mons pubis 锚点（否则AI画到屁股上）
    HAS_REAR_VIEW=$(echo "$PROMPT" | grep -qiE "(from behind|rear view|doggy|bent over|face down|face-down|on all fours|rear angle)" && echo 1 || echo 0)
    if [ "$HAS_REAR_VIEW" = "1" ]; then
        if ! echo "$PROMPT" | grep -qiE "mons pubis|between spread thighs|visible from behind" ; then
            echo -e "${RED}❌ [严重] §1b-4 后入视角阴毛缺少锚点 — AI 会画到屁股上${NC}"
            echo -e "${YELLOW}   背后视角时 pubic hair 默认画在可见皮肤上 → 屁股${NC}"
            echo -e "${GREEN}   修正：加 'pubic hair on mons pubis visible between spread thighs from behind' + 否定词 'no pubic hair on buttocks'${NC}"
            ERRORS=$((ERRORS + 1))
            echo ""
        fi
    fi

    # 检查5：有 pubic hair 但没有 mons pubis 锚点 → 建议补（通用提醒）
    HAS_POS_ANCHOR=$(echo "$PROMPT" | grep -qiE "mons pubis|above pussy|on mound" && echo 1 || echo 0)
    if [ "$HAS_POS_ANCHOR" = "0" ]; then
        echo -e "${YELLOW}⚠️  [警告] §1b-5 逼毛缺少 mons pubis 锚点 — 易偏上画到 belly${NC}"
        echo -e "${BLUE}   建议：加 'on mons pubis centered just above pussy' + 否定词 'no pubic hair on belly'${NC}"
        WARNINGS=$((WARNINGS + 1))
        echo ""
    fi
fi

# ============================================
# 2. 透明布料检查
# 本章只处理“敏感部位是否通过布料穿透展示”：
# - sheer / see-through / transparent / visible through fabric
# - 透感材质是否仍穿在身上
# 新增规则示例：
# - lace bra + nipple visible through cloth → 放这里
# - silk robe open showing breasts（已脱体）→ 若加新豁免，也放这里
# ============================================
echo -e "${BLUE}━━ 2. 透明/穿透布料检查 ━━${NC}"
echo ""

check_error "sheer (shirt|dress|fabric|blouse|top|bra|lingerie|lace|cloth).{0,40}nipple|sheer (shirt|dress|fabric|blouse|top|bra|lingerie|lace|cloth).{0,40}revealing.{0,30}breast|sheer (shirt|dress|fabric|blouse|top|bra|lingerie|lace|cloth).{0,40}showing.{0,30}breast" \
    "透明布料(sheer)直接展示乳头/乳房 - 会导致伪影" \
    "使用 'shirt unbuttoned showing breasts' 或 'bra lifted exposing nipples'" \
    "ERROR"

check_error "see-through.{0,80}nipple|see-through.{0,80}showing.{0,30}breast|see-through.{0,80}revealing.{0,30}breast" \
    "穿透布料(see-through)展示乳头/乳房 - 会导致伪影" \
    "布料必须被移开才能展示，不能穿透可见" \
    "ERROR"

check_error "transparent.{0,80}showing.{0,30}nipple|transparent.{0,80}revealing.{0,30}breast" \
    "透明布料(transparent)穿透展示乳头/乳房" \
    "改用衣物解开/滑落的方式展示" \
    "ERROR"

check_error "(nipple|breast).{0,60}visible through.{0,30}(fabric|cloth|clothes|bra|shirt|top|dress)|visible through.{0,30}(fabric|cloth|clothes|bra|shirt|top|dress).{0,60}(nipple|breast)" \
    "透过布料可见乳头/乳房" \
    "布料遮挡则不可见，可见则布料必须被移开（仅针对乳头/乳房，丝袜/下身场景不受影响）" \
    "ERROR"

# 严格检查：仅当“透感材质”明确修饰衣物/布料，且同时出现乳房暴露时才拦截。
# 目标：避免 pink satin ribbon bow / satin choker / sheer curtain 这类非穿着上下文误伤。
# 下身/配件豁免（两层保障）：第1层=sheer简单检查中已移除stockings/panties等下身词，第2层=UPPER_ONLY_GARMENTS不含stockings/pantyhose/tights/socks/panties，杜绝下身词跨段误杀。
UPPER_ONLY_GARMENTS="(robe|gown|shirt|dress|fabric|blouse|top|bra|lingerie|cloth|mesh|garment|outfit|sleeve)"
TRANSLUCENT_GARMENT_PATTERN="\b(silk|satin|lace|translucent|sheer|see-through|transparent)\b[^,.;|\n]{0,48}\b${UPPER_ONLY_GARMENTS}\b|\b${UPPER_ONLY_GARMENTS}\b[^,.;|\n]{0,48}\b(silk|satin|lace|translucent|sheer|see-through|transparent)\b"
HAS_TRANSLUCENT_GARMENT=$(echo "$PROMPT" | grep -qiE "$TRANSLUCENT_GARMENT_PATTERN" && echo 1 || echo 0)
HAS_EXPOSED=$(echo "$PROMPT" | grep -qiE "\b(bare|exposed|showing)\b.*(breast|nipple)|(breast|nipple).*\b(bare|exposed|showing)\b|\b(one|left|right)\b.*\b(breast|nipple)\b" && echo 1 || echo 0)
if [ "$HAS_TRANSLUCENT_GARMENT" = "1" ] && [ "$HAS_EXPOSED" = "1" ] && [ "$IS_BACKGROUND_DRAPE_EXEMPT" = "0" ]; then
    # 排除：robe/gown 等已脱体衣物（silk robe open = 不是穿在身上）
    if echo "$PROMPT" | grep -qiE "(silk|satin|lace).*(robe|gown).*(open|fallen|pooled|removed)" ; then
        : # 合规：silk robe 已脱体
    elif echo "$PROMPT" | grep -qiE "(translucent|sheer|see-through|transparent).*(slipped off|hanging loose|pooled|fallen off|removed|draped|unbuttoned|lifted|pulled|fully exposed)|(slipped off|hanging loose|pooled|fallen off|removed|draped|unbuttoned|lifted|pulled|fully exposed).*(translucent|sheer|see-through|transparent)" ; then
        : # 合规：透明布料已脱体/滑落
    else
        echo -e "${RED}❌ [严重] §2-1 透明/薄纱布料遮盖乳头${NC}"
        echo -e "${YELLOW}   有乳头/乳房暴露时，透感材质必须明确属于衣物且已移开，否则会被拦截${NC}"
        echo -e "${GREEN}   修正：删除 silk/satin/sheer/transparent 等衣物材质词，或搭配 'robe open/slipped off' 说明已脱体${NC}"
        ERRORS=$((ERRORS + 1))
        echo ""
    fi
fi

# ── §2-2 隐式穿透：no bra + 薄白面料 + 奶头细节 ──
# 原理：当 "no bra" / "without bra" 出现时，若同时存在薄白面料衣物（camisole,
#       tank top, blouse, shirt 等）和奶头/乳房身体细节，则奶头物理上会透过面料
#       显现，与"衣物覆盖"矛盾。这类组合不会触发 §2-1（因为没有 sheer/transparent
#       等显式透感词），需要单独拦截。
# 豁免（仅认「衣物已移开/敞开」的文本证据；不按 exposure_mode 豁免）：
#   - unbuttoned / pulled down|up|aside|open / removed / slipped off / lifted 等
#   - hanging open|loose / fully|wide open / open front
#   - shirt open / open blouse 等「上身衣物 + open」（不用裸 \bopen\b，避免 open-back/open sides 误豁免）
#   - clothing 为空 → 不触发
HAS_NO_BRA=$(echo "$PROMPT" | grep -qiE "\bno\s+bra\b|\bwithout\s+bra\b|\bno\s+underwear\b" && echo 1 || echo 0)
# 薄白面料衣物词（与 body shape 中的 nipple 同时出现时，物理上必然透出）
THIN_FABRIC_GARMENTS="camisole|tank\s*top|spaghetti\s*strap|white\s*(blouse|shirt|top|tee)|thin\s*(white|fabric)|light\s*(fabric|material)"
# 上身可解扣/可敞开的衣物锚点（用于 open 邻近匹配）
S22_UPPER_GARMENTS="camisole|tank\.?top|blouse|shirt|top|tee"
# 移开/敞开状态（不含裸 open；open-back / open sides 不在此列）
S22_OPEN_STATE="unbuttoned|removed|pulled\s*(down|up|aside|open)|slipped\s*off|fallen|draped|lifted|hanging\s*(loose|open|wide\s*open)|wide\s*open|fully\s*open|completely\s*open|open\s+front|open\s+at\s+(the\s+)?front|open\s+collar"
HAS_THIN_FABRIC=$(echo "$PROMPT" | grep -qiE "\b(${THIN_FABRIC_GARMENTS})\b" && echo 1 || echo 0)
HAS_NIPPLE_DETAIL=$(echo "$PROMPT" | grep -qiE "\b(nipple|nipples|areola|areolae|puffy\s*nipple|hard\s*nipple|erect\s*nipple|pink\s*nipple)\b" && echo 1 || echo 0)
if [ "$HAS_NO_BRA" = "1" ] && [ "$HAS_THIN_FABRIC" = "1" ] && [ "$HAS_NIPPLE_DETAIL" = "1" ]; then
    # 豁免：衣物已明确脱体/移开（限制距离 ≤40 字符，防止跨槽位误匹配）
    if echo "$PROMPT" | grep -qiE "(${S22_UPPER_GARMENTS}).{0,40}(${S22_OPEN_STATE})" ; then
        : # 合规：衣物已移开
    elif echo "$PROMPT" | grep -qiE "(${S22_OPEN_STATE}).{0,40}(${S22_UPPER_GARMENTS})" ; then
        : # 合规：衣物已移开
    # 上身衣物 + open（shirt open / open white blouse）；排除 open-back / open sides 设计词
    # 注：macOS grep -E 不支持 (?!...) lookaround；open 与衣物之间仅允许常见颜色/版型修饰词
    elif echo "$PROMPT" | grep -qiE "\b(${S22_UPPER_GARMENTS})\s+open\b" \
        && ! echo "$PROMPT" | grep -qiE "\bopen[- ](back|sides?)\b|\bopen[[:space:]]+(back|sides?)\b" ; then
        : # 合规：shirt open / blouse open
    elif echo "$PROMPT" | grep -qiE "\bopen[[:space:]]+(white[[:space:]]+|oversized[[:space:]]+|thin[[:space:]]+|sheer[[:space:]]+|cream[[:space:]]+|loose[[:space:]]+|soft[[:space:]]+|linen[[:space:]]+){0,3}(${S22_UPPER_GARMENTS})\b" \
        && ! echo "$PROMPT" | grep -qiE "\bopen[- ](back|sides?)\b|\bopen[[:space:]]+(back|sides?)\b" ; then
        : # 合规：open shirt / open white blouse
    else
        echo -e "${RED}❌ [严重] §2-2 无内衣+薄白面料隐式穿透乳头${NC}"
        echo -e "${YELLOW}   'no bra' + 薄白面料(camisole/tank top/blouse/shirt) + 奶头细节 → 奶头物理上会透过面料显露${NC}"
        echo -e "${GREEN}   修正：(1) 删除 no bra，改为 'bra visible under thin fabric' 或直接去掉 no bra 保留衣物；${NC}"
        echo -e "${GREEN}          (2) 改用 'shirt unbuttoned / shirt open / blouse hanging open' 明确衣物已移开；${NC}"
        echo -e "${GREEN}          (3) 删除 body_shape 中的奶头细节（保留体态描述即可）${NC}"
        ERRORS=$((ERRORS + 1))
        echo ""
    fi
fi

# ── §2-3 Skin-toned 贴身衣物隐式穿透 ──
# 原理：skin-toned / nude / beige 的贴身衣物（slip dress / leotard / bodysuit 等）面料
#       极薄且与肤色融合，AI 渲染时极易将 nipple/areola 细节穿透面料显示。即使没有
#       sheer/transparent 等显式透感词，物理上也必然穿透。
# 豁免：仅认「衣物已移开/前开」的文本证据；不按 exposure_mode 豁免；clothing 为空不触发。
SKIN_TONED_GARMENTS="slip\s*dress|leotard|bodysuit|singlet|ballet\s*leotard|dance\s*leotard|camisole|tank\s*top"
SKIN_TONED_COLOR="skin.toned|nude|beige|flesh.colored|porcelain|cream|champagne"
S23_GARMENTS="slip\s*dress|leotard|bodysuit|singlet|camisole|tank\.?top"
S23_OPEN_STATE="unbuttoned|removed|pulled\s*(down|up|aside|open)|slipped\s*off|fallen|draped|lifted|hanging\s*(loose|open|wide\s*open)|wide\s*open|fully\s*open|completely\s*open|open\s+front|open\s+at\s+(the\s+)?front"
if echo "$PROMPT" | grep -qiE "\b(${SKIN_TONED_GARMENTS})\b" ; then
    if echo "$PROMPT" | grep -qiE "\b(${SKIN_TONED_COLOR})\b" ; then
        HAS_S23_NIPPLE=$(echo "$PROMPT" | grep -qiE "\b(nipple|nipples|areola|areolae|puffy\s*nipple|hard\s*nipple|erect\s*nipple|pink\s*nipple)\b" && echo 1 || echo 0)
        if [ "$HAS_S23_NIPPLE" = "1" ]; then
            # 豁免：衣物已明确脱体/前开（排除 open-back / open sides）
            if echo "$PROMPT" | grep -qiE "(${S23_GARMENTS}).{0,40}(${S23_OPEN_STATE})" ; then
                : # 合规：衣物已移开
            elif echo "$PROMPT" | grep -qiE "(${S23_OPEN_STATE}).{0,40}(${S23_GARMENTS})" ; then
                : # 合规：衣物已移开
            elif echo "$PROMPT" | grep -qiE "(${S23_GARMENTS}).{0,40}open\s+(front|and)" ; then
                : # 合规：衣物前部打开/脱开
            elif echo "$PROMPT" | grep -qiE "open\s+(front|and).{0,40}(${S23_GARMENTS})" ; then
                : # 合规：衣物已移开
            else
                echo -e "${RED}❌ [严重] §2-3 Skin-toned贴身衣物隐式穿透乳头${NC}"
                echo -e "${YELLOW}   'skin-toned/nude' + 贴身衣物(slip dress/leotard/bodysuit) + 奶头细节 → AI必穿透${NC}"
                echo -e "${GREEN}   修正：(1) (推荐) 删除 body_shape 中的奶头/乳晕细节（如 nipples/areola），只保留胸部轮廓；${NC}"
                echo -e "${GREEN}          (2) 将衣服颜色从 skin-toned/nude 改为 white/black 或其他显色；${NC}"
                echo -e "${GREEN}          (3) 改用 'loose fit' / 'relaxed fit' 降低贴身感（注意：leotard/bodysuit 等连体舞蹈服不建议改宽松，应直接采用建议 1）。${NC}"
                ERRORS=$((ERRORS + 1))
                echo ""
            fi
        fi
    fi
fi

# ── §2-4 无扣薄内搭假敞开 + 乳头细节（穿模）──
# 原理：camisole / tank top / sports bra / crop top 等无扣薄内搭，写
#       hanging open / slipped off one shoulder / partially visible 时模型常仍
#       把衣物画在胸上，若同时 body_shape 强注 nipple/areola → 奶头穿出衣服。
#       不依赖 no bra；不按 exposure_mode 豁免。
# 有扣衣（shirt/blouse/cardigan）不走本条，仍由 §2-2 管。
# 豁免（硬露点或真脱体，弱敞开一律不算）：
#   - topless / bare breasts / breasts exposed / nipples|areolae visible / breasts visible
#   - 无扣衣锚点 40 字内：pulled (down|aside|up) / removed / below|under breasts / cup pulled
S24_STRAP_GARMENTS="camisole|tank\s*top|tank\.?top|sports\s*bra|crop\s*top|spaghetti\s*strap"
S24_HARD_EXPOSE="\btopless\b|\bbare\s+breasts?\b|\bbreasts?\s+exposed\b|\bnipples?\s+visible\b|\bareolae?\s+visible\b|\bbreasts?\s+visible\b"
S24_TRUE_OFF="pulled\s*(down|aside|up)|removed|below\s+breasts?|under\s+breasts?|cup\s+pulled"
HAS_S24_STRAP=$(echo "$PROMPT" | grep -qiE "\b(${S24_STRAP_GARMENTS})\b" && echo 1 || echo 0)
HAS_S24_NIPPLE=$(echo "$PROMPT" | grep -qiE "\b(nipple|nipples|areola|areolae|puffy\s*nipple|hard\s*nipple|erect\s*nipple|pink\s*nipple)\b" && echo 1 || echo 0)
if [ "$HAS_S24_STRAP" = "1" ] && [ "$HAS_S24_NIPPLE" = "1" ]; then
    if echo "$PROMPT" | grep -qiE "${S24_HARD_EXPOSE}" ; then
        : # 合规：硬露点信号
    elif echo "$PROMPT" | grep -qiE "(${S24_STRAP_GARMENTS}).{0,40}(${S24_TRUE_OFF})" ; then
        : # 合规：无扣衣真脱体
    elif echo "$PROMPT" | grep -qiE "(${S24_TRUE_OFF}).{0,40}(${S24_STRAP_GARMENTS})" ; then
        : # 合规：真脱体在衣物前
    else
        echo -e "${RED}❌ [严重] §2-4 无扣薄内搭假敞开导致乳头穿模${NC}"
        echo -e "${YELLOW}   camisole/tank/sports bra/crop top 仍在身 + 奶头/乳晕细节，但缺少硬露点或真脱体${NC}"
        echo -e "${YELLOW}   （hanging open / slipped off one shoulder / partially visible 不算豁免）${NC}"
        echo -e "${GREEN}   修正：(1) 删除 body_shape 中的 nipple/areola 细节；或${NC}"
        echo -e "${GREEN}          (2) 改成真露上：topless / bare breasts / nipples visible；或${NC}"
        echo -e "${GREEN}          (3) 无扣衣写清真脱体：camisole pulled down|aside / removed / below breasts${NC}"
        ERRORS=$((ERRORS + 1))
        echo ""
    fi
fi

# ============================================
# 2-AI. AI 语义检查（在有布料+身体细节或丝袜与姿势冲突等可疑组合时调用）
# 非阻塞：超时或 API 不可用时静默跳过
# ============================================
VALIDATION_SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VALIDATION_CONFIG_FILE="${VALIDATION_SCRIPT_DIR}/../config.json"
VALIDATION_WORKSPACE=$(python3 -c "import json, os; print(os.path.expanduser(json.load(open('${VALIDATION_CONFIG_FILE}')).get('openclaw_workspace_dir') or '~/.openclaw/workspace'))")
AI_CHECKER="${VALIDATION_SCRIPT_DIR}/ai_check_prompt.py"
if [ -f "$AI_CHECKER" ]; then
    # 快速预检：是否有布料词+身体细节，或存在丝袜/裸腿/腿部姿势冲突？
    IS_CLOTHING_BREAST=0
    if echo "$PROMPT" | grep -qiE "(fitted|tight|undershirt|camisole|tank top|bra|vest|pushed up by|shirt|blouse|sweater|dress|robe|uniform|undershirt)" && echo "$PROMPT" | grep -qiE "(nipple|areola|areolae|breast|chest)" ; then
        IS_CLOTHING_BREAST=1
    fi

    IS_LEG_CONFLICT=0
    if echo "$PROMPT" | grep -qiE "(stockings?|pantyhose|tights|socks?|thigh-highs?|legwear|fishnets?)" && echo "$PROMPT" | grep -qiE "(bare\s+(legs?|thighs?|feet|foot)|naked\s+(legs?|feet|foot))" ; then
        IS_LEG_CONFLICT=1
    elif [ $(echo "$PROMPT" | grep -o -iE "(stockings?|pantyhose|tights|socks?|thigh-highs?|legwear|fishnets?)" | wc -l) -ge 2 ]; then
        IS_LEG_CONFLICT=1
    elif echo "$PROMPT" | grep -qiE "(crossed|bent|kneeling)" && echo "$PROMPT" | grep -qiE "(straight|spread|extended)" ; then
        IS_LEG_CONFLICT=1
    fi

    IS_OTHER_CONFLICT=0
    if echo "$PROMPT" | grep -qiE "(buried|turned\s+away|facing\s+the\s+wall|face\s+covered|face\s+hidden|eyes?\s+closed|closed\s+eyes?|blindfolded)" && echo "$PROMPT" | grep -qiE "(looking\s+(at|directly\s+at)\s+(the\s+)?(camera|viewer)|locking\s+eyes|eye\s+contact)" ; then
        IS_OTHER_CONFLICT=1
    elif echo "$PROMPT" | grep -qiE "(underwater|submerged|swimming\s+under)" && echo "$PROMPT" | grep -qiE "(lit\s+candle|burning|candlelight|matchstick)" ; then
        IS_OTHER_CONFLICT=1
    elif echo "$PROMPT" | grep -qiE "(midday|noon|bright\s+sunlight|sunlight\s+streaming)" && echo "$PROMPT" | grep -qiE "(dark\s+night|pitch\s+black|neon\s+night|nighttime)" ; then
        IS_OTHER_CONFLICT=1
    elif echo "$PROMPT" | grep -qiE "(sweater|coat|jacket|hoodie|parka|bodysuit|catsuit|jumpsuit)" && echo "$PROMPT" | grep -qiE "(navel|belly|stomach|midriff|bare|exposed|naked|skin)" ; then
        # bodysuit/catsuit check
        IS_OTHER_CONFLICT=1
    elif echo "$PROMPT" | grep -qiE "(bottomless|bare[[:space:]]+from[[:space:]]+(the[[:space:]]+)?waist|crotch[[:space:]]+fully[[:space:]]+exposed|lower[[:space:]]+half[[:space:]]+fully[[:space:]]+nude)" && echo "$PROMPT" | grep -qiE "(crop([[:space:]]|-)?top|cropped[[:space:]]+(white[[:space:]]+|black[[:space:]]+|school[[:space:]]+|sailor[[:space:]]+)?(shirt|blouse|t-shirt|tee|sweater|hoodie|jacket))" ; then
        # bottomless + crop/cropped 上装：衣长语义交 AI
        IS_OTHER_CONFLICT=1
    elif echo "$PROMPT" | grep -qiE "(bottomless|bare[[:space:]]+from[[:space:]]+(the[[:space:]]+)?waist|crotch[[:space:]]+fully[[:space:]]+exposed)" && echo "$PROMPT" | grep -qiE "(shirt|blouse|sweater|hoodie|jacket|coat|uniform|cardigan|blazer)" && echo "$PROMPT" | grep -qiE "(exposed[[:space:]]+navel|bare[[:space:]]+(belly|midriff|navel)|exposed[[:space:]]+midriff)" && ! echo "$PROMPT" | grep -qiE "(hem[[:space:]]+covering|covering[[:space:]]+(the[[:space:]]+)?(navel|midriff)|hem[[:space:]]+(at|reaching))" ; then
        # bottomless + 有下摆上装 + 显式露腹且无衣长锚点
        IS_OTHER_CONFLICT=1
    elif echo "$PROMPT" | grep -qiE "(tied\s+behind|hands\s+tied|bound|restrained|shackled|hugging|arms?\s+wrapped|hands?\s+clasped|hands?\s+folded)" && echo "$PROMPT" | grep -qiE "(holding|gripping|carrying|clutching|bracing|supporting)" ; then
        IS_OTHER_CONFLICT=1
    elif echo "$PROMPT" | grep -qiE "(sitting|lying|kneeling|knees?\s+bent|seated)" && echo "$PROMPT" | grep -qiE "(standing|running|walking|jogging|leaping|jumping)" ; then
        IS_OTHER_CONFLICT=1
    fi

    if [ $IS_CLOTHING_BREAST -eq 1 ] || [ $IS_LEG_CONFLICT -eq 1 ] || [ $IS_OTHER_CONFLICT -eq 1 ]; then
        # stderr 单独收：LLM fail-open 告警不能被 2>/dev/null 吞掉
        AI_ERR_FILE=$(mktemp)
        AI_RESULT=$(echo "$PROMPT" | python3 "$AI_CHECKER" 2>"$AI_ERR_FILE")
        if [ -s "$AI_ERR_FILE" ]; then
            while IFS= read -r _ai_err_line || [ -n "$_ai_err_line" ]; do
                [ -n "$_ai_err_line" ] && echo -e "${YELLOW}${_ai_err_line}${NC}"
            done < "$AI_ERR_FILE"
        fi
        rm -f "$AI_ERR_FILE"
        if [ -z "$AI_RESULT" ]; then
            AI_RESULT='{"issue":false}'
        fi
        AI_ISSUE=$(echo "$AI_RESULT" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('issue',False))" 2>/dev/null || echo "False")
        AI_WARN=$(echo "$AI_RESULT" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('warning','') or '')" 2>/dev/null || echo "")
        if [ -n "$AI_WARN" ] && [ "$AI_ISSUE" != "True" ]; then
            echo -e "${YELLOW}⚠️  [提示] §2-AI 语义层 fail-open：$AI_WARN${NC}"
            echo ""
        fi
        if [ "$AI_ISSUE" = "True" ]; then
            AI_TYPE=$(echo "$AI_RESULT" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('check_type',''))" 2>/dev/null || echo "")
            AI_DETAIL=$(echo "$AI_RESULT" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('detail','语义矛盾'))" 2>/dev/null || echo "语义矛盾")
            echo -e "${RED}❌ [严重] §2-AI 语义矛盾 (AI语义检查 - $AI_TYPE)${NC}"
            echo -e "${YELLOW}   $AI_DETAIL${NC}"
            if [ "$AI_TYPE" = "丝袜及姿势去重" ] || [ "$AI_TYPE" = "丝袜与腿部姿势矛盾" ]; then
                echo -e "${GREEN}   修正：请检查并合并丝袜与裸腿设置，或清理相互冲突的腿部姿势词汇（如同时 crossed 与 straight）。${NC}"
            elif [ "$AI_TYPE" = "视线与面部遮挡矛盾" ]; then
                echo -e "${GREEN}   修正：如果面部被遮挡/埋起，请删除 looking at camera 等直视镜头的描述。${NC}"
            elif [ "$AI_TYPE" = "物理与光影矛盾" ]; then
                echo -e "${GREEN}   修正：请检查是否有水下点火，或者正午与深夜并存的光影冲突，并清理对应描述。${NC}"
            elif [ "$AI_TYPE" = "布料穿透与衣物版型冲突" ]; then
                echo -e "${GREEN}   修正：布料穿透 → 删乳头细节或明确衣服已移开；长款衣物下露肚脐 → 优先删 exposed navel/bare midriff，或写 hem lifted（bottomless/只露下时不要改成 crop top）；bottomless+衬衫却写成 crop/cropped → 改为自然衣长（hem covering navel and midriff）。${NC}"
            elif [ "$AI_TYPE" = "多余肢体与动作限制" ]; then
                echo -e "${GREEN}   修正：被绑缚的角色手部无法自由拿取物品或撑住表面，请删除对应的手部自由动作描述。${NC}"
            else
                echo -e "${GREEN}   修正：请检查并清理语义冲突描述。${NC}"
            fi
            ERRORS=$((ERRORS + 1))
            echo ""
        fi
    fi
fi

# ============================================
# 3. 身体朝向与可见性检查
# 本章只处理“身体朝向 / 机位方向 / 可见部位”是否彼此一致：
# - 背对镜头却看到正面
# - 正面视角却展示背面特征
# - 俯视/仰视与脸部朝向冲突
# 新增规则示例：
# - from behind + nipples visible → 放这里
# - top view + looking up at camera → 放这里
# ============================================
echo -e "${BLUE}━━ 3. 身体朝向一致性检查 ━━${NC}"
echo ""

# 镜面反射场景检测（背对相机+镜子映出正面是合法构图）
_IS_MIRROR_SCENE=$(echo "$PROMPT" | grep -qiE "mirror.{0,60}(reflect|reflection|showing)|reflection.{0,40}mirror|mirror.{0,40}back.{0,40}(reflect|show)" && echo 1 || echo 0)

if [ "$_IS_MIRROR_SCENE" = "0" ]; then
    check_error "back.*to.*camera.*showing.*vulva|back view.*exposed.*front" \
        "背对镜头却展示正面私处 - 方向矛盾" \
        "背对时只显示臀部，展示正面需转身" \
        "ERROR"

    check_error "facing away.*breasts visible|back turned.*nipples showing" \
        "背对却显示正面乳房 - 方向矛盾" \
        "调整身体朝向或可见部位" \
        "ERROR"
fi

# 视角-姿势互斥检查
check_error "facing camera.*showing.*\b(ass|buttocks)\b|front view.*\b(butt|buttocks)\b|kneeling.*facing.*showing.*back" \
    "正面视角却展示背面特征 - 视角矛盾" \
    "正面只能看到正面，背面需转身或侧视" \
    "ERROR"

# §3-1: 背面视角却看到正面脸部（排除光源/场景方向误判）
# from behind the shoji screen / from behind buildings / from behind the curtain 等描述场景而非身体朝向
_SCENE_FROM_BEHIND=$(echo "$PROMPT" | grep -qiE "from behind (the |a )?(shoji|screen|curtain|door|window|glass|buildings|wall|fence|tree|pillar|column|partition|divider|lamp|lantern|light|mirror|desk|counter|bar|stage|podium|lectern|board|shelf|cabinet|bookcase|wardrobe|closet|bed|sofa|chair|bench|table|rack|hanger|pole|pillar|column)" && echo 1 || echo 0)
# feet-first POV（丝袜视角脚前透视）豁免，低角度从脚向身体拍，非后入视角
if [ "$IS_FEET_FIRST_POV" = "1" ]; then
    _SCENE_FROM_BEHIND=1
fi
# 镜面反射场景豁免：背对相机+镜子映出正面是合法构图
# 镜面反射场景豁免已在上方 §3 开头统一检测
if [ "$_IS_MIRROR_SCENE" = "1" ]; then
    _SCENE_FROM_BEHIND=1
fi
if [ "$_SCENE_FROM_BEHIND" = "0" ]; then
    check_error "back view.*face visible|from behind.*looking.*at camera|from behind.*looking.*camera|from behind.*face toward|from behind.*pleading.*eyes" \
        "背面视角却看到正面脸部 - 视角矛盾" \
        "背对只能看到背部，正面需转身" \
        "ERROR"
fi

# 背面视角+看镜头（纯转头可接受，但上半身不能扭）
check_error "from behind.*(looking|face).*(camera|lens)|back view.*looking.*(camera|lens)" \
    "§3-2 后入视角+看镜头 — 转头看镜头可以，但确保上半身没有扭过来正面露奶" \
    "修正：用 'looking back over shoulder' / 'glancing back' / 'head turned to look back' 描述转头,同时确保上半身朝向为 from behind" \
    "WARNING"

# ERROR: from behind + looking at camera + chest/breast exposed = 上半身扭过来 = 回眸折腰（上下半身朝向矛盾）
# 精准放宽：后入视角仅允许单侧/侧面乳房及乳头曝光（如 'one breast visible from the side' / 'side breast' / 'one nipple visible'），严禁出现双乳或乳沟等正面词。
ORIG_PROMPT="$PROMPT"
PROMPT=$(python3 -c '
import sys, re
prompt = sys.argv[1]
pattern = r"\b(one breast visible from (the )?side|side breast (exposed|visible|bare|open)|one nipple visible|one areola visible|one collarbone visible)\b"
print(re.sub(pattern, "", prompt, flags=re.IGNORECASE))
' "$PROMPT")
check_error "from behind.*(breast|nipple|areola|areolae|chest|collarbone|cleavage)s?.*\b(exposed|visible|open|bare)\b" \
    "§3-3 回眸折腰（上下半身朝向矛盾）— 后入视角+露奶 = 上半身正面,物理不可能" \
    "修正：后入视角仅允许单侧/侧面乳房及乳头曝光（如 'one breast visible from the side' / 'side breast' / 'one nipple visible'），严禁出现双乳（breasts）、双乳头（nipples）或乳沟（cleavage）等正面曝光词。" \
    "ERROR"
PROMPT="$ORIG_PROMPT"


# §3-4: from behind + bottomless exposure
# ⚠️ Mode B（精确豁免）：
#   - 纯背面（无 camera/lens/face 引用）→ 豁免（有效构图）
#   - 有镜头/脸部引用 + from behind + 暴露 → ERROR（物理矛盾）
#   - from behind 描述光源方向（如 from behind buildings / light from behind）→ 豁免
HAS_REAR_BOTTOMLESS=$(echo "$PROMPT" | grep -qiE "from behind.*(bottomless|bare from waist|pussy visible)" && echo 1 || echo 0)
# feet-first POV（丝袜视角脚前透视）豁免——低角度从脚向身体拍，非后入视角
if [ "$IS_FEET_FIRST_POV" = "1" ]; then
    HAS_REAR_BOTTOMLESS=0
fi
if [ "$HAS_REAR_BOTTOMLESS" = "1" ]; then
    # 排除光源方向误判：from behind buildings / light from behind / 等
    IS_LIGHT_CONTEXT=$(echo "$PROMPT" | grep -qiE "(light|sunlight|sunset|moonlight|buildings|sky|window|lamp|lantern|glow).{0,20}from behind|from behind.{0,20}(light|sun|sky|buildings|window|lantern|glow)" && echo 1 || echo 0)
    if [ "$IS_LIGHT_CONTEXT" = "1" ]; then
        # from behind 描述的是光源方向，不是身体朝向 → 豁免
        :
    else
        # 检查是否有镜头/脸部/看镜头引用（仅这些才是真正的朝向矛盾）
        HAS_CAMERA_OR_FACE=$(echo "$PROMPT" | grep -qiE "\b(camera|lens|surveillance|CCTV)\b|looking (at|over shoulder|back).{0,20}(camera|viewer|lens)|(face|eyes).{0,20}(visible|looking|staring|toward camera)|(staring|gazing).{0,20}(at|toward).{0,20}(camera|viewer|lens)" && echo 1 || echo 0)
        if [ "$HAS_CAMERA_OR_FACE" = "1" ]; then
            ERRORS=$((ERRORS + 1))
            echo -e "${RED}❌ [严重] §3-4 回眸折腰（上下半身朝向矛盾）— 后入视角+露逼+看镜头 = 下半身背面+上半身正面${NC}"
            echo -e "${GREEN}   修正：要么 pure behind(删看镜头+删脸部描述)，要么侧身视角${NC}"
            echo ""
        fi
        # else: pure behind（无镜头/脸部引用），有效构图 → 放行
    fi
fi

# 俯拍(top/overhead) + 脸朝下 = 脸被头顶遮住 → 矛盾
# 误杀排除：overhead light/fixture（灯光词）+ looking down toward lens/camera（正确朝向）
check_angle_contradiction \
    "(top[ _-]*view|overhead)" \
    "(face looking down|head (?:bowed|lowered|hanging)|eyes (?:down|fixed on floor)|gaze down)" \
    "(overhead[ _-]*(light|fixture|lamp|bulb|ceiling)|looking down[ _-]*(toward|at|into)[ _-]*(the[ _-]*)?(lens|camera))" \
    "俯视角度应该拍到仰视的脸，现在脸朝下会被头顶遮住 - 视角矛盾" \
    "俯拍时人物应抬头看镜头；物/宠物/镜头角度的 looking 描述不算"

# 仰拍(bottom/from below) + 脸朝上 = 脸被下巴遮住 → 矛盾
# 误杀排除：from below light（灯光词）+ looking up toward lens/camera（正确朝向）
check_angle_contradiction \
    "(bottom[ _-]*view|from below|low angle)" \
    "(face looking up|head (?:tilted up|raised|lifted)|eyes (?:up|fixed on ceiling)|gaze up)" \
    "(from below[ _-]*(light|fixture|lamp)|looking up[ _-]*(toward|at|into)[ _-]*(the[ _-]*)?(lens|camera))" \
    "仰视角度应该拍到俯视的脸，现在脸朝上会被下巴遮住 - 视角矛盾" \
    "仰拍时人物应低头看镜头；物/宠物/镜头角度的 looking 描述不算"

# ============================================
# 4. 液体物理检查
# 本章处理“液体颜色 / 流向 / 附着状态”是否符合基本物理：
# - 爱液 / 口水 / 精液 / 泡沫
# 新增规则示例：
# - drool floating in air → 放这里
# - white vaginal fluid → 放这里
# ============================================
echo -e "${BLUE}━━ 4. 液体物理检查 ━━${NC}"
echo ""

check_error "white.{0,40}liquid.{0,40}pussy|white.{0,40}fluid.{0,40}vagina" \
    "爱液呈白色 - 生理错误" \
    "爱液应为透明/无色/清澈 (clear/transparent)" \
    "ERROR"

if [ "$IS_SPECIAL_PHYSICS" -eq 0 ]; then
    check_error "liquid.*flowing.*up|fluid.*going.*upward" \
        "液体向上流动 - 违反重力" \
        "液体必须向下流动 (flowing down/dripping)" \
        "ERROR"
fi

# 4-3. 悬浮检查 (非失重环境)
if [ "$IS_SPECIAL_PHYSICS" -eq 0 ]; then
    check_error "floating.{0,60}(semen|cum|drool|saliva|liquid|fluid|piss|urine)|suspended.{0,60}liquid" \
        "§4-3 液体悬浮 — 物理错误" \
        "液体应在皮肤表面或向下滴落 (on skin, dripping down, following body contour)" \
        "ERROR"
fi

# 4-4. 口水 (Saliva) 质地检查
check_error "white.*saliva|milky.*drool|white.*drool|opaque.*saliva" \
    "§4-4 口水颜色错误 — 生理矛盾" \
    "口水应为透明，禁止出现白色或乳白色。正确词参考：clear saliva string, transparent drool thread, water-clear spit trail, glistening on chin, saliva catching light as thin bright line" \
    "ERROR"


# 4-5. 精液 (Cum/Semen) 位置与颜色检查
check_error "\b(cum|semen|ejaculate|sperm|cumshot)\b.{0,20}\b(forehead|brow|hairline|temple)\b|\b(forehead|brow|hairline|temple)\b.{0,20}\b(cum|semen|ejaculate|sperm|cumshot)\b" \
    "§4-6 精液在额头/发际线 — 美学干扰" \
    "精液应避开额头高位，分布在 cheekbones / neck / breasts / collarbone" \
    "ERROR"

check_error "cum.*(pure white|snow white|solid white|paint-like|opaque white|white mask)" \
    "§4-7 精液颜色过白或不透明 — 看起来像油漆" \
    "精液应为半透明/乳白 (translucent milky white, opalescent sheen)" \
    "ERROR"

# §4-8 精液缺少皮肤交互 — 看起来像贴纸浮在表面
if echo "$PROMPT" | grep -qiE '\b(cum|semen|ejaculate|sperm|cumshot)\b' ; then
    if ! echo "$PROMPT" | grep -qiE '(conforming to skin|settling into|glistening on skin|trailing down|clinging to|skin contour|draped over|following the contour|against the skin|adhering to|spread across.*skin|streak down.*face|drip down.*chin|coating.*skin|pooling in.*cleft|beading on|trickling down|rolling down|seeping into|glazing over.*skin)' ; then
        echo -e "${RED}❌ [严重] §4-8 精液缺少皮肤交互 — 看起来像贴纸浮在表面${NC}"
        echo -e "${GREEN}   修正: 添加皮肤交互词 conforming to skin contour / trailing down skin / glistening on skin / clinging to cheek / trickling down jawline${NC}"
        ERRORS=$((ERRORS + 1))
        echo ""
    fi
fi

# §4-9 液体缺少高级质感修饰词 — 容易产生死白油漆感
if echo "$PROMPT" | grep -qiE '\b(cum|semen|ejaculate|sperm|cumshot)\b' ; then
    if ! echo "$PROMPT" | grep -qiE '(translucent|semi-translucent|viscous|glistening|opalescent sheen|dewy wet|fluid settling|thin film coating)' ; then
        echo -e "${RED}❌ [严重] §4-9 液体缺少高级质感修饰词 — 容易产生死白油漆感${NC}"
        echo -e "${GREEN}   修正: 添加半透明/黏稠质感词，如 semi-translucent, viscous 或 glistening 等修饰词${NC}"
        ERRORS=$((ERRORS + 1))
        echo ""
    fi
fi

# §4-10 液体使用高风险喷射动作 — 易导致物理崩坏
if echo "$PROMPT" | grep -qiE '\b(cum|semen|ejaculate|sperm|cumshot)\b' ; then
    DYNAMIC_SPRAY=$(echo "$PROMPT" | grep -oiE '\b(cumshot|shooting|spraying|splattering|splash|splashed|fountain|gushing|blast|sprayed)\b')
    if [ -n "$DYNAMIC_SPRAY" ]; then
        echo -e "${RED}❌ [严重] §4-10 液体使用高风险喷射动作 — 易导致物理崩坏${NC}"
        echo -e "${YELLOW}   发现: $DYNAMIC_SPRAY${NC}"
        echo -e "${GREEN}   修正: 移除飞溅/喷射动作，改为静态附着或流淌，如 glistening on skin, trailing down, trickling down${NC}"
        ERRORS=$((ERRORS + 1))
        echo ""
    fi
fi

# 泡沫检查（浴室/洗澡场景）
if [ "$IS_SPECIAL_PHYSICS" -eq 0 ]; then
    check_error "foam.*floating.*air|bubbles.*floating.*no.*water|soap.*foam.*suspended" \
        "泡沫悬浮在空中 - 物理错误" \
        "泡沫应附着在水面或皮肤表面，不能凭空漂浮" \
        "ERROR"
fi

check_error "foam.*on.*dry.*skin|bubbles.*without.*water" \
    "泡沫出现在干燥皮肤上 - 逻辑矛盾" \
    "泡沫只应在湿润/有水的地方 (wet skin with foam, soapy water)" \
    "ERROR"

# ============================================
# 5. 光源一致性检查
# 本章只处理“高光方向是否自洽”的轻量检查。
# 更复杂的阴影/形体问题放 §15，不放这里。
# 新增规则示例：
# - left rim light + right face highlight → 放这里
# ============================================
echo -e "${BLUE}━━ 5. 光源一致性检查 ━━${NC}"
echo ""

check_error "left.*light.*right.*highlight|right.*light.*left.*highlight" \
    "光源方向矛盾 - 左右都有高光" \
    "统一光源方向，所有高光在同一侧" \
    "WARNING"

# ============================================
# 6. 动作协调性检查
# 本章只处理“同一只手 / 同一身体动作”是否逻辑冲突：
# - 一手两用
# - 支撑手还在做别的动作
# - 束缚状态下却自由触摸
# 新增规则示例：
# - left hand holding skirt and left hand touching breast → 放这里
# ============================================
echo -e "${BLUE}━━ 6. 动作协调性检查 ━━${NC}"
echo ""

check_error "one hand.*unbuttoning.*same hand.*holding|left hand.*two things" \
    "一只手同时做两件事 - 动作矛盾" \
    "明确分配动作给两只手" \
    "WARNING"

if [ "$IS_SPECIAL_PHYSICS" -eq 0 ]; then
    check_error "levitating|floating.*no support|suspended.*without" \
        "悬浮姿势无支撑 - 物理错误" \
        "添加支撑点 (hand on wall/kneeling/leaning)" \
        "ERROR"
fi

# 手部动作逻辑检查
check_error "one hand.*holding.*and.*unbuttoning|single hand.*two actions" \
    "一只手同时做两件事 - 动作矛盾" \
    "明确分配：左手做A，右手做B" \
    "ERROR"

check_error "hand.*supporting.*body.*while.*touching" \
    "支撑手同时做其他动作 - 动作矛盾" \
    "支撑手不能同时抚摸/握持" \
    "ERROR"

check_error "bound.*hands.*free movement|tied.*hands.*touching" \
    "手被束缚却能自由活动 - 逻辑矛盾" \
    "束缚=活动受限，不能触摸" \
    "ERROR"

# 接触点有效性检查（预留）



# ============================================
# 7. 布料物理检查
# 本章处理“衣物本身的物理状态”是否合理：
# - 衣物悬浮
# - 湿发/湿衣的物理表现
# - 脱衣动作与当前穿着状态是否一致
# 新增规则示例：
# - soaked shirt but fluffy and floating → 放这里
# - no panties but underwear visible → 放这里
# ============================================
echo -e "${BLUE}━━ 7. 布料物理检查 ━━${NC}"
echo ""

if [ "$IS_SPECIAL_PHYSICS" -eq 0 ]; then
    check_error "clothes.*floating.*air|fabric.*suspended|garment.*midair" \
        "衣物悬浮在空中 - 物理错误" \
        "衣物必须有支撑点或自然垂落" \
        "ERROR"
fi

# 乳头穿透布料（检查"穿透"类描述，排除已移开布料的情况）
# 仅当提到透过布料可见时才报错，如果已说明布料移开则不报
if echo "$PROMPT" | grep -qiE "nipple.{0,60}(through|see-through|sheer).{0,60}fabric|nipple.{0,60}visible.{0,60}through|nipples.{0,60}showing.{0,60}through" ; then
    # 检查是否已说明布料移开
    if ! echo "$PROMPT" | grep -qiE "(unbuttoned|open|slipping off|falling off|lifted|pulled|removed|bare|fully exposed|completely open)"; then
        echo -e "${RED}❌ [严重] 乳头穿透布料可见 - 伪影风险${NC}"
        echo -e "${YELLOW}   发现: 乳头透过布料可见${NC}"
        echo -e "${GREEN}   修正: 移开布料: unbuttoned/slipping off/lifted/completely open 才能显示，不能穿透${NC}"
        ERRORS=$((ERRORS + 1))
        echo ""
    fi
fi

# see-through / sheer 透明布料展示乳头（仅当衣物仍穿在身上时）
if echo "$PROMPT" | grep -qiE "see-through.*nipple|sheer (shirt|dress|fabric|blouse|top|bra|panties|lingerie|lace|cloth).*nipple|transparent.*nipple" ; then
    if ! echo "$PROMPT" | grep -qiE "(unbuttoned|open|slipping off|falling off|lifted|pulled|removed|bare|fully exposed|completely open)"; then
        echo -e "${RED}❌ [严重] 透明布料穿透展示乳头 - 伪影风险${NC}"
        echo -e "${YELLOW}   发现: 透明布料穿透展示乳头${NC}"
        echo -e "${GREEN}   修正: 使用 'shirt unbuttoned showing breasts' 或 'bra lifted exposing nipples'${NC}"
        ERRORS=$((ERRORS + 1))
        echo ""
    fi
fi

# §7-4 无扣衣物强行解扣：运动背心/文胸/短袖等没有纽扣，写 unbuttoned 会引发 AI 绘图的布料逻辑穿透冲突，导致乳头直接穿透织物
# 注意：裸 \bbra\b 会误伤 "no bra / without bra + blouse unbuttoned"；先匹配明确无扣衣物，再对 bra 做否定剥离后二次判断。
if echo "$PROMPT" | grep -qiE "\b(sports\s+top|sports\s+bra|crop\s+top|tank\s+top|t-shirt|tshirt|bikini\s+top)\b.{0,30}\bunbuttoned\b|\bunbuttoned\b.{0,30}\b(sports\s+top|sports\s+bra|crop\s+top|tank\s+top|t-shirt|tshirt|bikini\s+top)\b" ; then
    echo -e "${RED}❌ [严重] §7-4 无扣衣物强行解扣 — 逻辑冲突伪影风险${NC}"
    echo -e "${YELLOW}   发现: 无扣衣物 + unbuttoned${NC}"
    echo -e "${GREEN}   修正: 运动背心/运动文胸/短袖/内衣没有纽扣，请勿使用 unbuttoned。建议改为 pulled down (拉下)、pulled up (拉起) 或 removed (脱下) 配合 exposed 描述，例如 sports top pulled down exposing breasts${NC}"
    ERRORS=$((ERRORS + 1))
    echo ""
elif echo "$PROMPT" | grep -qiE "\bbra\b.{0,30}\bunbuttoned\b|\bunbuttoned\b.{0,30}\bbra\b" ; then
    # 剥离 no bra / without bra 后再看是否仍有 bra+unbuttoned（真·文胸解扣）
    # 注：macOS sed 对 \b 与 /I 支持差，用字符类 + 大小写展开
    S74_STRIPPED=$(echo "$PROMPT" | sed -E 's/(no|without|No|Without|NO|WITHOUT)[[:space:]]+[Bb][Rr][Aa]/ /g')
    if echo "$S74_STRIPPED" | grep -qiE "\bbra\b.{0,30}\bunbuttoned\b|\bunbuttoned\b.{0,30}\bbra\b" ; then
        echo -e "${RED}❌ [严重] §7-4 无扣衣物强行解扣 — 逻辑冲突伪影风险${NC}"
        echo -e "${YELLOW}   发现: bra + unbuttoned${NC}"
        echo -e "${GREEN}   修正: 文胸没有纽扣，请勿使用 unbuttoned。建议改为 bra pulled down / bra pushed aside / bra removed${NC}"
        ERRORS=$((ERRORS + 1))
        echo ""
    fi
fi



check_error "wet.*hair.*fluffy|wet hair.*voluminous" \
    "湿发蓬松 - 物理错误" \
    "湿发应贴紧皮肤 (wet hair clinging to skin)" \
    "WARNING"

# 服装-动作-状态一致性检查
check_error "undressing.*but.*fully.*clothed|removing.*but.*wearing" \
    "脱衣动作与穿着状态矛盾" \
    "动作进展与状态必须一致" \
    "ERROR"

check_error "no.*panties.*but.*panties.*visible|without.*panties.*but.*panties.*showing|no.*underwear.*but.*underwear.*visible" \
    "未穿内裤却可见内裤 - 状态矛盾" \
    "状态描述与视觉呈现必须一致（注意：no panties + showing pussy 是合法的，不是矛盾）" \
    "ERROR"

check_error "tight.*clothes.*loose.*folds|loose.*clothes.*tight.*fit" \
    "服装松紧状态矛盾" \
    "紧身衣贴身，宽松衣才有大褶皱" \
    "WARNING"

check_error "wet.*clothes.*dry.*look|soaked.*but.*fluffy" \
    "湿衣服却呈现干燥状态 - 物理错误" \
    "湿衣服应贴身、有垂坠感" \
    "WARNING"

# ============================================
# 8. 情绪一致性检查
# 本章只处理“表情 / 情绪 / 身体姿态”是否在同一叙事频率上。
# 不处理嘴部具体结构风险，那是 §11。
# 新增规则示例：
# - crying happily while body fully relaxed in pain scene → 放这里
# ============================================
echo -e "${BLUE}━━ 8. 情绪与姿态一致性检查 ━━${NC}"
echo ""

check_error "enjoying.*stiff.*body|pleasure.*rigid|relaxed.*tense" \
    "情绪与身体姿态矛盾" \
    "享受时身体应放松舒展，紧张时身体应僵硬" \
    "WARNING"

check_error "crying.*smile|laughing.*tears of pain|smiling.*sobbing|happy.*screaming in pain" \
    "表情矛盾：哭泣却微笑 / 大笑却痛苦" \
    "统一情绪表达，不要同时写矛盾表情" \
    "WARNING"

# ============================================
# 9. 场景光源与时间矛盾
# 本章只处理“时间设定”和“场景光源来源”是否冲突：
# - 夜里有太阳
# - 地下室直射日光
# - dawn 与 midnight 共存
# 新增规则示例：
# - 2am sunlight through window → 放这里
# ============================================
echo -e "${BLUE}━━ 9. 场景光源与时间矛盾检查 ━━${NC}"
echo ""

check_error "midnight.*bright sunlight|2am.*sunlight|night.*direct sunlight|night.*sun shining" \
    "夜间场景出现日光 - 时间与光源矛盾" \
    "夜间使用 moonlight/neon light/fluorescent light，不能有 sunlight" \
    "ERROR"

check_error "indoor.*direct sunlight|basement.*sunlight|underground.*sunlit" \
    "室内/地下场景出现直射日光 - 物理错误" \
    "室内改用 window light/lamp light/ceiling light" \
    "ERROR"

check_error "sunset.*midnight|dawn.*2am|morning light.*late night" \
    "时段描述矛盾（日出/日落 + 深夜）" \
    "统一时间描述，只保留一个时段" \
    "ERROR"

# ============================================
# 10. 镜子/反射矛盾检查
# 本章只处理“镜中倒影是否符合物理反射”的问题：
# - 背对镜子却有正面倒影
# - 倒影姿势与本人不一致
# 不处理：
# - 镜前站姿但机位未交代（那是姿势/构图问题，放 §17）
# ============================================
echo -e "${BLUE}━━ 10. 镜子与反射矛盾检查 ━━${NC}"
echo ""

check_error "mirror.*facing away|mirror reflection.*back turned|reflection.*looking away from mirror" \
    "镜子反射矛盾：背对镜子却有正面倒影" \
    "背对镜子只能看到背影，正面倒影需要面对镜子" \
    "ERROR"

check_error "mirror.*different pose|reflection.*different angle|mirror.*inconsistent" \
    "镜中倒影姿势与本人不一致 - 物理错误" \
    "镜子倒影必须与本人姿态完全对称" \
    "ERROR"

# ============================================
# 11. 负面词混入正面提示词检查
# 本章处理：
# - 正面 prompt 中混入负面词
# - 嘴部高风险描述（牙碰唇 / 张嘴角度风险 / tongue out）
# - 面部局部高风险细节（如遮脸导致多头 / 敏感部位精液遮挡）
# 不处理：
# - 整体情绪矛盾（放 §8）
# - 镜像/倒影问题（放 §10）
# ============================================
echo -e "${BLUE}━━ 11. 负面词混入正面提示词检查 ━━${NC}"
echo ""

# §11-2 敏感部位精液遮挡风险：精液附着在下巴、嘴巴、嘴角、嘴唇、舌头、喉咙、嘴内或鼻周（包括鼻孔）会模糊面部轮廓，导致脸型畸形或结构失真
CHIN_NOSE_CUMSHOT=$(echo "$PROMPT" | grep -oiE "\b(cum|semen|ejaculate|sperm|cumshot)\b.{0,20}\b(mouth|lips?|lip\s+corner|corner\s+of\s+mouth|tongue|inside\s+mouth|throat|chin|nose|nostrils?)\b|\b(mouth|lips?|lip\s+corner|corner\s+of\s+mouth|tongue|inside\s+mouth|throat|chin|nose|nostrils?)\b.{0,20}\b(cum|semen|ejaculate|sperm|cumshot)\b|dripping.{0,20}from (the )?(chin|nose|mouth|lips?|tongue|lip\s+corner|corner\s+of\s+mouth)")
if [ -n "$CHIN_NOSE_CUMSHOT" ]; then
    echo -e "${RED}❌ [严重] §11-2 面部关键部位精液遮挡风险${NC}"
    echo -e "${YELLOW}   发现: $CHIN_NOSE_CUMSHOT${NC}"
    echo -e "${YELLOW}   精液附着在下巴、嘴巴、嘴角、嘴唇、舌头、喉咙、嘴内或鼻周会严重干扰面部特征识别，导致脸型畸形或产生不明异物感${NC}"
    echo -e "${GREEN}   修正：改到脸颊或锁骨，如 cum on cheeks / glistening on collarbone${NC}"
    ERRORS=$((ERRORS + 1))
    echo ""
fi

# §11-3 单侧乳房可见时的乳头分叉风险：不只侧面视角，衣物只露一乳也必须使用单数解剖词。
SINGLE_UPPER_CONTEXT="side view|profile view|side profile|(^|[^a-z])from the side([^s]|$)|\b(one|single|left|right)[[:space:]]+(bare|exposed|visible|uncovered)[[:space:]]+(breast|nipple|areola)\b|\b(one|single|left|right)[[:space:]]+(breast|nipple|areola)[[:space:]]+(visible|exposed|bare|uncovered|out)\b|\b(a[[:space:]]+)?(bare|exposed|visible|uncovered)[[:space:]]+breast\b|\bbreast[[:space:]]+(exposed|visible|bare|uncovered|out)\b|\b(showing|exposing|revealing)[[:space:]]+(a[[:space:]]+)?(bare[[:space:]]+)?breast\b|\bside[[:space:]]*breast\b|\bsideboob\b"
if echo "$PROMPT" | grep -qiE "$SINGLE_UPPER_CONTEXT" ; then
    PLURAL_UPPER_ANATOMY=$(echo "$PROMPT" | grep -oiE "\b(breasts|nipples|areolae)\b" | tr '\n' ' ')
    if [ -n "$PLURAL_UPPER_ANATOMY" ]; then
        echo -e "${RED}❌ [严重] §11-3 单侧乳房乳头分叉风险${NC}"
        echo -e "${YELLOW}   发现: 单侧可见语境 + 复数解剖词 ${PLURAL_UPPER_ANATOMY}${NC}"
        echo -e "${YELLOW}   只露一侧却保留 breasts/nipples/areolae，AI 容易把双侧细节挤到同一乳房上${NC}"
        echo -e "${GREEN}   修正：改成 only one breast visible / one nipple visible / one areola visible，并明确另一侧被衣物或身体角度遮挡${NC}"
        ERRORS=$((ERRORS + 1))
        echo ""
    fi
fi

# §11-4 眼睛关键部位精液遮挡
EYE_CUMSHOTS=$(echo "$PROMPT" | grep -oiE "\b(cum|semen|ejaculate|sperm|cumshot)\b.{0,30}\beye(s)?\b|\beye(s)?\b.{0,30}\b(cum|semen|ejaculate|sperm|cumshot)\b")
if [ -n "$EYE_CUMSHOTS" ]; then
    # 检查匹配的内容中是否包含放行条件
    if ! echo "$EYE_CUMSHOTS" | grep -qiE "closed|eyelid|around|under|shut" ; then
        echo -e "${RED}❌ [严重] §11-4 眼睛关键部位精液遮挡${NC}"
        echo -e "${YELLOW}   发现: $EYE_CUMSHOTS${NC}"
        echo -e "${YELLOW}   精液直接附着在睁开的眼睛上会严重导致“白内障”或眼部畸变，违反生理和美学${NC}"
        echo -e "${GREEN}   修正：改到闭着的眼睑上（closed eyelids）或眼周/眼下（around/under eyes）${NC}"
        ERRORS=$((ERRORS + 1))
        echo ""
    fi
fi

# 风格豁免词（手机画质/胶片/监控风格中这些是故意的美学选择，不是负面词）
if echo "$PROMPT" | grep -qiE "phone|smartphone|amateur|mobile.*photo|casual.*shot|film.*aesthetic|film.*style|film.*look|film.*grain|CCTV|surveillance|monitor.*feed|security.*camera|grainy.*aesthetic|retro.*photo"; then
    STYLE_EXEMPTION=true
else
    STYLE_EXEMPTION=false
fi

# 风格豁免的词汇（有美学意图时不拦截）
STYLE_KEYWORDS="noisy|grainy|fuzzy|compression artifacts|jpeg artifacts|text overlay"

NEGATIVE_KEYWORDS="low quality|worst quality|bad quality|blurry|watermark|username|photo\s*signature|digital\s*signature|embed\s*signature|deformed|bad anatomy|extra limbs|extra fingers|mutated hands|ugly|duplicate|morbid|out of frame|gross proportions|malformed limbs|missing arms|missing legs|extra arms|extra legs|fused fingers|too many fingers|bad hands|poorly drawn hands|disfigured|bad face|poorly drawn face|unclear eyes|long neck|mutation|disproportionate|wrong anatomy|unnatural pose|impossible pose|bad proportions|extra digit|fewer digits|missing digit|extra fingers|missing fingers"

# cropped 上下文豁免：服装语境（cropped top/jacket/shirt）是合法描述，非图像裁切
CROPPED_CLOTHING=$(echo "$PROMPT" | grep -oiE 'cropped (top|jacket|shirt|sweater|hoodie|blouse|tee|vest|cardigan|camisole|bustier|tank|pullover|knit)' | head -1)
if [ -n "$CROPPED_CLOTHING" ]; then
    :  # 服装语境，豁免
elif echo "$PROMPT" | grep -qiE '\bcropped\b'; then
    echo -e "${YELLOW}⚠️  [警告] cropped 词混入正面提示词 - cropped 会引导AI生成裁切图，如果是服装描述请用 cropped top/jacket 等，或移入 negative prompt${NC}"
    echo -e "${YELLOW}   发现: cropped（非服装语境）${NC}"
    WARNINGS=$((WARNINGS + 1))
    echo ""
fi

# 先检查非风格豁免的硬负面词（降级为 WARNING 以允许特殊视角画质等特定艺术设计）
if echo "$PROMPT" | grep -qiE "$NEGATIVE_KEYWORDS"; then
    FOUND=$(echo "$PROMPT" | grep -oiE "$NEGATIVE_KEYWORDS" | head -3 | tr '\n' ' ')
    echo -e "${YELLOW}⚠️  [警告] 疑似负面词混入正面提示词（已自动放行）${NC}"
    echo -e "${YELLOW}   发现: $FOUND${NC}"
    echo -e "${GREEN}   注意: 特殊视角/画质可能会需要特定词汇。如无特殊要求，建议移到 negative prompt${NC}"
    WARNINGS=$((WARNINGS + 1))
    echo ""
fi

# 场景氛围词（废弃/恐怖/阴暗场景的正常描述，降级为 WARNING）
SCENE_MOOD_KEYWORDS="peeling|flickering|eerie|decay|dilapidated|crumbling|abandoned|rusted|corroded|deteriorating|grimy|dingy|desolate"
if echo "$PROMPT" | grep -qiE "$SCENE_MOOD_KEYWORDS"; then
    FOUND_MOOD=$(echo "$PROMPT" | grep -oiE "$SCENE_MOOD_KEYWORDS" | head -3 | tr '\n' ' ')
    echo -e "${YELLOW}⚠️  [警告] 场景氛围词: $FOUND_MOOD — 废弃/恐怖场景可用，但确认是否需要${NC}"
    WARNINGS=$((WARNINGS + 1))
    echo ""
fi

# 再检查风格相关的词（统一降为 WARNING，不再拦截）
if echo "$PROMPT" | grep -qiE "$STYLE_KEYWORDS"; then
    FOUND_STYLE=$(echo "$PROMPT" | grep -oiE "$STYLE_KEYWORDS" | head -3 | tr '\n' ' ')
    if [ "$STYLE_EXEMPTION" = true ]; then
        echo -e "${YELLOW}⚠️  [警告] 风格词出现在提示词中 - 当前风格可能有此需求，但建议确认${NC}"
        echo -e "${BLUE}   发现: $FOUND_STYLE${NC}"
        echo -e "${BLUE}   注意: 手机画质/胶片/监控风格中这些是美学选择，但仍建议移入 negative prompt 以确保稳定${NC}"
        WARNINGS=$((WARNINGS + 1))
    else
        echo -e "${YELLOW}⚠️  [警告] 风格/噪点词出现在正面提示词中 — 如果是特殊相机风格的画质描述则正常，其它场景建议移到 negative prompt${NC}"
        echo -e "${YELLOW}   发现: $FOUND_STYLE${NC}"
        WARNINGS=$((WARNINGS + 1))
    fi
    echo ""
fi

# 嘴部风险词检查（§11 子检查）
# ============================================
echo -e "${BLUE}━━ 11. 嘴部风险词检查 ━━${NC}"
echo ""

# 牙齿咬唇/夹住描述在AI中极易产生嘴部畸形（牙齿穿模、嘴唇撕裂、不明物体）
# 仅针对咬(biting/bite)、夹住(caught/trapped)以及牙齿在嘴唇间等高风险变形动作进行拦截
# [原版超严限口拦截正则备份 (含静触词，随时可恢复)]:
# if echo "$PROMPT" | grep -qiE "biting.*lip|lip.*biting|biting.*lower|teeth.*pressing.*lip|teeth.*on.*lip|teeth.*lower lip|teeth.*grazing.*lip|lip.*between.*teeth|lower lip.*teeth|teeth.*biting|teeth.*touching.*lip|teeth.*resting.*lip|teeth.*caught.*lip|teeth.*trapped.*lip|caught.*between.*teeth|clenched.*teeth.*lip"; then
if echo "$PROMPT" | grep -qiE "biting.*lip|lip.*biting|biting.*lower|lip.*between.*teeth|teeth.*biting|teeth.*caught.*lip|teeth.*trapped.*lip|caught.*between.*teeth|clenched.*teeth.*lip"; then
    echo -e "${RED}❌ [严重] 含牙齿咬唇/夹唇描述 — AI 极易产生嘴部畸形（牙齿穿模/嘴唇撕裂/不明物体）${NC}"
    # [原版超严限口拦截发现匹配正则备份]:
    # echo -e "${YELLOW}   发现: $(echo "$PROMPT" | grep -oiE 'biting.*lip|lip.*biting|biting.*lower|teeth.*pressing.*lip|teeth.*on.*lip|teeth.*lower lip|teeth.*grazing.*lip|lip.*between.*teeth|lower lip.*teeth|teeth.*biting|teeth.*touching.*lip|teeth.*resting.*lip|teeth.*caught.*lip|teeth.*trapped.*lip|caught.*between.*teeth|clenched.*teeth.*lip' | head -1)${NC}"
    echo -e "${YELLOW}   发现: $(echo "$PROMPT" | grep -oiE 'biting.*lip|lip.*biting|biting.*lower|lip.*between.*teeth|teeth.*biting|teeth.*caught.*lip|teeth.*trapped.*lip|caught.*between.*teeth|clenched.*teeth.*lip' | head -1)${NC}"
    echo -e "${GREEN}   修正: lips slightly parted / pressing lips together / tense mouth / nervous mouth — 嘴唇独立描述，不提牙齿${NC}"
    ERRORS=$((ERRORS + 1))
    echo ""
fi

# open mouth + moaning/gasping 在侧脸角度下容易出现牙齿排列错乱
if echo "$PROMPT" | grep -qiE "open mouth.*(moan|gasp|cry|scream)|mouth.*wide.*(moan|gasp)"; then
    if ! echo "$PROMPT" | grep -qiE "front.*view|facing.*camera|straight.*on|eye.*level"; then
        echo -e "${YELLOW}⚠️  [警告] 张嘴 + 非正面角度 — 牙齿/嘴唇容易错位畸形${NC}"
        echo -e "${BLUE}   建议: 添加 'front view, facing camera' 或减少张嘴程度${NC}"
        WARNINGS=$((WARNINGS + 1))
        echo ""
    fi
fi

# tongue out / sticking tongue 在侧脸/仰视角度下容易出现漂浮舌头
if echo "$PROMPT" | grep -qiE "tongue out|sticking.*tongue|tongue.*visible"; then
    echo -e "${YELLOW}⚠️  [警告] 含 'tongue out' — AI 容易产生脱离嘴部的悬浮舌头${NC}"
    echo -e "${BLUE}   建议: 慎用，或加 'tongue naturally resting, tongue inside mouth' 约束${NC}"
    WARNINGS=$((WARNINGS + 1))
    echo ""
fi

echo ""

# ============================================
# 12. 支撑与平衡检查
# 本章处理“重心、支撑点、稳定性”：
# - 后仰无支撑
# - 单手撑全身
# - 跪姿却无法稳定
# 新增规则示例：
# - reclining backward with both feet off ground and no wall → 放这里
# ============================================
echo -e "${BLUE}━━ 12. 支撑与平衡检查 ━━${NC}"
echo ""

if [ "$IS_SPECIAL_PHYSICS" -eq 0 ]; then
    check_error "leaning\b.{0,80}back\b.{0,80}no.{0,20}support|reclining\b.{0,80}without.{0,20}hand" \
        "身体后仰倾斜却无支撑 - 重心不稳" \
        "后仰需手撑/靠墙/有支撑点" \
        "ERROR"
fi

check_error "one.*hand.*supporting.*full.*weight" \
    "单手支撑全身重量 - 难以维持" \
    "双手支撑或添加其他支撑点" \
    "WARNING"

if [ "$IS_SPECIAL_PHYSICS" -eq 0 ]; then
    check_error "leg.*in.*air.*no.*lift|floating.*leg.*no.*support" \
        "腿部悬空但无抬起动作/支撑" \
        "悬空肢体需要理由：抬起/被抬/绑定" \
        "WARNING"
fi

# ============================================
# 13. 数量与空间匹配检查
# 本章只处理“人数 ↔ 四肢数量 ↔ 肢体归属”这类计数问题。
# 不处理自拍+双手动作冲突，那属于姿势/构图组合问题，放 §17。
# 新增规则示例：
# - two girls with five hands → 放这里
# ============================================
echo -e "${BLUE}━━ 13. 数量与空间匹配检查 ━━${NC}"
echo ""

check_error "two.*people.*three.*legs|2.*persons.*3.*legs" \
    "肢体数量异常 - 2人出现3条完整腿" \
    "N人=2N条腿（被遮挡除外）" \
    "ERROR"

check_error "two.*people.*five.*hands|2.*persons.*5.*hands" \
    "肢体数量异常 - 2人出现5只手" \
    "N人=2N只手" \
    "ERROR"

check_error "limb.*unclear.*owner|cannot.*tell.*which.*leg" \
    "肢体归属不明" \
    "每个肢体应能明确归属" \
    "WARNING"

# ============================================
# 14. 动态与静态统一检查
# 本章预留给“同一 prompt 内，动态描述与静态描述彼此冲突”的规则：
# 例如：站立静止 + 高速奔跑中；安静端坐 + 头发猛烈甩动。
# 当前暂无启用规则。
# ⚠️ 禁止把“不知道放哪”的规则堆到这里：
# - 姿势/服装展示问题 → §17
# - 支撑/重心问题 → §12
# - 光影问题 → §15
# ============================================
echo -e "${BLUE}━━ 14. 动态与静态统一检查 ━━${NC}"
echo ""




# ============================================
# 15. 光影-形体一致性检查
# 本章处理“光源、阴影、透明物体阴影、形体受光”的中高阶问题。
# §5 只管轻量高光方向；更完整的光影逻辑放这里。
# 新增规则示例：
# - shadow on same side as key light → 放这里
# - clear glass casting heavy dark shadow → 放这里
# ============================================
echo -e "${BLUE}━━ 15. 光影-形体一致性检查 ━━${NC}"
echo ""

# ── 顶光豁免：天花板/顶灯/上方光源自然向下投阴影，不存在左/右光源同侧矛盾 ──
# 顶光下阴影均匀分布在物体下方所有方向，"影子与光源同侧"对顶光无意义
HAS_OVERHEAD_LIGHT=$(echo "$PROMPT" | grep -qiE "\b(ceiling light|overhead light|top.?down light|top.?down lighting|top light|fluorescent ceiling|overhead fluorescent|ceiling lamp|overhead lamp|light fixture above|light from above|ceiling fixture|harsh overhead|ceiling fluorescent|overhead.*lighting|ceiling.*lighting|top.?down.*light|overhead.*light fixture|overhead.*fluorescent|overhead.*lamp)\b" && echo 1 || echo 0)
if [ "$HAS_OVERHEAD_LIGHT" = "1" ]; then
    echo -e "${GREEN}⏭️  顶光光源豁免 — 跳过阴影方向检查（顶光向下投阴影，物理自洽）${NC}"
    echo ""
else
    # 拆分左右方向检查：要求 shadow 和 light 各自有明确的方向性上下文
    # shadow 方向：shadow (to|toward|on|cast|fall|falls) (the )?left/right
    # light 方向：(light|lit) (from|on) (the )?left/right
    # {0,60} 限定方向词紧邻对应主语，{0,150} 限定两句之间不能太远
    check_error "\bshadow\b.{0,60}\b(?:to|toward|on|cast|fall|falls)\s+(?:the\s+)?left\b.{0,150}\b(?:light|lit)\b.{0,60}\b(?:from|on)\s+(?:the\s+)?left\b" \
        "投影方向矛盾 - 影子与光源同为左侧" \
        "影子方向应与光源相反" \
        "ERROR"
    check_error "\bshadow\b.{0,60}\b(?:to|toward|on|cast|fall|falls)\s+(?:the\s+)?right\b.{0,150}\b(?:light|lit)\b.{0,60}\b(?:from|on)\s+(?:the\s+)?right\b" \
        "投影方向矛盾 - 影子与光源同为右侧" \
        "影子方向应与光源相反" \
        "ERROR"
    check_error "shadow.*same.*side.*as.*light" \
        "投影方向矛盾 - 影子与光源同侧" \
        "影子方向应与光源相反" \
        "ERROR"
fi

check_error "transparent.*glass.*heavy.*shadow|clear.*object.*dark.*shadow" \
    "透明物体却有浓重阴影" \
    "透明物体阴影应浅淡" \
    "WARNING"

check_error "left.*highlight.*right.*highlight.*strong" \
    "左右同时有强高光 - 光源不统一" \
    "统一光源方向" \
    "WARNING"

# ============================================
# 16. 空间占位检查
# 本章处理“人物和物体是否在空间中合理摆放”：
# - 同位置重叠
# - 家具尺度不对
# - 一个位置被双重占用
# 新增规则示例：
# - sitting on chair but also standing on it → 放这里
# ============================================
echo -e "${BLUE}━━ 16. 空间占位检查 ━━${NC}"
echo ""

check_error "occupying.*same.*space|overlapping.*bodies" \
    "空间重叠 - 人物/物体在同一位置" \
    "物体不能互相穿透" \
    "ERROR"

check_error "sitting.*on.*chair.*but.*standing.*on.*it" \
    "空间占用矛盾 - 坐着却站在同一位置" \
    "空间已被占用则不能再占用" \
    "ERROR"

check_error "furniture.*too.*small|chair.*disproportionate" \
    "尺寸比例失调 - 家具与人物不匹配" \
    "家具尺寸应与人体比例协调" \
    "WARNING"

# ============================================
# 17. 姿势与服装配合检查
# 本章处理“姿势 + 服装/遮挡状态 + 构图机位”的组合矛盾：
# - 张腿但裙子/内裤仍完全遮住应展示部位
# - 弯腰/床姿/镜前站姿的机位与可见性不匹配
# - 自拍与双手动作冲突、俯拍露阴、跪姿正面露阴等高风险构图
# 不处理：
# - 纯镜像物理矛盾（放 §10）
# - 单纯肢体数量统计（放 §13）
# - 单纯支撑/重心问题（放 §12）
# ============================================
echo -e "${BLUE}━━ 17. 姿势与服装配合检查 ━━${NC}"
echo ""

check_error "lying.*back.*legs.*spread.*skirt.*covering|spread.*legs.*skirt.*covering.*pussy|legs.*open.*skirt.*hiding" \
    "仰卧张腿但裙子仍遮盖私处 - 服装与姿势矛盾" \
    "张腿时裙子应滑落或掀开暴露，添加 skirt lifted 或 skirt fallen to side 或 panties visible" \
    "ERROR"

check_error "spread.*legs.*wide.*panties.*covering|legs.*spread.*panties.*in.*place.*pussy|vulva.*covered.*by.*panties.*spread" \
    "张腿但内裤完全遮盖私处 - 服装与姿势矛盾" \
    "张腿时内裤应移位露出缝隙或拉下，添加 panties pulled aside / panties at ankles / pussy visible" \
    "ERROR"

check_error "bent.*over.*from.*behind.*\bass\b.*covered|bent.*over.*back.*view.*\bbuttocks\b.*hidden.*by.*skirt|bent.*over.*no.*panties.*but.*covered" \
    "弯腰后视但臀部/私处被完全遮盖 - 姿势与可见性矛盾" \
    "弯腰后视且特意描述应可见时，添加 skirt lifted / bottomless / no panties 配合 visible" \
    "ERROR"

# 后视露下的后方生理结构双保险：按姿势强度给不同建议词
HAS_REAR_VIEW=$(echo "$PROMPT" | grep -qiE "(from behind|back view|rear view|\bass\b toward camera|buttocks toward camera|looking back over shoulder|bent over|kneeling from behind|doggy|buttocks spread|spread buttocks)" && echo 1 || echo 0)
# feet-first POV（丝袜视角脚前透视）豁免——低角度从脚向身体拍，非后入视角
if [ "$IS_FEET_FIRST_POV" = "1" ]; then
    HAS_REAR_VIEW=0
fi
HAS_SPREAD_REAR=$(echo "$PROMPT" | grep -qiE "(buttocks spread|spread buttocks|between spread thighs)" && echo 1 || echo 0)
HAS_STRONG_REAR=$(echo "$PROMPT" | grep -qiE "(bent over|kneeling from behind|doggy|rear view|from behind|\bass\b toward camera|buttocks toward camera)" && echo 1 || echo 0)
HAS_LOWER_EXPOSE=$(echo "$PROMPT" | grep -qiE "(bottomless|bare from waist down|bare pussy|pussy visible|vulva visible|fully nude|completely naked|full nude|shaved pussy|hairless vulva)" && echo 1 || echo 0)
HAS_REAR_ANATOMY=$(echo "$PROMPT" | grep -qiE "(anus|anal opening|between buttocks|in the cleft|puckered anus)" && echo 1 || echo 0)
if [ "$HAS_REAR_VIEW" = "1" ] && [ "$HAS_LOWER_EXPOSE" = "1" ] && [ "$HAS_REAR_ANATOMY" = "0" ]; then
    if [ "$HAS_SPREAD_REAR" = "1" ]; then
        echo -e "${RED}❌ [严重] §17-8 臀部分开后视缺少后方生理结构${NC}"
        echo -e "${YELLOW}   臀部分开且露下时，若没有后方结构词，后部容易平滑失真，缺乏真实解剖锚点${NC}"
        echo -e "${GREEN}   修正：优先补 'small visible anus between spread buttocks'${NC}"
        ERRORS=$((ERRORS + 1))
        echo ""
    elif [ "$HAS_STRONG_REAR" = "1" ]; then
        echo -e "${RED}❌ [严重] §17-8 强后视露下缺少后方生理结构${NC}"
        echo -e "${YELLOW}   强后方露下场景若没有后方结构词，臀缝区域容易过于平滑，缺乏真实解剖锚点${NC}"
        echo -e "${GREEN}   修正：优先补 'small visible anus in the cleft'；更柔和可用 'soft puckered anus visible from behind'${NC}"
        ERRORS=$((ERRORS + 1))
        echo ""
    else
        echo -e "${YELLOW}⚠️  [警告] §17-8 后视露下建议补后方生理结构${NC}"
        echo -e "${BLUE}   建议：补 'visible anus between buttocks'，提升后方真实感与解剖完整度${NC}"
        WARNINGS=$((WARNINGS + 1))
        echo ""
    fi
fi

check_error "sitting.*legs.*spread.*knees.*together|spreading.*legs.*closed.*thighs" \
    "张开腿但膝盖并拢 - 姿势矛盾" \
    "统一姿势描述：spreading legs = knees apart" \
    "ERROR"

check_error "missionary.*position.*intercourse.*fully.*clothed|missionary.*sex.*all.*clothes.*on|missionary.*penetration.*clothes.*intact" \
    "传教士性交但衣服完整遮盖 - 姿势与服装矛盾" \
    "性行为姿势应有衣物移开或脱除，添加 clothes pulled down / partially undressed / skirt lifted" \
    "ERROR"

# 床上姿势美感检查：仅在明确出现 lying/reclining on bed 时拦截；examination bed / bed edge / sitting on bed 不误伤
if echo "$PROMPT" | grep -qiE "(lying on bed|lying on the bed|reclining on bed|reclining on the bed|lying across bed|sprawled on bed)" ; then
    if ! echo "$PROMPT" | grep -qiE "(side-lying|side lie|face down|face-up|on stomach|on back|prone|supine|knees bent|legs bent|curled|fetal|arms over|legs stretched|leg extended|feet tucked|body curled|half-turn|twisted on bed|lying on side|on side|laying on side)" ; then
        echo -e "${RED}❌ [严重] §17-1 床上姿势美感缺失${NC}"
        echo -e "${YELLOW}   'lying on bed' 太模糊，模型随意生成丑陋姿势${NC}"
        echo -e "${GREEN}   修正：加具体方向词如 'side-lying curled' / 'face-down on sheets' / 'on back knees bent'${NC}"
        ERRORS=$((ERRORS + 1))
        echo ""
    fi
fi

# 肢体数量冲突检查：手持手机/拿东西 + 双手动作 = 3只手
# 白名单：surveillance/CCTV/security camera 是场景词，不是手持设备
PROMPT_NO_SURV=$(echo "$PROMPT" | sed -E 's/(surveillance|security|cctv|ceiling.mounted|ceiling|mounted|hidden|fixed)[[:space:]]+camera//gi')
if echo "$PROMPT_NO_SURV" | grep -qiE "(holding.{0,30}phone|holding.{0,30}camera|taking.{0,30}selfie|selfie.{0,30}holding|phone.{0,30}in.{0,10}hand|camera.{0,30}in.{0,10}hand)" ; then
    if echo "$PROMPT_NO_SURV" | grep -qiE "(both hands|two hands|palms|hands.{0,40}(cover|cup|clutch|grip|press|hold|squeeze|reach|shield|hide|conceal))" ; then
        echo -e "${RED}❌ [严重] §17-2 自拍与双手动作冲突${NC}"
        echo -e "${YELLOW}   同时需要「拿手机自拍」+「双手动作」= 超过2只手${NC}"
        echo -e "${GREEN}   修正：自拍改脚架/镜前不用手机，或手部动作只保留一个（单手遮胸 或 单手握手机）${NC}"
        ERRORS=$((ERRORS + 1))
        echo ""
    fi
fi

# §17-3 嘴部动作互斥：舌头动作 + 张嘴 = 矛盾
if echo "$PROMPT" | grep -qiE "(tongue.*touch|licking.*lip|tongue.*out|tongue.*lick)" ; then
    if echo "$PROMPT" | grep -qiE "(lips.*parted|mouth.*open|open.*mouth|lips.*slightly.*part)" ; then
        echo -e "${RED}❌ [严重] §17-3 嘴部动作互斥${NC}"
        echo -e "${YELLOW}   舌头碰唇（mouth closed） + 嘴张开/唇微启 = 肌肉矛盾${NC}"
        echo -e "${GREEN}   修正：二选一 → 舌头舔唇嘴闭合 / 张嘴呼吸无舌${NC}"
        ERRORS=$((ERRORS + 1))
        echo ""
    fi
fi

# §17-4 镜前站姿视角混淆
if echo "$PROMPT" | grep -qiE "standing.*in.*front.*of.*mirror|standing.*before.*mirror|facing.*mirror.*standing|in front of.*full.*length.*mirror" ; then
    if ! echo "$PROMPT" | grep -qiE "(from behind|back.*to.*camera|shot.*from.*behind|POV.*behind|behind.*her|rear.*view)" ; then
        echo -e "${RED}❌ [严重] §17-4 镜前站姿视角混淆${NC}"
        echo -e "${YELLOW}   站在镜前时，镜头在人物身后还是镜中？不明确导致AI画出双人或幽灵${NC}"
        echo -e "${GREEN}   修正：加 from behind（镜头在她身后拍）或去掉镜子改直面镜头${NC}"
        ERRORS=$((ERRORS + 1))
        echo ""
    fi
fi

# §11-1 脸部遮挡导致多头部：头发遮脸（无论是否有直视描述都触发）
# 头发遮住脸部时，模型倾向于生成第二个头/多张脸来"补全"被遮挡的面部
# 正面/侧面照时尤其高风险，闭眼/侧脸/看远处都不能免除
HAIR_COVER_FACE=$(echo "$PROMPT" | grep -oiE "hair flying across face|hair covering face|hair obscuring face|hair hiding face|hair across face|face covered by hair|face obscured by hair|long hair flowing across face|long hair covering face")
if [ -n "$HAIR_COVER_FACE" ]; then
    echo -e "${RED}❌ [严重] §11-1 脸部遮挡导致多头部风险${NC}"
    echo -e "${YELLOW}   发现: $HAIR_COVER_FACE${NC}"
    echo -e "${YELLOW}   头发遮脸会让模型生成第二个头/多张脸来补全被遮挡的面部${NC}"
    echo -e "${GREEN}   修正：撩开头发露出脸部 hair tucked behind ear / hair swept aside${NC}"
    ERRORS=$((ERRORS + 1))
    echo ""
fi

# §17-5 跪姿正面露阴（HARD）
if echo "$PROMPT" | grep -qiE "(kneeling|seiza)" ; then
    if echo "$PROMPT" | grep -qiE "(visible.*vulva|exposed.*vulva|vulva.*visible|exposed.*pussy|pussy.*exposed|visible.*pussy)" ; then
        if ! echo "$PROMPT" | grep -qiE "(from([ _-]+directly)?[ _-]+behind|directly[ _-]+behind|from below|between.*thighs|spread.*legs|legs.*spread|camera.*below)" ; then
            echo -e "${RED}❌ [严重] §17-5 跪姿正面露阴${NC}"
            echo -e "${YELLOW}   跪姿正面露阴AI无法渲染出合理角度，极易畸形${NC}"
            echo -e "${GREEN}   修正：加 from behind / camera angle from below between spread thighs${NC}"
            ERRORS=$((ERRORS + 1))
            echo ""
        fi
    fi
fi

# §17-12 颜射视角+露逼（HARD）
# 对齐真实「颜射视角」信号（非笼统 cum on face）：
#   · 中文路由：颜射视角 / 射脸 / 颜射（scene.label / 用户路由词）
#   · SAFE_CUMS 落点：颊/颧骨流线 → 锁骨窝沉淀 + chin clean 套话
#   · perspective_scenes 机位套餐：high angle from above (pov) + looking up + kneeling/seiza
# 颜射默认跪姿仰脸、焦点在脸，禁止同时露阴（legs spread / from below 亦不放行）
IS_FACIAL_VIEW=0
# A. 中文场景路由词（避免「非颜射」误命中裸「颜射」）
if echo "$PROMPT" | grep -qE "颜射视角|射脸|([^非]|^)颜射" ; then
    IS_FACIAL_VIEW=1
fi
# B. SAFE_CUMS 官方液体特征（6 条均含：颊/颧骨或锁骨窝 + semen + chin clean 系）
if echo "$PROMPT" | grep -qiE "\b(semen|milky-white|opalescent|viscous)\b" \
    && echo "$PROMPT" | grep -qiE "\b(cheek|cheekbone|collarbone hollow|collarbone dip|collarbone dips|collarbone hollows)\b" \
    && echo "$PROMPT" | grep -qiE "chin (remaining )?spotless|chin clean|chin untouched|chin completely clean|chin free of fluid|chin clean and free|chin clean and clear" ; then
    IS_FACIAL_VIEW=1
fi
# C. perspective_scenes 颜射机位套餐（scene_theme / pose_hint 常用词）
if echo "$PROMPT" | grep -qiE "high[ _-]?angle.{0,50}(from above|pov)|from above[ _-]*\([ _-]*pov|facing (the )?(POV|pov|camera) above|squarely facing the POV|directly beneath the camera" ; then
    if echo "$PROMPT" | grep -qiE "looking up|face tilted up|face turned up" ; then
        if echo "$PROMPT" | grep -qiE "\b(kneeling|seiza)\b" ; then
            IS_FACIAL_VIEW=1
        fi
    fi
fi

if [ "$IS_FACIAL_VIEW" = "1" ]; then
    if echo "$PROMPT" | grep -qiE "(visible[ _-]*vulva|exposed[ _-]*vulva|vulva[ _-]*visible|exposed[ _-]*pussy|pussy[ _-]*exposed|visible[ _-]*pussy|pussy[ _-]*visible|spread[ _-]*pussy|bare[ _-]*pussy)" ; then
        echo -e "${RED}❌ [严重] §17-12 颜射视角+露逼${NC}"
        echo -e "${YELLOW}   颜射视角=跪姿仰脸+高角 POV，焦点在脸/颊锁骨液体；同时露阴=机位冲突${NC}"
        echo -e "${GREEN}   修正：颜射卡删 pussy/vulva 等下体词（exposure 用 upper）；要露逼请换非颜射视角场景${NC}"
        ERRORS=$((ERRORS + 1))
        echo ""
    fi
fi

# §17-6 真·鸟瞰90°+阴部（HARD）
# 意图：只拦「作为机位的正俯/鸟瞰」+ 露阴导致的解剖畸变
# 拦截：监控/针孔/鱼眼机位 + 露阴同样拦截（不豁免）；顶光/氛围 overhead、high angle 斜俯不拦
# 颜射不豁免（见 §17-12：颜射+露逼一律 HARD）
# 触发词必须带 view/shot/angle 等视角语境，禁止裸匹配 overhead / top-down
# ────────────────────────────────────────
# 2026-08-01：取消 CCTV/鱼眼豁免（主人要求监控/鱼眼 + 露阴仍拦截）
SKIP_176=0

if [ "$SKIP_176" = "0" ]; then
    # 真·鸟瞰/正俯视角（必须是视角语境；灯光/道具 overhead 不命中）
    HAS_PURE_TOPDOWN=0
    if echo "$PROMPT" | grep -qiE "\b(bird'?s[ _-]?eye|god'?s[ _-]?eye)\b|\bfrom directly above\b|\bdirectly above\b|\b90[° ]?(degree[ _-]?)?(overhead|top[ _-]?down|topdown)\b|\boverhead[ _-]?(view|shot|angle|pov|perspective)\b|\btop[ _-]?down[ _-]?(view|shot|angle|pov|perspective)\b|\btop down (view|shot|angle)\b|\bPOV from above\b" ; then
        HAS_PURE_TOPDOWN=1
    fi
    # 灯光/布光语境下的 top-down / overhead 不算机位（无更强鸟瞰词时）
    if [ "$HAS_PURE_TOPDOWN" = "1" ]; then
        if echo "$PROMPT" | grep -qiE "\b(overhead[ _-]?(light|lamp|fixture|fluorescent|lighting|bulb)|fluorescent overhead|dimmed overhead|harsh overhead|soft overhead|beauty light|top[ _-]?down[ _-]?(light|lighting|glamour|inspection)|inspection light|light from above|ceiling light)\b" ; then
            if ! echo "$PROMPT" | grep -qiE "\b(bird'?s[ _-]?eye|god'?s[ _-]?eye|from directly above|directly above|90[° ]?|overhead[ _-]?(view|shot|angle|pov|perspective)|top[ _-]?down[ _-]?(view|shot|angle|pov|perspective)|POV from above)\b" ; then
                HAS_PURE_TOPDOWN=0
            fi
        fi
    fi

    if [ "$HAS_PURE_TOPDOWN" = "1" ]; then
        if echo "$PROMPT" | grep -qiE "(visible[ _-]*vulva|exposed[ _-]*vulva|vulva[ _-]*visible|exposed[ _-]*pussy|pussy[ _-]*exposed|visible[ _-]*pussy|pussy[ _-]*visible|spread[ _-]*pussy|bare[ _-]*pussy)" ; then
            # soft-pass：腿开即可摊开解剖（与 §17-5 对齐，不强制 wide）
            if ! echo "$PROMPT" | grep -qiE "(legs?[ _-]*spread|spread[ _-]*legs?|thighs?[ _-]*(wide|apart|open)|wide[ _-]*apart|knees?[ _-]*(apart|open|spread))" ; then
                echo -e "${RED}❌ [严重] §17-6 真·鸟瞰90°+阴部${NC}"
                echo -e "${YELLOW}   正俯/鸟瞰机位+露阴易畸变；监控/鱼眼/顶光已豁免，此处为真·鸟瞰${NC}"
                echo -e "${GREEN}   修正：改为 high angle / 45-60° 斜俯，或加 legs spread；监控写 CCTV/surveillance 即可豁免${NC}"
                ERRORS=$((ERRORS + 1))
                echo ""
            fi
        fi
    fi
fi

# §17-7 遮盖+暴露矛盾
if echo "$PROMPT" | grep -qiE "(hands.*cover.*nipple|palms.*cover|hands.*shield.*breast|covering.*nipple|coyly.*covering)" ; then
    if echo "$PROMPT" | grep -qiE "(nipples.*erect|nipple.*pink|areola.*visible|areola.*pores|nipple.*detail)" ; then
        echo -e "${YELLOW}⚠️  [警告] §17-7 遮盖+暴露矛盾${NC}"
        echo -e "${YELLOW}   手遮住乳头但又描述了乳头细节 = 被遮住看不到${NC}"
        echo -e "${GREEN}   修正：要么露乳不加手遮，要么手遮不加纹理词${NC}"
        WARNINGS=$((WARNINGS + 1))
        echo ""
    fi
fi

# §17-8 干湿发冲突
if echo "$PROMPT" | grep -qiE "(wet hair|damp hair|soaked hair|hair.*wet|wet.*strands)" ; then
    if echo "$PROMPT" | grep -qiE "(hair.*spread|hair.*fluffy|hair.*flowing|hair.*voluminous|hair.*fanning|hair.*billowing)" ; then
        echo -e "${YELLOW}⚠️  [警告] §17-8 干湿发冲突${NC}"
        echo -e "${YELLOW}   湿发贴肤沉重，不会蓬散/铺开${NC}"
        echo -e "${GREEN}   修正：湿发只用 clinging to skin/pasted to forehead/heavy wet strands 等贴肤词${NC}"
        WARNINGS=$((WARNINGS + 1))
        echo ""
    fi
fi

# §17-9 绳缚经过下体/身体开口（HARD）
HAS_BONDAGE=$(echo "$PROMPT" | grep -qiE "(rope|ropes|shibari|bondage|restraint|suspension|chain|chains|leather|straps?|cuffs?|cord|tape|绳缚|束缚|拘束|吊缚|捆绑)" && echo 1 || echo 0)
if [ "$HAS_BONDAGE" = "1" ]; then
    if echo "$PROMPT" | grep -qiE "(rope|chain|chains|leather|straps?|cuffs?|cord|tape)[^,.]{0,80}(pussy|vulva|labia|slit|crotch|阴部|下体|阴唇|阴蒂)|(pussy|vulva|labia|slit|crotch|阴部|下体|阴唇|阴蒂)[^,.]{0,80}(rope|chain|chains|leather|straps?|cuffs?|cord|tape)|across (the )?(vulva|pussy|slit|阴部)|through (the )?(vulva|pussy|slit|阴部)|between labia|into (the )?(vulva|pussy|slit|阴部)|groin (rope|chain)|crotch (rope|chain)|(rope|chain) (crossing|pressing into|pulled into|threaded through) (the )?(vulva|pussy|labia|slit|crotch|阴部)|(vulva|pussy|labia|slit|crotch|阴部) (bound|tied|cinched) by (rope|chain)|body opening|绑在(阴部|下体|阴唇)|穿过(阴部|下体|阴唇)" ; then
        echo -e "${RED}❌ [严重] §17-9 绑缚载体位置错误${NC}"
        echo -e "${YELLOW}   检测到绑缚载体（rope/chain/leather/straps/cuffs/cord/tape）经过下体/身体开口（如 vulva slit / pussy / labia / crotch / body openings）${NC}"
        echo -e "${GREEN}   修正：改为载体 tension above mons pubis / along hips / along inner thighs，禁止穿过 vulva / labia / slit${NC}"
        ERRORS=$((ERRORS + 1))
        echo ""
    fi
fi

# §17-10 自拍与旁观/监控视角冲突
if echo "$PROMPT" | grep -qiE "(taking.{0,10}selfie|selfie)" ; then
    # 排除镜前自拍（合法显现手机和全身）
    if ! echo "$PROMPT" | grep -qiE "(mirror|reflection|reflective|glass.*reflection)" ; then
        HAS_PHONE_VISIBLE=$(echo "$PROMPT" | grep -qiE "(phone.*in.*hand|holding.*phone|holding.*cellphone|holding.*smartphone)" && echo 1 || echo 0)
        HAS_THIRD_PERSON=$(echo "$PROMPT" | grep -qiE "(cctv|surveillance|security.camera|three-quarter|looking.away|body.angled|from.behind|behind.her|full.body|wide.shot)" && echo 1 || echo 0)
        
        # 场景一：同时描述自拍、手机在画面显现、且机位为旁观视角
        if [ "$HAS_PHONE_VISIBLE" = "1" ] && [ "$HAS_THIRD_PERSON" = "1" ]; then
            echo -e "${RED}❌ [严重] §17-10 自拍与旁观视角冲突${NC}"
            echo -e "${YELLOW}   提示词同时声明了自拍（selfie）、手机在画面中显现、且机位为旁观/偷拍视角，这会混淆第一与第三人称，极易产生第三只手。${NC}"
            echo -e "${GREEN}   修正：如果是旁观/偷拍，请将自拍动作改为 'posing as if taking a selfie' 并删除 'selfie' 词汇。${NC}"
            ERRORS=$((ERRORS + 1))
            echo ""
        # 场景二：自拍动作与监控设备（CCTV/监控）直接冲突
        elif echo "$PROMPT" | grep -qiE "(cctv|surveillance|security.camera)" ; then
            echo -e "${RED}❌ [严重] §17-10 自拍与监控视角矛盾${NC}"
            echo -e "${YELLOW}   监控摄像头视角（CCTV/surveillance）与自拍动作（selfie）存在物理矛盾，会导致AI多头多臂或画风崩溃。${NC}"
            echo -e "${GREEN}   修正：删除 'selfie/taking selfie'，只保留旁观偷拍风格描述。${NC}"
            ERRORS=$((ERRORS + 1))
            echo ""
        fi
    fi
fi

# §17-11 湿衣边界缺失（HARD ERROR）
# 湿透衣服若无面料边缘描述，模型会把布料渲染成半透明"第二层皮"，与皮肤融合
# v2: 扩展关键词 + 穿着状态门槛 + 排除非穿着场景，升级为阻断级

CLOTHES_PATTERN="shirt|blouse|dress|cloth|fabric|garment|uniform|white.?shirt|school.?shirt|camisole|tank.?top|henley|cardigan|kimono|yukata|corset|bodice|chemise|slip|nightgown|nightie|pajama|lingerie|bra|bralette"
# 注意：排除了 "top"（方位词太通用：wet top of hill）和 "tank top"（单独匹配 tank.?top）

# 排除：非穿着状态（挂着/晾晒/道具/毛巾/展示/展品）
EXCLUDE_WET=$(echo "$PROMPT" | grep -qiE "(hanging|display|rack|drying|laundry|clothesline|prop|towel|cloth.{0,10}pressed|wipe.{0,10}face|museum|exhibit|installation|gallery)" && echo 1 || echo 0)

# 排除："wet-look" 风格词（非真正湿衣，是面料光泽处理）
IS_WETLOOK_STYLE=$(echo "$PROMPT" | grep -qiE "wet.?look" && echo 1 || echo 0)

# 检测湿衣 + 穿着状态
if [ "$EXCLUDE_WET" = "0" ] && [ "$IS_WETLOOK_STYLE" = "0" ]; then
    # 正序：wet/soaked/drenched/damp/sodden + 衣物（[^,] 防跨逗号误匹配，{0,12} 限制距离）
    HAS_WET_CLOTHING=$(echo "$PROMPT" | grep -qiE "(wet[^,]{0,12}($CLOTHES_PATTERN)|soaked[^,]{0,12}($CLOTHES_PATTERN)|drenched[^,]{0,12}($CLOTHES_PATTERN)|damp[^,]{0,12}($CLOTHES_PATTERN)|sodden[^,]{0,12}($CLOTHES_PATTERN)|soaking[^,]{0,12}($CLOTHES_PATTERN)|rain.?soaked[^,]{0,12}($CLOTHES_PATTERN)|wet.?through[^,]{0,12}($CLOTHES_PATTERN)|spit.?soaked[^,]{0,12}($CLOTHES_PATTERN)|drool.?soaked[^,]{0,12}($CLOTHES_PATTERN))" && echo 1 || echo 0)
    # 反序：衣物 + soaked/through/drenched（[^,] 同理）
    HAS_WET_CLOTHING_REV=$(echo "$PROMPT" | grep -qiE "($CLOTHES_PATTERN)[^,]{0,12}(soaked|drenched|soaking|sodden|wet.?through|damp)" && echo 1 || echo 0)
    # clinging + 湿/透明（仅限衣物上下文）
    HAS_CLINGING_WET=$(echo "$PROMPT" | grep -qiE "clinging.{0,10}(wet|soaked|damp|drenched)" && echo 1 || echo 0)
    # 穿着状态信号
    HAS_WORN=$(echo "$PROMPT" | grep -qiE "(wearing|clinging.{0,10}(to|on)|on (her|his|the|their) body|draped.{0,10}(over|across|on)|hugging.{0,10}(her|his|the|body)|clings to)" && echo 1 || echo 0)

    IS_WET_CLOTHING="0"
    if [ "$HAS_WET_CLOTHING" = "1" ] || [ "$HAS_WET_CLOTHING_REV" = "1" ] || [ "$HAS_CLINGING_WET" = "1" ]; then
        # 有穿着信号 或 湿+衣物 在同一描述中 → 确认穿着湿衣
        IS_WET_CLOTHING="1"
    fi

    if [ "$IS_WET_CLOTHING" = "1" ]; then
        # 检查是否有面料边界锚点
        HAS_FABRIC_EDGE=$(echo "$PROMPT" | grep -qiE "(fabric.{0,10}(edges|outline|boundary|silhouette|visible|distinct)|garment.{0,10}(outline|boundary|edges|silhouette|visible|distinct)|clothing.{0,10}(boundary|outline|edges|silhouette|visible|distinct)|distinct.{0,10}(garment|clothing|fabric).{0,10}(outline|boundary|edges)|visible.{0,10}(fabric|garment|clothing).{0,10}(edges|outline|boundary)|wrinkle.{0,10}(folds|creases).{0,10}(in|of).{0,10}(fabric|cloth|garment)|fabric.{0,10}(wrinkle|fold|crease)|saturated.{0,10}(wet).{0,10}(cotton|fabric|cloth)|weave.{0,10}texture|hem.{0,10}(visible|distinct|clear|edge)|collar.{0,10}(visible|distinct|clear|edge)|cuff.{0,10}(visible|distinct|clear|edge))" && echo 1 || echo 0)
        if [ "$HAS_FABRIC_EDGE" = "0" ]; then
            echo -e "${RED}❌ [严重] §17-11 湿衣边界缺失${NC}"
            echo -e "${YELLOW}   检测到穿着湿衣描述但缺少面料边缘锚点${NC}"
            echo -e "${YELLOW}   → 模型会把湿布料渲染成半透明贴肤层，与皮肤融合，丢失衣物轮廓${NC}"
            echo -e "${GREEN}   修正：在湿衣描述后加 'with visible fabric edges and wrinkle folds, distinct garment outline against skin'${NC}"
            ERRORS=$((ERRORS + 1))
            echo ""
        fi
    fi
fi

# ============================================
# 18. 特写画面解剖学检查
# 本章处理“极特写 / macro / close-up”下的局部解剖和真实感：
# - 私处特写的结构拆分
# - 乳房极特写的自然形状/纹理建议
# 新增规则示例：
# - close-up vulva 但没有任何 labia / clitoral hood 词 → 放这里
# ============================================
echo -e "${BLUE}━━ 18. 特写画面解剖学检查 ━━${NC}"
echo ""

# 乳房特写检查（缩窄触发范围 - 仅极致特写/明确乳房焦点）
# v3.1: 排除 medium close-up 和手机画质，瑕疵为美服务
if echo "$PROMPT" | grep -qiE "extreme.*close-up.*breast|breast.*extreme.*close-up|breasts.*filling.*frame|nipple.*detail|areola.*close|breast.*macro" && ! echo "$PROMPT" | grep -qiE "phone|smartphone|amateur|mobile.*photo|casual.*shot"; then
    # 检查是否有自然形状限定词（降为WARNING）
    if ! echo "$PROMPT" | grep -qiE "natural.*shape|natural.*breast|slight.*asymmetry|asymmetrical|gravity.*affected|realistic.*shape"; then
        echo -e "${YELLOW}⚠️  [警告] 乳房极致特写建议添加自然形状限定词 - 非必须${NC}"
        echo -e "${BLUE}   建议: 如需自然感可加 natural shape, slight asymmetry, gravity affected${NC}"
        WARNINGS=$((WARNINGS + 1))
        echo ""
    fi
    # 检查是否有皮肤纹理（降为WARNING）
    if ! echo "$PROMPT" | grep -qiE "skin.*texture|visible.*pores|subtle.*veins|realistic.*skin|natural.*skin"; then
        echo -e "${YELLOW}⚠️  [警告] 乳房极致特写建议补充皮肤质感 - 非必须${NC}"
        echo -e "${BLUE}   建议: 如需写实感可加 skin texture, subtle veins（手机/甜美风格可不加）${NC}"
        WARNINGS=$((WARNINGS + 1))
        echo ""
    fi
fi

# 私处特写检查（严格模式 - ERROR）
if echo "$PROMPT" | grep -qiE "close-up.*pussy|close-up.*vulva|pussy.*close-up|vulva.*close-up|extreme.*close-up.*pussy|labia.*detail|genitalia.*close"; then
    # 检查是否分解了解剖结构
    ANATOMY_COUNT=0
    if echo "$PROMPT" | grep -qiE "labia.*majora|outer.*labia|outer.*lips"; then ANATOMY_COUNT=$((ANATOMY_COUNT + 1)); fi
    if echo "$PROMPT" | grep -qiE "labia.*minora|inner.*labia|inner.*lips"; then ANATOMY_COUNT=$((ANATOMY_COUNT + 1)); fi
    if echo "$PROMPT" | grep -qiE "clitoral.*hood|clitoris"; then ANATOMY_COUNT=$((ANATOMY_COUNT + 1)); fi
    if echo "$PROMPT" | grep -qiE "vaginal.*opening|introitus"; then ANATOMY_COUNT=$((ANATOMY_COUNT + 1)); fi
    
    if [ $ANATOMY_COUNT -lt 2 ]; then
        echo -e "${RED}❌ [严重] 私处特写解剖结构不足 - 会产生"一坨糊"${NC}"
        echo -e "${YELLOW}   发现: 仅 $ANATOMY_COUNT 个解剖结构词（需≥2个）${NC}"
        echo -e "${GREEN}   修正: 添加 labia majora, labia minora, clitoral hood, vaginal opening（至少2个）${NC}"
        ERRORS=$((ERRORS + 1))
        echo ""
    fi
    # 检查是否有解剖学正确性词
    if ! echo "$PROMPT" | grep -qiE "anatomically.*correct|realistic.*anatomy|natural.*proportion|detailed.*anatomy"; then
        echo -e "${RED}❌ [严重] 私处特写缺少解剖学正确性限定 - 形状会失真${NC}"
        echo -e "${YELLOW}   发现: 特写但未限定解剖学正确性${NC}"
        echo -e "${GREEN}   修正: 添加 anatomically correct, realistic anatomy, natural proportions${NC}"
        ERRORS=$((ERRORS + 1))
        echo ""
    fi
fi

# 通用特写真实感检查（WARNING - 瑕疵为美服务，不强制）
# ⚠️ 排除手机画质/生活感风格（这类风格自带质感，加纹理反而脏）
if echo "$PROMPT" | grep -qiE "extreme.*close-up|ECU|macro|lens.*ultra.*close" && ! echo "$PROMPT" | grep -qiE "phone|smartphone|amateur|mobile.*photo|casual.*shot"; then
    # 检查是否有自然瑕疵（仅当追求超写实风格时才需要）
    if ! echo "$PROMPT" | grep -qiE "natural.*imperfection|slight.*asymmetry|asymmetrical|realistic.*imperfection|photorealistic|8k"; then
        echo -e "${YELLOW}⚠️  [警告] 极致特写建议添加瑕疵/真实感 - 但非必须（瑕疵为美服务）${NC}"
        echo -e "${BLUE}   建议: 如需超写实可加 natural imperfections, slight asymmetry（手机画质/女友甜美感不加）${NC}"
        WARNINGS=$((WARNINGS + 1))
        echo ""
    fi
    # 皮肤细节检查（WARNING，非阻断）
    if ! echo "$PROMPT" | grep -qiE "skin.*texture|skin.*fold|pores.*visible|fine.*lines|photorealistic|realistic.*skin"; then
        echo -e "${YELLOW}⚠️  [警告] 极致特写建议补充皮肤细节 - 但非必须（风格优先）${NC}"
        echo -e "${BLUE}   建议: 如需写实感可加 skin texture, fine lines（清纯/甜美/手机风格可不加）${NC}"
        WARNINGS=$((WARNINGS + 1))
        echo ""
    fi
fi

# ── §18-4 解剖器官移位与腹部位移防护 ──
# A. 上半身特写/镜中像视角与下身生殖器/阴毛矛盾（防阴毛逼画在胸上）
# 豁免条件：若包含 full body / wide shot / standing / kneeling / bottomless 等全身/下半身景别信号，则豁免
if echo "$PROMPT" | grep -qiE "waist up|from (the )?waist up|upper body focus|upper body shot|portrait framing|headshot|close-up on face|face close-up|chest shot|chest focus|cleavage focus|breasts? focus|sitting (for|at) (last minute )?makeup|adjusting earring|applying lipstick" \
   && ! echo "$PROMPT" | grep -qiE "full body|full length|wide shot|cowboy shot|bottomless|standing|kneeling|legs spread|legs visible" \
   && echo "$PROMPT" | grep -qiE "pubic hair|pubic mound|mons pubis|mons veneris|pussy|vulva|labia majora|labia minora|camel toe|cunt|snatch"; then
    echo -e "${RED}❌ [严重] §18-5 上半身/镜中像视角包含下身生殖器/阴毛描述 - 阴毛/逼会被误画在胸上${NC}"
    echo -e "${YELLOW}   发现: 画面视角限定于上半身/镜中像，但 Prompt 包含下身敏感器官与阴毛词（且无全身景别信号）${NC}"
    echo -e "${GREEN}   修正: 从提示词中移除 pubic hair, vulva, pussy, labia 等下身词，或将视角切换为全景/下半身${NC}"
    ERRORS=$((ERRORS + 1))
    echo ""
fi

# B. 孕妇/大孕肚视角缺少腹部解剖隔离词（防阴毛逼画在孕肚正中央）
if echo "$PROMPT" | grep -qiE "pregnant|pregnancy|belly in profile|round belly|pregnant belly|swollen belly" && echo "$PROMPT" | grep -qiE "pubic hair|pubic mound|mons pubis|mons veneris|pussy|vulva|labia"; then
    if ! echo "$PROMPT" | grep -qiE "strictly below|below the belly fold|inside lower crotch|crotch crease|clean smooth belly"; then
        echo -e "${YELLOW}⚠️  [警告] §18-6 孕妇/孕肚视角缺少腹部解剖隔离词 - 阴毛/逼可能被误画在孕肚正中央${NC}"
        echo -e "${YELLOW}   发现: 包含孕肚描述及阴毛/阴部词，但未标注 below the belly fold / inside lower crotch 限定${NC}"
        echo -e "${GREEN}   修正: 在下身描述添加 below the belly fold, inside lower crotch crease 或 clean smooth belly 隔离短语${NC}"
        WARNINGS=$((WARNINGS + 1))
        echo ""
    fi
fi

# ============================================
# 19. 纹身质量检查
# 本章只处理“纹身作为图像元素是否像真正长在皮肤上”：
# - 皮肤融合词
# - 颜色/墨水描述
# - CJK 文字纹身在侮辱/占有场景下的手写风格
# 新增规则示例：
# - tattoo 但没有任何 ink embedded / pores visible through ink → 放这里
# ============================================
echo -e "${BLUE}━━ 19. 纹身质量检查 ━━${NC}"
echo ""

# 检测是否有纹身/中文侮辱文字
HAS_TATTOO=$(echo "$PROMPT" | grep -qiE "\b(tattoo|tattooed|hand-poked|irezumi|ink.*dermis|ink.*tattoo)" && echo 1 || echo 0)

if [ "$HAS_TATTOO" = "1" ]; then
    # ── 检测是否是否定表达（偷懒写法）──
    IS_NEGATIVE=$(echo "$PROMPT" | grep -qiE "\b(no tattoo|without tattoo|clean skin|no marking|clean smooth|no ink)" && echo 1 || echo 0)
    if [ "$IS_NEGATIVE" = "1" ]; then
        echo -e "${YELLOW}⚠️ [警告] 检测到否定式纹身占位表达（no tattoo / clean skin 等）${NC}"
        echo -e "${YELLOW}   纹身已改为高优先级选填；若本卡确实不需要纹身，建议直接留空 slots.tattoo，而不是把否定占位词写进 prompt${NC}"
        echo -e "${GREEN}   若需要纹身：small butterfly on inner wrist, ink embedded in dermis, follows body contours${NC}"
        echo -e "${GREEN}   见 10-纹身标记.md §纹身风格库${NC}"
        WARNINGS=$((WARNINGS + 1))
        echo ""
    else
        # ── A. 皮肤融合词（核心融合6词，必含≥2个）──
        FUSION_COUNT=0
        echo "$PROMPT" | grep -qiE "realistic tattoo" && FUSION_COUNT=$((FUSION_COUNT + 1))
        echo "$PROMPT" | grep -qiE "ink embedded in dermis|ink embedded deep" && FUSION_COUNT=$((FUSION_COUNT + 1))
        echo "$PROMPT" | grep -qiE "beneath skin surface|tattoo beneath skin" && FUSION_COUNT=$((FUSION_COUNT + 1))
        echo "$PROMPT" | grep -qiE "follows body contour" && FUSION_COUNT=$((FUSION_COUNT + 1))
        echo "$PROMPT" | grep -qiE "slightly faded edge" && FUSION_COUNT=$((FUSION_COUNT + 1))
        echo "$PROMPT" | grep -qiE "pores visible through ink" && FUSION_COUNT=$((FUSION_COUNT + 1))

        if [ $FUSION_COUNT -lt 2 ]; then
            echo -e "${RED}❌ [严重] 纹身缺少皮肤融合词 — AI 会生成\"贴纸\"浮在皮肤上${NC}"
            echo -e "${YELLOW}   当前融合词数: $FUSION_COUNT / 至少需要2个${NC}"
            echo -e "${GREEN}   修正: realistic tattoo, ink embedded in dermis, follows body contours, slightly faded edges, pores visible through ink (6选2)${NC}"
            echo -e "${GREEN}   见 10-纹身标记.md §皮肤融合词${NC}"
            ERRORS=$((ERRORS + 1))
            echo ""
        fi

        # ── B. 颜色描述（除默认纯黑外任何颜色皆可，不再限定12色）──
        # 检测是否有任何颜色/墨水描述。无颜色描述 → AI 用默认纯黑，视觉效果差。
        HAS_TATTOO_COLOR=$(echo "$PROMPT" | grep -qiE "\b(pink ink|red ink|blue ink|green ink|purple ink|white ink|gold ink|bronze ink|silver ink|color ink|colored ink|black ink|dark.*ink|deep.*ink|ink in|sumi ink|carbon black|charcoal|sepia|crimson|scarlet|indigo|vermilion|permanent marker|sharpie|ballpoint|lipstick|chalk|spray.*paint|painted|henna|temporary|marker|stamp.*ink|seal impression|cinnabar|pastel|metallic|vibrant|muted|neon)\b" && echo 1 || echo 0)
        if [ "$HAS_TATTOO_COLOR" = "0" ]; then
            echo -e "${YELLOW}⚠️  [警告] 纹身缺少颜色描述 — AI 可能生成不自然的默认纯黑色${NC}"
            echo -e "${BLUE}   建议: 添加任意颜色/墨水词，如 pink ink / blue ink / black ink / permanent marker 等，不限颜色${NC}"
            WARNINGS=$((WARNINGS + 1))
            echo ""
        fi

        # ── C. 物理位置防位移安全保护（防纹身画在乳头/私处/肛门上） ──
        # 与 autofix / SAFE_TATTOOS 对齐：优先 sensitive areas；旧版 nipple/vulva/anus 句仍兼容
        # （勿建议写 vulva：会与 §17-5 visible.*vulva 跨句误伤，如 nipples visible + tattoo…vulva）
        if ! echo "$PROMPT" | grep -qiE "away from.*(sensitive areas?|nipple|vulva|anus|groin|private)"; then
            echo -e "${YELLOW}⚠️  [警告] 纹身缺少安全定位防位移词 — 可能会被 AI 误画在乳头/私处/肛门等敏感位置${NC}"
            echo -e "${BLUE}   建议: 在纹身描述末尾追加: tattoo placed strictly away from sensitive areas${NC}"
            WARNINGS=$((WARNINGS + 1))
            echo ""
        fi
    fi

    # ── C. 文字纹身手写风格 ──
    # 所有 CJK（中日韩汉字）纹身强制手写/记号笔风格，增加真实感，禁用书法字体。
    HAS_TEXT_TATTOO=$(python3 -c "
import sys, re
prompt = sys.argv[1].lower()

# 1. 显式文字纹身标识
explicit_markers = ['text tattoo', 'characters meaning', 'handwritten chinese',
    'handwritten japanese', 'handwritten korean', 'handwritten kanji',
    'handwritten.*character', 'written on.*skin',
    'writing on.*skin', 'marker.*tattoo']
for e in explicit_markers:
    if re.search(e, prompt):
        print(1); sys.exit(0)

# 2. 仅在“明确文字纹身语义”下，才把 CJK 视为文字纹身
cjk_runs = [(m.start(), m.end()) for m in re.finditer(r'[\\u4e00-\\u9fff]+', prompt)]
text_tattoo_positions = [m.start() for m in re.finditer(r'\b(?:text tattoo|character(?:s meaning)?|writing on skin|written on skin|handwritten|marker tattoo|marker handwriting|calligraphy|scribble|cursive|crooked)\b', prompt)]

if cjk_runs and text_tattoo_positions:
    for cs, ce in cjk_runs:
        for tp in text_tattoo_positions:
            if abs(tp - cs) < 80:
                print(1); sys.exit(0)

print(0)
" "$PROMPT")

    if [ "$HAS_TEXT_TATTOO" = "1" ]; then
        if ! echo "$PROMPT" | grep -qiE "permanent marker|sharpie|ballpoint pen.*writing|ballpoint.*pen.*writing|marker.*handwriting|messy.*handwritten|crooked.*uneven|crude.*handwritten|handwritten|hand-drawn|lipstick-written|smeared.*red|spray-painted|stencil.*overspray|blood-written|charcoal-written|stick-drawn|uneven line width|hand-poked|stick and poke|irregular stroke|slightly smudged|marker ink sheen|scratchy.*pen|rough sketch|crude.*stick|finger-drawn|drips of paint|street tagging|no computer font|no print typeface|no uniform strokes|no rigid lines|no square characters|no digital text|marker stroke"; then
            echo -e "${RED}❌ [严重] CJK 文字纹身缺少手写/记号笔风格词${NC}"
            echo -e "${GREEN}   修正: permanent marker handwriting / sharpie / messy handwritten / ballpoint pen writing${NC}"
            echo -e "${YELLOW}   禁止: brush calligraphy / flowing cursive / 书法字体${NC}"
            ERRORS=$((ERRORS + 1))
            echo ""
        fi
    fi
fi

# ============================================
# 输出结果
# ============================================
echo ""
echo "============================================"
echo "  📊 检查结果"
echo "============================================"

if [ $ERRORS -eq 0 ] && [ $WARNINGS -eq 0 ]; then
    echo -e "${GREEN}✅ 检查通过！未发现常见错误。${NC}"
    echo ""
    echo "提示词可以安全使用。"
    exit 0
elif [ $ERRORS -gt 0 ]; then
    echo -e "${RED}发现 $ERRORS 个严重错误${NC}"
    if [ $WARNINGS -gt 0 ]; then
        echo -e "${YELLOW}另有 $WARNINGS 个警告${NC}"
    fi
    echo ""
    echo -e "${RED}⚠️ 请在生成前修正严重错误，避免画面出现逻辑矛盾。${NC}"
    exit 1
else
    echo -e "${YELLOW}发现 $WARNINGS 个警告（不阻断生成）${NC}"
    echo ""
    echo -e "${YELLOW}⚠️ 建议修正警告项以提升画面质量。${NC}"
    exit 2
fi
