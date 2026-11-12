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

**macOS** 是主要使用平台；**Windows** 可双击 `install.bat` 安装运行。另有 [提示词反推 bot](https://t.me/PromptReverseBot)，欢迎使用。

## Skill

解压目录根有 `SKILL.md`。把**整个目录**交给 [Cursor](https://www.cursor.com/) / [Claude Code](https://github.com/anthropics/claude-code) / [dsh](https://github.com/deepseek-ai/deepseek-harness) / [OpenClaw](https://github.com/openclaw/openclaw) / [Cherry Studio](https://github.com/CherryHQ/cherry-studio) 等 AI Agent，一句话就能抽卡，例如 `随机抽三张`、`办公室 半裸 抽一张`。也可以自定义场景库和角色库。

![总架构](doc/architecture.svg)

## 安装

1. 到 **[GitHub Releases](https://github.com/AmazingDraw/AmazingDraw/releases)** 下载下表对应压缩包。
2. 解压到固定目录（macOS 例如 `~/AmazingDraw`，Windows 例如 `C:\\AmazingDraw`），不要拆散、不要解进 ComfyUI。
3. 在解压根目录安装。

| 包 | 系统 | Python |
| --- | --- | --- |
| `AmazingDraw-darwin-cp39.zip` | macOS | 3.9（Apple 自带 `/usr/bin/python3` 用这个） |
| `AmazingDraw-darwin-cp312.zip` | macOS | 3.12 |
| `AmazingDraw-windows-cp39.zip` | Windows | 3.9 |
| `AmazingDraw-windows-cp312.zip` | Windows | 3.12 |

跑 WebUI / CLI 的 Python **必须和 zip 标签一致**。内核在 `card_engine_core/native/`，`assets.bin` 必须同树；不要混 `.so` / `.pyd`，也不要混用 3.9 / 3.12。

**macOS**：`bash install.sh`

**Windows**：双击 `install.bat`（cmd / PowerShell 同样可以）。缺 Git Bash 或匹配的 **x64 Python** 时会尝试自动补（优先 winget）。ARM64 请仍用 x64 Git/Python。免确认：`install.bat -Yes` 或 `AMAZINGDRAW_INSTALL_YES=1`。已装好 Git Bash 时也可 `bash install.sh`（PowerShell 不能直接跑 `install.sh`）。ComfyUI 在其它盘时先设 `COMFYUI_DIR`。

**WebUI 可选**：Skill / CLI / Agent 不需要。`install.bat` 会问是否 `pip install fastapi uvicorn`（失败只警告）。`-Yes` 默认跳过；要装加 `-WithWebUI` 或 `AMAZINGDRAW_WITH_WEBUI=1`。出图须自备 ComfyUI 与模型。

安装会尽量探测 ComfyUI 与 LLM 端点（默认 `127.0.0.1:8317`）；已有有效配置不覆盖。运行期配置是 `~/.amazingdraw/config.json`。包内 `scripts/config.json` 只作首次迁入种子（由 `config.example.json` 生成，不含私人路径）。数据在 `~/.amazingdraw/`；从 `~/.openclaw/draw-cards/` 升级时会复制过来并校验，旧目录保留。

## 推荐模型

库内容较多，选**上下文长、跟指令、限制少**的模型。

| 推荐 | 模型 | 说明 |
| :--- | :--- | :--- |
| ⭐⭐⭐⭐⭐ | **DeepSeek Flash** | 首选。JSON 与门禁稳，限制少，适合日常连抽。 |
| ⭐⭐⭐⭐ | **Grok** | 尺度与创意更好，格式偶有发散。 |
| ⭐⭐⭐⭐ | **Gemini Flash** | 吞吐大；安全过滤偏严，需自己调教。 |

## 使用

出图走本机 ComfyUI（默认 <http://127.0.0.1:8188>）。`install.sh` 会把三大官方工作流拷进探测到的 ComfyUI `workflows/`（Comfy 用它自己的 venv 即可）：
- **moss**：Moody Moss Mix 4.1（默认推荐，MOSS Image DiT，25步CFG3）
- **krea**：Moody Krea Mix 6（Krea 2 Turbo 极速成片，8步CFG1）
- **zi**：Moody ZIB+ZIT（Z-Image 真实感双采样）

### WebUI

```bash
bash scripts/webui/webui-start.sh start          # http://127.0.0.1:8318
bash scripts/gpu-pipeline/comfyui-start.sh start
```

**卡片工作台**看图、管卡；闪电=直投，骰子=精选；**相册**分类成品；右侧盯队列。连抽 / 常规 fill 走 CLI。

### CLI

```bash
cd scripts/card-engine
python3 card_cli.py -h
python3 card_cli.py create -h
python3 card_cli.py chain -h      # 默认连抽
python3 card_cli.py direct -h
python3 card_cli.py featured -h
```

## 配置

- 运行期 `~/.amazingdraw/config.json`（包内种子 `scripts/config.json`，示例 `config.example.json`）
- 自定义预设：`user_presets/`
- LLM：`llm.base_url`（默认 `http://127.0.0.1:8317/v1`）；Comfy 路径可在 WebUI 配置页填

## 文档

- `doc/webui/DEPENDENCIES_GUIDE.md` — 依赖与装机
- `doc/webui/USER_GUIDE.md` — WebUI
- `doc/webui/CARD_ENGINE_COMMANDS.md` — CLI
- `doc/webui/CONFIG_GUIDE.md` — 配置
