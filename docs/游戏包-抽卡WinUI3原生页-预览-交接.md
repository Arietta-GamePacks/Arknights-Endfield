# 游戏包 · 抽卡 WinUI3 原生页（鸣潮同款）调研与预览 - 交接

> 时间：2026-11-15 上午
> 性质：**方向纠偏 + 设计打样**。上一轮做成了 WebView 面板（`ui/gacha.html` + `PackPanelPage`），不是要的形态。本轮按「跟鸣潮一样的 WinUI3 原生页」重新拆宿主实现，产出 `preview-endfield-gacha.html` 预览稿，**尚未改任何运行代码**。

## 一、鸣潮抽卡页是怎么实现的

宿主：`D:/Work/Code Project/Arietta/src/Features/GachaLog/`
原型：`D:/Work/Github/Scighost_Starward/src/Starward/Features/Gacha/`（本地副本，照抄机制不照抄代码）

| 层 | 文件 | 干什么 |
| --- | --- | --- |
| 页面骨架 | `GachaLogPage.xaml` | 根 `Grid` 两行：44px 页头 + `SplitView`（Content = 横向卡池列，Pane = 右侧 508px 物品统计）。页头：账号 `ComboBox` + `SplitButton`（更新记录 / Flyout 四种方式）+ 设置 `Button + Flyout` + `AccentButtonStyle` 的半圆角边栏开关。 |
| 卡池列 | `GachaLogPage.xaml:322-507` | `ScrollViewer`（横纵都原生滚动）→ `ItemsControl` → 横向 `StackPanel Spacing=12` → 每列 `Border Width=268`，亚克力底 + 1px 分隔线 + 阴影。列内：池名/总抽、时间跨度、4 行星级统计（5★平均绿 / 5★橙 / 4★紫 / 3★蓝）、`cwc:Segmented` 二选一、`BarItemTemplate` 列表。 |
| 垫抽条 | `GachaLogPage.xaml:32-84`、`BarItemTemplate` | 行高 30，列宽 `32 / * / Auto / Auto(28)`：28×28 头像、22px 渐变条、斜体 `up!`、右对齐抽数。`up!` 列按**卡池级**预留、文字按行用 `Opacity` 显隐，避免 `*` 列宽跳动。 |
| 渐变算法 | `GachaLogViewModel.cs:712-780` `BarItemViewModel.CreateBarBrush` | `LinearGradientBrush` 在 `pity/80` 处硬切：`< 66` 绿 `#00E079`，`>= 66` 红 `#C83C23`，整条 `Opacity=0.4`。对齐 Starward 的 `GachaPityProgressBackgroundBrushConverter`。 |
| 统计 | `GachaStatService.cs` | 记录转正序扫描，累计 `since5/since4`，出 `PoolStat`（Total / Count5 / Count4 / Count3 / CurrentPity5 / Avg5 / UpAvg / Items5 / Items4）。UP 判据 = 活动池 ∧ 不在常驻 ID 集合。 |
| 视图模型 | `GachaLogViewModel.cs:583-664` `PoolViewModel` | `PoolStat` → 显示串（`2 [2.56%]` / `38.50 / 42.00 (2)`），「已垫」行插到列表最前，`SelectedRarityIndex` 切 5★/4★。 |
| 右侧边栏 | `GachaLogPage.xaml:536-589` | `GridView` 的 80×80 方图卡 + 3px 品质底条（5★金 / 4★紫）+ 次数/名字；`GachaItemStat` 与 `GachaIcon` 负责补图。 |
| Starward 原型 | `GachaStatsCard.xaml` / `GachaLogPage.xaml` | 同一套：`Grid Padding=12,8`、四色星级前景、`MenuFlyoutSeparator`、SplitButton + 隐藏卡池二级 Flyout、右侧 Accent 半圆按钮。宿主注释里逐处标了「对齐 Starward」。 |

**结论**：鸣潮是纯 XAML + ViewModel，没有 WebView。要「一样」就得走 `PoolStat → PoolViewModel → BarItemViewModel` 这条链，而不是 HTML。

## 二、预览稿做了什么

文件：`preview-endfield-gacha.html`（包根目录，与 `preview-endfield-settings.html` 同一套窗口骨架；**不与部署副本同步**，不进运行时签名）。

1:1 复刻的 WinUI 控件映射（打开页面后点底部「WinUI3 控件标注」可在对应元素上看标签）：

| 预览 HTML | 宿主 WinUI3 | 位置 |
| --- | --- | --- |
| `.window / .titlebar / .sidebar / .bottombar` | 应用窗口 + NavigationView | 与 settings 预览同款 |
| `.pagehead` 44px | `Grid.Row=0` 页头 | `GachaLogPage.xaml:88-100` |
| `.combo` | `ComboBox`（账号） | `:107-111` |
| `.splitbtn` + `.flyout` | `SplitButton` + `MenuFlyout` | `:114-144` |
| `.toolbtn` + `#settingsMenu` | `Button` + `Flyout`（其他设置 / 隐藏卡池 / 删除） | `:147-280` |
| `.panebtn` | `AccentButtonStyle` 半圆角开关 | `:283-294` |
| `.columns` 横向滚动 | `ScrollViewer` → `ItemsControl` → 横向 StackPanel | `:316-327` |
| `.poolcol` 268px | `Border Width=268` 亚克力列 | `:331-339` |
| `.stat` 四行 | 5★平均 / 5★ / 4★ / 3★ 统计行 | `:369-465` |
| `.segmented` | `cwc:Segmented`（底部强调条改成品牌黄） | `:471-488` |
| `.barrow` + 硬切渐变 | `BarItemTemplate` + `CreateBarBrush` | `:32-84` |
| `.splitpane` 508px + `.itemgrid` | `SplitView.Pane` + `GridView` 物品卡 | `:297-306, 536-589` |

**换成终末地的部分**（全部来自包侧 `gacha.py` 的口径，宿主仍不该认识这些词）：

- 星级轴从 5/4/3 变成 **6/5/4**，配色沿用橙 / 紫 / 蓝；
- 列头严格对齐鸣潮：只有池名 / 总抽数 / 日期，日期下面**不放任何额外徽标**（用户钦定，已删掉最初那版金色保底条）；
- 卡池列：特许寻访、重构寻访 #1、基础寻访、限定申领 —— **首页最多 4 个**（268×4 + 12×3 = 1108px，一屏完整可见，与鸣潮默认视图一致）；
- 6★ 行带 UP / 歪 / 常驻标记、免费抽口径、重构跨版本继承；
- 强调色用包的 `accentColor #E6D800`。

**可交互**：更新记录下拉、设置 Flyout（含隐藏卡池多选）、账号切换、每列独立的 6★/5★ Segmented、右侧物品统计开合、控件标注开关、行悬停看时间。数据为演示样例，无任何真实账号信息。

验证：内联 JS 已过 `node --check`；卡池对象 4 个、`badge` / `pbadge` 残留 0 处（脚本计数校验）；HTML 由预览面板直接打开。

## 三、落地方案（架构设计；2026-11-15 中午已按此实现，见第六节）

红线（AGENTS.md）：宿主不得出现任何游戏代码，换一个游戏包宿主一行不用改。做法照 `settings-model` 的先例 —— **包出通用行模型，宿主只渲染**。

1. **包侧**（`gacha.py` / `provider.py`，游戏知识都留这儿）
   `gacha-stats` 增加一个与游戏无关的 `winui-model` 输出：
   ```jsonc
   {
     "players": [{"uid":"...", "display":"..."}],
     "pools": [{
       "id":"special", "name":"特许寻访 · 演示期", "range":"...", "total":78,
       "rows": [{"label":"6★ 平均","value":"38.50","tone":"avg"}, ...],
       "tabs": [{"label":"6★","rows":[{"name":"已垫","pity":23,"up":false,"icon":null,"time":"..."}]},
                {"label":"5★","rows":[...]}],
       "pityPoint":66, "pityGuarantee":80, "showUpColumn":true,
       "items": [{"name":"...","count":2,"quality":6,"icon":"..."}]
     }]
   }
   ```
   卡池名、星级轴标签、保底阈值、UP 判据、物品名与图标**都由包给**；宿主只认 `label/value/tone/pity/pityPoint/pityGuarantee`。

2. **宿主侧**（新增通用页，不碰鸣潮管线）
   - 新增 `PackGachaPage.xaml(.cs)`，**复用 `GachaLogPage.xaml` 的列模板 / `BarItemTemplate` / SplitView 结构**（可抽成共享 `ResourceDictionary`，或复制一份避免污染内置游戏）；
   - `PackGachaViewModel` 把通用模型映射成 `PoolViewModel` / `BarItemViewModel` 等价物：`CreateBarBrush` 的 `point/guarantee` 改由模型传入，名称/图标走包模型，不再查 `GachaNameTable` / `GachaIcon`；
   - `MainView.NavigateTo` 对声明了 `gachaModel` 能力的包改道到这个原生页；
   - 数据链：宿主存 token（通用凭据）→ 调 provider `fetch` → `gacha-stats` → 渲染，全量/增量由包决定。

3. **撤掉上一轮的东西**：`PackPanelPage`（WebView 桥）、`ui/gacha.html`、`game.json` 的 `ui.gacha` 导航改道。`gacha.py` 统计引擎与 `provider.py` 的 `gacha-stats` / `gacha-url` / `fetch` 增强**保留**，它们正好是原生页的数据层。

## 四、未决

- 预览稿的保底渐变仍按 66 / 80 画（对齐宿主视觉），终末地实际硬保底 80、特许 120 大保底；落地时 `pityPoint` / `pityGuarantee` 由包模型给，宿主不再有 66/80 常量。
- 右侧物品卡需要 `icons/<item_id>.png`，包内 `icons/` 目前为空；缺图回落名称占位（宿主已有 `NameVisibility` 机制）。
- 动宿主需按项目流程 `rebuild.bat` 全量重建，改包文件需同步部署副本并重签（第六节已完成）。

## 五、2026-11-15 11:35 补记：页面错位与运行页同步

用户截图反馈「看起来还是这样」，画面是**应用里跑的 `ui/gacha.html`**（上一轮 WebView 卡片页：总览 6 卡、角色/武器 tab、带「大保底 120」「小保底 80」的金色 chips、6★ 出货历史），不是本轮的 WinUI3 打样稿。原因：前两轮只改了 `preview-endfield-gacha.html`（预览稿），**没有同步应用实际加载的 `ui/gacha.html`**，所以宿主界面当然没变。

本轮处置（都已落盘）：

| 文件 | 改动 |
| --- | --- |
| `preview-endfield-gacha.html` | 上一轮已改：4 个卡池列、删掉日期下的金色 `.pbadge` 保底条 |
| `ui/gacha.html` | 本轮补齐：chips 不再渲染 `badge`（金色小字）、box 标题右侧的保底 badge 去掉、首页 groups 上限 4 |
| 部署副本 `ui/gacha.html` | 已同步，内联 JS 过 `node --check` |
| 签名 | `GamePackSign sign` + `verify` → `valid · PaperKito` |

**要看变化**：重启 Arietta（WebView 不会自动重载本地 HTML），预览面板也要刷新一次。

**现状澄清**：应用里那个仍然是 **WebView 过渡页**，布局是卡片式，不是鸣潮那套横向 268px 卡池列。真正「跟鸣潮一样」的样子只在 `preview-endfield-gacha.html` 里；WinUI3 原生页（第三节的方案）当时**尚未落地**，现已按第六节实现。别把两个文件搞混。

## 六、原生 WinUI3 抽卡页已落地（2026-11-15 12:xx）

用户明确质问「到底写了 WinUI 的文件没有」，本轮补上**真正的 XAML / C# 原生页**，并撤掉抽卡入口的 WebView 挂载。

### 宿主（真实文件）

| 文件 | 作用 |
| --- | --- |
| `Arietta/src/Features/GamePacks/PackGachaPage.xaml` **新增** | 原生 WinUI3 页。44px 页头（账号 + `SplitButton` 更新 + 右侧 `AccentButtonStyle` 开关）+ `SplitView`；Content 是 `ScrollViewer → ItemsControl → 横向 StackPanel` 的 **268px 卡池列**（列头池名/总抽/日期、4 行星级统计、`cwc:Segmented` 6★/5★、`PackBarTemplate` 渐变垫抽条），Pane 是 508px `GridView` 物品卡。视觉 1:1 对齐 `GachaLogPage.xaml`，**没有任何金色保底徽标条**。 |
| `Arietta/src/Features/GamePacks/PackGachaPage.xaml.cs` **新增** | `PackGachaViewModel` / `PackPool` / `PackStatRow` / `PackBarItem` / `PackItemCard`；`CreateBarBrush` 复刻鸣潮的硬切渐变（`<pityPoint` 绿 / `≥` 红，Opacity .4），`pityPoint` / `pityGuarantee` 由包模型给，宿主不写死 66/80。 |
| `Arietta/src/Features/ViewHost/MainView.xaml.cs` | 抽卡导航改道：`pack.Capabilities.Gacha == true` → `PackGachaPage`（与 community 的 `PackCommunityPage` 同模式），不再走 `PackPanelPage`。 |

### 包侧（数据源）

| 文件 | 作用 |
| --- | --- |
| `gacha.py` | 新增 `winui_model()`（UGF → 通用列模型：`account` / `pools[].rows,tabs,pityPoint,pityGuarantee` / `items`）、`demo_ugf()`、`demo_pool_info()`、`_five_history()`。首页**最多 4 个卡池列**。 |
| `provider.py` | 新增 `gacha-model` 方法 + `ping.capabilities`：有 token / u8_token 走真实 `fetch` → UGF；无凭证返回演示模型（页面标「演示数据」，点更新可换真数据）。 |
| `game.json` | `ui` 清空 —— 抽卡不再声明 WebView 面板。 |

`PackPanelPage`（WebView 桥）保留为通用能力，但抽卡入口已不再使用它；`ui/gacha.html` 留作静态预览，不再被宿主加载。

### 验证（全跑过）

```
宿主 rebuild.bat 全量重建：0 错误（97 个既有警告）
  途中两个真错误：CS0246 缺 using Arietta.Core；CS0123 SplitButton.Click
  需要 TypedEventHandler<SplitButton, SplitButtonClickEventArgs> 签名 —— 都已修
包侧 gacha-model 真跑：ok=true, demo=true, pools=4, items=18
部署副本同步 + GamePackSign：valid · PaperKito
部署副本内再跑 gacha-model：ok=true, pools=4
```

### 使用 / 遗留

重启 Arietta → 选终末地 → 左侧「寻访记录」→ 应看到 **4 个 268px 卡池列**（演示数据）、Segmented 切换、渐变垫抽条、右侧物品统计。点「更新记录」下拉里的「输入账号 token」或「读取本地日志」换真实数据，token 存宿主 `AppConfig`（`PackGachaToken_<packId>`），不写包目录。

遗留：`/api/content`、`rerun-counts`、GRYPHLINE 抽卡域仍未真打；`icons/` 为空所以物品卡走名称占位；增量同步未做；仓库 `signature.json` 按约定仍等 assets 收尾统一重签（部署副本已即时重签）。
