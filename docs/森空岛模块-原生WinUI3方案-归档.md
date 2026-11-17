# 森空岛模块 · 原生 WinUI3 方案归档

> 归档时间：2026-11-15 10:42
> 状态：**方案已定，原生页面未实现**。数据层已真打可用；WebView/本地 HTML 方案作废。
> 这份文档取代之前所有关于「森空岛入口」的实现口径。
> **（2026-11-15 下午更新：第四节的方案已落地，交接文档在宿主仓库 `docs/游戏包-社区模块原生容器-交接.md`；导航项显隐改走 `capabilities.community` 声明而非 ping，差异与理由见其第四节。）**
> **（2026-11-15 13:20 终态归档：签到页、自动签到、游戏数据面板均已实装并真打验证，最新口径见 `森空岛模块-归档.md`；本文件仅保留方案决策过程。）**

---

## 一、结论先行

1. **森空岛模块必须是原生 WinUI3**：`NavigationView` + `Frame` + 独立 XAML 子页，与宿主「库街区」模块同一套结构。
2. **包目录里的 `ui/community.html` 是本地 HTML，既不是官方 H5，也不是 WinUI 模块**。它占了「森空岛入口」的位置，作废。
3. **官方 H5 只是外链**：`game.skland.com/endfield/...`，由宿主用系统浏览器打开；它不等于模块本体。
4. **数据全部来自森空岛 API 直连**（PC 上完成，不装 App、不 root、不抓包），四个模块含签到日历都有只读接口。

## 二、需求与两次纠偏（原话要点）

- 最初需求：加一个「森空岛」一级入口（相当于把库街区改个名字），二级入口为**每日签到、危机合约、影拓丰碑、战争回响**，官方 H5 入口也要有，图标用「游戏数据」。
- 第一次纠偏：**「我要的是 API 数据，你给个网页是有什么大病；PC 网页又不能提取我要的信息」** —— 要包内直接显示数据，不是跳转官方网页。
- 第二次纠偏：**「我们 tm 是 WinUI3 项目，不会看 Arietta 的库街区模块啊？你个网页管这个叫 H5」** —— 要原生 XAML 界面，照库街区结构；本地 HTML 不能叫 H5。
- 追加要求：先看完 Arietta 的文档和代码，再给预览。

## 三、宿主现有机制（代码证据）

### 库街区模块 = 原生

| 位置 | 内容 |
|---|---|
| `src/Features/KuroBbs/KuroBbsPage.xaml:15-21` | `<NavigationView IsPaneToggleButtonVisible="False" IsSettingsVisible="False" OpenPaneLength="248" PaneDisplayMode="Left">` |
| 同上 `:30` | `<NavigationView.PaneCustomContent>` 账号栏：头像 + 名字 + 等级 + 上下箭头（账号切换 Flyout） |
| 同上 `:215` 起 | `<NavigationView.MenuItems>`：每项一个 `NavigationViewItem`，`Tag` 标识功能，Content 是 `Grid(26px 图标 + TextBlock)`，文字 `{x:Bind lang:Lang.Instance.Xxx}` |
| 同上 `:529` | `<Frame Name="Frame_KuroBbs" Margin="0,8,0,0" />` 内容区 |
| `KuroBbsPage.xaml.cs:566-576` | `NavigationView_KuroBbs_ItemInvoked` → `NavigateToTag(item.Tag as string)` |
| 同上 `:603-622` | `NavigateToTag`：Tag → `typeof(SignInPage)` / `typeof(RolePage)` / … → `Frame_KuroBbs.Navigate(pageType, FeatureOf(tag))` |
| `src/Features/KuroBbs/SignInPage.xaml:36-53` | 子页布局：`InfoBar` 空态 + `ScrollViewer` + `Border`（`CardBackgroundFillColorDefaultBrush`）卡片 |

### 官方 H5 的定位

`docs/KuroBbs-Data-Terminal.md:6-16`：

| 游戏 | 名称 | 地址 |
|---|---|---|
| 鸣潮 | 数据终端 | `https://web-static.kurobbs.com/mcbox/index.html#/mc-role-box` |
| 战双 | 作战数据 | `https://web-static.kurobbs.com/pns-box/index.html#/pns-role-box` |

即：**H5 是外部 URL**，宿主用独立窗口/系统浏览器打开；库街区模块本身是原生页。

### 通用模型 → 原生控件的现成先例

`src/Features/GamePacks/PackSettingsPage.xaml.cs`：

- `:112-125` 包声明 `SettingsProvider` 时，`GamePackService.RunProviderAsync(pack, provider, "settings-model", null, 30)` 拿 `JsonElement`；
- `:173` `ParseProviderModel` 把 JSON 解析成 `GroupModel` / `RowModel`；
- `:135-148` 遍历 groups，往 `StackPanel` 里 `Children.Add(BuildRow(row))`，由 `BuildRow` 生成 `ToggleSwitch` / `ComboBox` / `NumberBox` / `Slider` 等原生控件。

**这就是原生「包模型 → XAML」的合规范式，森空岛模块照抄这个思路即可。**

### GamePack 的 UI 扩展点现状

- `src/Core/GamePack.cs:110-114`：`Ui` 字典注释明确写的是 "Web panels rendered by the host WebView"，只服务 WebView；
- 同文件 `:129-135`：`SettingsProvider` 是「包进程生成模型」的入口；
- **目前没有任何「包声明原生页面 / 原生导航项模型」的字段**，也没有非 WebView 的通用面板页。

## 四、正确实现方案（未落地）

### 宿主侧（只做通用能力，不含游戏词）

| 文件 | 内容 |
|---|---|
| `src/Features/GamePacks/PackCommunityPage.xaml` | `PageBase` + `NavigationView`（248px、无设置项、无 PaneToggle）+ `PaneCustomContent`（账号头像/昵称/等级，来自模型）+ `MenuItems`（由模型生成）+ `Frame` 内容区 |
| `src/Features/GamePacks/PackCommunityPage.xaml.cs` | 调 `RunProviderAsync(pack, "community-model", …)`；解析 `items[]` 生成 `NavigationViewItem`（`Tag=id`，图标从 `pack.Folder` 加载）；`ItemInvoked` → 渲染对应 `panel`；`links[]` 用 `Launcher.LaunchUriAsync` 打开；凭证 `PasswordBox` → 存 `AppConfig.LocalFolder/gamepacks/<pack>/community.json`，调用时透传 |
| `src/Features/GamePacks/PackPanelSectionPage.xaml(.cs)`（可选） | 内容区通用渲染：`cards` → 指标卡 Grid；`blocks` → `Border` 卡片 + rows + `ProgressBar`；`calendar` → `ItemsRepeater`/`GridView` 格子；`note` → 次级文字 |
| `src/Features/ViewHost/MainView.xaml.cs` | community 改道：`PackPanelPage`（WebView）→ `PackCommunityPage`（原生）；gacha 仍走 `PackPanelPage`，不动 |

### 包侧（全部游戏知识）

`provider.py` 新增 `community-model`，复用 `skland.py`：

```json
{
  "account": { "name": "纸鸢", "level": 60, "worldLevel": 7, "avatar": "https://…" },
  "items": [
    { "id": "sign",     "label": "每日签到", "icon": "assets/toolbox/每日签到.png" },
    { "id": "crisis",   "label": "危机合约", "icon": "assets/toolbox/游戏数据.png" },
    { "id": "monument", "label": "影拓丰碑", "icon": "assets/toolbox/游戏数据.png" },
    { "id": "echoes",   "label": "战争回响", "icon": "assets/toolbox/游戏数据.png" },
    { "id": "h5",       "label": "官方 H5",  "icon": "assets/toolbox/游戏数据.png", "external": true }
  ],
  "credential": { "label": "鹰角账号 token", "help": "…", "required": true },
  "panels": {
    "sign": { "title": "每日签到", "cards": [...], "blocks": [...], "calendar": [...], "links": [...], "note": "…" }
  }
}
```

- `cards`：`{label, value, hint, tone}`
- `blocks`：`{title, rows:[{label,value,tone}], bars:[{label,value,total}]}`
- `calendar`：`{day, award, done, available}`
- `links`：`{label, url}`（官方 H5）

这套模型与已实现的 `skland.overview()` 输出几乎同构，只需再包一层 `items` / `credential`。

## 五、已完成且可用的部分（数据层）

- `skland.py`（包内，20533 字节）：端点、appCode `4ca99fa6b56cc2ba`、sign 算法（HMAC-SHA256 → hex → MD5，四头参与，时间戳回拨 5 秒）、字段映射、官方 H5 链接。
- `provider.py` 已注册 `skland-overview`，`ping.capabilities` 含同名方法；`SklandError` 转 `ProviderError`。
- 真打验证（2026-11-15）：
  - 账号 Lv60 / 26 干员 / 49 武器；
  - 签到 `GET /web/v1/game/endfield/attendance` → `calendar` 30 天、`first`、`resourceInfoMap`、`hasToday`；
  - 危机合约 `card/detail.crisisContract` → 最高难度 1、挑战 1、周常 0/4、指标 1/5；
  - 影拓丰碑 `card/detail.indieHard` → 8 系列 33 关，普通 33/33、苦难 9/33；
  - 战争回响 `card/endfield/card/war-echoes` → 赛季、轮换、星数、成就。
- 部署副本已同步 `provider.py` / `skland.py` / `ui/community.html`，`GamePackSign verify = valid · PaperKito`；仓库 `signature.json` 按约定等 assets 收尾统一重签。

## 六、未完成 / 作废清单

| 项 | 状态 |
|---|---|
| `PackCommunityPage`（原生容器） | **未实现** |
| `community-model` provider 方法 | **未实现**（数据层可复用） |
| `MainView.xaml.cs` 改道到原生页 | **未实现**（当前仍改道 `PackPanelPage` WebView） |
| `ui/community.html` + `game.json` 的 `ui.community` | **作废**。原生页落地后应删除 html 并移除 `ui.community`（届时导航项改由 `community-model` 驱动） |
| `docs/森空岛入口与二级模块H5接入-交接.md` 第八节 | 描述的是 WebView 面板方案，随 html 一起作废；以本归档为准 |
| 界面预览 | 2026-11-15 已按库街区结构给出 WinUI3 界面稿（NavigationView + 账号栏 + 四模块 + 数据卡/日历/进度条 + H5 外链按钮），尚未写成 XAML |

## 七、验收标准（实现后照此验）

1. 切到终末地 → 左栏「森空岛」→ 打开的是**原生页**，没有 WebView、没有本地 html。
2. 左侧 248px：账号头像/昵称/等级 + 四个模块 + 官方 H5 + 凭证设置；选中项高亮，切换即时换内容。
3. 四个模块显示真实 API 数据（签到日历、合约进度、丰碑通关、回响赛季），控件全是 XAML 原生。
4. 官方 H5 按钮 → 系统浏览器打开 `game.skland.com/endfield/...`。
5. 宿主源码里搜不到「森空岛 / 危机合约 / 影拓丰碑 / 战争回响 / zonai」等游戏词（红线）。
6. `dotnet build src/Arietta.csproj -c Release` 0 错误；部署副本重签 `valid`。

## 八、相关文件

- 数据层：`skland.py`、`provider.py`
- 作废：`ui/community.html`
- 预览（包外）：`../build-out/community-panel-preview.html`（HTML 版，仅作历史参考，不要再作为交付物）
- 调查脚本（包外）：`../build-out/skland_probe.py`、`probe_sign_and_detail.py`、`make_panel_preview.py`
- 前置实测记录：`docs/森空岛API-数据终端直连实测-交接.md`
