# 配置文件使用指南

运行时只认 `~/.amazingdraw/config.json`（由 `amazingdraw_paths.config_file()` 解析）。旧位置 `scripts/config.json` 仅在目标文件还不存在时自动迁入。环境变量 `AMAZING_DRAW_CONFIG_FILE` 可覆盖路径（容器 / 单测）。模板见 `config.example.json`（skill 在 `scripts/`，发行包在仓根）。不能写 `//` 注释。WebUI 保存设置会整文件重写，手动加的未知字段也会被擦掉。本机文件不进 git。

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
| `custom_presets_dir` | 第三方角色 / 场景。空则 `~/.amazingdraw/custom_presets`。子目录 `amateurs/`、`roles/`、`scenes/`。名为 `template.json` 的文件会被跳过。不在 WebUI 设置页展示 |
| `recording_dir` | 抽卡历史 MD（submit 通过后写入） |
| `cards_dir` | 卡片 JSON。空则 `~/.amazingdraw/cards`（数据根目录固定为 `~/.amazingdraw`，无独立配置键；旧数据用 `python3 scripts/amazingdraw_paths.py migrate` 从 `~/.openclaw/draw-cards`、`~/.openclaw/webui-chat` 复制过来） |
| `tmp_dir` | 临时目录。空则 `/tmp/cu-card`（Windows 由 `install.sh` 改成系统临时目录） |

---

## 服务

| 键 | 默认 | 说明 |
| :--- | :--- | :--- |
| `comfyui_host` | `http://127.0.0.1:8188` | ComfyUI HTTP API |
| `webui_host` / `webui_port` | `0.0.0.0` / `8318` | WebUI 绑定 |

---

## LLM

独立调用走 OpenAI 兼容 HTTP：`card_llm_client.chat_completion` → `{llm.base_url}/chat/completions`。Base URL 按本机实际端点配置。WebUI 已取消抽卡对话（`POST /api/chat` 返回 410）。

| 键 | 说明 |
| :--- | :--- |
| `llm.base_url` | OpenAI 兼容 `/v1` 端点，按本机填写 |
| `llm.api_key` | 可空；端点不需要 key 时留空 |
| `llm.model` / `llm_model` | 唯一模型，设置页从 `/v1/models` 拉取。所有 LLM 调用共用 |
| `llm.timeout_seconds` | 单次请求超时秒数，代码默认 `10` |
| `llm.retry_limit` / `llm_retry_limit` | 单个候选最大尝试次数（含首次），代码默认 `1` |
| `chat_mode` | 读盘时强制为工作台 `cards`；写入会被下次加载覆盖 |

---

## 抽卡与画面

| 键 | 说明 |
| :--- | :--- |
| `exposure_allowed_modes` | 允许的裸露档集合，优先。例 `["upper","lower","half_nude"]`。WebUI chips 写入，至少一项 |
| `exposure_limit` | 兼容区间 `[min, max]`。没有 `exposure_allowed_modes` 时用。WebUI 保存 chips 时会派生写入 |
| `perspective_exposure_bindings` | 特殊视角允许的裸露档。缺省：颜射 `upper`/`half_covered`，后入 `lower`/`half_nude`，丝袜 `half_nude`/`half_covered`，偷拍 `half_nude（region=lower）` |
| `disabled_celebrities` | 默认 `[]`。禁用明星名单：支持填中文名（例 `"高叶"`）或 LoRA 键（例 `"girlslike_zi_gy"`），填入后不进入随机抽取池与候选列表 |
| `enable_independent_llm` | 默认 `true`。引擎独立调用总闸。关闭后节点 ①②④⑤⑦⑧ 不发 HTTP。环境变量 `AMAZING_DRAW_NO_INDEPENDENT_LLM=1` 强制关。WebUI 在服务参数区 |
| `llm_calls` | 分项，默认全 `true`：`route_hint` / `multi_roles` / `body_classify` / `metadata`。总闸关时不生效。不含翻译 |
| `enable_ai_check` | 默认 `false`。打开后 `check_prompt.sh` 在物理门禁之外再调 LLM 语义检查。还要求总闸开。WebUI 在独立调用分项里 |
| `scene_cooldown_window` | 连续 N 张内避免同一具体场景，默认 `9` |
| `auto_horizontal_for_multi` | 仅当检测到 **>=3 人**（3P、双洞、三人合影等）时是否自动切横版，默认 `true`。双人（含深喉第一人称 / 第三人称机位）保持竖屏 |
| `scene_library_weights` | 子库抽样权重，键名带 `_scenes`：`school_scenes` / `general_scenes` / `medical_scenes` / `workplace_scenes` / `sm_scenes` / `special_scenes` / `ancient_scenes` / `perspective_scenes`（日常混合池里 `perspective_scenes` 应为 `0`） |
| `scene_registry` | 场景库注册（enabled / 中文名 / 文件名）。WebUI 权重面板依赖它 |
| `resolution_presets` | 全局回退版式像素（常见 `vertical` 512×768、`horizontal` 768×512、`square` 640×640、`widescreen` 1088×464）。`lock_size_to_workflow` 为 `true` 时优先用当前工作流自己的预设（ZIB/ZIT 512×768，Krea / Moss 768×1152） |
| `perspective_metrics_enabled` | 默认 `true`。特殊视角指标打点统计（可用环境变量 `AMAZING_DRAW_PERSPECTIVE_METRICS` 覆盖），不记录完整 prompt |

---

## 工作流架构与配置

工作流元数据采用 **只读基底 + 状态/差异覆盖**：

- **系统只读基底**：`scripts/card-engine/config/workflows.json`（内置 `moody_zib_zit`、`krea2_turbo`、`moody_moss` 的完整节点与参数，随 Git 代码库升级）。
- **用户运行期覆盖**：写在 `~/.amazingdraw/config.json` 的 `default_workflow` / `workflows_aliases` / `workflows`。无需覆写时 `workflows` 可为 `{}`。

| 键 | 说明 |
| :--- | :--- |
| `default_workflow` | 默认工作流 id（`moody_zib_zit` / `krea2_turbo` / `moody_moss`，可用 `card_cli.py workflow --set zi` / `krea` / `moss` 切换） |
| `workflows_aliases` | （可选）自定义短名别名；基底已预置 `zi`、`krea`、`moss` 等 |
| `workflows` | （可选）用户自定义工作流或覆写基底项。无需覆写时为空 `{}` |
| `lock_size_to_workflow` | 卡片尺寸是否跟工作流走，默认 `true`。优先使用工作流自己的 `resolution_presets` |

---

## 投递

| 键 | 说明 |
| :--- | :--- |
| `delivery_telegram` / `delivery_webui` | 是否推 Telegram / 控制台预览 |
| `telegram_chat_id` / `telegram_bot_token` | 推送目标。Token 可空：空则读环境变量 `TELEGRAM_BOT_TOKEN`（见下）。真实 ID/Token 不要提交 git |

**Bot Token 优先级**：`config.json` 的 `telegram_bot_token` → 环境变量 `TELEGRAM_BOT_TOKEN`。都没有则投递报错；格式须为 `数字:字符串`。

各系统设置 `TELEGRAM_BOT_TOKEN`（换成自己的 token，别提交 git）：

| 系统 | 做法 |
| :--- | :--- |
| macOS / Linux（终端启动） | `export TELEGRAM_BOT_TOKEN='...'`，写进 `~/.bashrc` / `~/.bash_profile`（zsh 用 `~/.zshrc`） |
| macOS（Dock / launchd 等图形方式启动 WebUI，读不到 shell rc） | `launchctl setenv TELEGRAM_BOT_TOKEN '...'`，重启 WebUI；该设置重启电脑后失效 |
| Windows（PowerShell / cmd） | `setx TELEGRAM_BOT_TOKEN "..."`，**新开**终端后生效 |
| Windows Git Bash / WSL | Git Bash 同上（`setx` 后新开 Git Bash）；WSL 按 Linux 写 `~/.bashrc`（WSL 不继承 Windows 的 `setx`） |

只用环境变量也可：把 `config.json` 里 `telegram_bot_token` 留空即可。

---

## 云端出图（可选，默认关）

叠加在建卡流程上的出图策略：开启后交给外部渲染。缺省 `enabled: false`，现网 Comfy + Telegram 不变。

```json
"cloud": {
  "enabled": false,
  "image_backend": "comfy",
  "delivery": "telegram",
  "exposure_allowed_modes": ["half_covered"]
}
```

`enabled: true` 时强制 `image_backend=cloud`、`delivery=none`、裸露仅 `half_covered`（视角绑定不得绕过），且 `submit` / `chain --resume` / `direct` **拒绝**入 Comfy 队列。WebUI 设置「渲染后端」写入该开关（本地 / 云端）。`llm_retry_limit` 仍可写在 config.json，设置页不再展示。

AI / bot：**不要**只靠 CLI help；开云端后的步骤、停在 check 后的 `reason=cloud_draw`、以及 `_render_output.prompt` 路径，一律以 [CLOUD_DRAW.md](../cli/CLOUD_DRAW.md)（`doc cloud`）为准。

---

## 可选覆盖（不写就用内置）

| 键 | 缺省 | 说明 |
| :--- | :--- | :--- |
| `enable_cjk_sanitization` | `true` | 是否启用 CJK 中文清洗与校验拦截。默认开启；设为 `false` 则关闭对非白名单槽位的中文清洗与连抽中文拦截（适用于原生支持中文的底层模型） |
| `direction_map` | `scripts/card-engine/config/direction-map.json` | 方向覆盖表 |
| `auto_direction_pool` | 代码 `DIRECTION_POOL` | 自动方向池 |
| `validation_rules` | 代码门禁阈值 | 校验门禁阈值 |

---

## 连抽卡间（环境变量，不是 config.json）

`cu-deliver.sh` 在队列里还有下一张时执行；只抽一张或末张会跳过。

| 变量 | 默认 | 说明 |
| :--- | :--- | :--- |
| `CU_BETWEEN_CARDS` | `restart` | `restart` 停 Comfy 再由下一 worker start；`free` 调 `/free`；`off` 跳过 |
| `CU_FREE_BETWEEN` | `1` | 仅 `free` 时有效 |
| `CU_FREE_TIMEOUT` | `90` | `/free` 等待秒数 |
| `CU_AUTO_STOP_DELAY` | `60` | 队列空后延迟停 Comfy |
