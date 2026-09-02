# RealWorld 分析界面设计

> 状态：原型已定稿（`doc/ui_mockup_realworld.html`，可交互验证）
> 属于：`doc/GUI_Design.md` 第 4 节"realworld 分析配置"的落地细化
> 对应 solver：`/score/create/realWorldLogVol <LV>`（一个逻辑体 = 一个 scoring cell）

## 一、界面风格

> **总原则：风格不独立，完全跟随主界面颜色模式（主题）**。弹窗不定义自己的配色，只消费主界面提供的同一套主题 token。主界面切换主题（深色 / 浅色 / 跟随系统）时，本弹窗与其它所有弹窗同步换肤，布局、字体、间距不变，只换颜色。

**模态弹窗 · 三栏布局**，主界面打开，未确认不能返回：

```
┌─ RealWorld 分析设置 ────────────────────────────────┐
│ ① 逻辑体（GDML 层级）  │ ② Quantity 设置   │ ③ 能谱直方图 │
│   ▼ TOP       世界     │  名称/类型/单位/…  │  关联量/bins  │
│   ├─ vXBox  ☑ ALU     │  + 添加 quantity  │  范围/log    │
│   ├─ vYBox     ALU     │  + filter 行内展开│  + 添加直方图 │
│   └─ vArrow ×3 ALU     │                   │              │
│ 底部：已配置逻辑体统计  │       [取消] [确认]│              │
└──────────────────────────────────────────────────────┘
```

**视觉基调**（与 1dRad / 其它弹窗一致）：

| CSS 变量 | 值 | 用途 |
|---|---|---|
| `--bg / --p / --p2` | `#16171d / #1f212b / #262936` | 页面 / 面板 / 标题栏底色 |
| `--bd` | `#33364a` | 边框（hover `#4a4e6a`） |
| `--ac` | `#4f8cff` | 主色：选中高亮、勾选、主按钮、锁定单位 |
| `--ok` | `#3fbf6f` | 运行成功语义色 |
| `--wr` | `#f0a94e` | 运行按钮 / 提示色 |
| `--red` | `#e05555` | 删除悬停 |

- 正文 `13px Segoe UI`；名称、数值、单位一律 `11.5px Consolas` 等宽
- 选中逻辑体：`#26334f` 底 + 3px 左侧主色边；逻辑体名 hover `#2a2d3d`
- 空态：虚线框居中引导文案；toast：底部浮出绿色提示条
- 单位锁定：只读灰底主色字，鼠标悬停解释"由类型锁定"
- filter 已挂：金色标签 `✓ gamma`；未挂：主色虚线 `+ filter`

### 主题联动实现要点（后续修正/落地时对照）

1. **上表就是全局主题 token 清单（深色版）**：`--bg / --p / --p2 / --bd / --ac / --ok / --wr / --red` 全部由主界面主题管理，弹窗只引用变量，**不出现任何硬编码色值**。
2. **换肤 = 换 token**：深色 / 浅色 / 跟随系统三套主题，每套只是这些变量的取值不同；布局、字体、圆角、间距等非颜色属性是主题无关的，不随之变化。
3. **mockup 阶段**：主题即 `:root` 下的 CSS 变量，切主题 = 改 `:root` 变量值；原型只实现深色一套，但颜色必须全部走变量（已如此）。
4. **落地阶段（PySide6）**：全局 QSS 模板 + 主题字典 `{dark:{...}, light:{...}}`，主窗口与 realworld / probe / voxel 所有弹窗共用同一份 QSS；主题切换即切换当前 token 字典并重设 QSS。
5. **新增色值约束**：新控件需要新颜色时，先追加到全局主题 token，再在组件里引用；禁止在组件内部直接 new 一个颜色（否则浅色主题下必然出现一处漏改）。
6. **语义色不得混用**：`--ok` 只用于成功/运行语义，`--wr` 只用于告警，`--red` 只用于删除等危险操作，避免主题下某个颜色被视觉误读。

## 二、设置方式（操作路径）

```
项目树 Runs → Analysis → 双击「RealWorld 分析」（模态）
   → 点击左侧任意逻辑体 → 右侧刷新为该逻辑体的专属配置
   → ①「+ 添加 quantity」：起名 / 选类型 / 单位自动锁定
   → ② 点该行 filter 标签 → 行内展开选 filter 类型与粒子
   → ③「+ 添加直方图」：选关联量 / bins / 范围 / log 轴
   → 右下角「确认」保存关闭 → 回主界面点「▶ 运行」
```

## 三、联动逻辑（核心规则）

1. **点选即刷新**：点击左侧逻辑体 → 右侧 quantity / 直方图两栏刷新为该逻辑体的专属配置；未配置时显示空态引导。
2. **配置持久化**：每个逻辑体独立存储（`cfg[LV].qs / .hs`）——切换走再点回来，配置不丢失；删空该逻辑体全部配置后勾选自动消失。
3. **勾选由配置驱动，不是手动勾选**：左侧 ☑ = 该逻辑体"已有任一 quantity 或直方图"，随配置自动打/消，无需全选/全不选。
4. **确认 ≠ 运行**：右下角「确认」只保存配置并关闭弹窗；「▶ 运行」在主界面工具栏，弹窗全程不触发模拟。
5. **filter 行内展开**：点 quantity 行右侧 filter 标签，该行下方展开编辑区（类型 + 粒子下拉），不弹子窗。
6. **单位完全锁定**：quantity 单位与直方图 x 轴单位均只读、由类型一一对应（见下表），关联量切换时 x 轴单位自动跟换。
7. **类型候选 = realWorld 可用全部 15 种**：17 种 primitive scorer 去掉仅 boxMesh 的 `flatSurfaceCurrent` / `flatSurfaceFlux`，首版全开放，不收敛。
8. **直方图关联量只允许"支持 fill1D"的量**：Table 8 中 x 轴为 n/a 的 5 种（trackLength / cellCharge / nOfCollision / nOfTerminatedTrack / population）不会出现在关联量下拉里。
9. **类型切换联动**：若把已被直方图引用的 quantity 改成不支持能谱的类型，对应直方图自动移除并 toast 提示，不留悬空引用。

### 单位映射（BFAD Table 8，GUI 只读）

| quantity 类型 | quantity 单位（默认单位列） | 直方图 x 轴单位（x 轴列） |
|---|---|---|
| energyDeposit | MeV | MeV |
| doseDeposit | Gy | Gy |
| volumeFlux | —（计数） | MeV（入射动能） |
| nOfStep | — | mm（步长） |
| nOfTrack | — | MeV（入射动能） |
| nOfSecondary | — | MeV（入射动能） |
| cellFlux | cm⁻² | MeV |
| passageCellFlux | cm⁻² | MeV |
| passageCellCurrent | — | MeV |
| passageTrackLength | mm | mm（径迹长度） |
| trackLength | mm | 不支持能谱 |
| cellCharge | e⁺ | 不支持能谱 |
| nOfCollision | — | 不支持能谱 |
| nOfTerminatedTrack | — | 不支持能谱 |
| population | — | 不支持能谱 |

## 四、状态模型（原型 JS）

```js
state = {
  active: 'vXBox',                     // 当前选中逻辑体
  cfg: {
    vXBox: {                            // 每逻辑体独立一份
      qs: [{ name:'q1', type:'energyDeposit',
             f: { t:'particle', p:'gamma' } }],   // f=null 表示无 filter
      hs: [{ q:'q1', bins:100, rng:'0.001 – 1000.', log:false }]
    },
    vYBox: { qs:[], hs:[] },            // 未配置 → 左侧无勾
    ...
  }
}
```

勾选判定：`configured(LV) = cfg[LV].qs.length > 0 || cfg[LV].hs.length > 0`。

## 五、mac 生成规则

每个已配置逻辑体生成一个 mesh，各带自己的 quantity + 直方图：

```mac
/score/create/realWorldLogVol vXBox
/score/quantity/energyDeposit q1
/score/filter/particle f1 gamma        # 若有 filter：紧跟其 quantity 之后
/score/close

/analysis/h1/create q1 vXBox_q1 100 0.001 1000. MeV ! log   # x 轴单位由类型锁定
/score/fill1D 1 vXBox q1
```

- mesh 名称用逻辑体名（realWorldLogVol 自带唯一性）
- filter 行必须紧跟其 target quantity 之后（G4 顺序绑定规则）
- 不支持 fill1D 的类型不生成直方图行
- 后续实现由 `core/mac_generator.py` 承接（见 `GUI_Design.md` §1 目录结构）

## 六、与总设计文档的关系

| 条目 | 位置 |
|---|---|
| 弹窗整体归类、三种分析对比 | `GUI_Design.md` §3 |
| realworld 概要 | `GUI_Design.md` §4 |
| Filter 通用规则（5 种类型、离子特例、多粒子拆分） | `GUI_Design.md` §7 |
| 本文件 | realworld 弹窗的布局 / 风格 / 联动细则 |
