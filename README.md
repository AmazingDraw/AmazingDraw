# AmazingDraw Card Engine

卡牌绘制引擎，带 WebUI 与 ComfyUI。支持 **macOS** 与 **Windows（Git Bash）**。

## 安装

到 GitHub **Releases** 下载对应平台压缩包，解压后在目录里执行。Releases 提供两套包，文件名里的 `cp39` / `cp312` 就是 Python 主版本。

- macOS：`AmazingDraw-darwin-cp39.zip`（Python **3.9**，本机编 `.so`）和 `AmazingDraw-darwin-cp312.zip`（Python **3.12**，本机编 `.so`）
- Windows：`AmazingDraw-windows-cp39.zip` 和 `AmazingDraw-windows-cp312.zip`（CI 编 `.pyd`，Git Bash）

跑 WebUI/CLI 的 Python **必须和 zip 标签一致**。Apple 自带 `/usr/bin/python3` 是 3.9，请下 cp39；本机 3.12 请下 cp312。ComfyUI 用它自己的 venv，可以和引擎 Python 不是同一个。不要把 `.so` 和 `.pyd` 混放，也不要混 3.9/3.12 native。

```bash
bash install.sh
```

Windows 请安装与 zip 标签一致的 Python（3.9 或 3.12，勾选 Add to PATH），并用 Git for Windows 的 Git Bash。PowerShell 不能直接跑 `install.sh`。

安装会对照 `config.example.json` 生成用户配置 `~/.openclaw/draw-cards/config.json`（若该文件已存在则保留，不覆盖）。对话后端默认 `custom`，OpenClaw 可选。`install.sh` 会把 `ComfyUI-Card-Engine/` 装进 ComfyUI 的 custom_nodes。

## 启动

```bash
# ComfyUI
bash scripts/gpu-pipeline/comfyui-start.sh start

# WebUI
bash scripts/webui/webui-start.sh start
```

| 服务 | 地址 |
| --- | --- |
| WebUI | http://127.0.0.1:8318 |
| ComfyUI | http://127.0.0.1:8188 |

## 内核位置（必读）

内核在 `card_engine_core/native/`。**`assets.bin` 必须和这套内核放在同一棵目录树里，不要拆开、不要单独拷走。**

| 平台 | 文件 | 说明 |
| --- | --- | --- |
| macOS | `*.cpython-39-darwin.so` 或 `*.cpython-312-darwin.so` | 必须与 zip 标签一致：`cp39` → Python 3.9，`cp312` → Python 3.12。Apple 自带 3.9 请用 cp39 |
| Windows | `*.cp39-*.pyd` 或 `*.cp312-*.pyd` | 由 CI 编译。**不能**使用 macOS 的 `.so`，也不能把 `.so` 和 `.pyd` 混在同一目录，也不要混 3.9/3.12 native |

一个发行包只对应一个平台、一个 Python 主版本。Python 主版本对不上，或把错误平台的内核放进来，模块会无法加载。

## 配置

- 示例：`config.example.json`
- 安装后：`~/.openclaw/draw-cards/config.json`
- `agent_backend` 默认 `custom`（不依赖 OpenClaw）；需要 OpenClaw 时再自行改配置

自定义预设放在 `user_presets/`。

## 文档

- `doc/webui/USER_GUIDE.md` — WebUI 使用
- `doc/webui/DEPENDENCIES_GUIDE.md` — 依赖与装机
- `doc/CONFIG_GUIDE.md` — 配置说明
