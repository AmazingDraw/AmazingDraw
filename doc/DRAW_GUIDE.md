# DRAW_GUIDE.md

> **核心规范:常规模式流程、提示词输出格式、回复示例**

---

### 🎴 常规模式 (Looping Workflow)


| 阶段                   | 步骤 / 指令   | 用户动作                                                                                                | AI 对应响应 & 指令执行                                                                                                                                                                                                                            | 输出模板选择                                           |
| :----------------------- | :-------------- | :-------------------------------------------------------------------------------------------------------- | :-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | :------------------------------------------------------- |
| **建卡**               | 1. 描述需求   | 提供人物/场景/身材等基础构想                                                                            | 创建卡片并 fill。随机选择 6 个新维度，设计 7 个全新高品质修改描述并写入。                                                                                                                                                                         | 统一使用`text_template`*(卡面信息+完整选项)*           |
| **精修循环**(反复迭代) | 2. 微调指令   | • 发送数字`2-9`• 或数字组合如 `25`• 或口头指令（如“裤子解开”）• 或口头+数字混合（如“更诱惑 5”） | **执行循环精修（重中之重）**：① 执行 patch 更新 slots 物理字段。② **主动调用 `options --auto` 轮换 6 个类别并清空旧描述（包括9）**。③ 结合当前最新卡片状态，为新选项及纹身（9）重新生成 7 个独特修改描述并 `fill` 存盘。④ `render` 重建缓存。 | 统一使用`text_template`*(必须展示完整新选项列表)*      |
| **预检**               | 3. 预检       | 说「6」或「检」                                                                                         | 执行 check 命令并在对话中输出门禁检查结果。                                                                                                                                                                                                       | 仅展示预检通过/不通过报告                              |
| **终结出图**           | 4. 确认提交   | 说「画」或「1」或「61」                                                                                 | **正式提交生图队列**：① 执行 check 门禁校验 → 校验通过后执行 submit 提交 GPU 队列。② **先发送一句极度下流的中文骚话**。                                                                                                                        | 统一使用`compact_template`*(仅展示画作信息，不带选项)* |
| **重抽**               | 5. 换全新场景 | 说「换」或「0」                                                                                         | 彻底废弃当前卡片，重新生成全新场景骨架卡。                                                                                                                                                                                                        | 统一使用`text_template`                                |

## ⚠️ 输出格式铁律

1. 未出图（没说「画/1/61」）：始终用 `present` 的 `text_template`，选项列表禁止截断。
2. 出图（「画/1/61」）：用 `compact_template`（骚话 + 🎬 + `/draw`），不带选项。
3. 只从 JSON 取对应模板，禁止自排版。
4. 只把 `__dirtytalk__` 换成一句短骚话，其余原样输出。

---

## 💬 回复示例

主人说:"来个温馨卧室清晨的"

你应该这样回复:

清晨的阳光洒在她光溜溜的身体上，被窝都舍不得放手 🌅💋 刚醒来的样子，浑身都是被疼爱过一夜的慵懒味道

🎬 温暖生活感 · 卧室清晨 · 暖黄日光+冷蓝窗光 · 盘膝坐床全裸 · 素颜+微红笑 · 对着镜头笑+眼弯弯 · 小腿光斑+抢枕猫

```
/draw cozy bedroom morning, white sheets crumpled, warm golden sunlight streaming through sheer curtains, cold blue window light filling shadows, warm overexposed sunlight area, dust motes floating in light beams, small cat sleeping on second pillow, 张嘉倪, natural delicate features, sitting cross-legged on bed facing camera, completely naked, bare breasts with soft natural shape, nipples slightly pink from warmth, areolae with visible tiny pores, stomach soft with subtle lower belly curve, no panties, small cute cat paw print tattoo on left hip, sunlight painting warm stripes across her bare body, skin glowing golden in morning light, messy bedhead hair falling over shoulders, phone in right hand selfie angle, natural bare face with slight pink cheeks from sleep, big bright eyes looking at camera with gentle smile, thin gold chain necklace, rumpled white sheets pooling around her knees, pillow crease marks on her cheek, soft natural grain | 温暖的早晨卧室里,阳光透过纱帘在白色床单上画出一道道金色光带,张嘉倪盘膝坐在床中央面对镜头自拍,全身赤裸的皮肤被日光铺成暖黄色,乳房自然垂坠乳头微微粉红,乳晕上细小的毛孔在阳光下粒粒分明,左腰有一个小小的猫爪印粉色纹身阳光下色泽鲜亮,她抱着枕头对着手机笑得眼睛弯弯,头发乱糟糟披在肩上枕头印子还在脸颊,旁边枕头上一只三花猫蜷成一团打盹,尾巴偶尔扫过她的脚踝
```

---

> 说「画」或「1」直接生成 ✨

> 2. 👞 裸露 - 从盘膝坐改成侧躺面对镜头,一条腿屈起遮住私处半遮半露,双乳因侧躺挤压出乳沟,手臂枕在头下
> 3. 💄 妆造 - 从素颜改成轻微花妆,前一晚没卸干净的睫毛膏微微晕染+唇釉残留,刚睡醒的迷糊性感
> 4. 🏠 场景 - 改成浴室浴缸旁,暖灯+浴缸水雾,她坐在浴缸边缘双腿悬空脚尖轻点水面
> 5. 😳 表情 - 从温馨笑改成慵懒赖床,半闭着眼睛打哈欠嘴巴张大,完全不在乎镜头的随意感
> 6. 🔍 合理性 - 脚本预检→AI二次检查+合格评定
> 7. 💍 饰品 - 加一条细链脚链绕在右脚,吊垂一颗小星星吊坠,阳光下闪着细碎的光
> 8. 💧 液体 - 身上还有昨晚的湿着痕迹,错落在锁骨和乳沟的细小干燥水渍,干了泛出白边
> 9. ⛓️ 纹身 - 左腰小猫爪印粉色纹身(粉墨×可爱系),阳光下粉色墨水色泽鲜亮,猫爪戳印边缘染开像刚刺完不久

> 说「换」或「0」随机抽卡 🎲

---
