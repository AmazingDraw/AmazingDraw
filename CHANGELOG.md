# 更新日志

发行包版本是 GitHub Releases 的 tag（`v主.次.补`）。四个 zip 文件名仍是平台 × Python（`AmazingDraw-darwin-cp39.zip` 这类），不把版本写进文件名。zip 根有 `VERSION` 和本文件。

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
