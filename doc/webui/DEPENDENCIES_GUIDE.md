# amazing-draw · 软件、模型与环境依赖全量指南 (DEPENDENCIES)

> **目标**：为全新的 macOS / Windows 机器提供从零搭建、环境依赖、模型下载、软件放置到一键绿线验证的完整指南。
> **平台兼容**：内核按平台分发：macOS 在本机编译 `.so`，Windows 由 CI 编译 `.pyd`。Windows 用 [Git for Windows](https://git-scm.com/download/win) 提供 bash 层（见 §1.2 / §8）。**Windows 尚未实机测试。**
>
> **发行包放哪**：zip 解压到任意固定目录即可（例如 macOS `~/AmazingDraw`，Windows `C:\AmazingDraw`）。解压目录就是运行时（WebUI / CLI / skill），不要拆散、不要放进 ComfyUI，也不要把 `assets.bin` 从 `card_engine_core/native/` 拆走。`install.sh` 会把工作流拷到 `~/ComfyUI/workflows/`、自定义节点拷到 ComfyUI `custom_nodes/`；配置写到 `~/.openclaw/draw-cards/config.json`。

---

## 1. 💻 系统环境与基础软件

要在机器上跑通完整的 **amazing-draw** 抽卡工作流，需满足以下基础系统环境：

- **操作系统**：macOS (Apple Silicon / Intel)、Windows 10/11
- **终端 Shell**：`bash` 终端
- **基础工具链**：
  - [`python3`](https://www.python.org/downloads/)（引擎只认两套 Python：**3.9**（zip 标 `cp39`）和 **3.12**（zip 标 `cp312`）。必须和压缩包文件名一致，不要用 3.10 / 3.11。Apple 自带 `/usr/bin/python3` 是 3.9，请下 cp39。ComfyUI 用它自己的 venv，可以和引擎不是同一个。不要把 `.so` 和 `.pyd` 混放，也不要混 3.9/3.12 native）
  - [`pip`](https://pip.pypa.io/en/stable/installation/)（Python 包管理器）
  - [`git`](https://git-scm.com/)（版本控制与插件同步）
  - [`curl`](https://curl.se/)（网络请求与后端通信）
  - [`Obsidian`](https://obsidian.md/)（可选。精选笔记和出图归档是 Obsidian 库结构，可用 Obsidian 打开管理）
  - [`ffmpeg`](https://ffmpeg.org/download.html)（可选，某些视频/图像处理预览需要）

macOS 可用 [Homebrew](https://brew.sh/)；Windows 也可用 [`uv`](https://github.com/astral-sh/uv)。

### 1.1 平台工具链差异

| 平台 | Python 获取 | bash 获取 | 内核产物 |
| :--- | :--- | :--- | :--- |
| macOS | 安装器 / [Homebrew](https://brew.sh/) / [`uv`](https://github.com/astral-sh/uv) | 自带 bash | 本机编译 `native/*.so`（`cpython-39-darwin` / `cpython-312-darwin`，与 zip 的 `cp39` / `cp312` 对应） |
| Windows | 安装器 / [`uv`](https://github.com/astral-sh/uv) | **[Git for Windows](https://git-scm.com/download/win)（Git Bash）** | CI 编译 `native/*.pyd`（cpython-3x-win_amd64） |

### 1.2 Windows 特别说明

Windows 下 bash 由 **[Git for Windows](https://git-scm.com/download/win)** 提供（Git Bash），补上后 shell 管线（`gpu-pipeline/*.sh`）才能运行。安装页：[git-scm.com/download/win](https://git-scm.com/download/win)。**Windows 发行包尚未在实机上测试。**

⚠️ **关键**：Windows 内核是 `.pyd`（非 macOS 的 `.so`），且 `.pyd` 的 Python 主版本必须与运行环境一致（必须与 zip 标签一致：`cp39` 跑 3.9，`cp312` 跑 3.12）。只装 [Git for Windows](https://git-scm.com/download/win)、不配对应 `.pyd`，内核无法加载（详见 §8）。


---


### 1.3 [Obsidian](https://obsidian.md/)（可选）精选与归档

骰子「精选」和出图后的 markdown 归档，落在一个 [Obsidian](https://obsidian.md/) 库里。用 Obsidian 打开这个目录即可浏览、改笔记、管理配图。不装也能抽卡出图，只是精选池和库内归档不可用。

- **下载**：[obsidian.md](https://obsidian.md/)（免费本地笔记）
- **配置**：`config.json` 的 `obsidian_vault_dir`（库根目录）。空则精选会提示找不到库。
- **目录约定**（引擎按文件夹名查找，不要改中文名）：

```text
<obsidian_vault_dir>/
  灵感库/         # 每条精选一篇 .md；骰子随机抽这里
  attachments/    # 与笔记同名的 .png
  .obsidian/      # Obsidian 自己的库配置，引擎不读
```

在 Obsidian 里选「打开库文件夹」，指到 `obsidian_vault_dir`。改 `灵感库/` 里的 md 就是在改精选池。Windows 路径用正斜杠，例如 `"D:/vault"`。

---

## 2. 📦 Python 依赖库清单

### WebUI & HTTP 依赖

> **平台提示**：[`cryptography`](https://pypi.org/project/cryptography/) 在 macOS 由源码编译或 wheel 安装；**Windows 建议直接装预编译 wheel**（`pip install cryptography` 会自动取 win_amd64 wheel）。`.pyd` 编译版本须与本机 Python 主版本一致（§1.2）。

```bash
python3 -m pip install --upgrade pip
python3 -m pip install fastapi uvicorn requests websockets cryptography httpx
```

| 包 | 用途 |
| :--- | :--- |
| [`fastapi`](https://fastapi.tiangolo.com/) / [`uvicorn`](https://www.uvicorn.org/) | WebUI 8318 服务网关与路由 |
| [`requests`](https://pypi.org/project/requests/) / [`httpx`](https://www.python-httpx.org/) | 调用 ComfyUI 8188 API 以及模型直投通信 |
| [`websockets`](https://pypi.org/project/websockets/) / [`cryptography`](https://pypi.org/project/cryptography/) | [OpenClaw Gateway](https://docs.openclaw.ai/gateway) WebSocket 鉴权与私钥握手签名 |

---

## 3. ⚡ ComfyUI 后端引擎配置

工作流依赖本机独立安装的 **[ComfyUI](https://github.com/comfyanonymous/ComfyUI)**：

- **项目**：[github.com/comfyanonymous/ComfyUI](https://github.com/comfyanonymous/ComfyUI)
- **默认根路径**：`~/ComfyUI`（Windows 在 Git Bash 下 `~` 映射到 `C:\Users\<用户名>`，即 `C:\Users\<用户名>\ComfyUI`）
- **默认监听端口**：`http://127.0.0.1:8188`
- **配置文件**：修改 `scripts/config.json` 中的 `comfyui_dir` 与 `comfyui_host`。
- **Windows 路径提示**：`config.json` 中所有 POSIX 风格路径（`~/...`、`/tmp/...`）在 Git Bash 内由 `os.path.expanduser` 解析为 Windows 用户目录；`cryptography`/模型路径建议显式写 Windows 绝对路径（`C:${HOME}/...`）避免歧义。
- **本机模型清单**（命名与下载页）：`~/ComfyUI/models/README.md`

### 自带启停与管理脚本

```bash
# 启动 ComfyUI 后端（自动读取 config.json）
bash scripts/gpu-pipeline/comfyui-start.sh start

# 查看 ComfyUI 运行状态
bash scripts/gpu-pipeline/comfyui-start.sh status

# 停止 ComfyUI 后端
bash scripts/gpu-pipeline/comfyui-start.sh stop
```

---

## 4. 🎭 模型、工作流与 LoRA 依赖规范

模型和 LoRA 都放在 [ComfyUI](https://github.com/comfyanonymous/ComfyUI) 自己的目录里（`models/diffusion_models`、`models/text_encoders`、`models/vae`、`models/loras`），启动不再另挂 extra-models yaml。

### 4.1 默认工作流

当前默认工作流 id 是 `moody_zib_zit`（别名 `moody`）：

- **Moody ZIB+ZIT**（主打写真）：`~/ComfyUI/workflows/Moody_ZIB_ZIT_20步_CFG3_512x768.json`
- 双阶段：先 [Moody Wild Mix（ZIB Base）](https://civitai.red/models/2384856/moody-wild-mix)，再 [Moody Real Mix（ZIT Turbo）](https://civitai.com/models/621441)
- 角色 LoRA 子目录：`girls_like_zi`

### 4.2 默认 Moody 工作流用到的模型

| 用途 | 文件 | 放置目录 | 来源 |
| :--- | :--- | :--- | :--- |
| 一阶段 UNET（ZIB） | `MoodyWildMix-zib-base.safetensors` | `models/diffusion_models/` | [CivitAI · Moody Wild Mix](https://civitai.red/models/2384856/moody-wild-mix) |
| 二阶段 UNET（ZIT） | `MoodyRealMix-zit-write.safetensors` | `models/diffusion_models/` | [CivitAI · Moody Real Mix](https://civitai.com/models/621441) |
| 文本编码器 | `qwen_3_4b.safetensors` | `models/text_encoders/` | [Hugging Face · Comfy-Org/z_image_turbo](https://huggingface.co/Comfy-Org/z_image_turbo) |
| VAE | `ae.safetensors` | `models/vae/` | [Hugging Face · Comfy-Org/z_image_turbo](https://huggingface.co/Comfy-Org/z_image_turbo) |

> CLIPLoader type 选 `lumina2`。推荐采样参数以 CivitAI 模型页为准（ZIB 约 CFG 4 · 40 步；ZIT 约 CFG 1 · 8 步）。

### 4.3 角色 LoRA（`girls_like_zi`）

常规素人与明星写真依赖 GirlsLike 人物 LoRA（**本机 129 个 zi，与 HF `girlslike-zimage` 对齐**）：

- **包**：[ifmylove2011/girlslike-zimage](https://huggingface.co/ifmylove2011/girlslike-zimage)
- **画廊**：[GirlsLike LoRA Gallery](https://huggingface.co/spaces/ifmylove2011/girlslike_lora_gallery)
- **物理存放**：`~/ComfyUI/models/loras/girls_like_zi/`
- **本机全表**：`~/ComfyUI/models/loras/README.md`
- **抽卡键名**：`scripts/card-engine/config/celebrities.json` 的 `z`

文件名不要改。触发词跟文件名绑定，并写进 `celebrities.json` 才能抽到。

---

## 5. 🦞 OpenClaw Agent 网关

发行版默认 `agent_backend=custom`，**不要求安装 OpenClaw**。OpenClaw 网关是可选对话后端；需要时再自行改配置。抽卡与出图主路径走 WebUI + [ComfyUI](https://github.com/comfyanonymous/ComfyUI)。

### 5.1 安装与版本

- **安装方式**：npm 全局包（`/opt/homebrew/lib/node_modules/openclaw`）
- **运行时**：[Node.js](https://nodejs.org/)（本机 v24）
- **当前版本**：以本机 `openclaw --version` 为准（桥接按 **2026.8.1** Gateway protocol v4 握手）
- **主配置**：`~/.openclaw/openclaw.json`
- **网关端口**：`18789`（见下方端口表）

WebUI 通过 WebSocket 连本机网关，握手用设备私钥签名。2026.8.1 起真源是 `~/.openclaw/state/openclaw.sqlite` 的 `device_identities`（`identity_key=primary`）；`identity/device.json` 只是升级前的遗留文件，Doctor 迁完就会删。Python 侧需要 `websockets` 与 `cryptography`。

### 5.2 模型来源

WebUI 设置页的模型下拉直接读 OpenClaw 的可用模型。OpenClaw 里有什么，WebUI 里就能选什么。

### 5.3 ⏱️ 两处超时，分属不同层

出问题时先分清是哪一层在喊停，两者互相独立：

| 层级 | 配置位置 | 含义 | 默认 |
| :--- | :--- | :--- | :--- |
| **OpenClaw 空闲看门狗** | `openclaw.json` → `models.providers.<provider>.timeoutSeconds` | 模型**连续多久不吐字**就判超时 | 未配置时 **120 秒** |
| **WebUI 单轮总时限** | 设置页「WebUI 本地服务运行参数」→ 单轮对话总时限<br>（`config.json` 的 `openclaw_ws_timeout_seconds`） | 一轮对话**最长允许跑多久** | 600 秒（可填 60–7200） |

**关键坑**：`models.providers` 里没有条目的 provider 拿不到任何超时配置，只能吃 120 秒默认值。通过 auth-profile 注册的 provider（如 `opencode-go`）尤其容易踩到 —— 它不会自动出现在 `models.providers` 里。

报错长这样，一眼可辨：

```
LLM idle timeout (120s): no response from model
```

补配置只需在 `models.providers` 下加一个**只带超时**的条目即可，不用重复写 `baseUrl` / `api` / 模型列表 —— 配置是叠加在 auth-profile 已注册的信息之上，不是替换：

```json
{
  "models": {
    "mode": "merge",
    "providers": {
      "opencode-go": { "timeoutSeconds": 600 }
    }
  }
}
```

另一个反直觉之处：**`agents.defaults.timeoutSeconds` 抬不高这个值**。它在解析时走的是「取较小者」，只能往下压。想突破 120 秒，唯一的路就是上面这个 provider 级 `timeoutSeconds`。

`models` 前缀属于热加载，改完**不需要重启网关**。

### 5.4 常用排查命令

```bash
# 网关版本与存活
openclaw --version

# 各 provider 的超时配置一览（未列出的即吃 120 秒默认值）
python3 -c "import json,os;p=json.load(open(os.path.expanduser('~/.openclaw/openclaw.json')))['models']['providers'];[print(f'{k}: {v.get(\"timeoutSeconds\",\"未配置\")}') for k,v in p.items()]"

# 翻网关日志确认超时的原始报错（8.1 会话正文在 sqlite，不再翻 sessions/*.jsonl）
openclaw logs --limit 80 --plain | grep -E 'idle timeout|LLM idle'
```

---

## 6. 🔌 服务端口与网络拓扑

| 服务名称 | 默认端口 | 绑死地址 | 用途说明 |
| :--- | :--- | :--- | :--- |
| **[ComfyUI](https://github.com/comfyanonymous/ComfyUI) 后端** | `8188` | `127.0.0.1` | GPU 图像采样渲染引擎 |
| **WebUI 控制台** | `8318` | `0.0.0.0` | 本地抽卡与配置前端 |
| **[OpenClaw Gateway](https://docs.openclaw.ai/gateway)** | `18789` | `127.0.0.1` | WebSocket 设备握手与消息网关（见第 5 节） |

---

## 7. ✅ 一键环境自检与绿线验证

安装部署完成后，在终端运行以下命令进行全量环境自检：

```bash
# 1. 验证 ComfyUI 连通性
curl -fsS "http://127.0.0.1:8188/system_stats" && echo "✅ ComfyUI 连通正常"

# 2. 跑通引擎快测绿线（连抽前门禁 / 自愈回归）

# 3. 校验场景库与角色预设

# 4. 验证 OpenClaw 网关存活
openclaw --version && echo "✅ OpenClaw 可用"
```


---

## 8. 🖥️ macOS 与 Windows

内核是平台绑定层：**macOS 在本机编译** `.so`，**Windows 由 CI 编译** `.pyd`。前端和明文 Python 两边通用。

### 8.1 对照

| 项 | macOS | Windows |
| :--- | :--- | :--- |
| 内核 | 本机编译 `native/*.so` | CI 编译 `native/*.pyd` |
| Python 版本 | 必须和 zip 标签一致（`cp39`→3.9，`cp312`→3.12；Apple 自带 3.9 请下 cp39） | **必须与 .pyd 编译版本一致** |
| bash | 自带 | **[Git for Windows](https://git-scm.com/download/win)（Git Bash）** |
| OpenClaw | npm 全局安装 | npm 安装（路径 `~/.openclaw` 映射） |
| [ComfyUI](https://github.com/comfyanonymous/ComfyUI) | 支持 | 支持（有 Windows 版） |

### 8.2 Windows 装机清单（按序）

1. **[Git for Windows](https://git-scm.com/download/win)** → 提供 Git Bash
2. **[Python 3.9 或 3.12](https://www.python.org/downloads/)**（必须和 zip 标签一致：`cp39`→3.9，`cp312`→3.12）
3. **pip 安装依赖**（§2 命令）
4. **放置 `.pyd`** 到 `card_engine_core/native/`（CI 编译产物，随发行版分发）
5. **安装 [ComfyUI](https://github.com/comfyanonymous/ComfyUI)**（Windows 版）。OpenClaw 可选，默认不需要
6. `bash scripts/gpu-pipeline/comfyui-start.sh start` 启动 ComfyUI
7. `python3 scripts/webui/web_server.py` 启动 WebUI

### 8.3 Windows 差异速查

| 差异 | 处理 |
| :--- | :--- |
| 路径 `~/...` / `/tmp/...` | Git Bash 内 `expanduser` 解析；Windows 可写 `C:/...` 绝对路径 |
| `.so` → `.pyd` | macOS 本机编译的 `.so` 不能拿到 Windows 用；必须用 CI 的 `.pyd`，且 Python 主版本须匹配 |
| 模型路径 | `comfyui_dir` 指向 Windows 上 ComfyUI 实际目录 |
| 启动脚本 | 全部经 Git Bash 的 `bash` 运行 |
| OpenClaw 网关 | 端口 18789 不变，安装方式见 §5 |

### 8.4 关键约束（务必读）

- **只装 [Git for Windows](https://git-scm.com/download/win) ≠ 可用**：内核需要 Windows `.pyd`（非 macOS `.so`），且 Python 版本匹配。
- 前端（webui 明文壳）+ 明文 Python 两边通用；**内核是平台绑定层**。
- macOS `.so` 不能直接复制到 Windows 用（Mach-O ≠ PE/DLL）。Windows 必须用 CI 编译的 `.pyd`。
