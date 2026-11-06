# PROMPT_TEMPLATE.md — 提示词装配手册（v8.0）

> 💡 **核心原则**：先决策，后装配。不知画面意图就开始填词 = 废图。

---

## 🎬 导演决策链（组装前必走）

---

### 三阶段标准编译管线 (3-Phase Pipeline)

顺序：导演决策 → 槽位填充 → 叙事升华。消拼接感。

1. **8 维决策 (director)**：`intent`、`exposure_mode`（必填）、`style_recipe`、`lighting_palette`、`pose_direction`、`makeup_direction`、`expression_gaze`、`focus_detail`。完成后预过滤 `body_shape`。
2. **12 槽位 (slots)**：全部选填。英文场景真相源是 **`scene.keywords`**。**例外**：`manual-custom` / keywords 为空时必须写入。**`slots.body_shape`**：素人卡（单人与多人）默认开启**四轴体型盲盒**，由引擎全权托管（单人 `"{{BODY}}"`、多人 `"{{BODY:1}}"` 等占位符），AI 仅根据骨架中的四轴粗标签（`阶段(Y1~Y5) · 身材(V1~V6) · 奶量(A~F) · 私密(P1~P6×H1~H6)`）搭配服饰与姿态，**严禁在 `body_shape` / `clothing` / `pose` 中自行编写体型或胸部尺寸词**（如需重抽体型用 `mend --card <id> --reroll-body`）；仅明星模式、老卡、云端出图或 `--no-blind` 卡由 `slots.body_shape` 明文承载。
3. **叙事升华 (elevation)**：独立最后一步。把前两步收成一段有电影感的中文 `story_elevation_zh`（60~240字）。

> 三阶段顺序硬校验。重填 director 会级联清空 slots 与 elevation。

### 8 维导演决策与叙事升华表

| #  | 维度               | 导演字段（`director.*`） | 决策核心                                                                                                                                                                                                             | 落地槽位                                                       |
| :- | :----------------- | :------------------------- | :------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | :------------------------------------------------------------- |
| 1  | **画面意图** | `intent`                 | 用情感词定义核心冲动：禁忌、偷窥、反差、羞耻、情欲、孤独、压迫臣服、私密氛围等。                                                                                                                                     | 全局指导，不直接落槽位                                         |
| 2  | **裸露模式** | `exposure_mode`          | **必填**。决定 body_shape 和 clothing 的过滤边界：`upper`(只露上) / `lower`(只露下) / `both`(全露) / `half_nude`(半裸) / `half_covered`(半遮) / `none`(不露)。选完后系统立即预过滤，当场看到结果。 | 控制`body_shape` + `clothing` 过滤                         |
| 3  | **风格配方** | `style_recipe`           | 选定风格配方（AV封面/监控/手机/港风/霓虹/黑白/日常/SM）。                                                                                                                                                            | `style_quality` + `makeup_hair`(方向)                      |
| 4  | **光影色彩** | `lighting_palette`       | 决定光型（硬/柔/逆/侧/顶）、光色及色彩基调（冷暖对撞/单色锚定/低饱和克制）。                                                                                                                                         | `lighting`                                                   |
| 5  | **身体叙事** | `pose_direction`         | 决策姿势、裸露策略、服装状态及物理痕迹（汗湿/潮红/勒痕）。**严禁**写面部与身份描述。                                                                                                                           | `pose` + `clothing`                                        |
| 6  | **情绪妆造** | `makeup_direction`       | 决定脸型轮廓、情绪方向与妆造配合（如娃娃脸配裸妆、冷艳骨相配红唇）。只定方向，具体词落槽。                                                                                                                           | `makeup_hair`(脸型五官轮廓 + 发型妆容)                       |
| 7  | **表情眼神** | `expression_gaze`        | 融合角色专属气质氛围（如清冷禁欲、乖巧怯生、慵懒熟韵）与眼神表情（迷离勾引、回避羞耻、直视挑衅），须与身体叙事同频。                                                                                                 | `expression_gaze`(人物气质 + 眼神表情)                       |
| 8  | **焦点细节** | `focus_detail`           | 撑起视觉重心的肉眼可见锚点。**含 imperfections、liquids、tattoo**。                                                                                                                                            | `accessories` + `imperfections` + `tattoo` + `liquids` |
| — | **叙事升华** | `story_elevation_zh`     | **去拼凑感**：确保每个词都服务于同一个叙事帧，体现时间的前因后果与悬念（60~240字中文叙事，供展示与归档；**槽位填完后才做**）。                                                                           | 整合中文叙事                                                   |

> **执行顺序**：先做 8 维导演决策 → 填槽位 → 最后做叙事升华（叙事升华需要看到完整槽位细节才能去拼凑感）。
>
> **核心追求**：画面越简洁，叙事越要强。图画应当如电影帧，而非词语的无脑堆砌。

### 裸露状态（由 `exposure_mode` 控制）

`exposure_mode` 决定 `body_shape` 与 `clothing` 的过滤边界。**半裸必须保留服装结构**（如解开纽扣、撩起裙摆），与脱掉衣服的露上/露下/全裸有本质区别。

| `exposure_mode` | 子分类 (`half_nude_region`) | 含义               | 核心规则与门禁要求                                               |
| :---------------- | :---------------------------- | :----------------- | :--------------------------------------------------------------- |
| `upper`         | —                            | 只露上半身         | 下身强制遮挡，移除下体敏感与裸露词                               |
| `lower`         | —                            | 只露下半身         | 上身强制覆盖且必须指定实体上装，移除露胸词                       |
| `both`          | —                            | 全部裸露           | 上下全裸，不过滤（不要求保留衣服结构）                           |
| `half_nude`     | `upper`（半裸露上）         | 上露下遮，保留衣服 | 留衣物结构（如解开纽扣）；严禁下体裸露（鱼眼视角默认绑定）       |
|                   | `lower`（半裸露下）         | 下露上遮，保留衣服 | 留衣物结构（如掀起裙摆）；严禁上身露点（偷拍视角默认绑定）       |
|                   | `both`（双侧半裸）          | 双侧允许，保留衣服 | 留衣物结构（如衣衫凌乱半脱）；上下均允许暴露细节（缺省三档随机） |
| `half_covered`  | —                            | 半遮擦边           | 仅允许擦边（湿身/透视/微露内衣），禁止直接露点                   |
| `none`          | —                            | 无裸露             | 移除所有裸露信号与敞开衣物                                       |

---

## 🎨 八种 JAV 风格配方

根据画面意图选定配方作为骨架，直接将以下 8 维导演决策值写入对应的 `director` 字段，再在细节槽位上进行个性化：

| # | 风格               | <span style="white-space: nowrap;">风格配方 style_recipe</span>   | <span style="white-space: nowrap;">裸露模式 exposure_mode</span> | <span style="white-space: nowrap;">光影色彩 lighting_palette</span> | <span style="white-space: nowrap;">姿势方向 pose_direction</span>     | <span style="white-space: nowrap;">妆容方向 makeup_direction</span> | <span style="white-space: nowrap;">表情眼神 expression_gaze</span> | <span style="white-space: nowrap;">焦点细节 focus_detail</span>                                           |
| :-: | :----------------- | :---------------------------------------------------------------- | :--------------------------------------------------------------- | :------------------------------------------------------------------ | :-------------------------------------------------------------------- | :------------------------------------------------------------------ | :----------------------------------------------------------------- | :-------------------------------------------------------------------------------------------------------- |
| 1 | **AV封面**   | `85mm portrait lens, gravure idol photography, photorealistic`  | `half_nude`                                                    | `ring light, soft studio lighting, neutral white`                 | `standing S-curve pose, leaning forward slightly`                   | `gravure idol makeup, glossy pink lips`                           | `looking at viewer, confident smile, slight blush`               | `tack-sharp focus on eyes, high-fidelity skin texture, studio light catching reflection`                |
| 2 | **监控纪实** | `CCTV footage, security camera style, surveillance camera view` | `half_covered`                                                 | `harsh fluorescent ceiling light, cool white 6500K`               | `unaware body pose, bending over desk, looking down`                | `bare face, sweat-glistened skin, exhausted look`                 | `looking down, startled expression, wide eyes`                   | `overhead static camera angle, grainy scanlines, low resolution artifacts, digital timestamp watermark` |
| 3 | **手机私密** | `phone camera selfie, mobile photography snapshot`              | `upper`                                                        | `warm lamp light, glow from phone screen, 2700K`                  | `holding phone for mirror selfie, one leg slightly bent`            | `casual makeup, slightly messy hair`                              | `looking at screen, seductive smile, shy gaze`                   | `handheld phone selfie perspective, mirror reflection lens flare, soft background blur`                 |
| 4 | **复古港风** | `35mm film camera photography, 1990s Hong Kong cinematic look`  | `half_covered`                                                 | `warm golden environmental light, neon refraction`                | `lounging on velvet sofa, relaxed head rest, bare shoulder`         | `retro makeup, matte skin, bold red lipstick`                     | `gazing into distance, melancholy look, parted lips`             | `warm analog film grain, cinematic color grading, Kodak Gold 200 tones, realistic skin texture`         |
| 5 | **霓虹欲望** | `anamorphic lens cinematic photography, cyberpunk night style`  | `half_nude`                                                    | `vibrant neon ambient, pink and blue rim light`                   | `sitting cross-legged, arched back, dynamic silhouette`             | `nightclub heavy makeup, dark eyeliner, glossy lips`              | `dilated pupils, heavy lidded eyes, sensual gaze`                | `cinematic depth of field, anamorphic purple neon lens flare, water droplets on glistening skin`        |
| 6 | **黑白艺术** | `medium format monochrome photography, classic film noir style` | `both`                                                         | `high contrast side light, chiaroscuro shadows`                   | `crouching on floor, arms wrapping knees, stretched spine`          | `completely bare face, natural skin textures`                     | `empty gaze, staring into space, neutral face`                   | `dramatic chiaroscuro shadows, fine analog film grain, sharp contrast outline of body`                  |
| 7 | **日常素人** | `candid DSLR photography, casual lifestyle snapshot`            | `half_covered`                                                 | `natural sunlight through window, daylight`                       | `standing in kitchen, oversized knit sweater slipping off shoulder` | `no-makeup look, clean skin, ponytail`                            | `casual smile, looking at glass, relaxed mood`                   | `natural depth of field, soft background bokeh, realistic everyday lighting, coarse knit texture`       |
| 8 | **SM束缚**   | `50mm lens photography, dramatic cinematic art portrait`        | `half_nude`                                                    | `single hard spotlight, dramatic shadows, warm candle glow`       | `kneening pose, bound in ropes over strappy harness lingerie`       | `tear-streaked face, smudged eyeliner`                            | `gazing up, pleading eyes, parted lips`                          | `shallow focus, high-fidelity rope texture contrast on skin, glistening sweat`                          |
