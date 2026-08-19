# amazing-draw 配置文件使用指南 (CONFIG_GUIDE)

> [!NOTE]
> 本文件为 `config.json` 的专属注释与字段说明。
> 标准 JSON 不支持行内注释；在 `config.json` 里写 `//` / `#` 会导致解析崩溃。WebUI 保存设置时会重新序列化覆盖该文件，手动加的非标字段也会被擦掉。请以本指南维护参数说明。

**配置文件路径**：发行包 / 仓库内 `scripts/config.json`（已跟踪）。安装后运行时权威副本为 `~/.openclaw/draw-cards/config.json`  
（`card_config.load_system_config` / WebUI 均读此路径；勿与仓库外其它副本混淆。）

---

## 1. 工作区与环境路径 (Paths & Environment)

### 出图两目录职责对照（勿混）

| 键 | 角色 | 当前推荐 | WebUI |
|----|------|----------|-------|
| `output_dir` | ComfyUI **本地实时落盘** | macOS `~/ComfyUI/output` · Windows `C:\ComfyUI\output` | `/images` 双挂载之一 |
| `output_dir_archive` | **外置归档**；交付优先 `cp` 到此 | macOS `~/Downloads/card-engine-out` · Windows `D:\amazing_draw` | `/images` 优先源 |

交付「归档超时 → 本地 rename」落在 **`output_dir`**。已移除废弃键 `output_dir_fallback`（旧第三搜救源；职责已由本地 `output_dir` + `/images` 双挂载覆盖）。

* **`openclaw_workspace_dir`**
  - OpenClaw 工作区根目录。空字符串时由调用方/默认逻辑处理；支持 `~` 展开。

* **`comfyui_dir`**
  - 本地 ComfyUI 根目录；`comfyui-start.sh` 拉起后端时使用。

* **`output_dir`**
  - ComfyUI / 工作流当前输出目录（生图落盘主路径，宜本地 SSD）。
  - 示例：macOS `"~/ComfyUI/output"` · Windows `"C:\ComfyUI\output"`
  - WebUI `/images` 在配置了 `output_dir_archive` 时**仍会同时挂载**本目录（交付外置盘超时本地命名后仍可预览）。

* **`output_dir_archive`**
  - 归档扫描目录（交付优先拷贝、历史图检索优先扫这里）。可与 `output_dir` 不同。
  - 示例：macOS `"~/Downloads/card-engine-out"` · Windows `"D:\amazing_draw"`
  - WebUI `/images` 优先从此目录取图。

* **`obsidian_vault_dir`**
  - Obsidian 双链归档库路径；提交后把 prompt/卡片信息写成 markdown。

* **`custom_presets_dir`**
  - 第三方角色 / 场景预设根目录（抽卡与 WebUI 共用）。
  - 约定子目录：`amateurs/`、`roles/`（角色，格式见目录内 `template.json`）、`scenes/`（场景）。
  - 引擎**跳过**名为 `template.json` 的文件；复制改名后才生效。
  - 本机自定；常见为 OpenClaw 工作区下的 `draw-cards/custom_presets`（或 `scripts/presets` 软链）。

* **`recording_dir`**
  - 抽卡历史 MD 归档目录（submit 门禁通过后写入）。

* **`cards_dir`** / **`tmp_dir`**
  - 卡片 JSON 与临时目录；空字符串时回退代码默认（如 `~/.openclaw/draw-cards/cards`、`/tmp/cu-card`）。
  - **消费方**：`card-engine`（读写卡）、`cu-queue.py` / `cu-submit.sh` / `cu-deliver.sh` / `cu-progress.sh` / WebUI `api_queue`（队列、GPU 锁、done/meta、进度面板）。改路径后上述链路会跟着走；部分周边脚本（如 `cu-worker.sh`、`cu-draw-card.py` 默认日志）仍可能写死默认值，改 `tmp_dir` 时需一并核对。

---

## 2. 服务与网络 (Services & Hosts)

* **`comfyui_host`**：ComfyUI HTTP API，默认 `"http://127.0.0.1:8188"`
  - 消费方含 `cu-draw-card` 轮询、`cu-queue.py health`、`cu-progress.sh`、WebUI 队列状态等；勿只改代码硬编码端口。
* **`webui_host`** / **`webui_port`**：控制台绑定，默认 `0.0.0.0` / `8318`
* **`open_webui_url`** / **`open_webui_api_key`**：可选 LLM 控制端对接（密钥勿提交仓库）

---

## 3. 大语言模型 (LLM)

* **`llm_model`**：主模型（Prompt / 导演填充等）
* **`independent_llm_model`**：独立会话 / 预检等；不可用时走 fallback
* **`llm_fallback_models`**：备用模型列表
* **`llm_temperature`**：默认 `0.7`（建议 `0.5 ~ 0.85`）
* **`llm_retry_limit`**：失败重试次数，默认 `3`

---

## 4. 生图、会话与裸露限制 (Draw & Exposure)

* **`agent_backend`**：`"openclaw"` / `"custom_http"` 等
* **`agent_api_key`** / **`agent_webhook_url`**：自定义 Agent 对接（可空；密钥勿入库）

* **`chat_mode`**（WebUI 侧栏会话键）
  - `"cards"`（兼容旧 `"single"`）：卡片列表；发送会交接至抽卡会话
  - `"draw"`（兼容旧 `"raw_llm"`）：真 AI 抽卡对话
  - `"chain"` / `"direct"`：兼容键；主路径分别走连抽 / 闪电提交 API

* **`perspective_draw_prob`**（可选）
  - 随机场景时优先命中视角库的概率；**未写入 config 时走代码默认**（若调用方读取缺失则自行兜底）。

* **`exposure_allowed_modes`**（优先）
  - 全局允许的裸露档**真集合**，例：`["upper", "lower", "half_nude"]`
  - WebUI「画面裸露范围限制」chips 多选写入；至少保留一项
  - 完整语义见 [EXPOSURE_LIMITS_GUIDE.md](./EXPOSURE_LIMITS_GUIDE.md) §1

* **`exposure_limit`**（兜底 / 兼容区间）
  - `[min_mode, max_mode]` 闭区间；无 `exposure_allowed_modes` 或为空时使用
  - WebUI 保存 chips 时会**派生**写入本字段以兼容旧逻辑

* **`perspective_exposure_bindings`**（可选；缺省用代码内置默认）
  - 视角 → 允许 `director.exposure_mode` 集合。默认摘要：
    - `颜射视角` → `upper` / `half_covered`
    - `后入视角` → `lower` / `half_nude`
    - `丝袜视角` → `half_nude` / `half_covered`
  - **仅完整「X视角」四词触发**；短词「颜射 / 后入 / 丝袜」**不**再绑定（防误绑普通场景）
  - 场景条目 `allowed_exposure` 可覆盖；详解见 [EXPOSURE_LIMITS_GUIDE.md](./EXPOSURE_LIMITS_GUIDE.md) 视角绑定节

* **`scene_cooldown_window`**：连续 N 张内避免重复同一具体场景

* **`auto_horizontal_for_multi`**：检测多人时是否自动切横版

* **`scene_library_weights`**：各场景子库相对抽样权重  
  （`school` / `general` / `medical` / `workplace` / `sm` / `special` / `perspective`）  
  「灵感原点 / featured」不在 special 库内，由代码 meta 服务。

* **`resolution_presets`**：版式像素字典  
  常见键：`vertical` / `horizontal` / `square` / `widescreen`

---

## 5. 工作流 (Workflows)

原独立 `workflow_defaults.json` 已并入本配置。

* **`workflows`**：工作流 id → 元数据（尺寸、节点映射等）字典
* **`default_workflow`**：默认工作流 id（例：`moody_zib_zit`）
* **`workflows_aliases`**：短名别名，例：`{"moody": "moody_zib_zit"}`
* **`lock_size_to_workflow`**：是否锁定卡片尺寸跟随工作流预设（默认 `true`）

WebUI「默认工作流」下拉读写以上字段。

---

## 6. 投递与通知 (Delivery)

* **`delivery_telegram`** / **`delivery_webui`**：是否推 Telegram / 控制台预览
* **`telegram_chat_id`** / **`telegram_bot_token`**：推送目标；Token 可空并回退 `~/.openclaw/workspace/.bot_tokens`  
  **勿把真实 ID/Token 提交进 Git**

---

## 7. 可选引擎表（缺省回退文件或代码）

下列键**可以不写在 config.json**；存在则覆盖，否则走旁路文件 / 内置默认。

* **`direction_map`**：数字指令位映射（亦可读 `card-engine/config/direction-map.json`）
* **`auto_direction_pool`**：`options --auto` 方向池（缺省用 `card_config.DIRECTION_POOL`）
* **`validation_rules`**：故事字数 / prompt 词数门禁阈值（缺省见 `load_validation_rules`）
* **`scene_registry`**：场景库注册表（已启用子库列表）；当前主配置通常内含 `libraries`

---

## 7. 连抽卡间内存策略（环境变量，非 config.json）

交付脚本 `cu-deliver.sh` 在**队列仍非空**（还有下一张）时执行；**只抽一张 / 末张**跳过。

| 变量 | 默认 | 说明 |
|------|------|------|
| `CU_BETWEEN_CARDS` | `restart` | 平级互斥：`restart` 停 Comfy 进程级释放 → 下一 worker 再 start；`free` 调 Comfy `/free`；`off` 跳过 |
| `CU_FREE_BETWEEN` | `1` | 仅 `CU_BETWEEN_CARDS=free` 时有效；`0` 关闭 `/free` |
| `CU_FREE_TIMEOUT` | `90` | `/free` 等待显存回升秒数 |
| `CU_AUTO_STOP_DELAY` | `60` | 队列空后延迟自动停 Comfy |

示例：测完若重启太慢，临时切回软清空：

```bash
export CU_BETWEEN_CARDS=free
```

---

## 相关文档

| 文档 | 内容 |
| :--- | :--- |
| [EXPOSURE_LIMITS_GUIDE.md](./EXPOSURE_LIMITS_GUIDE.md) | 裸露集合 / 区间 / 绑定 / 直通 / 填卡可见可选档 |
| [CARD_ENGINE_COMMANDS.md](./CARD_ENGINE_COMMANDS.md) | CLI 与 featured 旁路 |
| [USER_GUIDE.md](./USER_GUIDE.md) | 日常改配置入口 |

*文档更新：2026-08-07 — 连抽卡间 CU_BETWEEN_CARDS（restart/free/off，默认 restart）。*
