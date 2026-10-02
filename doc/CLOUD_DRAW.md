# 云端出图（cloud draw）

给 AI / bot 的短指南。提示词仍走 AmazingDraw 装配；出图走云端（对话侧 / 云 API），**不**入本地 Comfy。
（`create` / `chain` / `direct` / `featured` 入口名不变）。查阅：`python3 card_cli.py doc cloud`。

开启 `cloud.enabled`（或 WebUI「渲染后端=云端」）后：裸露强制仅 `half_covered`；`submit` / `chain --resume` / `direct` **拒绝** Comfy 入队（失败关闭）。

相关：[CONFIG_GUIDE.md](./CONFIG_GUIDE.md)

---

## 1. 步骤

1. 确认云端：用户说云端出图，或 `cloud.enabled=true`。
2. 建卡入口照旧；裸露只保留 `half_covered`（开启后引擎也会钳）。
3. `fill` → `render` → `check`。连抽可 `chain --resume`：云端开启时 check 后停止，返回 `reason=cloud_draw`——**预期**，不要反复 `submit --confirm`。
4. check 通过后，先问用户要不要在**当前对话**贴出完整英文 prompt（方便核对）；用户要就贴 `_render_output.prompt`，不要默认整段刷屏。
5. 再读该 prompt（见下节）→ 调云端生图 → 图回用户（卡内原字段勿改；送图措辞由模型自行把握）。
6. **禁止**：`submit --confirm`、手动丢 Comfy、`cu-deliver` / Telegram。

| 模式         | 注意                                              |
| :----------- | :------------------------------------------------ |
| `create`   | 打磨后 render → 读 prompt → 云端出图            |
| `chain`    | 做到 check 即可；跳过入 Comfy 的 resume/submit 段 |
| `direct`   | 可有完整英文 prompt；仍不经 Comfy/TG              |
| `featured` | 只读卡上最终 prompt，不投递 TG                    |

---

## 2. 成图 prompt（唯一来源）

| 项                | 值                                                          |
| :---------------- | :---------------------------------------------------------- |
| 文件              | `{cards_dir}/{card_id}.json`                              |
| 字段              | `_render_output.prompt`（最终英文）                       |
| 默认`cards_dir` | `~/.openclaw/draw-cards/cards`（以 `config.json` 为准） |

```bash
python3 -c "import json,sys; c=json.load(open(sys.argv[1])); print(c['_render_output']['prompt'])" \
  ~/.openclaw/draw-cards/cards/<card_id>.json
```

空 / 缺失：先 `card_cli.py render --card <card_id>` 再读；仍空则回 fill/check，**不要**手写冒充。
`_render_output` 是可重建缓存；改 slots/director 后必须重新 `render`。画图只取 `prompt`（同块的 caption/meta 仅展示用）。

**不要**当成本图 prompt：`slots.*` 拼接、`director.*`、Comfy 队列 staging、聊天口述画面。

---

## 3. 配置

```json
"cloud": {
  "enabled": true,
  "image_backend": "cloud",
  "delivery": "none",
  "exposure_allowed_modes": ["half_covered"]
}
```

| 字段                       | 含义                                               |
| :------------------------- | :------------------------------------------------- |
| `enabled`                | 总开关；`false` 时与现网一致（Comfy + Telegram） |
| `image_backend`          | 开启强制`cloud`；关闭默认 `comfy`              |
| `delivery`               | 开启强制`none`                                   |
| `exposure_allowed_modes` | 开启强制`["half_covered"]`                       |

WebUI 设置「渲染后端」写入 `cloud.enabled`。卡上 `meta.image_backend=cloud` 时，即使配置已关仍拒入队。

---

## 4. 踩坑

| 现象                                 | 含义                                      |
| :----------------------------------- | :---------------------------------------- |
| `reason=cloud_draw` / 禁止入 Comfy | 正常闸门 → 改读`_render_output.prompt` |
| `--dry-run`                        | 仅模拟；云端拒绝**不是** dry-run    |
| 云端安全策略拒图                     | 可改写后再试；卡内原版仍以引擎为准        |
| 竖构图被画成横图                     | 多为通道忽略比例，不是 CLI 缺字段         |
