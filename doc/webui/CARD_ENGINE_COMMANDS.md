# 抽卡命令速查

工作目录：`cd scripts/card-engine`

---

## 1. 创建 `create`

```bash
python3 card_cli.py create --user-input "可爱风格"
python3 card_cli.py create --person "OL" --scene "停车场" --user-input "高冷风格"
python3 card_cli.py create --person "JK" --scene "校园" --user-input "加入宠物元素"
```

`--user-input` 必填。库外自定义场景 fill 时再写 `scene.keywords`。

| 参数 | 说明 |
|------|------|
| `--user-input` | **必填**。风格/元素补充（如：可爱风格、高冷风格、加入宠物元素） |
| `--mode` | `amateur`（默认）/ `celebrity` |
| `--bundle` | 加载词库参考。不带值：常用章节；带值：按章节名加载 |

---

## 2. 填词 `fill`

```bash
python3 card_cli.py fill --card <id> --json-file fill.json
python3 card_cli.py fill --card <id> --json '{"theme_zh":"...","director":{...},"slots":{...}}'
python3 card_cli.py fill --card <id> --phase director
python3 card_cli.py fill --card <id> --phase slots
python3 card_cli.py fill --card <id> --phase elevation
```

连抽用一次 `--json-file`，不要拆 `--phase`。`--phase` 只给常规精修。存盘前会做文本预检，不通过则拒绝写入。

---

## 3. 动态选项 `options`

```bash
python3 card_cli.py options --card <id> --auto
```

常规模式要先跑 `--auto`，数字 2–5 / 7 / 8 才有菜单。

---

## 4. 局部修改 `patch`

```bash
python3 card_cli.py patch --card <id> --direction 9
python3 card_cli.py patch --card <id> --user-input "51"
python3 card_cli.py patch --card <id> --set slots.tattoo --value "small pink heart"
```

---

## 5. 展示 `present`

```bash
python3 card_cli.py present --card <id>
python3 card_cli.py present --card <id> --compact
```

常规：`options --auto` 之后再 `present`。`options` 会升 `card.version`，若已经 `check` 过，提交前要再 `check`。

---

## 6. 渲染 / 检查 / 提交

```bash
python3 card_cli.py render --card <id>
python3 card_cli.py check --card <id>
python3 card_cli.py submit --card <id> --confirm
python3 card_cli.py submit --card <id> --confirm --dry-run
```

`submit` 必须 `--confirm`。`check` 之后改过卡，要再 `check`。精选走灵感库，不套这套凭证。

---

## 7. 数字指令（常规）

| 指令 | 操作 |
|------|------|
| `1` / `画` | 提交生成 |
| `6` | 合理性检查 |
| `9` | 纹身 |
| `0` / `换` | 重抽 |
| `2-5,7,8` | 动态方向（先 `options`） |

连抽不用数字指令，走 `fill` → `chain --resume`。

---

## 8. 连抽 `chain`

```bash
python3 card_cli.py chain --count 3 --person "JC" --user-input "可爱风格"
python3 card_cli.py chain --count 3 --person "JK" --scene "教室" --user-input "高冷风格"
python3 card_cli.py chain --resume <card_id>
python3 card_cli.py chain --resume <card_id> --dry-run
```

`--resume` 自动 render → check → autofix → submit。`--dry-run` 停在提交前，不入 GPU 队列。没有批量 `--batch`，请逐张 resume。草稿不会自动删，在 WebUI 里确认清理。

---

## 9. 直投 `direct`

```bash
python3 card_cli.py direct \
  --prompt "英文prompt" \
  --person "OL" --scene "卧室" --theme "主题" \
  --narrative "中文叙事" --lighting "光影" --style "风格" \
  [--width 512 --height 768] [--dry-run]
```

`--prompt` 必填。CLI 直投不走场景库。WebUI 闪电会先建卡再提交原始 Prompt。

---

## 10. 精选 `featured`

```bash
python3 card_cli.py featured [--workflow moody_zib_zit] [--width 512] [--height 768]
```

从 `obsidian_vault_dir/灵感库/` 随机抽一篇已归档笔记，原样出图。用 Obsidian 打开该库即可管理。

---

## 11. 连抽修复 `mend`

```bash
python3 card_cli.py mend --card <id> --set slots.clothing --value "xxx"
python3 card_cli.py mend --card <id> --get slots.clothing
python3 card_cli.py mend --card <id> --undo
python3 card_cli.py mend --card <id> --history
python3 card_cli.py mend --card <id> --set slots.pose --value "..." --dry-run
```

---

## 12. 搜索

```bash
python3 card_cli.py doc prompt
python3 card_cli.py doc pitfalls
python3 card_cli.py search --person jk
python3 card_cli.py resolve --person OL --scene 办公室
```

---

## 13. 队列

```bash
python3 card_cli.py queue status
python3 card_cli.py queue health
python3 card_cli.py queue clear [--force]
python3 card_cli.py queue remove --job-id JOB_ID
python3 card_cli.py queue remove --position N
```

---

## 14. 记录与归档

```bash
python3 card_cli.py progress
python3 card_cli.py record --card <id>
python3 card_cli.py archive --card <id>
```

`archive` 把当前卡的图和笔记写入 Obsidian `灵感库/` + `attachments/`。同一张卡重复归档会直接提示已存在，不覆盖。

---

## 15. 快捷

路径跟 `config.json` 的 `cards_dir` / `tmp_dir`（默认如下）。

```bash
python3 -m json.tool ~/.openclaw/draw-cards/cards/<card_id>.json
tail -20 /tmp/cu-card/cu-submit-bg_*.log
rm -f /tmp/cu-card/cu-gpu.lock
```

---

## 16. 注意

- prompt / person 里不要写「素人」
- 常规动态位先 `options --auto`
- 连抽不要走数字指令
