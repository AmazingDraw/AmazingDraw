---
name: amazing-draw
description: >
  ComfyUI 抽卡控制台与 WebUI 运维指南。基于 Card Engine：场景选型、人物建模、AI 导演填槽到存档，以及 WebUI 工作台、相册与队列。
category: image
triggers:
  - 抽卡
  - 连抽
  - 画图
  - 生图
  - draw
  - comfyui
  - amazing draw
  - webui
---
# ComfyUI 抽卡控制台 (Card Engine Workflow)

本地绘图核心控制台。**Card Engine** 将绘画拆为「导演决策」与「渲染执行」。

下文路径相对本文件所在目录（zip / 仓库根）。正斜杠 `/` 在 macOS 与 Windows 通用。启动脚本：`bash scripts/...`（Windows 请用 Git Bash）。先 `cd` 到 skill 根再执行。

> 🔒 **AI 铁律**
>
> 1. **严禁扫库与刺探**：禁止 grep / find / cat 刺探源码、内部配置（角色/场景库）与历史卡片；场景查询只走 `card_cli.py search`；体型由盲盒全自动采样托管，严禁刺探或手写 `body_shape`。
> 2. **角色直传**：任何角色直接传 `--person`（无需搜库，库外自由发挥）；严禁用泛词「素人」作 `--person`。
> 3. **Help 规范与严格闭环**：参数与步骤以 `card_cli.py <命令> --help` 为唯一真相源，严禁跳步、合步或自创顺序；严格遵循「建卡（`create` / `chain`）➔ 读返回模板 ➔ 填槽（`fill`）➔ 提交（`resume` / `render`）」闭环推进。

**真相源**：`card.json` 唯一。盲盒卡（默认开启）由引擎在 `_private.body_shape` 托管体型，Agent 侧 `slots.body_shape` 固定为 `"{{BODY}}"`（多人 `"{{BODY:1}}"` 等；明星 / 云端出图或 `--no-blind` 豁免，沿用明文）。改核心字段后须作废 render 缓存。优先级：`用户指定 > 库内命中 > 随机补全`。

---

## ⚡️ 启停

```bash
bash scripts/gpu-pipeline/comfyui-start.sh start|stop|status
bash scripts/webui/webui-start.sh start|stop|status|restart
```

|      | ComfyUI                                                                  | WebUI                                                                        |
| :--- | :----------------------------------------------------------------------- | :--------------------------------------------------------------------------- |
| 端口 | `8188`                                                                 | `8318` → `http://127.0.0.1:8318`                                        |
| 日志 | `/tmp/comfyui-headless.log`（Windows `%TEMP%\comfyui-headless.log`） | `/tmp/amazing-draw-webui.log`（Windows `%TEMP%\amazing-draw-webui.log`） |

出图目录见 `config.json`：`output_dir`（Comfy 实时落盘）· `output_dir_archive`（外置归档，交付优先拷贝）。

---

## 1. 四种模式

> **默认模式：未指定时走 `chain`（连抽）。**
> 💡 **填槽前置**：执行 `fill` 前务必阅读 [PROMPT_TEMPLATE.md](doc/cli/PROMPT_TEMPLATE.md)（导演决策）与 [CHECK_PITFALLS.md](doc/cli/CHECK_PITFALLS.md)（高频避坑）。

| 模式    | 入口                | 核心流程                                                                                                            | 适用         | 额外约束                                                                                                                       |
| :------ | :------------------ | :------------------------------------------------------------------------------------------------------------------ | :----------- | :----------------------------------------------------------------------------------------------------------------------------- |
| 🎴 常规 | `create`          | 骨架 → fill（导演含 exposure_mode + 槽位）→ 叙事升华 → render 交互                                               | 精细打磨     | `workflow_mode=single`；**必** `options --auto`；`present` 只替换 `__dirtytalk__`，禁止自排版 / 泄露 `card_id` |
| 🚄 连抽 | `chain --count N` | 建骨架 → 逐张决策 → **一次** `fill --json-file`（勿拆 `--phase`）→ 逐张 resume（引擎串行）→ 失败 mend | 批量         | **不要** `options --auto`；中途不停问；语义冲突看 `💡 [自愈建议]` 再 fill                                            |
| 🚀 直投 | `direct --prompt` | 英文 prompt raw 直投 GPU，零干预                                                                                    | 已有完整英文 | **禁止**改 / 扩 / 删 prompt 或追加画质词                                                                                 |
| 🎲 精选 | `featured`        | 随机抽 Obsidian 灵感库，meta 原样旁路                                                                               | 随机灵感     | 与 CLI `direct` 无关                                                                                                         |

---

## 2. 文档

| 文档                                                        | 用途                                 |
| :---------------------------------------------------------- | :----------------------------------- |
| [CARD_ENGINE_COMMANDS.md](doc/webui/CARD_ENGINE_COMMANDS.md) | CLI 速查                             |
| [DRAW_GUIDE.md](doc/cli/DRAW_GUIDE.md)                       | 常规模式交互（交互前必读）           |
| [PROMPT_TEMPLATE.md](doc/cli/PROMPT_TEMPLATE.md)             | 导演决策链 / 填槽规范（fill 前必读） |
| [CHECK_PITFALLS.md](doc/cli/CHECK_PITFALLS.md)               | 高频避坑（fill 前必读）              |
| [CONFIG_GUIDE.md](doc/webui/CONFIG_GUIDE.md)                 | `config.json`                      |
| [CLOUD_DRAW.md](doc/cli/CLOUD_DRAW.md)                       | 外部渲染                             |

---

## 3. 维护

* **归档**：`python3 scripts/card-engine/card_cli.py archive --card <id>`，命名 `人物·场景·主题`
* **自检**（skill 根，按需）：连抽前 `python3 tests/smoke_test_fast.py`；WebUI 改动 `python3 tests/smoke_test_webui.py`；全量 `python3 -m pytest -q`
* **队列**：

```bash
python3 scripts/card-engine/card_cli.py queue status
python3 scripts/card-engine/card_cli.py queue remove --position N
python3 scripts/card-engine/card_cli.py queue clear --force
rm -f /tmp/cu-card/cu-gpu.lock            # Windows：%TEMP%\cu-card\cu-gpu.lock
```
