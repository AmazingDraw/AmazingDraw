<h1 align="center">AmazingDraw</h1>

<p align="center"><b>不用写复杂提示词 · 对 AI 说一句话就抽卡</b></p>

<p align="center">
  <a href="https://github.com/AmazingDraw/AmazingDraw/releases"><img src="https://img.shields.io/github/v/release/AmazingDraw/AmazingDraw?style=flat" alt="Release"></a>
  <a href="https://github.com/AmazingDraw/AmazingDraw/releases"><img src="https://img.shields.io/github/downloads/AmazingDraw/AmazingDraw/total?style=flat&color=success" alt="Downloads"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-blue?style=flat" alt="License MIT"></a>
  <a href="https://github.com/AmazingDraw/AmazingDraw/releases"><img src="https://img.shields.io/badge/platform-macOS%20%7C%20Windows-lightgrey?style=flat" alt="macOS | Windows"></a>
  <a href="https://github.com/AmazingDraw/AmazingDraw/releases"><img src="https://img.shields.io/badge/python-3.9%20%7C%203.12-3776AB?style=flat&logo=python&logoColor=white" alt="Python 3.9 | 3.12"></a>
</p>

<p align="center">
  <a href="https://x.com/AmazingDrawBot"><img src="https://img.shields.io/badge/X-点击关注%20%40AmazingDrawBot-000000?style=for-the-badge&logo=x&logoColor=white" alt="点击关注"></a>
  <a href="https://t.me/AmazingDraw"><img src="https://img.shields.io/badge/Telegram-点击加群%20%40AmazingDraw-26A5E4?style=for-the-badge&logo=telegram&logoColor=white" alt="点击加群"></a>
  <a href="https://t.me/PromptReverseBot"><img src="https://img.shields.io/badge/🤖-点击反推%20%40PromptReverseBot-8A2BE2?style=for-the-badge" alt="提示词反推"></a>
</p>

---

说一句「**温泉旅馆，浴衣半敞，抽一张**」，引擎自己抽场景、选角色、定构图、组 prompt、投进 ComfyUI——你只管开口。

## ✨ 特性

- 🎲 **一句话抽卡 / 连抽** —— `随机抽三张`、`指定办公场景 6 连抽`，中文口语直接下指令
- 📚 **16 套词库、上百章节** —— 场景/角色/服装/纹身/饰品/宠物……命中场景自动路由选词
- 🎚 **裸露分级 L1–L6** —— 从全包裹到展示级，一句话锁档
- 🖥 **WebUI 卡片工作台** —— 看图、管卡、相册、队列；闪电=直投、骰子=精选
- 🤖 **Agent 原生** —— `SKILL.md` 交给 [Cursor](https://www.cursor.com/) / [Claude Code](https://github.com/anthropics/claude-code) / [dsh](https://github.com/deepseek-ai/deepseek-harness) / [OpenClaw](https://github.com/openclaw/openclaw) / [Cherry Studio](https://github.com/CherryHQ/cherry-studio) 即用
- 🔧 **全开放自定义** —— 场景库、角色库、`user_presets/` 随你扩

## 🚀 安装与上手

**三步走**：Releases 下载对应 zip → 解压到固定目录 → `install.sh`（Windows 双击 `install.bat`）→ 对 Agent 说「随机抽三张」。

| 包 | 系统 | Python |
| --- | --- | --- |
| `AmazingDraw-darwin-cp39.zip` | macOS | 3.9（Apple 自带 `/usr/bin/python3` 用这个） |
| `AmazingDraw-darwin-cp312.zip` | macOS | 3.12 |
| `AmazingDraw-windows-cp39.zip` | Windows | 3.9 |
| `AmazingDraw-windows-cp312.zip` | Windows | 3.12 |

跑 WebUI / CLI 的 Python **必须和 zip 标签一致**。内核在 `card_engine_core/native/`，`assets.bin` 必须同树；不要混 `.so` / `.pyd`，也不要混用 3.9 / 3.12。解压目录不要拆散、不要解进 ComfyUI。

**Windows 补充**：双击 `install.bat`（cmd / PowerShell 同样可以）。缺 Git Bash 或匹配的 **x64 Python** 时会尝试自动补（优先 winget）。ARM64 请仍用 x64 Git/Python。免确认：`install.bat -Yes` 或 `AMAZINGDRAW_INSTALL_YES=1`。已装好 Git Bash 时也可 `bash install.sh`（PowerShell 不能直接跑 `install.sh`）。ComfyUI 在其它盘时先设 `COMFYUI_DIR`。

**WebUI 可选**：Skill / CLI / Agent 不需要。`install.bat` 会问是否 `pip install fastapi uvicorn`（失败只警告）。`-Yes` 默认跳过；要装加 `-WithWebUI` 或 `AMAZINGDRAW_WITH_WEBUI=1`。出图须自备 ComfyUI 与模型。

安装会尽量探测 ComfyUI 与 LLM 端点（默认 `127.0.0.1:8317`）；已有有效配置不覆盖。运行期配置是 `~/.amazingdraw/config.json`。包内 `scripts/config.json` 只作首次迁入种子（由 `config.example.json` 生成，不含私人路径）。数据在 `~/.amazingdraw/`；从 `~/.openclaw/draw-cards/` 升级时会复制过来并校验，旧目录保留。

## 🎬 用法

解压目录根有 `SKILL.md`——把**整个目录**交给 [Cursor](https://www.cursor.com/) / [Claude Code](https://github.com/anthropics/claude-code) / [dsh](https://github.com/deepseek-ai/deepseek-harness) / [OpenClaw](https://github.com/openclaw/openclaw) / [Cherry Studio](https://github.com/CherryHQ/cherry-studio) 等 AI Agent，一句话就能抽卡：

```
你   ：「猫耳女仆咖啡厅，半裸，三连抽」
引擎 ：抽场景 → 自动路由兽耳/女仆饰品 → AI 导演组卡 → 队列渲染
```

![总架构](doc/architecture.svg)

出图走本机 ComfyUI（默认 <http://127.0.0.1:8188>）。`install.sh` 会把三大官方工作流拷进探测到的 ComfyUI `workflows/`：

- **moss**：Moody Moss Mix 4.1（默认推荐，MOSS Image DiT，25步CFG3）
- **krea**：Moody Krea Mix 6（Krea 2 Turbo 极速成片，8步CFG1）
- **zi**：Moody ZIB+ZIT（Z-Image 真实感双采样）

**WebUI**（可选）：

```bash
bash scripts/webui/webui-start.sh start          # http://127.0.0.1:8318
bash scripts/gpu-pipeline/comfyui-start.sh start
```

**卡片工作台**看图、管卡；**相册**分类成品；右侧盯队列。连抽 / 常规 fill 走 **CLI**：

```bash
cd scripts/card-engine
python3 card_cli.py -h
python3 card_cli.py create -h
python3 card_cli.py chain -h      # 默认连抽
python3 card_cli.py direct -h
python3 card_cli.py featured -h
```

## 🧠 推荐模型

库内容较多，选**上下文长、跟指令、限制少**的模型。

| 推荐 | 模型 | 说明 |
| :--- | :--- | :--- |
| ⭐⭐⭐⭐⭐ | **SWE-2** | 首选。上下文最长，JSON 与格式门禁最稳，复杂指令一次到位，连抽不翻车。 |
| ⭐⭐⭐⭐⭐ | **Gemini 4 系列** | 首选。吞吐大、响应快、理解力强；安全过滤偏严，需要自己调教提示。 |
| ⭐⭐⭐⭐ | **DeepSeek Flash** | 限制最少、性价比高，日常连抽够用；JSON 稳定性略逊于首选。 |
| ⭐⭐⭐⭐ | **Grok** | 创意与尺度最奔放，出词大胆；格式偶有发散，靠门禁兜着。 |

## ⚙️ 配置与文档

- 运行期 `~/.amazingdraw/config.json`（包内种子 `scripts/config.json`，示例 `config.example.json`）；LLM 走 `llm.base_url`（默认 `http://127.0.0.1:8317/v1`）
- 自定义预设：`user_presets/`；Comfy 路径可在 WebUI 配置页填
- 文档：`doc/webui/` 下 `DEPENDENCIES_GUIDE.md`（装机）、`USER_GUIDE.md`（WebUI）、`CARD_ENGINE_COMMANDS.md`（CLI）、`CONFIG_GUIDE.md`（配置）
