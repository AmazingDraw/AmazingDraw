# 抽卡命令速查

> 工作目录：`cd scripts/card-engine` · 完整参数见 `python3 card_cli.py <子命令> --help`

---

## 一、连抽模式（默认主线）

### 1. 连抽 `chain`

```bash
python3 card_cli.py chain --count 3 --user-input "可爱风格"
python3 card_cli.py chain --count 3 --person "护士" --scene "诊室" --user-input "高冷风格"
python3 card_cli.py chain --resume <card_id>            # 自动 render → check → autofix → submit
python3 card_cli.py chain --resume <card_id> --dry-run  # 仅校验不入 GPU 队列
```

> 流程：**一次** `fill --json-file` 填完后逐张 `--resume`（引擎级全局串行，不会自动删旧草稿）。

### 2. 填词 `fill`

```bash
# 连抽主力：一次导入（勿拆 --phase）
python3 card_cli.py fill --card <id> --json-file fill.json
python3 card_cli.py fill --card <id> --json '{"theme_zh":"...","director":{...},"slots":{...},"story_elevation_zh":"...","lighting_palette_zh":"...","style_recipe_zh":"..."}'

# 常规精修可选分阶段（连抽禁止）
python3 card_cli.py fill --card <id> --phase director|slots|elevation
```

> 盲盒卡勿填 `body_shape`；人物气质写 `expression_gaze`（逐字段参数见 `fill --help`）。

### 3. 连抽修复 `mend`

```bash
python3 card_cli.py mend --card <id> --set slots.clothing --value "xxx" [--dry-run]
python3 card_cli.py mend --card <id> --get slots.clothing   # 读取字段
python3 card_cli.py mend --card <id> --reroll-body          # 重抽盲盒体型
python3 card_cli.py mend --card <id> --undo | --history     # 撤销 / 修改记录
```

---

## 二、常规单卡模式（精细打磨）

> 闭环：`create` → `fill` → `options --auto` → `patch`（按需）→ `present` → `render` → `check` → `submit --confirm`。

### 4. 创建 `create`

```bash
python3 card_cli.py create --user-input "可爱风格"
python3 card_cli.py create --person "女大学生" --scene "校园" --aspect portrait --user-input "高冷风格"
python3 card_cli.py create --person "护士" --profile nurse-milk --seed 123456 --workflow moody_zib_zit --bundle --user-input "加入宠物元素"
```

| 参数 | 说明 |
| :--- | :--- |
| `--user-input` | **必填**。风格/元素等用户补充 |
| `--mode` | `amateur`（默认，开启体型盲盒 `{{BODY}}`）/ `celebrity` |
| `--bundle` | 扩充词库：不带值按场景扩一圈；带值指定章节（如 `"tattoo:图案速查"`） |
| `--no-blind` | 关闭体型盲盒，退回明文 `slots.body_shape` |
| `--trope` | 特色桥段：不带值随机；带值 `深喉[:机位][:全插\|半插]` / `鱼眼` |

### 5. 动态选项 `options`

```bash
python3 card_cli.py options --card <id> --auto   # 自动分配 6 个动态方向（推荐）
python3 card_cli.py options --card <id> --json '{"2":{"kind":"exposure","name":"裸露","emoji":"🍆","targets":["slots.clothing","director.pose_direction","director.exposure_mode"]}}'
```

### 6. 局部修改 `patch`

```bash
python3 card_cli.py patch --card <id> --direction 9                    # 组合如 51 须按位拆开多次传 --direction
python3 card_cli.py patch --card <id> --user-input "not nude"          # 只传文字/裸露指令，不拆数字
python3 card_cli.py patch --card <id> --set slots.tattoo --value "small pink heart"
python3 card_cli.py patch --card <id> --direction 2 --targets-json '{"slots.clothing":"pleated skirt hiked up, lace panties pulled aside","director.pose_direction":"front-facing lower-body reveal","director.exposure_mode":"lower"}'
```

> 裸露改档须同步 `slots.clothing` 与 `director.exposure_mode` 并清除旧校验；常规 `lower` 保留掀/拨衣物，连抽 `chain` 走零遮挡。

### 7. 展示 `present`

```bash
python3 card_cli.py present --card <id> [--json | --compact]
```

> 必先跑 `options --auto`；`options` 会推进 `card.version`，若在 `check` 后重跑须重新 `check`（推荐顺序：`options → render → check → submit`）。

### 8. 渲染 / 检查 / 提交

```bash
python3 card_cli.py render --card <id>
python3 card_cli.py check --card <id>
python3 card_cli.py submit --card <id> --confirm [--dry-run]
```

> `submit` 强校验 `check` 凭证（Prompt 哈希 / 卡版本 / 工作流），改过源字段须重新 `check`（精选模式豁免）。

### 9. 数字指令（常规模式）

| 指令 | 操作 | 指令 | 操作 |
| :--- | :--- | :--- | :--- |
| `1` / `画` | 提交生成 | `6` | 合理性检查 |
| `0` / `换` | 重抽 | `9` | 纹身修改 |
| `2-5,7,8` | 动态方向（先 `options`） | — | — |

---

## 三、其他抽卡模式

### 10. 直投 `direct`

```bash
python3 card_cli.py direct --prompt "英文prompt" --person "OL" --scene "卧室" --theme "主题" --narrative "中文叙事" --lighting "光影" --style "风格" [--width 512 --height 768] [--dry-run]
```

> 仅 `--prompt` 技术必填，其余中文元数据用于展示与归档（可省）；直走 `cu-submit --raw`，不经场景库。

### 11. 精选 `featured`

```bash
python3 card_cli.py featured [--workflow moody_zib_zit] [--width 512 --height 768] [--dry-run]
```

> 从 Obsidian `vault/灵感库/` 随机抽取已归档词条旁路渲染。

---

## 四、查询、队列与运维

### 12. 文档/搜索

```bash
python3 card_cli.py doc prompt|pitfalls|避坑       # 查阅核心文档
python3 card_cli.py search --scene 走廊|校园|颜射视角
python3 card_cli.py search --person 护士
python3 card_cli.py search --trope 深喉|鱼眼
python3 card_cli.py resolve --scene-library general_scenes --include-tags office --exposure-focus auto
python3 card_cli.py resolve --scene-id some-scene-id --mood 暧昧
```

### 13. 队列管理

```bash
python3 card_cli.py queue status | health | clear [--force]
python3 card_cli.py queue remove --job-id JOB_ID | --position N
```

### 14. 记录与进度

```bash
python3 card_cli.py progress
python3 card_cli.py record --card <id>
python3 card_cli.py archive --card <id>            # 幂等归档至 Obsidian 灵感库（须能唯一匹配当前卡 PNG）
```

### 15. 快捷操作

```bash
cat ~/.amazingdraw/cards/<card_id>.json | python3 -m json.tool
tail -20 /tmp/cu-card/cu-submit-bg_*.log
rm -f /tmp/cu-card/cu-gpu.lock                     # 清理僵尸 GPU 锁
```

### 16. 禁止事项

- ❌ `--person` / prompt 中禁止出现「素人」
- ❌ 常规模式未先执行 `options --auto` 禁止使用动态数字位
- ❌ 连抽模式禁止使用数字指令或 `--phase`

### 17. ComfyUI 维护

```bash
curl -s http://127.0.0.1:8188/api/settings/Comfy.Queue.ShowRunProgressBar
curl -s -X POST http://127.0.0.1:8188/api/settings/Comfy.Queue.ShowRunProgressBar -H "Content-Type: application/json" -d 'true'
```
