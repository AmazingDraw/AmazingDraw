# 抽卡命令速查

> 工作目录：`cd scripts/card-engine`

---

## 1. 创建 `create`

```bash
# 随机
python3 card_cli.py create

# 指定场景/人物
python3 card_cli.py create --person "OL" --scene "停车场"
python3 card_cli.py create --person "张嘉倪" --scene "办公室"

# 库外自定义场景（未命中库且非纯主题词 → manual-custom；fill 须写 scene.keywords）
python3 card_cli.py create --person "女秘书" --scene "赛博竹林夜宴" --user-input "赛博竹林夜宴"

# 纯主题词仍进主题池（如校园/办公室/SM）
python3 card_cli.py create --person "JK" --scene "校园" --user-input "校园连抽"

# 视角路由（场景名含关键词自动命中对应视角场景）
python3 card_cli.py create --person "JC" --scene "颜射视角"
python3 card_cli.py create --person "JK" --scene "后入视角"

# 比例
python3 card_cli.py create --aspect portrait    # 512x768（默认）
python3 card_cli.py create --aspect landscape   # 768x512
python3 card_cli.py create --aspect square      # 640x640
python3 card_cli.py create --aspect widescreen  # 1088x464
python3 card_cli.py create --size 768x1024      # 手动指定

# 体型 profile（用户指定优先）
python3 card_cli.py create --person "JK" --profile jk-pink
python3 card_cli.py create --person "JC" --profile jc-sporty

# 其他
python3 card_cli.py create --seed 123456 --workflow moody_zib_zit --bundle
```

| 参数 | 说明 |
|------|------|
| `--mode` | `amateur`(默认) / `celebrity` |
| `--bundle` | 启用结构化 JSON 词库参考（默认关闭）。不带值：智能加载四类词库常用章节；带值：`--bundle "tattoo:图案速查|皮肤融合,props:振动棒"` 按指定章节加载 |

---

## 2. 填词 `fill`

```bash
# 逐字段
python3 card_cli.py fill --card <id> \
  --clothing "..." --pose "..." --expression-gaze "..." \
  --style-quality "..." --makeup-hair "..." --accessories "..." \
  --imperfections "..." --tattoo "..." --props "..." --liquids "..." \
  --dir-intent "..." --dir-exposure-mode half_nude \
  --dir-style-recipe anime_style --dir-lighting-palette warm_soft \
  --dir-pose-direction frontal_close_up --dir-makeup-direction natural_flush \
  --dir-expression-gaze cute_flirty --dir-focus-detail face_expression \
  --theme-zh "中文主题" --story-elevation-zh "..." \
  --lighting-palette-zh "暖光" --style-recipe-zh "动漫风格"

# 结构化 JSON 一次导入（连抽默认；勿拆 --phase）
python3 card_cli.py fill --card <id> --json-file fill.json
python3 card_cli.py fill --card <id> --json '{"theme_zh":"...","director":{...},"slots":{...},"story_elevation":"...","story_elevation_zh":"...","lighting_palette_zh":"...","style_recipe_zh":"..."}'

# 分阶段填（仅常规模式精细打磨；连抽禁止）
python3 card_cli.py fill --card <id> --phase director   # 第一阶段：8维导演
python3 card_cli.py fill --card <id> --phase slots      # 第二阶段：12槽位
python3 card_cli.py fill --card <id> --phase elevation  # 第三阶段：叙事升华

> 🚦 **内置 Preflight 前置预检**：在 `fill` 的最终提交存盘时刻，系统会自动跑一遍纯文本 preflight 门禁检查（包括 theme_zh 撞字、pose_direction 包含身份词、裸露方向互斥、`lower` 必须明确实体上装、连体衣封闭裆+露下冲突、裙装「开裆」误写、`half_nude` 缺结构词/缺裸露表达、`half_covered` 残留直接露点、`lower`/`none` 下 unbuttoned 敞衣冲突等），若校验不通过会直接拦截并退出（exit code 1），拒绝将修改写入 JSON 库。`half_nude` 下的 `unbuttoned` **不**在此拦截。完整清单见 [PREFLIGHT_GUIDE.md](./PREFLIGHT_GUIDE.md) §2。
```

| 参数 | 说明 |
|------|------|
| `--json-file` / `--json` | **连抽推荐**：一次写齐 director + slots + elevation |
| `--phase` | 可选分阶段；**仅**常规模式精细打磨，连抽勿用 |
| `--clothing` | 服装描述（旧 `--exposure-clothing` 已弃用） |

---

## 3. 动态选项 `options`

```bash
# 自动分配 6 个动态方向（推荐）
python3 card_cli.py options --card <id> --auto

# 手动指定
python3 card_cli.py options --card <id> --json '{
  "2": {"kind": "exposure", "name": "裸露", "emoji": "🍆", "targets": ["slots.clothing", "director.pose_direction", "director.exposure_mode"]},
  "3": {"name": "姿势", "emoji": "🧘", "targets": ["slots.pose"]}
}'
```

---

## 4. 局部修改 `patch`

```bash
# 数字指令（方向编号）
python3 card_cli.py patch --card <id> --direction 9  # 纹身
python3 card_cli.py patch --card <id> --user-input "51"  # 组合指令

# 直接改字段
python3 card_cli.py patch --card <id> --set slots.tattoo --value "small pink heart"
python3 card_cli.py patch --card <id> --set direction_descriptions.9 --value "在左肩设计樱花刺青"

# 按 target 分别赋值
python3 card_cli.py patch --card <id> --direction 3 --targets-json '{
  "slots.pose": "kneeling on bed",
  "director.pose_direction": "跪姿"
}'

# 裸露方向必须同步 clothing 与 exposure_mode
python3 card_cli.py patch --card <id> --direction 2 --targets-json '{
  "slots.clothing": "pleated skirt hiked up, lace panties pulled aside",
  "director.pose_direction": "front-facing lower-body reveal",
  "director.exposure_mode": "lower"
}'
```

> 常规 `single` 的 `lower` 会保留已明确掀起、拨开或褪下的衣物，并补足私处可见性；连抽 `chain` 仍采用零遮挡规则。裸露数字 patch 会替换旧裸露 directive，并清除旧 render/validation。

---

## 5. 展示 `present`

```bash
python3 card_cli.py present --card <id>          # 展示卡片与菜单
python3 card_cli.py present --card <id> --compact # 精简展示
```

> 常规模式必跑 `options --auto` 后才能 `present`。`options` 只更新交互菜单并清理旧描述，
> **不会**修改卡片状态、Prompt 缓存或清除验证内容；但它会推进 `card.version`，因此若在
> `check` 之后再次运行，提交前必须重新 `check`。推荐始终按 `options → render → check → submit` 排序。

---

## 6. 渲染 / 检查 / 提交

```bash
python3 card_cli.py render --card <id>            # 渲染 prompt
python3 card_cli.py check --card <id>             # 预检
python3 card_cli.py submit --card <id> --confirm  # 提交（必须 --confirm）
python3 card_cli.py submit --card <id> --confirm --dry-run  # 模拟预览
```

`check` 会从当前源字段重建最终 Prompt，并在 `_validation` 中记录：

* `prompt_hash`：最终 Prompt 的 SHA-256；
* `card_version`：校验结果实际保存到的卡片版本；
* `workflow`：规范化后的工作流名称。

`submit` 会再次重建 Prompt 并逐项核对这三个字段；任一字段缺失或变化都会拒绝入队，要求重新
执行 `check`。历史常规卡若没有该凭证，也需要重新检查一次。精选模式读取的是已校验灵感库，
继续按可信来源直接提交，不套用此凭证门禁。

---

## 7. 数字指令（常规模式）

| 指令 | 操作 |
|------|------|
| `1` / `画` | 提交生成 |
| `6` | 合理性检查 |
| `9` | 纹身修改 |
| `0` / `换` | 重抽 |
| `2-5,7,8` | 动态方向（需先 `options`） |

> 连抽模式不用数字指令，走 `fill → chain --resume → submit`

---

## 8. 连抽 `chain`

```bash
# 创建骨架
python3 card_cli.py chain --count 3 --person "JC"
python3 card_cli.py chain --count 3 --person "JK" --scene "教室"

# resume 提交（自动 render → check → autofix → submit）
python3 card_cli.py chain --resume <card_id>
```

> 连抽填卡：**一次** `fill --json-file`，不要拆三次 `--phase`。批量 `--batch` **未实现**，请逐张 `--resume`。
>
> `chain --resume` 为**引擎级全局串行**（`/tmp/cu-card/chain-resume.lock`）：多进程并行 resume 会排队，避免 `check_prompt` 并发互拖；`fill`/`create` 不受此锁影响。GPU 渲染仍由 `cu-gpu.lock` 串行。
>
> `chain` **不会自动删除任何旧草稿**。草稿清理由用户在 WebUI 中显式预览并确认，避免跨会话误删。
>
> **dry-run 测试（2026-08-16 新增）**：`chain --resume <card_id> --dry-run` 仅跑 render→check→autofix 全流程校验，**停在提交前不渲染**（卡 status 停在 validated，不入 GPU 队列），用于审查/测试。普通 `--resume` 会走到 submit 入队。

---

## 9. 直投 `direct`

```bash
python3 card_cli.py direct \
  --prompt "英文prompt" \
  --person "OL" --scene "卧室" --theme "主题" \
  --narrative "中文叙事" --lighting "光影" --style "风格" \
  [--width 512 --height 768] [--dry-run]
```

> `--prompt` 为唯一技术必填，6 个中文元数据参数生成归档文件名。  
> **CLI `direct`** 走 `cu-submit --raw`，**不**经过卡引擎场景库 / 灵感原点 meta。
> **WebUI 直投**仍会先提取人物、场景和叙事并生成卡片，再提交原始 Prompt；其卡号使用
> 并发安全的唯一 ID。所有入口统一拒绝含路径分隔符、控制字符或越出卡片目录的 `card_id`。

---

## 10. 精选 `featured`

```bash
python3 card_cli.py featured [--workflow moody_zib_zit] [--width 512] [--height 768]
```

> 从 Obsidian `vault/灵感库/` 随机抽已归档词条；卡片写死 **灵感原点 meta**（`special-ethereal-origin`，代码内建，**不在** `special_scenes.json`），原样旁路渲染。  
> 与 CLI `direct` 无关。`create` 若 topic 含「直投 / direct injection」会旁路同一 meta，仍不等于 `direct` 命令。

---

## 11. 连抽修复 `mend`

```bash
python3 card_cli.py mend --card <id> --set slots.clothing --value "xxx"
python3 card_cli.py mend --card <id> --get slots.clothing   # 读取字段
python3 card_cli.py mend --card <id> --undo                 # 撤销
python3 card_cli.py mend --card <id> --history              # 修改记录
python3 card_cli.py mend --card <id> --set slots.pose --value "..." --dry-run
```

---

## 12. 文档/搜索

```bash
python3 card_cli.py doc prompt   # 查阅提示词装配手册
python3 card_cli.py doc pitfalls # 高频报错避坑指南
python3 card_cli.py search --person jk    # 模糊搜索场景/角色库
python3 card_cli.py resolve --person OL --scene 办公室  # 解析 fill-ready 字段
```

---

## 13. 队列管理

```bash
python3 card_cli.py queue status
python3 card_cli.py queue health
python3 card_cli.py queue clear [--force]
python3 card_cli.py queue remove --job-id JOB_ID  # 推荐，稳定标识
python3 card_cli.py queue remove --position N
```

`status` 保留旧 `length/next/avg-eta` 兼容字段，同时返回 QueueStore v2 的 `revision/jobs/state_counts`。写操作遇到 `lock_busy` 或坏 JSON 会返回非零，禁止按成功处理。

---

## 14. 记录与进度

```bash
python3 card_cli.py progress
python3 card_cli.py record --card <id>
python3 card_cli.py archive --card <id>  # 存档到 Obsidian 灵感库
```

`archive` 只接受可证明属于当前卡的 PNG，匹配优先级为：
卡片 `render_image`（路径或精确 basename）→ 精确 `<card_id>.png` →
旧卡“人物-场景-主题 / 人物-场景”唯一前缀。候选为空或超过一个都会失败并列出原因，
不会再按时间戳或“最新图片”猜测。

归档写入是幂等的：同一 `card_id` 且附件完整时直接返回 `already_archived`；
缺失附件时只补附件；不同卡生成同名笔记时自动使用 `·2`、`·3` 成对后缀，
既有 Markdown 与 PNG 均不覆盖。中文短名称直接本地生成文件名；只有需要翻译或提炼时
才调用 LLM（单次超时 8 秒，失败后使用本地降级）。
内部服务返回 `ok / status / source_image / image_path / note_path / match_strategy`；
WebUI 据此区分 `archived` 与 `already_archived`，不再解析 CLI stdout。

---

## 15. 快捷操作

> 下列路径默认对应 `config.json` 的 `cards_dir` / `tmp_dir`（未改配置时即为下方写法）。

```bash
# 查看卡面 JSON
cat ~/.openclaw/draw-cards/cards/<card_id>.json | python3 -m json.tool

# 查看后台日志
tail -20 /tmp/cu-card/cu-submit-bg_*.log

# 清理僵尸锁（GPU 锁为 O_EXCL 原子文件；释放仍是删文件）
rm -f /tmp/cu-card/cu-gpu.lock
```

---

发行包不含 `tests/` 目录；自测命令仅 skill 开发树提供，zip 用户请跳过。


---

## 17. 禁止事项

- ❌ prompt/person 中禁止出现「素人」
- ❌ 常规模式下，动态位必须先 `options --auto` 才能用
- ❌ 连抽模式不要走数字指令

---

## 18. ComfyUI 维护

```bash
# 渲染进度条
curl -s http://127.0.0.1:8188/api/settings/Comfy.Queue.ShowRunProgressBar
curl -s -X POST http://127.0.0.1:8188/api/settings/Comfy.Queue.ShowRunProgressBar \
  -H "Content-Type: application/json" -d 'true'
```

> 设置存储在 `~/ComfyUI/user/comfyui.db`（SQLite），重启后持久保留。
