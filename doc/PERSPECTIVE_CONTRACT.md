# PerspectiveContract · 特殊视角 Spec / key 契约

> AmazingDraw 丝袜 / 后入 / 颜射统一运行时说明（简体中文）。  
> 权威实现：`scripts/card-engine/perspective_runtime.py`、`perspective_metrics.py`；  
> check 旁路：`scripts/validation/check_prompt.sh`（`PERSPECTIVE_KEY`）；  
> 桌面总纲「实现进度」为施工备忘，**以本文件 + 源码为准**。  
> 同步日：2026-09-09（Asia/Shanghai）

---

## 1. 核心原则

1. **Opt-in**：仅当卡上存在 `meta.perspective_key`（或 resolve 能稳定解析出完整「X视角」）时，特殊逻辑才生效。
2. **完整「X视角」才是通行证**：只认 `丝袜视角` / `后入视角` / `颜射视角`。短词（丝袜、后入、颜射、射脸、from behind…）**永不**当 key。
3. **普通场景零差分**：无 key → create/fill/render/autofix/check 的视角 Spec 路径全部 noop；不得因弱词误绑。
4. **Spec 是唯一行为表**：新增视角 = 新增一份 `PerspectiveSpec`；主干不堆硬编码分支。
5. **占位符保留**：`{clothing}` / `{pose}` / `{liquids}` 全局替换逻辑**保持**；视角 Spec **不**废除占位符契约（见 [DEDUPE_GUIDE.md](./DEDUPE_GUIDE.md)）。

解析顺序（`resolve_perspective_key`）：

```text
card.meta.perspective_key
  → detect_perspective_key(label/name/tags…）仅完整「X视角」
  → Spec.match.scene_tags_any（silk_view / rear_view / facial_view，仅特殊库兼容）
  → None
```

全入口（create / WebUI 选场景等）应调用 `ensure_card_perspective_key` 写入 `meta.perspective_key`。

---

## 2. 三视角 Spec 摘要

实现字典：`PERSPECTIVE_SPECS`（`perspective_runtime.py`）。

| 字段 | 丝袜视角 | 后入视角 | 颜射视角 |
| :--- | :--- | :--- | :--- |
| **key** | `丝袜视角` | `后入视角` | `颜射视角` |
| **match.scene_tags_any** | `silk_view` | `rear_view` | `facial_view` |
| **exposure_modes** | `half_nude`, `half_covered` | `lower`, `half_nude` | `upper`, `half_covered` |
| **render_hooks** | `silk_pose_clothing_dedupe` | （无专用 hook 名；geometry/rewrite） | `ensure_upper_focus_framing`, `inject_safe_facial_liquids` |
| **skip_plugins** | `rear_anatomy` | （不 skip；声明 `inject.plugins=rear_anatomy`） | `rear_anatomy`, `ensure_feet_first_camera_core` |
| **check_exempts** | `IS_FEET_FIRST_POV` | `[]` | `[]`（**故意为空**：不削弱 §4 / §11） |
| **rewrite 要点** | — | `looking at camera` → `looking back over shoulder` 等 | `from behind` / feet-first / anus 锚点等清掉或改上身构图 |
| **liquids** | — | — | `inject.liquids_from=SAFE_CUMS` |

> 路由层 `silk_view` / `rear_view` / `facial_view` **仍可**用于场景池兼容；**门控与拼装以 key 为准**。

---

## 3. 丝袜视角

- **门控**：`is_silk_perspective(key)`（`key == 丝袜视角`）。**不再**仅靠 `scene.tags` 含 `silk_view` 做 render 去重判定（tag 仍可经 Spec.match 解析出 key）。
- **拼装**：key 命中时跳过二次拼装 `slots.pose` / `slots.clothing`（`silk_pose_clothing_dedupe`）；`{clothing}`/`{pose}`/`{liquids}` 占位符仍先替换进 `scene_theme`。
- **后入短路**：`should_skip_plugin(key, "rear_anatomy")` → `inject_rear_anatomy_by_pose` **noop**，防丝袜与后入串味。
- **check**：优先 `PERSPECTIVE_KEY=丝袜视角` → 置 `IS_FEET_FIRST_POV=1`；无 key 时才弱 grep `feet-first POV` 等。

---

## 4. 后入视角

- **Spec rewrite**：有 rear key 时，autofix / `apply_perspective_card_rewrites` 将正视冲突词改为回眸（`looking at camera` → `looking back over shoulder` 等）。这是 **Spec.rewrite**，**不是** 2026-08-16 已删除的三条旧 `CARD_RULES`。
- **inject**：`rear_anatomy` 仍可在**无 key**时按姿势弱特征注入（保持历史零差分路径）；有 silk/facial key 则 short-circuit。
- **check**：优先 `PERSPECTIVE_KEY=后入视角` → `HAS_REAR_VIEW=1`；无 key 时弱 grep `from behind` / `doggy` 等兜底。
- **普通卡**：无 key 时 Spec rewrite **不跑**（打点 `spec_rewrite_skipped_no_key`）。

---

## 5. 颜射视角

- **SAFE_CUMS**：create 可注入；autofix 在 facial key 下脏/空 `slots.liquids` → 换 `SAFE_CUMS`（已是 SAFE 句则不动）。
- **skip rear**：不跑 `rear_anatomy` / feet-first 强制；check 在 facial key 下清零 rear / feet-first 身份。
- **门禁**：`check_exempts=[]` —— **不要**借视角 key 放水 §4（液体）/ §11 等；脏液体靠 SAFE_CUMS autofix，不靠豁免。

---

## 6. check：`PERSPECTIVE_KEY` 优先

`card_validation` / CLI 在调 `check_prompt.sh` 时应注入环境变量：

```bash
PERSPECTIVE_KEY=丝袜视角|后入视角|颜射视角
```

| 身份 | 优先 | 无 key 兜底 |
| :--- | :--- | :--- |
| feet-first / silk | `PERSPECTIVE_KEY=丝袜视角` | 弱 grep `feet-first POV` 等 |
| rear / `HAS_REAR_VIEW` | `PERSPECTIVE_KEY=后入视角` | 弱 grep `from behind` / `doggy` 等 |
| facial | `PERSPECTIVE_KEY=颜射视角` | （并清零 silk/rear 身份） |

详见 [CHECK_SCRIPT_GUIDE.md](./CHECK_SCRIPT_GUIDE.md) §3。

---

## 7. Metrics（P1 已合入）

| 组件 | 路径 |
| :--- | :--- |
| 打点 | `scripts/card-engine/perspective_metrics.py` |
| 汇总 | `scripts/card-engine/tools/perspective_metrics_summary.py` |
| 开关 | `config.perspective_metrics_enabled`（默认 True）；或环境变量 `AMAZING_DRAW_PERSPECTIVE_METRICS` |

**禁止**在 metrics payload 中写入完整 prompt / card JSON / 性描写正文——只记 key、计数、rule id、布尔。

用法：

```bash
python3 scripts/card-engine/tools/perspective_metrics_summary.py
python3 scripts/card-engine/tools/perspective_metrics_summary.py --tail 20 --json
```

---

## 8. 实现进度（与总纲对齐）

### P0 已完成（Spec/key 门控）

| 视角 | commit | 要点 |
| :--- | :--- | :--- |
| 丝袜 | `68207545` | Spec/key；render gate；silk 下 rear inject short-circuit；check 认 `PERSPECTIVE_KEY`；占位符保留 |
| 后入 | `f0d55034` | Spec/key；autofix Spec rewrite looking→over shoulder；check prefer rear key；普通零差分 |
| 颜射 | `be857955` | Spec/key；SAFE_CUMS autofix；skip rear；check 认 key 且不削弱 §4/§11 |

共享：`perspective_runtime.py`；create/entry 写 `meta.perspective_key`。

### P1 指标已完成

- commit `d73dc142`：`perspective_metrics.py` + summary 工具

### P1 未完成

1. **定妆模板挂库**（只锁 camera / gaze 核，禁止整槽死冻）
2. **重填预算强制**（每槽 ≤1）— 目前仅有 stub `record_slot_precheck_refill`

---

## 9. 测试

```bash
```

> ⚠️ **不要用 `pytest` 跑这些文件。** 它们用的是自研 `check()` 沙盒（判定失败只记录、**从不 raise/assert**），
> `pytest` 会把它们全部报成 "passed" —— 即使断言实际失败。必须直接执行文件本身，
> 看输出里的 `📊 汇总: N/M 通过` 与进程退出码。

| 文件 | 覆盖 |
| :--- | :--- |
| `tests/test_perspective_silk.py` | silk key 门控、render 跳过、rear skip、check exempt |
| `tests/test_perspective_rear.py` | rear rewrite、inject、零差分 |
| `tests/test_perspective_facial.py` | SAFE_CUMS、skip rear、§4/§11 不削弱 |
| `tests/test_perspective_metrics.py` | 打点、sanitize、summary |
| `tests/test_perspective_exposure_region.py` | 鱼眼白名单三效果、`half_nude.region` 子约束、persist / Spec 回退、普通场景零差分 |

---

## 10. 相关文档

| 文档 | 与本文关系 |
| :--- | :--- |
| [FALLBACK_GUIDE.md](./FALLBACK_GUIDE.md) | silk 拼装跳过、视角曝光绑定 |
| [CHECK_SCRIPT_GUIDE.md](./CHECK_SCRIPT_GUIDE.md) | §3 / `PERSPECTIVE_KEY` |
| [AUTO_FIX_GUIDE.md](./AUTO_FIX_GUIDE.md) | Spec rewrite vs 旧 CARD_RULES |
| [EXPOSURE_CLAMPING.md](./ops/EXPOSURE_CLAMPING.md)（索引：[EXPOSURE_LIMITS_GUIDE.md](./ops/EXPOSURE_LIMITS_GUIDE.md)） | `Spec.exposure_modes` / `exposure_constraints.half_nude.region` / `meta.perspective_key` |
| [DEDUPE_GUIDE.md](./DEDUPE_GUIDE.md) | 占位符 + silk 去重门控 |
| [CONFIG_GUIDE.md](./CONFIG_GUIDE.md) | `perspective_metrics_enabled` |
| [dev/ARCHITECTURE.md](./dev/ARCHITECTURE.md) | 模块指针 |

---

## 11. 一句话

> **完整「X视角」→ `meta.perspective_key` → `PerspectiveSpec`；无 key 全跳过；占位符保留；普通场景零差分。**
