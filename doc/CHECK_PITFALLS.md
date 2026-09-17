# CHECK_PITFALLS.md — 高频避坑速查

> [!WARNING]
> **⚠️ 维护提醒**：本文件**仅放高频出错与最易画崩的拦截情况**。

> fill/check 前快速自检**最容易被脚本拦截或画崩的坑**。

## 🚫 ERROR 高频拦截与修正


| 类别                  | ❌ 错误写法                                                                               | ✅ 修正写法                                                                                                                                        | 备注                                                                                |
| :---------------------- | :------------------------------------------------------------------------------------------ | :--------------------------------------------------------------------------------------------------------------------------------------------------- | :------------------------------------------------------------------------------------ |
| **口唇与舌**          | `biting lip`, `tongue out`, `drool`                                                       | `lips softly parted`, `pressing lips together`                                                                                                     | 避免AI画出悬浮舌头或白色粘稠口水                                                    |
| **内裤私处**          | `panties` + `pussy/vulva` 共存                                                            | 改为`no panties` 或 `bottomless`                                                                                                                   | 严禁隔着内裤透视私处，必须直接裸露或脱掉                                            |
| **半透露点与解构**    | `sheer nipple` / `see-through nipple`；或 `bra pushed aside` + `nipples visible` 同在      | 改为移开：`unbuttoned` / `lifted` / `slipped off`；或 clothing 删 bra 只留露点                                                                     | 半透衣服或胸罩露点易穿模冲突，二选一表达，推荐直接敞开/拨开裸露                     |
| **§2-2 隐式穿透**    | `no bra` + 白衬衫/薄上衣 + nipples，却未写移开                                            | 写清`shirt open` / `unbuttoned` / `hanging open`；或去掉 no bra / 奶头细节                                                                         | 后置不按 half_nude 豁免；`open-back` 不算前敞；外敞叠扣好内衬属合法半遮放行        |
| **§2-4 无扣假敞开**   | `camisole/tank/sports bra` + nipples，只写`hanging open`/`one shoulder`/`partially visible` | 删奶头细节；或写`topless`/`bare breasts`/`nipples visible`；或`camisole pulled down / aside`/`removed` | 有扣`shirt/blouse`不走本条；无扣衣弱敞开会穿模，不豁免                               |
| **§11-3 单侧乳头分叉** | 侧面视角，或衣物只露一侧乳房，但仍写复数 `breasts` / `nipples` / `areolae`                 | 改为 `only one breast visible` / `one nipple visible` / `one areola visible`，并写明另一侧被衣物或身体角度遮挡                                     | 卡片渲染会自动单数化；门禁负责拦截绕过修正后的残留复数                              |
| **阴毛姿势**          | `pubic hair` + 闭腿 (`legs closed`/`knees together`)（**非** half_covered 擦边）           | **normal/lower**：配 `legs spread` / `knees apart` + 锚点 `on mons pubis centered`。<br>**half_covered 例外（§1-4）**：闭腿 + panty-edge/mons peek（`panty edge` / `inner thigh` / `mons pubis`）→ **最多软警告**，勿强制分腿 | 闭腿露毛在露下场景属解剖冲突；半遮裤边偷看合法擦边，不 HARD                         |
| **§17-13 站姿露下**   | `standing` + 露私处/露逼，但双腿完全并拢未分                                               | 在姿势中显式补充 `thighs parted` / `legs spread slightly` / `knees slightly apart`                                                                 | 站直并腿时解剖上私处自然闭合，硬写露阴会导致毛发撕裂成上下截怪异毛球与夹缝畸变      |
| **精液规范**          | 喷射词 (`spraying`/`cumshot`)；附着在嘴/唇/鼻/下巴/睁眼；涂抹感/珠状 beads/从脸顺流到锁骨 | 颜射以`SAFE_CUMS` 为底本可微调：脸+锁骨/上胸同框、半透明软沉积/短贴肤流线（禁死白绳丝）；下巴下颌干净；脸上不跨区到锁骨，锁骨仅到上胸、不上乳房    | 静态附着+局部短流线。绝对拉黑嘴/舌/口内/睁眼；禁止整段自编跨区导流                  |
| **构图冲突**          | 自拍且双手动 (`both hands`)；背面且露胸露私 (`from behind` + `nipples visible` + `vulva`)；埋脸直视镜头 | 自拍改单手动作；背面改侧身视角或纯背面（删看镜头）；埋脸删直视镜头                                                 | 避免AI生成逻辑冲突（如第三只手、身体180度扭曲或面部穿模）                           |
| **床姿/镜前**         | 裸写`lying on bed` 或 `standing in front of mirror`                                       | 床姿加方向：`side-lying`/`on back knees bent`；镜前加视角：`from behind`                                                                           | 必须有明确动作方向和机位，避免被拦截                                                |
| **纹身融合**          | 仅写`tattoo`；使用否定词 (`no tattoo`/`without tattoo`)；中文无风格                       | 纹身用词组合 (`ink embedded in dermis`, `pores visible through ink`)；不要纹身直接在 slots.tattoo 留空；中文纹身加 `hand-drawn`/`permanent marker` | 中文无风格或仅有单词容易画出贴纸感，否定词会引发AI误解                              |

## ⚠️ 常见误杀与规避

* **half_covered 外敞叠扣好内衬**：`blazer hanging open over buttoned blouse` 合法擦边，不算直接露点；真露点仍写 `no bra` / `bare breasts`。

* **自拍限制**：不要在 prompt 里用 `camera`（容易被判定为相机非自拍），用 `lens` / `phone` 代替。
* **床上姿势**：如果在床上躺着，道具不要放在床上（容易被床姿正则误杀），道具位置写到 `nearby shelf` / `table surface`。

## 💡 使用原则

1. **裸露不重复**：服装 (clothing) 写了 bra 移开，身材 (body_shape) 就不要提 areolae/nipples；反之亦然。
2. **私处统一写法**：展示私处统一使用 `bottomless / bare from waist down / no panties`。
3. **镜/床/自拍/俯拍** 是高频拦截雷区，设计前先通过本表核对一遍。
