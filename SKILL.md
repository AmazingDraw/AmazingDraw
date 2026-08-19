---
name: amazing-draw
description: >
  ComfyUI 抽卡控制台与 WebUI 运维指南。基于 Card Engine：场景选型、人物建模、AI 导演填槽到存档，以及 WebUI 会话、队列与直投提取。
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

> **参数与步骤以 CLI `--help` 为准**；本文只保留 Agent 契约、入口路径与文档索引。
>
> **路径约定**：下文路径均相对本文件所在目录（zip / 仓库根）。正斜杠 `/` 在 macOS 与 Windows 通用。解释器必须和发行包文件名里的 Python 标签一致：`cp39` → Python 3.9，`cp312` → Python 3.12。Apple 自带 `/usr/bin/python3` 是 3.9，请下 cp39；本机 3.12 请下 cp312。不要把 `.so` 和 `.pyd` 混放，也不要混 3.9/3.12 native。ComfyUI 用它自己的 venv，可以和引擎 Python 不是同一个。启动脚本：`bash scripts/...`（Windows 请用 Git Bash）。

---

## ⚡️ ComfyUI 后端 (8188)

```bash
bash scripts/gpu-pipeline/comfyui-start.sh start|stop|status
```

输出目录见 `config.json`：

* `output_dir` — Comfy 本地实时落盘（例：macOS `~/ComfyUI/output` · Windows `C:\ComfyUI\output`）
* `output_dir_archive` — 外置归档（例：macOS `~/Downloads/card-engine-out` · Windows `D:\amazing_draw`）；交付优先拷贝

日志：macOS / Linux / Git Bash：`/tmp/comfyui-headless.log` · Windows cmd/PowerShell：`%TEMP%\comfyui-headless.log`

## ⚡️ WebUI (8318)

```bash
bash scripts/webui/webui-start.sh start|stop|status|restart
```

日志：macOS / Linux / Git Bash：`/tmp/amazing-draw-webui.log` · Windows cmd/PowerShell：`%TEMP%\amazing-draw-webui.log` · 浏览器：`http://127.0.0.1:8318`

---

## 1. 工作模式总览

> [!IMPORTANT]
> 进入任意模式前，**必须先**执行对应 `--help`。`argparse` 帮助是参数/流程真相源。
>
> ```bash
> python3 scripts/card-engine/card_cli.py <命令> --help
> # Windows: python scripts/card-engine/card_cli.py <命令> --help
> ```

> **真相源**：`card.json` 唯一；`slots.body_shape` 为体型真相源。改核心字段后须作废 render 缓存。

> ⭐ **默认模式**：未指定模式时，默认走 🚄 连抽模式（chain 流程）。


| 模式        | 入口命令          | 核心流程                                                                                            | 适用场景                        |
| :------------ | :------------------ | :---------------------------------------------------------------------------------------------------- | :-------------------------------- |
| 🎴 常规模式 | `create`          | 创建骨架 → fill 导演(含 exposure_mode) + 槽位 → 叙事升华 → render 交互循环                       | 精细打磨、逐步调控、强交互      |
| 🚄 连抽模式 | `chain --count N` | 建骨架 → 逐张决策 → **一次 fill**（`--json-file`，勿拆 `--phase`）→ 逐张 resume（**引擎全局串行**，防 check 并发）→ 失败 mend | 批量出片、追求高效一致性        |
| 🚀 直投模式 | `direct --prompt` | 英文 prompt 经 raw 直投 GPU，**零干预**（不经场景库 / 灵感原点）                                    | 已有完整英文 prompt，要求零修改 |
| 🎲 精选模式 | `featured`        | 随机抽 Obsidian 灵感库词条；灵感原点**代码 meta** 原样旁路，无需输入                                | 随机灵感探索、经典重温          |

### Agent 铁律（help 不替代）

* **通用**：优先级 `用户指定 > 库内命中 > 随机补全`；禁止通用词「素人」作 `--person`。库外 `--person`（amateur）自由发明；库外 `--scene`（非纯主题分类词）→ `manual-custom`，fill 必写英文 `scene.keywords`。纯主题词（如「校园」「办公室」）仍进主题池。`restrict_roles` 打开时，限制角色不进入角色库；关掉则恢复。
* **🎴 single**：`workflow_mode=single`；**必** `options --auto`；`present` 只替换 `__dirtytalk__`，禁止自排版/泄露 `card_id`；交互前读 [DRAW_GUIDE.md](doc/DRAW_GUIDE.md)。
* **🚄 chain**：**不要** `options --auto`；中途**不停问**；每张卡 **一次** `fill --json-file`（勿拆 `--phase`）；语义冲突看 `💡 [自愈建议]` 再 fill。
* **🚀 direct**：**禁止**改/扩/删 prompt 或追加画质词；元数据中文参数见 `direct --help`。
* **🎲 featured**：原样渲染灵感库词条；与 CLI `direct` 无关。

填槽/避坑：先 `view` [PROMPT_TEMPLATE.md](doc/PROMPT_TEMPLATE.md) · [CHECK_PITFALLS.md](doc/CHECK_PITFALLS.md)。

---

## 2. 📂 关键文档速查


| 文档                                                                                                                                         | 用途                    |
| :--------------------------------------------------------------------------------------------------------------------------------------------- | :------------------------ |
| [CARD_ENGINE_COMMANDS.md](doc/CARD_ENGINE_COMMANDS.md) | CLI 速查                |
| [DRAW_GUIDE.md](doc/DRAW_GUIDE.md)                     | 常规模式交互            |
| [PROMPT_TEMPLATE.md](doc/PROMPT_TEMPLATE.md)           | 导演决策链 / 提示词装配 |
| [CHECK_PITFALLS.md](doc/CHECK_PITFALLS.md)             | 高频避坑                |
| [CONFIG_GUIDE.md](doc/CONFIG_GUIDE.md)                 | config.json             |

---

## 3. ⚙️ 配置与维护

* **归档**：命名 `人物·场景·主题`（`·` 分隔）；`card_cli.py archive --card <id>`
* **常用命令**（在 zip/仓库根执行；Python 必须和 zip 标签一致：`cp39`→3.9，`cp312`→3.12；macOS：`python3`/`python3.12`；Windows：`python`）。发行包不含 `tests/`，那些自测仅 skill 开发树提供：

```bash

card_cli.py queue status
card_cli.py queue remove --position N
card_cli.py queue clear --force           # 谨慎
rm -f /tmp/cu-card/cu-gpu.lock            # Windows：%TEMP%\cu-card\cu-gpu.lock
```

---

## 4. WebUI 运维 (端口 8318)


| 文件                | 路径                                                                                                                               | 说明                                                    |
| :-------------------- | :----------------------------------------------------------------------------------------------------------------------------------- | :-------------------------------------------------------- |
| **Web 服务网关**    | [web_server.py](scripts/webui/web_server.py) | FastAPI 入口：挂载路由与静态资源                        |
| **卡片/流水线 API** | [api_cards.py](scripts/webui/api_cards.py)   | settings / cards CRUD、四模式流水线、roles/scenes       |
| **队列/文档 API**   | [api_queue.py](scripts/webui/api_queue.py)   | ComfyUI 队列、models、docs                              |
| **对话 API**        | [api_chat.py](scripts/webui/api_chat.py)     | 会话历史、`POST /api/chat` SSE                          |
| **前端应用**        | [static/](scripts/webui/static/)             | `index.html` + 拆分 JS（core / shell / settings / chat） |

```bash
# 日常启停（推荐）
bash scripts/webui/webui-start.sh start|stop|status|restart

# 开发自检（在 zip/仓库根目录执行后 cd；macOS / Linux：python3；Windows：python）
cd scripts/webui
python3 -m py_compile web_server.py api_cards.py api_queue.py api_chat.py
```
