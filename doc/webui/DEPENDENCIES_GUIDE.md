# amazing-draw · 软件、模型与环境依赖全量指南 (DEPENDENCIES)

> **目标**：为全新的 macOS / Windows 机器提供从零搭建、环境依赖、模型下载、软件放置到一键绿线验证的完整指南。
> **平台兼容**：内核按平台分发：macOS 在本机编译 `.so`，Windows 由 CI 编译 `.pyd`。Windows 用 [Git for Windows](https://git-scm.com/download/win) 提供 bash 层（见 §1.2 / §8）。**Windows 尚未实机测试。**
>
> **发行包放哪**：zip 解压到任意固定目录即可（例如 macOS `~/AmazingDraw`，Windows `C:\AmazingDraw`）。解压目录就是运行时（WebUI / CLI / skill），不要拆散、不要放进 ComfyUI，也不要把 `assets.bin` 从 `card_engine_core/native/` 拆走。`install.sh` 只会把工作流拷到 `~/ComfyUI/workflows/`；发行包本身从固定解压目录运行。
>
> **配置权威路径**：运行期只认 `~/.amazingdraw/config.json`。包内 / skill 的 `scripts/config.json` 仅在家里这份还不存在时迁入。可用环境变量 `AMAZING_DRAW_CONFIG_FILE` 覆盖。

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
| [`websockets`](https://pypi.org/project/websockets/) / [`cryptography`](https://pypi.org/project/cryptography/) | ComfyUI 队列/预览通道等本地 WebSocket；`cryptography` 给部分签名场景 |

---

## 3. ⚡ ComfyUI 后端引擎配置

工作流依赖本机独立安装的 **[ComfyUI](https://github.com/comfyanonymous/ComfyUI)**：

- **项目**：[github.com/comfyanonymous/ComfyUI](https://github.com/comfyanonymous/ComfyUI)
- **默认根路径**：`~/ComfyUI`（Windows 在 Git Bash 下 `~` 映射到 `C:\Users\<用户名>`，即 `C:\Users\<用户名>\ComfyUI`）
- **默认监听端口**：`http://127.0.0.1:8188`
- **配置文件**：修改 `~/.amazingdraw/config.json` 中的 `comfyui_dir` 与 `comfyui_host`。
- **Windows 路径提示**：`config.json` 中所有 POSIX 风格路径（`~/...`、`/tmp/...`）在 Git Bash 内由 `os.path.expanduser` 解析为 Windows 用户目录；`cryptography`/模型路径建议显式写 Windows 绝对路径（`C:${HOME}/...`）避免歧义。
- **本机模型清单**（命名与下载页）：ComfyUI 安装目录 `models/`（文件名需与配置一致）

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

### 4.1 支持的工作流（`config/workflows.json`）

当前内置支持三大生产级工作流（只读基底 `scripts/card-engine/config/workflows.json`，运行期通过 `~/.amazingdraw/config.json` 的 `default_workflow` 选择）：

1. **Moody Moss Mix 4.1 (MOSS Image)**（默认，id: `moody_moss`，简称 `moss`）：
   - 25 步 CFG3 DiT 架构，原生支持 Qwen 3.5 9B int8 编码器与 Flux2 VAE
   - 工作流文件：`~/ComfyUI/workflows/Moody_Moss_Standard_25步_CFG3.json`
   - 专用 LoRA 目录：`models/loras/moss/`
2. **Moody Krea Mix 6 (Krea 2 Turbo)**（id: `krea2_turbo`，简称 `krea`）：
   - 8 步 CFG1 极速成片，底模 `Moody-Krea-Mix-fp8.safetensors` + 官方标量文本编码器 `qwen3vl_4b_fp8_scaled.safetensors`
   - 工作流文件：`~/ComfyUI/workflows/Krea2_Turbo_fp8_8步_CFG1_768x1152.json`
   - 明星 LoRA 目录：`models/loras/girls_like_krea2/`
3. **Z-Image Turbo 写真**（id: `moody_zib_zit`，简称 `zi`）：
   - 双阶段：先 [Moody Wild Mix（ZIB Base）](https://civitai.com/models/2384856/moody-wild-mix-zibzid)，再 [Moody Real Mix（ZIT Turbo）](https://civitai.com/models/621441/moody-real-mix)
   - 工作流文件：`~/ComfyUI/workflows/Moody_ZIB_ZIT_20步_CFG3_512x768.json`
   - 明星 LoRA 目录：`models/loras/girls_like_zi/`（136 人）

> 💡 **简称规则**：切换工作流统一使用 `zi` / `krea` / `moss`。

### 4.2 工作流模型依赖

#### A. Z-Image (Moody ZIB+ZIT) 模型

| 用途 | 文件 | 放置目录 | 来源 |
| :--- | :--- | :--- | :--- |
| 一阶段 UNET（ZIB） | `MoodyWildMix-zib-base.safetensors` | `models/diffusion_models/` | [CivitAI · Moody Wild Mix](https://civitai.com/models/2384856/moody-wild-mix-zibzid) |
| 二阶段 UNET（ZIT） | `MoodyRealMix-zit-write.safetensors` | `models/diffusion_models/` | [CivitAI · Moody Real Mix](https://civitai.com/models/621441/moody-real-mix) |
| 文本编码器 | `qwen_3_4b.safetensors` | `models/text_encoders/` | [HF · Comfy-Org/Z-Image-Turbo · text_encoders](https://huggingface.co/Comfy-Org/Z-Image-Turbo/tree/main/split_files/text_encoders) |
| VAE | `ae.safetensors` | `models/vae/` | [HF · Comfy-Org/Z-Image-Turbo · vae](https://huggingface.co/Comfy-Org/Z-Image-Turbo/tree/main/split_files/vae) |

#### B. MOSS Image (Moody Moss Mix) 模型

| 用途 | 文件 | 放置目录 | 来源 |
| :--- | :--- | :--- | :--- |
| 扩散模型 DiT | `MoodyMossMix-fp8.safetensors` | `models/diffusion_models/` | [CivitAI · Moody Moss Mix](https://civitai.com/models/3007871/moody-moss-mix-free-download) |
| 文本编码器 | `qwen3.5_9b_int8_convrot.safetensors` | `models/text_encoders/` | [HF · Comfy-Org/MOSS-Image · text_encoders](https://huggingface.co/Comfy-Org/MOSS-Image/tree/main/text_encoders) |
| VAE | `flux2-vae.safetensors` | `models/vae/` | [HF · Comfy-Org/MOSS-Image · vae](https://huggingface.co/Comfy-Org/MOSS-Image/tree/main/vae) |

#### C. Krea 2 Turbo (Moody Krea Mix 6) 模型

| 用途 | 文件 | 放置目录 | 来源 |
| :--- | :--- | :--- | :--- |
| 扩散模型 DiT | `Moody-Krea-Mix-fp8.safetensors` | `models/diffusion_models/` | [CivitAI · Moody Krea 2 Mix](https://civitai.com/models/2731187) |
| 文本编码器 | `qwen3vl_4b_fp8_scaled.safetensors` | `models/text_encoders/` | [HF · Comfy-Org/Krea-2 · text_encoders](https://huggingface.co/Comfy-Org/Krea-2/tree/main/text_encoders) |
| VAE | `qwen_image_vae.safetensors` | `models/vae/` | [HF · Comfy-Org/Krea-2 · vae](https://huggingface.co/Comfy-Org/Krea-2/tree/main/vae) |

> 推荐采样参数：KSamplerAdvanced · 8 步 · CFG 1.0 · euler_ancestral / beta · 默认画幅 768 × 1152。CLIPLoader type 选 `krea2`。

> CLIPLoader type 选 `lumina2`。推荐采样参数以 CivitAI 模型页为准（ZIB 约 CFG 4 · 40 步；ZIT 约 CFG 1 · 8 步）。

### 4.3 角色 LoRA 架构映射

常规素人无 LoRA（引擎自动旁路）；明星写真根据当前工作流架构自动路由到对应权重目录：

- **Z-Image 明星 LoRA**：`~/ComfyUI/models/loras/girls_like_zi/`（对应池 `z`）
- **Krea 2 明星 LoRA**：`~/ComfyUI/models/loras/girls_like_krea2/`（对应池 `krea2`）
- **MOSS Image 专属 LoRA**：`~/ComfyUI/models/loras/moss/`（对应池 `moss`）
- **画廊参考**：[GirlsLike LoRA Gallery](https://huggingface.co/spaces/ifmylove2011/girlslike_lora_gallery)
- **本机全表**：`~/ComfyUI/models/loras/`（按架构分子目录，文件名需与 celebrities 映射一致）
- **抽卡键名映射**：`scripts/card-engine/config/celebrities.json`

触发词与文件名严格绑定，引擎会根据当前激活工作流由 `role_resolver` 自动对齐架构，杜绝跨架构混载。

---

## 5. 🤖 LLM

标题提取、场景路由等独立调用走 **OpenAI 兼容 HTTP**：`POST {llm.base_url}/chat/completions`。Base URL、Key、模型在配置页填写，按这台机器实际端点来，不要假设端口或软件名。模型列表来自该端点的 `GET /v1/models`。出图只走 ComfyUI。

端点不可用或总闸关闭时：直投 / 精选 / 渲染仍可进 Comfy；依赖 LLM 的步骤立刻降级为正则 / 词表 / 占位，不发 HTTP。设置页「引擎独立调用 LLM」是总闸（默认开）；分项在总闸下面。`enable_ai_check` 默认关，且总闸关时也不跑。中文改法由主 Agent 写 `--targets-json`，不走独立 LLM。


---

## 6. 🔌 服务端口与网络拓扑

| 服务名称 | 默认端口 | 绑死地址 | 用途说明 |
| :--- | :--- | :--- | :--- |
| **[ComfyUI](https://github.com/comfyanonymous/ComfyUI) 后端** | `8188` | `127.0.0.1` | GPU 图像采样渲染引擎 |
| **WebUI 控制台** | `8318` | `0.0.0.0` | 本地工作台 / 相册与配置前端 |
| **LLM 端点** | 可配 | 见 `llm.base_url` | OpenAI 兼容 `/v1` |

---

## 7. ✅ 一键环境自检与绿线验证

安装部署完成后，在终端运行以下命令进行全量环境自检：

```bash
# 1. 验证 ComfyUI 连通性
curl -fsS "http://127.0.0.1:8188/system_stats" && echo "✅ ComfyUI 连通正常"

# 4. 验证 LLM（把 URL 换成配置里的 llm.base_url）
curl -fsS "<llm.base_url>/models" && echo "✅ LLM /v1 可用"
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
| [ComfyUI](https://github.com/comfyanonymous/ComfyUI) | 支持 | 支持（有 Windows 版） |

### 8.2 Windows 装机清单（按序）

1. **[Git for Windows](https://git-scm.com/download/win)** → 提供 Git Bash
2. **[Python 3.9 或 3.12](https://www.python.org/downloads/)**（必须和 zip 标签一致：`cp39`→3.9，`cp312`→3.12）
3. **pip 安装依赖**（§2 命令）
4. **放置 `.pyd`** 到 `card_engine_core/native/`（CI 编译产物，随发行版分发）
5. **安装 [ComfyUI](https://github.com/comfyanonymous/ComfyUI)**（Windows 版）；独立 LLM 在配置页填 OpenAI 兼容 Base URL
6. `bash scripts/gpu-pipeline/comfyui-start.sh start` 启动 ComfyUI
7. `python3 scripts/webui/web_server.py` 启动 WebUI

### 8.3 Windows 差异速查

| 差异 | 处理 |
| :--- | :--- |
| 路径 `~/...` / `/tmp/...` | Git Bash 内 `expanduser` 解析；Windows 可写 `C:/...` 绝对路径 |
| `.so` → `.pyd` | macOS 本机编译的 `.so` 不能拿到 Windows 用；必须用 CI 的 `.pyd`，且 Python 主版本须匹配 |
| 模型路径 | `comfyui_dir` 指向 Windows 上 ComfyUI 实际目录 |
| 启动脚本 | 全部经 Git Bash 的 `bash` 运行 |
| LLM | 配置 `llm.base_url`，须为 OpenAI 兼容 `/v1` |

### 8.4 关键约束（务必读）

- **只装 [Git for Windows](https://git-scm.com/download/win) ≠ 可用**：内核需要 Windows `.pyd`（非 macOS `.so`），且 Python 版本匹配。
- 前端（webui 明文壳）+ 明文 Python 两边通用；**内核是平台绑定层**。
- macOS `.so` 不能直接复制到 Windows 用（Mach-O ≠ PE/DLL）。Windows 必须用 CI 编译的 `.pyd`。
