# AmazingDraw

抽卡引擎，带 WebUI 与 CLI。**macOS** 为实际使用平台；**Windows（Git Bash）** 有发行包，尚未在实机上测试。

![总架构](doc/architecture.svg)

## 安装

到 GitHub **[Releases](https://github.com/AmazingDraw/AmazingDraw/releases)** 下载对应压缩包，解压到一个固定目录（例如 macOS `~/AmazingDraw`，Windows `C:\AmazingDraw`）。这个目录就是运行时（WebUI / CLI / skill），可以放在任意位置；不要拆散文件，不要解压进 ComfyUI。然后在解压后的根目录执行 `bash install.sh`。文件名里的 `cp39` / `cp312` 就是 Python 主版本。

| 包 | 系统 | Python |
| --- | --- | --- |
| `AmazingDraw-darwin-cp39.zip` | macOS | 3.9（Apple 自带 `/usr/bin/python3` 请用这个） |
| `AmazingDraw-darwin-cp312.zip` | macOS | 3.12 |
| `AmazingDraw-windows-cp39.zip` | Windows | 3.9 |
| `AmazingDraw-windows-cp312.zip` | Windows | 3.12 |

跑 WebUI / CLI 的 Python **必须和 zip 标签一致**。不要把 `.so` 和 `.pyd` 混放，也不要混 3.9 / 3.12 的内核。

```bash
bash install.sh
```

Windows 请安装对应版本的 Python（勾选 Add to PATH），并用 Git Bash。PowerShell 不能直接跑 `install.sh`。Windows 安装路径按 Git Bash 写了，但尚未在实机上测试。

安装会按 `config.example.json` 生成 `~/.openclaw/draw-cards/config.json`（已有则不覆盖）。对话后端默认 `custom`，OpenClaw 可选。

## 使用

出图走本机 ComfyUI（<http://127.0.0.1:8188>）。

### Skill

解压目录根有 `SKILL.md`，整棵交给 Cursor / Claude Code / OpenClaw 加载，不要拆散。对人说一句就抽卡，例如 `随机抽三张`、`护士 可爱风格`、`连抽 5 张，办公室`。没指定的按库内命中或随机补全。

### WebUI / CLI

```bash
bash scripts/webui/webui-start.sh start          # http://127.0.0.1:8318
bash scripts/gpu-pipeline/comfyui-start.sh start

cd scripts/card-engine
python3 card_cli.py -h          # 总 help
python3 card_cli.py create -h   # 单卡
python3 card_cli.py chain -h    # 连抽
```

`install.sh` 会把工作流拷到 `~/ComfyUI/workflows/`，并把 `ComfyUI-Card-Engine/` 装进 ComfyUI 的 custom_nodes。ComfyUI 用它自己的 venv，可以和引擎 Python 不是同一个。

## 内核

内核在 `card_engine_core/native/`。**`assets.bin` 必须和这套内核放在同一棵目录树里**，不要拆开、不要单独拷走。一个发行包只对应一个平台、一个 Python 主版本。

## 配置

- 示例：`config.example.json`
- 安装后：`~/.openclaw/draw-cards/config.json`
- 自定义预设：`user_presets/`

## 文档

- `doc/webui/USER_GUIDE.md` — WebUI
- `doc/CARD_ENGINE_COMMANDS.md` — CLI
- `doc/CONFIG_GUIDE.md` — 配置
- `doc/webui/DEPENDENCIES_GUIDE.md` — 依赖与装机
