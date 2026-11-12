# PROMPT_TEMPLATE.md — 提示词装配手册（v8.0）

> 💡 **核心原则**：先决策，后装配。不知画面意图就开始填词 = 废图。

---

## 🎬 导演决策链（组装前必走）

---

### 三阶段标准编译管线 (3-Phase Pipeline)

顺序：导演决策 → 槽位填充 → 叙事升华。

> 三阶段顺序硬校验。重填 director 会级联清空 slots 与 elevation。

### 8 维导演决策与叙事升华表

| #  | 维度               | 导演字段（`director.*`） | 决策核心                                                                                                                                                                                                             | 落地槽位                                                                   |
| :- | :----------------- | :------------------------- | :------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | :------------------------------------------------------------------------- |
| 1  | **画面意图** | `intent`                 | 用情感词定义核心冲动：禁忌、偷窥、反差、羞耻、情欲、孤独、压迫臣服、私密氛围等。                                                                                                                                     | 全局指导，不直接落槽位                                                     |
| 2  | **裸露模式** | `exposure_mode`          | **必填**。决定 body_shape 和 clothing 的过滤边界：`upper`(只露上) / `lower`(只露下) / `both`(全露) / `half_nude`(半裸) / `half_covered`(半遮) / `none`(不露)。选完后系统立即预过滤，当场看到结果。 | 控制`body_shape` + `clothing` 过滤                                     |
| 3  | **风格配方** | `style_recipe`           | 选定或自创风格配方（监控/手机/港风/霓虹/黑白/日常 等）。                                                                                                                                                             | `style_quality` + `makeup_hair`(方向)                                  |
| 4  | **光影色彩** | `lighting_palette`       | 决定光型（硬/柔/逆/侧/顶）、光色及色彩基调（冷暖对撞/单色锚定/低饱和克制）。                                                                                                                                         | `lighting`                                                               |
| 5  | **身体叙事** | `pose_direction`         | 决策姿势、裸露策略、服装状态及物理痕迹（汗湿/潮红/勒痕）。单人卡严禁写面部与身份描述；多人/伴侣卡须明确分镜站位、编号分人或第一人称 POV 视角借位。                                                                   | `pose` + `clothing`                                                    |
| 6  | **情绪妆造** | `makeup_direction`       | 决定脸型轮廓、情绪方向与妆造配合（如娃娃脸配裸妆、冷艳骨相配红唇）。只定方向，具体词落槽。                                                                                                                           | `makeup_hair`(脸型五官轮廓 + 发型妆容)                                   |
| 7  | **表情眼神** | `expression_gaze`        | 融合角色专属气质氛围（如清冷禁欲、乖巧怯生、慵懒熟韵）与眼神表情（迷离勾引、回避羞耻、直视挑衅），须与身体叙事同频。                                                                                                 | `expression_gaze`(人物气质 + 眼神表情)                                   |
| 8  | **焦点细节** | `focus_detail`           | 撑起视觉重心的肉眼可见锚点。**含 props、imperfections、liquids、tattoo**。                                                                                                                                     | `accessories` + `props` + `imperfections` + `tattoo` + `liquids` |
| — | **叙事升华** | `story_elevation_zh`     | **去拼凑感**：确保每个词都服务于同一个叙事帧，体现时间的前因后果与悬念（60~240字中文叙事，供展示与归档；**槽位填完后才做**）。                                                                           | 整合中文叙事                                                               |

> **执行顺序**：先做 8 维导演决策 → 填槽位 → 最后做叙事升华（叙事升华需要看到完整槽位细节才能去拼凑感）。
>
> **核心追求**：画面越简洁，叙事越要强。图画应当如电影帧，而非词语的无脑堆砌。

### 裸露状态（由 `exposure_mode` 控制）

`exposure_mode` 决定 `body_shape` 与 `clothing` 的过滤边界。**半裸必须保留服装结构**（如解开纽扣、撩起裙摆），与脱掉衣服的露上/露下/全裸有本质区别。

| `exposure_mode` | 子分类 (`half_nude_region`) | 含义                   | 核心规则与门禁要求                                                           |
| :---------------- | :---------------------------- | :--------------------- | :--------------------------------------------------------------------------- |
| `upper`         | —                            | 只露上半身             | 下身强制遮挡，移除下体敏感与裸露词                                           |
| `lower`         | —                            | 只露下半身             | 上身强制覆盖且必须指定实体上装，移除露胸词                                   |
| `both`          | —                            | 全部裸露               | 上下全裸，不过滤（不要求保留衣服结构）                                       |
| `half_nude`     | `upper`（半裸露上）         | 上露下遮，保留衣服     | 留衣物结构（如解开纽扣）；严禁下体裸露                                       |
|                   | `lower`（半裸露下）         | 下露上遮，保留衣服     | 留衣物结构（如掀起裙摆）；严禁上身露点（偷拍视角默认绑定）                   |
|                   | `both`（半裸不指定）        | 半裸自由选侧，保留衣服 | 须有裸露信号 + 服装结构（解开纽扣 / 掀裙等）。可只露上、只露下，或两边都写。 |
| `half_covered`  | —                            | 半遮擦边               | 仅允许擦边（湿身/透视/微露内衣），禁止直接露点                               |
| `none`          | —                            | 无裸露                 | 移除所有裸露信号与敞开衣物                                                   |

---

## 🎨 六种风格配方

根据画面意图选定一条作为骨架，把下表 8 维写入 `director`，再在槽位上改细节。

| # | 风格               | <span style="white-space: nowrap;">画面意图 intent</span> | <span style="white-space: nowrap;">风格配方 style_recipe</span>                                                                     | <span style="white-space: nowrap;">裸露模式 exposure_mode</span> | <span style="white-space: nowrap;">光影色彩 lighting_palette</span>       | <span style="white-space: nowrap;">姿势方向 pose_direction</span>                                                                                                                               | <span style="white-space: nowrap;">妆容方向 makeup_direction</span> | <span style="white-space: nowrap;">表情眼神 expression_gaze</span>     | <span style="white-space: nowrap;">焦点细节 focus_detail</span>                           |
| :-: | :----------------- | :-------------------------------------------------------- | :---------------------------------------------------------------------------------------------------------------------------------- | :--------------------------------------------------------------- | :------------------------------------------------------------------------ | :---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | :------------------------------------------------------------------ | :--------------------------------------------------------------------- | :---------------------------------------------------------------------------------------- |
| 1 | **监控纪实** | `偷窥, 纪实, 冷感`                                      | `CCTV security footage from a high-mounted corner camera looking down the room, not a ninety-degree overhead, not a fisheye dome` | `half_covered`                                                 | `harsh fluorescent ceiling light, cool white 6500K, flat institutional` | `standing at a desk leaning over paperwork, both hands on the desktop, thin office blouse still on, damp fabric clinging, unaware of the camera`                                              | `bare face, sweat sheen, no styled makeup`                        | `looking down at the papers, unaware, mouth slightly open`           | `interlaced scanlines, jpeg blocks, burned-in timestamp in the corner, 480p grain`      |
| 2 | **手机私密** | `私密, 挑逗, 羞涩反差`                                  | `front-camera mirror selfie, smartphone snapshot, bathroom mirror, not a security camera`                                         | `upper`                                                        | `warm tungsten lamp, faint glow from the phone screen, 2700K`           | `standing before a bathroom mirror, one hand holding the phone up, the other hand on the sink edge, jeans still on, upper body bare`                                                          | `thin everyday makeup, slightly messy hair`                       | `looking at the phone screen in the mirror, small shy smile`         | `phone bezel in the mirror, screen glare on tiles, phone-camera background blur`        |
| 3 | **复古港风** | `复古, 慵懒, 叙事悬念`                                  | `35mm film still, 1990s Hong Kong night interior, Kodak Gold 200`                                                                 | `half_nude` / `upper`                                        | `warm tungsten practicals, leftover neon leaking through blinds`        | `reclining on a velvet sofa, one arm along the backrest, the other hand resting on her stomach, cheongsam unbuttoned down the chest and still worn, the skirt of the dress covering her hips` | `matte skin, bold red lipstick, 90s eye makeup`                   | `looking past the lens toward the window, tired mouth slightly open` | `coarse analog grain, Kodak Gold warmth, neon smear on the glass, visible skin texture` |
| 4 | **霓虹欲望** | `情欲, 沉沦, 迷醉压迫`                                  | `anamorphic night cinematography, wet street neon, not a selfie`                                                                  | `lower`                                                        | `magenta and cyan neon, wet pavement bounce, no daylight`               | `sitting on a barstool, silk blouse still buttoned, skirt hiked to the waist, one elbow on the bar, the other hand on her bare thigh`                                                         | `smoky liner, glossy lips, hair stuck to her neck`                | `heavy lids, looking just off-lens, mouth parted`                    | `anamorphic horizontal flare, condensation on a glass, neon on wet collarbones`         |
| 5 | **黑白艺术** | `孤独, 疏离, 身体雕塑`                                  | `medium format black and white, film noir studio, no color`                                                                       | `both`                                                         | `single hard side key, deep negative fill, chiaroscuro`                 | `sitting on the floor hugging both knees to her chest, forehead lowered toward her knees, spine rounded`                                                                                      | `bare face, visible pores, dry lip texture`                       | `eyes open, looking at the floor, no performance`                    | `hard shadow cut across the ribs, analog grain, skin as sculpture`                      |
| 6 | **日常素人** | `清纯, 真实, 日常反差`                                  | `handheld DSLR candid, available window light, lifestyle snapshot, not a selfie`                                                  | `half_nude` / `lower`                                        | `late morning window light, no studio strobe`                           | `standing at a kitchen counter, both hands around a glass of water, oversized knit still covering her chest, pajama shorts pulled down to her thighs`                                         | `no-makeup skin, hair in a loose ponytail`                        | `unposed mouth, eyes on the glass, not on the lens`                  | `knit weave, window bokeh, condensation on the glass, everyday clutter behind her`      |
