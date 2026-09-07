# 更新日志

发行包版本是 GitHub Releases 的 tag（`v主.次.补`）。四个 zip 文件名仍是平台 × Python（`AmazingDraw-darwin-cp39.zip` 这类），不把版本写进文件名。zip 根有 `VERSION` 和本文件。

## 0.1.10 — 2026-09-08

- 建卡：无人物/仅体型预设时身份与体型正确关联；孕妇类人物不再被清成随机身份
- 角色库：「甜辣微胖」「图书馆女神」独立身份，不再误挂女大学生；大学组仍为 6 个 college-*
- 安装：报告/就绪端口跟随 comfyui_host；探活在填写 host 之后；install 脚本去重；有 .venv 时轻查 comfy-aimdo（仅警告）
- 工作流：UI→API 转换加固（4-tuple 连线、Power Lora）；安装向导支持 Desktop basePath 探测

## 0.1.9 — 2026-09-07

- 新增交互安装向导与就绪矩阵（ComfyUI / OpenClaw / 工作流 / Telegram 引导）
- 中文升华字数范围调整为 60–240
- Telegram 发版改为纯文本：表格短名嵌 zip 直链（不挂包、不附 Release 页链接）
- 多人卡编号分人格式强制

## 0.1.8 — 2026-09-04

- WebUI / gpu-pipeline 子进程改用 sys.executable（Windows 无 python3 时更稳）
- OpenClaw 提示去掉 custom / 登录；安装与 WebUI 加载时自动将旧 custom / claudecode / hermes 迁为 openclaw
- 安装脚本：写入安装报告（含 install-report.txt）、安装期迁配置、card_cli 冒烟加强
- README 开头居中与徽章排版

## 0.1.7 — 2026-09-04

- WebUI：可操作错误提示、新手引导、外接状态；OpenClaw/ComfyUI 路径探测；卡片/抽卡 URL 为 #cards / #draw
- 去掉 custom 对话后端；开源默认 restrict_roles 开、enable_ai_check 关、agent_backend=openclaw
- 安装脚本自动探测本机 ComfyUI / OpenClaw（已有有效配置不覆盖）
- 用户 README：徽章横排、推荐模型（DeepSeek V4 Flash / Grok 4.x）、GitHub Releases 链接整理

## 0.1.6 — 2026-09-04

- Windows: 场景库抽样改进程内读取；子进程强制 UTF-8 输出并多编码解码（禁止裸 encoding=utf-8）
- install: 更智能的 Python 匹配/别名/硬依赖检查，并增加 workplace 进程内抽样自检

## 0.1.5 — 2026-09-03

- README 加上提示词反推 bot 入口；Windows 改为尚未真机测试
- autofix 收紧误杀（警服 KEEP、保安服浅蓝）；保留 balanced 掀裙位移
- 删除确认无调用的死函数；FALLBACK 与渲染兜底对齐

## 0.1.4 — 2026-09-01

- 无 OpenClaw 时设置页提示安装网关，推荐 DeepSeek V4 Flash；下拉不再写死模型 id
- WebUI 增加 AI check 开关（默认关）；物理互斥正则收紧
- 聊天 Markdown 兼容中文加粗侧翼与内侧空格
- 依赖文档去掉 Gateway protocol / LoRA HF 括注

## 0.1.3 — 2026-08-31

- 路径：CLI 入口 as_posix 正斜杠；文档改回 skill 根相对命令
- OpenClaw 8.1：握手、deltaText 流式；删除会话不再误标 tombstone
- WebUI 流式按帧匀开
- 保健室病床场景库调整

## 0.1.2 — 2026-08-30

- CARD_ENGINE_COMMANDS 精简工作目录说明，并只保留 doc/ 一份
- 同步精简后的 DRAW_GUIDE、PROMPT_TEMPLATE
- WebUI 文档接口改为读 doc/CARD_ENGINE_COMMANDS.md

## 0.1.1 — 2026-08-26

- 多人场景改为广义编号：合影、闺蜜等也编号，日常合影不强迫接吻
- 有站位词不再误报；多人模式保护角色代词
- 写作引导 / autofix 与姿势模板插入章节补强

## 0.1.0 — 2026-08-19

- 首个公开发行：macOS / Windows × Python 3.9 / 3.12
- 之后几次曾在同一 tag 上覆盖上传（README、WebUI 等），未升版本
