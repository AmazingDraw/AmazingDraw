#!/bin/bash
# check_prompt_multi.sh — 多人 / 3P 专用 prompt 检查
# exit 0 = pass, 1 = error, 2 = warning
set -euo pipefail

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" || "${1:-}" == "help" ]]; then
    echo "👥 多人 / 3P 场景合理性门禁校验脚本 (check_prompt_multi.sh)"
    echo "========================================="
    echo "用法:"
    echo "  $0 '<多人提示词内容>'"
    echo "  $0 <多人提示词文件路径>"
    echo ""
    echo "功能说明:"
    echo "  针对双女、多人、3P、双洞同插等复杂交互提示词进行专项校验，"
    echo "  防止出现肢体畸变、透视冲突或物理穿透等逻辑错误。"
    exit 0
fi

if [ "${#}" -gt 0 ]; then
  PROMPT="${*}"
else
  PROMPT="$(cat)"
fi

PROMPT="$PROMPT" python3 <<'PY'
import os, re, sys

prompt = os.environ.get('PROMPT', '')
text = prompt.lower()
errors = []
warnings = []

def has_any(words):
    return any(w in text for w in words)

def add_error(msg, found="", fix=""):
    if not any(e[0] == msg for e in errors):
        errors.append((msg, found, fix))

def add_warning(msg, fix=""):
    if not any(w[0] == msg for w in warnings):
        warnings.append((msg, fix))

def find_proximity_conflict(words1, words2, max_dist=50):
    """
    检查两个词集中的词是否在较近的距离内出现（同一主体）。
    这能极其精确地避免多人场景下的跨角色误判。
    """
    for w1 in words1:
        for w2 in words2:
            # 搜索 w1 ... w2
            p1 = re.compile(r'\b' + re.escape(w1) + r'\b.{0,' + str(max_dist) + r'}\b' + re.escape(w2) + r'\b', re.IGNORECASE)
            m1 = p1.search(text)
            if m1:
                return m1.group()
            # 搜索 w2 ... w1
            p2 = re.compile(r'\b' + re.escape(w2) + r'\b.{0,' + str(max_dist) + r'}\b' + re.escape(w1) + r'\b', re.IGNORECASE)
            m2 = p2.search(text)
            if m2:
                return m2.group()
    return None

# =====================================================================
# ─── §1 服装/裸露状态 (含乳头/乳房/自然重力与皮肤纹理) ─────────────────
# =====================================================================

# §1-1 乳头/乳房细节与自然皮肤纹理
has_breast_detail = has_any(['nipple', 'areola', 'bare breast', 'exposed breast', 'bare nipples'])
if has_breast_detail:
    texture_words = [
        'areola texture', 'montgomery glands', 'montgomery', 'skin pores', 'visible pores', 'areola detail', 
        'natural areola', 'natural nipple', 'natural skin texture', 'slight asymmetry', 'asymmetrical areola', 
        'uneven areola', 'natural pigmentation', 'skin detail', 'realistic skin', 'bumpy areola', 'puffy areola', 
        'puffy nipple', 'small areola', 'large areola', 'wide areola', 'pale areola', 'dark areola', 'brown areola', 
        'pink-brown gradient', 'wrinkled areola', 'wrinkled nipple', 'inverted nipple', 'flat nipple', 'nipple pointing', 
        'nipple slightly higher', 'nipple slightly darker', 'freckle on areola', 'mole near nipple', 'underboob crease', 
        'natural gravity pull', 'breast with natural', 'asymmetrical breast', 'slightly sagging', 'skin fold', 
        'perky nipple', 'nipple with', 'tan areola', 'purplish-pink', 'light pink nipple', 'one nipple', 'color gradient', 
        'brown nipple', 'areola bump', 'areola edge', 'bumpy texture around'
    ]
    if not any(w in text for w in texture_words):
        add_warning(
            '§1-1 发现乳头/乳房暴露，但缺少自然生理特征/皮肤纹理词汇（容易导致AI生成塑料感/死白乳房）',
            '建议在 breast/nipple 后面补充 areola texture, skin pores, underboob crease 或 natural gravity pull 等自然生理细节词'
        )

# §1-2 内裤与私处暴露冲突
if has_any(['panties', 'underwear']):
    fixed_text = text
    panty_remove_keywords = [
        'panties pulled aside', 'panties down', 'panties pulled down', 'panties pulled to one side',
        'panties on ankles', 'panties around ankle', 'panties around leg', 'panties on one leg',
        'panties at knee', 'panties tangled', 'panties half off', 'panties off body', 'panties falling',
        'panties hanging', 'panties bunched', 'underwear off body',
        'no panties', 'without panties', 'no underwear', 'without underwear', 'pantyless', 'underwearless'
    ]
    for w in panty_remove_keywords:
        fixed_text = fixed_text.replace(w, '')
    if any(p in fixed_text for p in ['panties', 'underwear']):
        if any(pv in fixed_text for pv in ['pussy', 'vulva']):
            add_error(
                '§1-2 内裤与私处同时出现（且未注明移位/脱下） — AI会产生矛盾理解',
                'wearing panties + bare pussy/vulva',
                '删除内裤描述（使用 no panties/bottomless）或删除私处细节，或注明内裤已拉下/移开（如 panties pulled aside）'
            )

# §1-3 女警警服颜色样式检查
is_cop = has_any(['police', 'cop', 'policewoman', '警服', '女警'])
if is_cop:
    dark_blue_cop_patterns = [
        r'\b(dark\s+blue|navy\s+blue|navy)\s+(police\s+|cop\s+)?(uniform|costume|shirt|attire|outfit|skirt)\b',
        r'\b(uniform|costume|shirt|attire|outfit|skirt)\b.*\b(dark\s+blue|navy\s+blue|navy)\b',
        r'(深蓝色|深蓝|藏青色|藏青)警服'
    ]
    has_ugly = False
    for pat in dark_blue_cop_patterns:
        m = re.search(pat, text)
        if m:
            add_error(
                '§1-3 检测到女警身份使用了被禁止的深蓝色警服。深蓝色警服很土很丑，已强力拦截！',
                m.group(0),
                '建议使用：浅蓝色警服（例如 "tight low-cut light blue police shirt and sexy white bodycon police skirt"），或者黑色乳胶警服（"sexy black latex cop bodysuit"）。'
            )
            has_ugly = True
            break
            
    if not has_ugly:
        has_generic = False
        found_word = ""
        for m in re.finditer(r'\b(police|cop)\s+(uniform|costume|shirt|attire|outfit|skirt)\b', text):
            start = m.start()
            prefix = text[max(0, start-30):start]
            approved_en = ['light blue', 'light-blue', 'baby blue', 'sky blue', 'white', 'latex', 'vinyl', 'leather', 'shiny', 'pink', 'low-cut', 'tight', 'sexy', 'bodycon', 'form-fitting', 'open']
            if not any(w in prefix for w in approved_en):
                has_generic = True
                found_word = m.group(0)
                break
        if not has_generic:
            for m in re.finditer(r'警服|警裙|警衣', prompt):
                start = m.start()
                prefix = prompt[max(0, start-10):start]
                approved_zh = ['浅蓝', '白色', '乳胶', '漆皮', '粉色', '低胸', '紧身', '包臀']
                if not any(w in prefix for w in approved_zh):
                    has_generic = True
                    found_word = m.group(0)
                    break
        if has_generic:
            add_error(
                '§1-3 检测到女警身份使用了未指定颜色/样式的普通警服。为了防止模型默认画出土气丑陋的深蓝色警服，必须显式指定警服颜色和样式。',
                found_word,
                '建议使用：浅蓝色警服（例如 "tight low-cut light blue police shirt and sexy white bodycon police skirt"），或者黑色乳胶警服（"sexy black latex cop bodysuit"）。'
            )

# =====================================================================
# ─── §1b 阴毛与私处暴露合理性 ──────────────────────────────────────────
# =====================================================================

if has_any(['pubic hair', 'bush']):
    if not has_any(['mons pubis', 'above pussy', 'just above pussy', 'on mons']):
        add_warning(
            '§1b-1 阴毛(pubic hair)描述缺少位置锚点，易画错位置',
            '在 pubic hair/bush 后紧跟 on mons pubis 或 just above pussy 锚定位置'
        )

# =====================================================================
# ─── §2 透明/穿透布料 ────────────────────────────────────────────────
# =====================================================================

# 检查 see-through/sheer 穿透敏感部位
m_sheer = find_proximity_conflict(
    ['sheer', 'see-through', 'transparent'],
    ['nipple', 'nipples', 'areola', 'vulva', 'pussy'],
    max_dist=40
)
if m_sheer:
    # 检查是否已说明布料移开
    if not has_any(['unbuttoned', 'open', 'slipping off', 'falling off', 'lifted', 'pulled', 'removed', 'bare', 'fully exposed', 'completely open']):
        add_error(
            '§2 透明布料穿透展示敏感部位 — 极易产生物理穿透畸形',
            m_sheer,
            '建议将衣服改为敞开式 (open) 衣物描述，如 \"open shirt showing breasts\" 或 \"bra lifted exposing nipples\"'
        )

# =====================================================================
# ─── §3 身体朝向与可见性 (多人安全版) ──────────────────────────────────
# =====================================================================

# 1) 后入与正脸直视冲突 (只限于单主体描述中，多人可能一个是后入一个是正脸)
m_rear_face = find_proximity_conflict(
    ['from behind', 'rear view', 'back view', '后入', '从后面'],
    ['frontal face', 'facing camera fully', 'full face to camera', '正脸直视'],
    max_dist=40
)
if m_rear_face:
    add_error(
        '§3-1 同一主体后入/背面视角与正脸直视描述重叠，视角冲突',
        m_rear_face,
        '建议将正脸直视 (facing camera fully) 改为回头望向镜头 (looking back over shoulder)'
    )

# 2) 同一主体姿势冲突 (doggy vs missionary)
m_pose_conflict = find_proximity_conflict(
    ['on all fours', 'doggy', '四肢着地', '狗爬'],
    ['lying on back', 'missionary', '仰躺', '传教士'],
    max_dist=40
)
if m_pose_conflict:
    add_error(
        '§3-2 同一主体同时描述了 doggy 与 missionary/仰躺 姿势，发生物理矛盾',
        m_pose_conflict,
        '二选一进行保留：保留 doggy 姿势，或保留仰躺/传教士姿势，不要在同一主体句中混用'
    )

# 3) 坐在边缘却双腿并拢 (常用于插入动作的物理矛盾)
m_sit_close = find_proximity_conflict(
    ['sitting on edge of seat', 'edge of bench', '坐在边缘'],
    ['knees together', 'legs closed', '双腿并拢'],
    max_dist=40
)
if m_sit_close:
    add_error(
        '§3-3 坐在边缘插入场景却描述双腿并拢，物理上无法完成交互',
        m_sit_close,
        '将双腿并拢 (legs closed) 修正为双腿大张 (legs spread wide)'
    )

# =====================================================================
# ─── §4 液体物理与质感 ────────────────────────────────────────────────
# =====================================================================

# 1) 液体物理冲突 (禁止液体漂浮或向上流动)
if re.search(r'\b(flowing up|going upward|upward flow)\b', text, re.IGNORECASE):
    add_error('§4-1 液体向上流动 — 违反重力与物理常识', 'flowing up', '改为 dripping down 向下滴落')
if re.search(r'\b(floating semen|floating drool|floating saliva|floating cum|cum floating|semen floating)\b', text, re.IGNORECASE):
    found_float = re.search(r'\b(floating semen|floating drool|floating saliva|floating cum|cum floating|semen floating)\b', text, re.IGNORECASE).group()
    add_error('§4-2 液体在空中悬浮/漂浮 — 违反重力与物理常识', found_float, '改为 dripping down 或 splashing 飞溅动作')

# 2) 精液质感与高危动作校验
if re.search(r'\b(cum|semen|ejaculate|sperm|cumshot)\b', text, re.IGNORECASE):
    texture_words = ['translucent', 'semi-translucent', 'viscous', 'glistening', 'opalescent sheen', 'dewy wet', 'fluid settling', 'thin film coating']
    if not any(w in text for w in texture_words):
        add_error('§4-3 精液缺少高级质感修饰词 — 容易产生死白油漆感', 'cum/semen', '添加半透明/黏稠质感词，如 semi-translucent, viscous 或 glistening 等修饰')
    
    spray_match = re.search(r'\b(cumshot|shooting|spraying|splattering|splash|splashed|fountain|gushing|blast|sprayed)\b', text, re.IGNORECASE)
    if spray_match:
        add_error('§4-4 精液使用高风险喷射动作 — 易导致物理崩坏', spray_match.group(), '建议移除飞溅/喷射动作，改为静态附着或流淌，如 glistening on skin, trailing down, trickling down')
    
    # 精液在额头/发际线 — 美学干扰
    m_forehead = re.search(r'\b(cum|semen|ejaculate|sperm|cumshot)\b.{0,20}\b(forehead|brow|hairline|temple)\b', text, re.IGNORECASE)
    if not m_forehead:
        m_forehead = re.search(r'\b(forehead|brow|hairline|temple)\b.{0,20}\b(cum|semen|ejaculate|sperm|cumshot)\b', text, re.IGNORECASE)
    if m_forehead:
        add_error('§4-5 精液在额头/发际线 — 美学干扰', m_forehead.group(), '精液应避开额头高位，分布在 cheekbones / neck / breasts / collarbone')

# =====================================================================
# ─── §7 布料物理/穿着状态 (含干湿发与松紧矛盾) ─────────────────────────
# =====================================================================

# 1) 无扣衣物强行解扣
# 注意：裸 \bbra\b 会误伤 "no bra / without bra / braless + blouse|shirt unbuttoned"
# （与单人 check_prompt.sh §7-4 对齐：先匹配明确无扣衣，再对 bra 做否定剥离后二次判断）
unbuttonless_tops = r'\b(sports\s+top|sports\s+bra|crop\s+top|tank\s+top|t-shirt|tshirt|bikini\s+top)\b'
m_unbuttonless = re.search(unbuttonless_tops + r'.{0,30}\bunbuttoned\b', text, re.IGNORECASE)
if not m_unbuttonless:
    m_unbuttonless = re.search(r'\bunbuttoned\b.{0,30}' + unbuttonless_tops, text, re.IGNORECASE)
if m_unbuttonless:
    add_error(
        '§7-1 无扣衣物强行解扣 — 逻辑冲突伪影风险',
        m_unbuttonless.group(),
        '运动背心/运动文胸/短袖/内衣没有纽扣，请勿使用 unbuttoned。建议改为 pulled down (拉下)、pulled up (拉起) 或 removed (脱下) 配合 exposed 描述'
    )
else:
    # 真·文胸解扣：剥离否定后再看是否仍有 bra + unbuttoned
    bra_probe = re.sub(r'\b(?:no|without)\s+bras?\b', ' ', text, flags=re.IGNORECASE)
    bra_probe = re.sub(r'\bbraless\b', ' ', bra_probe, flags=re.IGNORECASE)
    m_bra_unbuttoned = re.search(r'\bbra\b.{0,30}\bunbuttoned\b', bra_probe, re.IGNORECASE)
    if not m_bra_unbuttoned:
        m_bra_unbuttoned = re.search(r'\bunbuttoned\b.{0,30}\bbra\b', bra_probe, re.IGNORECASE)
    if m_bra_unbuttoned:
        add_error(
            '§7-1 无扣衣物强行解扣 — 逻辑冲突伪影风险',
            m_bra_unbuttoned.group(),
            '文胸没有纽扣，请勿使用 unbuttoned。建议改为 bra pulled down / bra pushed aside / bra removed'
        )

# 2) 湿发蓬松物理矛盾
if has_any(['wet hair', 'damp hair', 'soaked hair', 'hair wet', 'wet strands']) and has_any(['fluffy', 'voluminous', '蓬松']):
    add_warning(
        '§7-2 湿发与蓬松(fluffy/voluminous)矛盾',
        '湿发应贴紧皮肤，建议使用 wet hair clinging to skin 或 heavy wet strands 替换'
    )

# 3) 湿衣服呈现干燥外观
if has_any(['wet clothes', 'soaked clothes', 'wet outfit']) and has_any(['dry look', 'fluffy', '干燥']):
    add_warning(
        '§7-3 湿衣服却呈干燥状态',
        '湿衣服应有贴身、垂坠感，建议使用 wet clothes clinging to skin 替换'
    )

# 4) 脱衣动作与穿着状态矛盾
if has_any(['undressing', 'removing clothing']) and has_any(['fully clothed', 'fully dressed']):
    add_error(
        '§7-4 脱衣动作与完全穿着状态冲突',
        'undressing + fully clothed',
        '统一动作与服装状态，二选一进行保留'
    )

# =====================================================================
# ─── §9 场景光源与时间 ────────────────────────────────────────────────
# =====================================================================

if re.search(r'\b(midnight|2am|night|dark night)\b', text, re.IGNORECASE) and re.search(r'\b(bright sunlight|direct sunlight|sun shining|sunlit)\b', text, re.IGNORECASE):
    add_error('§9-1 深夜与直射阳光并存 — 违反天时与光源常识', 'midnight + sunlight', '二选一：改深夜为 midday 中午，或将直射阳光改为 moonlight/streetlights')
if re.search(r'\b(sunset|dawn)\b', text, re.IGNORECASE) and re.search(r'\b(midnight|2am|late night)\b', text, re.IGNORECASE):
    add_error('§9-2 日落/黎明与深夜并存 — 违反天时常识', 'sunset/dawn + midnight', '统一时间：全部使用 sunset 或全部使用 midnight')

# =====================================================================
# ─── §10 镜子与反射物理一致性 ──────────────────────────────────────────
# =====================================================================

if re.search(r'\bmirror\b', text, re.IGNORECASE):
    if re.search(r'\b(facing away|back turned|looking away)\b', text, re.IGNORECASE) and re.search(r'\b(reflection.*looking at camera|reflection.*facing camera)\b', text, re.IGNORECASE):
        add_error('§10 人物背对镜子但镜中反射正面直视 — 违反反射几何逻辑', 'facing away + reflection looking at camera', '移除镜中正面直视描述，或将主人物改为 front-facing 正面对镜')

# =====================================================================
# ─── §11 负面词/嘴部风险/面部精液 ──────────────────────────────────────
# =====================================================================

# 1) 咬嘴唇畸形高危词
if has_any(['biting lip', 'lip between teeth', 'teeth pressing into lip']):
    add_error('§11-1 牙齿咬嘴唇描述，极易生成嘴部畸形', 'biting lip / lip between teeth', '使用 lips slightly parted / tense mouth 代替，不提及牙齿接触嘴唇')

# 2) 唾液呈白色
if has_any(['drool', 'saliva', '口水']) and has_any(['milky', '乳白', 'white drool', 'white saliva']):
    add_error('§11-2 口水呈白色/乳白色，违反生理常识', 'white/milky drool/saliva', '将白色 (white/milky) 修正为透明 (clear/translucent)')

# 3) 面部关键部位精液遮挡
if has_any(['cum', 'semen', 'ejaculate', 'sperm', 'cumshot']) or has_any(['dripping']):
    m_mouth = re.search(r'\b(cum|semen|ejaculate|sperm|cumshot)\b.{0,20}\b(chin|nose|nostril|nostrils|mouth|lip|lips|tongue|throat|inside\s+mouth|lip\s+corner|corner\s+of\s+mouth)\b', text, re.IGNORECASE)
    if not m_mouth:
        m_mouth = re.search(r'\b(chin|nose|nostril|nostrils|mouth|lip|lips|tongue|throat|inside\s+mouth|lip\s+corner|corner\s+of\s+mouth)\b.{0,20}\b(cum|semen|ejaculate|sperm|cumshot)\b', text, re.IGNORECASE)
    m_drip = re.search(r'\bdripping\b.{0,20}\bfrom\b.{0,10}\b(chin|nose|mouth|lips?|tongue|lip\s+corner|corner\s+of\s+mouth)\b', text, re.IGNORECASE)
    
    found_mouth = None
    if m_mouth:
        found_mouth = m_mouth.group()
    elif m_drip:
        found_mouth = m_drip.group()
        
    if found_mouth:
        add_error('§11-3 面部关键部位精液遮挡风险', found_mouth, '精液在嘴唇、下巴、鼻孔等位置会严重干扰面部五官识别，建议改到脸颊或锁骨，如 cum on cheeks / glistening on collarbone')

# 4) 眼睛关键部位精液遮挡
if re.search(r'\b(cum|semen|ejaculate|sperm|cumshot)\b', text, re.IGNORECASE):
    m_eye = re.search(r'\b(cum|semen|ejaculate|sperm|cumshot)\b.{0,30}\beye(s)?\b', text, re.IGNORECASE)
    if not m_eye:
        m_eye = re.search(r'\beye(s)?\b.{0,30}\b(cum|semen|ejaculate|sperm|cumshot)\b', text, re.IGNORECASE)
    if m_eye:
        matched_str = m_eye.group()
        if not re.search(r'(closed|eyelid|around|under|shut)', matched_str, re.IGNORECASE):
            add_error('§11-4 眼睛关键部位精液遮挡', matched_str, '精液直接附着在睁开的眼睛上易产生五官畸变，改到闭着的眼睑上 (closed eyelids) 或眼周/眼下 (around/under eyes)')

# =====================================================================
# ─── §13 肢体数量/归属/人数匹配 ────────────────────────────────────────
# =====================================================================

# 1) 手臂/腿部异常数量
if has_any(['three arms', 'four arms', 'five arms', 'six arms', '三只手', '四只手', '五只手', '六只手']):
    add_error('§13-1 直接写出异常手臂数量，极易导致肢体崩坏', 'three/four arms', '去掉异常手臂数量词，由多人物理空间关系自然带出肢体')
if has_any(['three legs', 'four legs', 'five legs', 'six legs', '三条腿', '四条腿', '五条腿', '六条腿']):
    add_error('§13-2 直接写出异常腿部数量，极易导致肢体崩坏', 'three/four legs', '去掉异常腿部数量词，由多人物理空间关系自然带出肢体')

# 2) 单人手部动作过载矛盾 (限制在 40 字邻近空间内，避免误判多人)
m_hand_overload1 = find_proximity_conflict(
    ['both hands on her hips'],
    ['holding his penis', 'gripping the bench', 'covering her mouth', '双手扶胯'],
    max_dist=40
)
if m_hand_overload1 and not has_any(['another girl', 'other hand', '第三只手']):
    add_warning('§13-3 同一主体手部任务过载（如双手扶胯又拿东西），可能产生多余肢体', '建议具体指明是 another person/girl 的手在做什么，避免单个主体分身')

m_hand_overload2 = find_proximity_conflict(
    ['both hands gripping bench'],
    ['holding phone', 'touching breast', '扶着头'],
    max_dist=40
)
if m_hand_overload2 and not has_any(['another girl', 'other hand']):
    add_warning('§13-4 同一主体双手已占满又被分配额外手部动作，可能产生多余肢体', '建议去掉冲突的手部动作，保持双手各做一件事')

# =====================================================================
# ─── §17 姿势/遮挡/构图组合矛盾 (含绳缚与自拍) ──────────────────────────
# =====================================================================

# 1) 自拍手部动作冲突
if re.search(r'\b(selfie|taking\s+selfie|holding\s+phone)\b', text, re.IGNORECASE):
    m_hand_conflict = re.search(r'\bboth\s+hands\b|\bhands\b.*(cover|grip|press|hold|touch|rest)\b|\b(cover|grip|press|hold|touch|rest)\b.*\bhands\b', text, re.IGNORECASE)
    if m_hand_conflict and not re.search(r'\b(tripod|monopod|selfie\s+stick|phone\s+on\s+table)\b', text, re.IGNORECASE):
        add_error('§17-2 自拍动作手部冲突 — 防止自拍时描述双手动作导致生成三只手', 
                  m_hand_conflict.group(), 
                  '将自拍改为 tripod/monopod，或者只在自拍时保留一只手的动作描述，另一只手拿手机')

# 2) 绳缚位置校验 (绳子穿过私处)
if re.search(r'\b(rope|shibari|bondage|restraint|suspension|chain|cord|harness)\b', text, re.IGNORECASE):
    m_rope = re.search(r'\b(rope|shibari|bondage|restraint|suspension|chain|cord|harness)\b.{0,20}\b(vulva|labia|slit|crotch|pussy|anus|asshole|vagina|clitoris|body\s+opening(s)?)\b', text, re.IGNORECASE)
    if not m_rope:
        m_rope = re.search(r'\b(vulva|labia|slit|crotch|pussy|anus|asshole|vagina|clitoris|body\s+opening(s)?)\b.{0,20}\b(rope|shibari|bondage|restraint|suspension|chain|cord|harness)\b', text, re.IGNORECASE)
    if m_rope:
        add_error('§17-9 绳缚位置错误 — 绳子/链条穿过私处或身体开口易产生解剖学扭曲和穿透畸形', 
                  m_rope.group(), 
                  '改到耻骨上方、臀股沟外或大腿内侧，如 rope tension above mons pubis / along hips / along inner thighs')

# 3) 侧面视角乳头分叉风险 (只限 side view 紧邻 nipples，避免误判多人)
m_side_nipples = find_proximity_conflict(
    ['side view', 'profile view', 'from the side', 'side profile'],
    ['nipples'],
    max_dist=30
)
if m_side_nipples and not has_any(['one nipple', 'single nipple', 'other nipple occluded']):
    add_error('§11-3 侧面视角乳头分叉风险 — 侧向透视时若不限定单侧可见，易在单侧乳房生成两个乳头', 
              m_side_nipples, 
              '将 nipples 改为 one nipple visible 并加 other nipple occluded')

# =====================================================================
# ─── §19 纹身质量与 CJK 规范 ──────────────────────────────────────────
# =====================================================================

if re.search(r'\b(tattoo|inked skin|body art)\b', text, re.IGNORECASE):
    if not (re.search(r'ink embedded in dermis', text, re.IGNORECASE) or re.search(r'follows body contour', text, re.IGNORECASE)):
        add_error('§19 纹身描述缺少融合词 — 容易产生浮贴纸感', 'tattoo', '添加 ink embedded in dermis 或 follows body contour 使其融入皮肤纹理')
    
    # CJK 纹身强制手写/记号笔风格
    if re.search(r'(汉字|中文|文字|字样|手写|字符|书写)', prompt) or any(ord(c) > 127 for c in prompt):
        if not re.search(r'\b(handwritten|marker|sharpie|marker style|hand-drawn)\b', text, re.IGNORECASE):
            add_warning('§19 发现 CJK 文字纹身 — 缺少笔法和物理笔触风格修饰词', '建议添加 marker style 或 handwritten 风格修饰词')

# =====================================================================
# ─── 多人/3P 场景特设校验（专项防散架） ──────────────────────────────────
# =====================================================================

# 1) 多人基本多人场景提示
multi_markers = [
    '3p', 'threesome', 'double penetration', 'oral + vaginal', 'oral and vaginal',
    'two men', 'two cocks', 'one in mouth', 'one in pussy', 'mouth and pussy',
    'two girls', 'three girls', '2girls', '3girls', 'all girls', 'lesbian group', 'girl on girl',
    'two people', 'two subjects', 'both girls', 'both boys', 'another girl', 'another boy',
    'another man', 'another woman', 'second girl', 'second boy', 'second man', 'second woman',
    'sisters', 'two sisters', 'three sisters', 'twin sisters',
    'exactly two', 'exactly two women', 'exactly two girls', 'no third person',
    '两男一女', '双洞同插', '前后夹击', '嘴和逼', '口交', '插嘴', '插逼',
    '多人', '三人', '双女', '两女', '三女', '多女', '群p', '群交', '百合', '磨豆腐',
    '双人', '两人', '两个女孩', '两个男人', '双飞', '夹攻', '同框', '合照', '加入一个', '另一个', '男主', '女主',
    '三姐妹', '姐妹花', '两个妹妹', '两姐妹', '双胞胎', '三胞胎', '母女', '闺蜜组合'
]
if not has_any(multi_markers):
    add_warning('当前 prompt 像是非多人场景', '若不是 3P/多人，建议回常规检查使用单人校验')

# 2) 基本插入位点一致性：双洞同插时，必须同时出现至少两个插入位点以确保合理性
oral_markers = ['mouth', 'oral', 'blowjob', 'deep throat', 'cock in mouth', 'inserting into her mouth', '嘴', '口交', '插嘴']
vaginal_markers = ['pussy', 'vagina', 'vaginal', 'labia', 'slit', 'cock in her pussy', 'inserted in her pussy', '逼', '小穴', '插逼']
vaginal_regex = r'\b(pussy|vagina|vaginal|labia|slit|cock in her pussy|inserted in her pussy)\b|逼|小穴|插逼'
anal_markers = ['anus', 'anal', 'asshole', '肛', '屁眼']

has_oral = has_any(oral_markers)
has_vag = bool(re.search(vaginal_regex, text)) or has_any(vaginal_markers)
has_anal = has_any(anal_markers)

# 如果明确指定了嘴和逼的双插模式，强校验口交位点与阴道位点
if has_any(['mouth and pussy', 'one in mouth', 'one in pussy']):
    if not has_oral:
        add_error('多人嘴和逼双插场景缺少口交位点（mouth/oral）', 'mouth and pussy / one in mouth / one in pussy', '添加 mouth/oral/blowjob 口交动作描述')
    if not has_vag:
        add_error('多人嘴和逼双插场景缺少阴道位点（pussy/vagina）', 'mouth and pussy / one in mouth / one in pussy', '添加 pussy/vagina 阴道插入动作描述')

# 如果使用了通用的双洞同插/前后夹击/DP描述，要求在口、阴道、肛门三者中至少描述两个，防止位点丢失导致AI画成单插或肢体混乱
if has_any(['double penetration', '双洞同插', '前后夹击']):
    active_points = [
        ('口交位点 (mouth/oral)', has_oral),
        ('阴道位点 (pussy/vagina)', has_vag),
        ('肛门位点 (anus/anal)', has_anal)
    ]
    detected_count = sum(1 for name, ok in active_points if ok)
    if detected_count < 2:
        add_error(
            '多人双插场景缺少足够的位点描述，必须至少同时包含口(mouth)、阴道(pussy)或肛门(anus)中的任意两个位点以确保画面合理性',
            'double penetration / 双洞同插 / 前后夹击',
            '补充缺少的动作描述，例如同时包含 vagina (阴道) 与 anus (肛门)，或 mouth (口) 与 vagina (阴道) 的动作描述'
        )

# 3) 人数 / 生殖器数量对齐
if has_any(['two men', '两男', '2 men']) and not has_any(['two cocks', 'two dicks', '两根鸡巴', '两个男人', 'each man', 'both men']):
    add_warning('已写 two men / 两男，但未明确两根阴茎参与', '建议补充 two cocks/two dicks 词汇并补强人物站位与器官位置关系')

# 4) 多女场景：至少要有互动 / 空间关系，否则容易散架
if has_any(['two girls', 'three girls', '2girls', '3girls', '双女', '两女', '三女', '多女', '百合', '磨豆腐', 'sisters', 'two sisters', 'three sisters', 'twin sisters', '三姐妹', '姐妹花', '两个妹妹', '两姐妹', '双胞胎', '三胞胎', '母女']):
    if not has_any(['kissing', 'licking', 'embracing', 'grinding', 'touching', 'straddling', 'scissoring', 'fingering', '互摸', '亲吻', '舔', '抱', '骑乘', '磨蹭']):
        add_warning('多女场景已成立，但缺少明确互动动作，容易画成松散同框', '建议补充 kissing/licking/embracing 等明确亲密互动词汇以防画面松散')
    if not has_any(['beside each other', 'one above the other', 'between her thighs', 'facing each other', 'side by side', 'wrapped around', 'kneeling between', '面对面', '并排', '压在身上', '夹在腿间']):
        add_warning('多女场景缺少空间关系词，建议补充面对面/并排/一上一下/夹在腿间等', '建议补充 facing each other / beside each other / one above the other（勿写 two one above）')

# 5) 多人位姿最好显式写站位关系
if has_oral and has_vag and not has_any(['between her legs', 'beside her head', 'standing behind', 'in front of', '坐在旁边', '站在后面', '跪在头侧', '在她前面']):
    add_warning('多人双插已成立，但站位关系不够明确，建议补前/后/侧/头侧等空间关系', '添加 kneeling beside head, standing behind 等具体站位修饰')

# =====================================================================
# ─── §M 双人防崩硬规则（防第三人 / 融肢 / 姿势过载 / 纹身抢权重）──────
# =====================================================================

# M-1) 禁烂空间句：two one above (the other) — 语义糊，易拆第三人/乱肢
m_bad_spatial = re.search(r'\btwo\s+one\s+above(?:\s+the\s+other)?\b', text, re.IGNORECASE)
if m_bad_spatial:
    add_error(
        '§M-1 烂空间句 two one above — 易拆成第三人或肢体乱叠',
        m_bad_spatial.group(),
        '改为 one above the other，并加 exactly two heads / no third person；勿写 two one above'
    )

# M-2) 双女 + 亲密姿势：必须人数硬锚（exactly two / no third …）
duo_girl_markers = [
    'two girls', '2girls', '双女', '两女', '两个女孩', 'both girls', 'girl on girl',
    '闺蜜组合', 'two sisters', 'twin sisters', '两姐妹', '姐妹花', '两个妹妹', '双胞胎', 'two women', 'two people'
]
trio_or_more_markers = [
    'three girls', '3girls', '三女', 'three sisters', '三姐妹', '三胞胎',
    'threesome', '3p', 'three women', '三人', '多人', '群p', '群交'
]
duo_count_anchors = [
    'exactly two', 'only two', 'no third', 'no third person', 'no third girl',
    'exactly two heads', 'exactly two people', 'exactly two girls', 'exactly two women',
    'only two girls', 'only two women', 'two heads only', 'two pairs of arms',
    '仅两人', '刚好两人', '不要第三人', '没有第三人', '仅两女'
]
intimate_pose_markers = [
    'kissing', 'embracing', 'wrapping around', 'wrapped around', 'grinding',
    'straddling', 'scissoring', 'kneeling between', 'licking', 'fingering',
    '亲吻', '互吻', '环抱', '抱紧', '磨蹭', '骑乘'
]
is_duo_girls = has_any(duo_girl_markers) and not has_any(trio_or_more_markers)
if is_duo_girls and has_any(intimate_pose_markers) and not has_any(duo_count_anchors):
    add_error(
        '§M-2 双女亲密姿势缺少人数硬锚 — 复杂缠绕下易画出第三人',
        'two girls + intimate pose, missing exactly two / no third',
        '添加 exactly two adult women only, no third person, exactly two heads two pairs of arms two pairs of legs'
    )

# M-3) 亲密姿势动词堆叠上限（≥3 类同时出现 → 拦）
# 注意：arms/legs/hands wrapped around 是肢体动作，不算「身体缠绕」类姿势堆叠
pose_probe = re.sub(
    r'\b(?:arms?|legs?|hands?|手|臂|腿)\s+wrapped\s+around\b',
    ' ',
    text,
    flags=re.IGNORECASE,
)
pose_verb_patterns = [
    (r'\bkissing\b|亲吻|互吻', 'kissing'),
    (r'\bembracing\b|环抱|抱紧', 'embracing'),
    (r'\bwrapping\s+around\b|\bwrapped\s+around\b', 'wrapping/wrapped around'),
    (r'\bkneeling\s+between\b|跪在.{0,6}膝', 'kneeling between'),
    (r'\bstraddling\b|骑乘', 'straddling'),
    (r'\bscissoring\b|磨豆腐', 'scissoring'),
    (r'\bgrinding\b|磨蹭', 'grinding'),
]
found_pose_verbs = []
for pat, name in pose_verb_patterns:
    if re.search(pat, pose_probe, re.IGNORECASE) and name not in found_pose_verbs:
        found_pose_verbs.append(name)
if len(found_pose_verbs) >= 3:
    add_error(
        '§M-3 亲密姿势动词堆叠过多 — 易肢体融接或角色拆成旁观第三人',
        ', '.join(found_pose_verbs),
        '同一对最多保留 2 类核心动作（如 kissing + embracing）；勿再叠 body wrapping around / kneeling between / straddling 等；arms wrapped around 可保留'
    )

# M-4) 纹身：禁抢权重的否定落点长句；鼓励短落点锚
if re.search(r'\b(tattoo|inked skin|body art)\b', text, re.IGNORECASE):
    m_tattoo_noise = re.search(
        r'(?:tattoo\s+)?placed\s+strictly\s+away\s+from|away\s+from\s+(?:the\s+)?nipple.{0,40}(?:vulva|anus)|away\s+from.{0,20}(?:nipple|vulva|anus).{0,20}(?:nipple|vulva|anus)',
        text,
        re.IGNORECASE,
    )
    if m_tattoo_noise:
        add_warning(
            '§M-4 纹身否定落点段过长抢权重 — 踝侧落点易漂到脚底',
            '删掉 away from nipple/vulva/anus 长句；改短：one tiny ... tattoo only on outer left ankle, not on soles'
        )
    if not re.search(
        r'\b(?:tattoo|ink)\b.{0,60}\b(?:on|upon)\s+(?:the\s+)?(?:outer\s+|inner\s+)?(?:left\s+|right\s+)?'
        r'(?:ankle|wrist|shoulder|hip|thigh|nape|collarbone|forearm|upper\s+arm|lower\s+back|ribcage)\b'
        r'|\b(?:on|upon)\s+(?:the\s+)?(?:outer\s+|inner\s+)?(?:left\s+|right\s+)?'
        r'(?:ankle|wrist|shoulder|hip|thigh|nape|collarbone|forearm|upper\s+arm|lower\s+back|ribcage)\b.{0,40}\b(?:tattoo|ink)\b',
        text,
        re.IGNORECASE,
    ):
        add_warning(
            '§M-4 纹身缺少短落点锚（ankle/wrist/…）',
            '用短句锚定：tattoo only on outer left ankle；勿用大段 dermis/away-from 抢权重'
        )

# =====================================================================
# ─── 输出最终结果 ─────────────────────────────────────────────────────
# =====================================================================

if errors:
    for msg, found, fix in errors:
        print(f"❌ [严重] {msg}")
        print(f"   发现: {found or 'N/A'}")
        print(f"   修正: {fix or 'N/A'}\n")
    if warnings:
        for msg, fix in warnings:
            print(f"⚠️  [警告] {msg}")
            print(f"   建议: {fix or 'N/A'}\n")
    sys.exit(1)

if warnings:
    for msg, fix in warnings:
        print(f"⚠️  [警告] {msg}")
        print(f"   建议: {fix or 'N/A'}\n")
    sys.exit(2)

print('✅ 多人 prompt 检查通过')
PY
