# 配置文件使用指南

`config.json` 不能写 `//` 注释。WebUI 保存设置会整文件重写，手动加的未知字段也会被擦掉。

| 环境 | 实际读取 |
| :--- | :--- |
| 本地 skill | `scripts/config.json`（本机文件，不进 git） |
| 发行包 | 安装后 `~/.openclaw/draw-cards/config.json`（对照 `config.example.json` 生成；已有则不覆盖） |

引擎始终读 `scripts/config.json`。发行包安装时会把它和 `~/.openclaw/draw-cards/config.json` 同步。

---

## 路径

出图两目录不要混：

| 键 | 作用 | 常见值 |
| :--- | :--- | :--- |
| `output_dir` | ComfyUI 本地实时落盘 | macOS `~/ComfyUI/output` · Windows `C:\ComfyUI\output` |
| `output_dir_archive` | 外置归档，交付优先拷到这里；WebUI `/images` 优先扫这里 | macOS `~/Downloads/card-engine-out` · Windows `D:\amazing_draw` |

归档拷贝超时会回落到 `output_dir` 做本地 rename。

| 键 | 作用 |
| :--- | :--- |
| `comfyui_dir` | 本机 ComfyUI 根目录，`comfyui-start.sh` 用 |
| `obsidian_vault_dir` | Obsidian 库根。提交后写 markdown；精选从 `灵感库/` 抽 `.md`，图在 `attachments/`。空则精选不可用 |
| `custom_presets_dir` | 第三方角色 / 场景。子目录 `amateurs/`、`roles/`、`scenes/`。名为 `template.json` 的文件会被跳过 |
| `recording_dir` | 抽卡历史 MD（submit 通过后写入） |
| `cards_dir` | 卡片 JSON。空则 `~/.openclaw/draw-cards/cards` |
| `tmp_dir` | 临时目录。空则 `/tmp/cu-card`（Windows 由 `install.sh` 改成系统临时目录） |
| `openclaw_workspace_dir` | OpenClaw 工作区根。空则不用。支持 `~` |

---

## 服务

| 键 | 默认 | 说明 |
| :--- | :--- | :--- |
| `comfyui_host` | `http://127.0.0.1:8188` | ComfyUI HTTP API |
| `webui_host` / `webui_port` | `0.0.0.0` / `8318` | WebUI 绑定 |

---

## LLM 与 Agent

| 键 | 说明 |
| :--- | :--- |
| `llm_model` | 主模型（导演填槽 / prompt） |
| `independent_llm_model` | 独立会话 / 预检；不可用时走 fallback |
| `llm_fallback_models` | 备用模型列表 |
| `llm_temperature` | 默认 `0.7` |
| `llm_retry_limit` | 失败重试。代码默认 `1` |
| `agent_backend` | 发行默认 `custom`；本地 skill 常用 `openclaw`。旧值 `claudecode` / `hermes` 会归一成 `openclaw` |
| `openclaw_ws_timeout_seconds` | OpenClaw 等待秒数，默认 `600` |
| `chat_mode` | WebUI 会话：`cards`（卡片列表）和 `draw`（抽卡对话） |

---

## 抽卡与画面

| 键 | 说明 |
| :--- | :--- |
| `exposure_allowed_modes` | 允许的裸露档集合，优先。例 `["upper","lower","half_nude"]`。WebUI chips 写入，至少一项 |
| `exposure_limit` | 兼容区间 `[min, max]`。没有 `exposure_allowed_modes` 时用。WebUI 保存 chips 时会派生写入 |
| `restrict_roles` | 默认 `true`。WebUI「限制角色」：打开后限制角色不进角色库 |
| `enable_ai_check` | 默认 `false`。打开后 `check_prompt.sh` 在物理门禁之外再调 LLM 语义检查。WebUI 在「单轮对话总时限」右侧 |
| `scene_cooldown_window` | 连续 N 张内避免同一具体场景，默认 `9` |
| `auto_horizontal_for_multi` | 检测到多人时是否自动切横版，默认 `true` |
| `scene_library_weights` | 子库抽样权重，键名带 `_scenes`：`school_scenes` / `general_scenes` / `medical_scenes` / `workplace_scenes` / `sm_scenes` / `special_scenes` / `perspective_scenes` |
| `scene_registry` | 场景库注册（enabled / 中文名 / 文件名）。WebUI 权重面板依赖它 |
| `resolution_presets` | 版式像素。常见键 `vertical` 512×768、`horizontal` 768×512、`square` 640×640、`widescreen` 1088×464 |

---

## 工作流

已不再使用独立的 `workflow_defaults.json`。

| 键 | 说明 |
| :--- | :--- |
| `default_workflow` | 默认工作流 id，例如 `moody_zib_zit` |
| `workflows_aliases` | 短名，例如 `{"moody":"moody_zib_zit"}` |
| `workflows` | id → 元数据（路径、节点、默认宽高） |
| `lock_size_to_workflow` | 卡片尺寸是否跟工作流走，默认 `true` |

发行包工作流在仓根 `workflows/*.json`。

---

## 投递

| 键 | 说明 |
| :--- | :--- |
| `delivery_telegram` / `delivery_webui` | 是否推 Telegram / 控制台预览 |
| `telegram_chat_id` / `telegram_bot_token` | 推送目标。Token 可空。真实 ID/Token 不要提交 git |

---

## 可选覆盖（不写就用内置）

| 键 | 缺省 |
| :--- | :--- |
| `direction_map` | `scripts/card-engine/config/direction-map.json` |
| `auto_direction_pool` | 代码 `DIRECTION_POOL` |
| `validation_rules` | 代码门禁阈值 |

---

## 连抽卡间（环境变量，不是 config.json）

`cu-deliver.sh` 在队列里还有下一张时执行；只抽一张或末张会跳过。

| 变量 | 默认 | 说明 |
| :--- | :--- | :--- |
| `CU_BETWEEN_CARDS` | `restart` | `restart` 停 Comfy 再由下一 worker start；`free` 调 `/free`；`off` 跳过 |
| `CU_FREE_BETWEEN` | `1` | 仅 `free` 时有效 |
| `CU_FREE_TIMEOUT` | `90` | `/free` 等待秒数 |
| `CU_AUTO_STOP_DELAY` | `60` | 队列空后延迟停 Comfy |
