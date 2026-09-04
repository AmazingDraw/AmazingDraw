<h1 align="center">AmazingDraw</h1>

<p align="center">
  <a href="https://x.com/AmazingDrawCLI"><img src="https://img.shields.io/badge/X-%40AmazingDrawCLI-000000?style=flat&logo=x&logoColor=white" alt="X @AmazingDrawCLI"></a>
  <a href="https://t.me/AmazingDraw"><img src="https://img.shields.io/badge/Telegram-%40AmazingDraw-26A5E4?style=flat&logo=telegram&logoColor=white" alt="Telegram @AmazingDraw"></a>
</p>

<p align="center">
  <a href="https://github.com/AmazingDraw/AmazingDraw/releases"><img src="https://img.shields.io/github/v/release/AmazingDraw/AmazingDraw?style=flat" alt="Release"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-blue?style=flat" alt="License MIT"></a>
  <a href="https://github.com/AmazingDraw/AmazingDraw/releases"><img src="https://img.shields.io/badge/platform-macOS%20%7C%20Windows-lightgrey?style=flat" alt="macOS | Windows"></a>
  <a href="https://github.com/AmazingDraw/AmazingDraw/releases"><img src="https://img.shields.io/badge/python-3.9%20%7C%203.12-3776AB?style=flat&logo=python&logoColor=white" alt="Python 3.9 | 3.12"></a>
</p>

<br><br>

解决**不会写提示词的问题**：内置场景库、角色库，想抽什么只需简单一句话，不必自己攒 prompt。

**macOS** 是主要使用平台；**Windows** 可用 Git Bash 安装运行。另有 [提示词反推 bot](https://t.me/PromptReverseBot)，欢迎试用。

## Skill

解压目录根有 `SKILL.md`。把**整个目录**交给 Cursor / Claude Code / OpenClaw 等 AI Agent，一句话就能抽卡，例如 `随机抽三张`、`办公室 轻松风格 抽一张`。也可以自定义场景库和角色库。

![总架构](doc/architecture.svg)

## 安装

1. 到 **[GitHub Releases](https://github.com/AmazingDraw/AmazingDraw/releases)** 下载对应压缩包。
2. 解压到一个**固定目录**（例如 macOS `~/AmazingDraw`，Windows `C:\\AmazingDraw`）。这就是运行时目录（WebUI / CLI / skill），不要拆散文件，也不要解压进 ComfyUI。
3. 在解压后的根目录执行：

```bash
bash install.sh
```

| 包 | 系统 | Python |
| --- | --- | --- |
| `AmazingDraw-darwin-cp39.zip` | macOS | 3.9（Apple 自带 `/usr/bin/python3` 请用这个） |
| `AmazingDraw-darwin-cp312.zip` | macOS | 3.12 |
| `AmazingDraw-windows-cp39.zip` | Windows | 3.9 |
| `AmazingDraw-windows-cp312.zip` | Windows | 3.12 |

跑 WebUI / CLI 的 Python **必须和 zip 标签一致**。不要把 `.so` 和 `.pyd` 混放，也不要混用 3.9 / 3.12 的内核。

**Windows**：请安装对应版本的 Python（勾选 Add to PATH），并用 **Git Bash** 跑 `install.sh`（PowerShell 不能直接跑）。脚本在需要时会补 `python3` 别名；若 ComfyUI 装在其它盘，可先设环境变量 `COMFYUI_DIR` 再安装。

安装时会尽量**自动探测**本机 ComfyUI、OpenClaw，并在配置为空或无效时写入路径；已有有效配置不会被覆盖。找不到也不影响装完——可之后在 WebUI「配置」里填写。

安装会按 `config.example.json` 生成 `~/.openclaw/draw-cards/config.json`（已有则不覆盖）。

## 推荐模型

场景库和角色库内容较多，**上下文够长、内容限制少**的模型更合适。

| 推荐 | 模型 | 说明 |
| --- | --- | --- |
| ⭐⭐⭐ | DeepSeek V4 Flash | 首选。限制少，跟指令稳，相对便宜，适合日常抽卡与连抽 |
| ⭐⭐ | Grok 4.x | 次选。限制少，创意空间大，适合放开写的场景 |


## 使用

出图走本机 ComfyUI（默认 <http://127.0.0.1:8188>）。

### WebUI

```bash
bash scripts/webui/webui-start.sh start          # http://127.0.0.1:8318
bash scripts/gpu-pipeline/comfyui-start.sh start
```

浏览器打开 WebUI 后：顶栏可看 ComfyUI 是否在线；配置页「外接状态」可看 OpenClaw / Telegram / Obsidian 是否就绪。

### CLI

```bash
cd scripts/card-engine
python3 card_cli.py -h          # 总 help
python3 card_cli.py create -h   # 单卡
python3 card_cli.py chain -h    # 连抽
```

`install.sh` 会把工作流拷到 ComfyUI 的 `workflows/`（探测到的安装根下），并把 `ComfyUI-Card-Engine/` 装进 `custom_nodes`。ComfyUI 用它自己的 venv，可以和引擎 Python 不是同一个。

## 目录请保持完整

内核在 `card_engine_core/native/`。**`assets.bin` 必须和这套内核放在同一棵目录树里**，不要拆开、不要单独拷走。一个发行包只对应一个平台、一个 Python 主版本。

## 配置

- 示例：`config.example.json`
- 安装后：`~/.openclaw/draw-cards/config.json`
- 自定义预设：`user_presets/`
- Windows 若自动探测失败：可在 WebUI 填写 `comfyui_dir`、`openclaw_home`、`openclaw_bin`

## 文档

- `doc/webui/DEPENDENCIES_GUIDE.md` — 依赖与装机（装不起来优先看）
- `doc/webui/USER_GUIDE.md` — WebUI
- `doc/CARD_ENGINE_COMMANDS.md` — CLI
- `doc/CONFIG_GUIDE.md` — 配置
