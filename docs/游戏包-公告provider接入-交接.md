# 游戏包 · 公告 provider 接入 - 交接

> 时间：2026-11-15 凌晨
> 性质：**新能力落地，已实测（包侧真打）+ 宿主构建通过**。包游戏首页公告卡从 provider 取数，宿主零游戏知识。
> 前置：`docs/Collapse-终末地插件-调查与画面设置预览-交接.md`（batch_proxy API 实测）、`docs/游戏包-终末地接入-归档-交接.md`（公告位与架构）。

## 一、背景与架构裁定

归档文档遗留待办「公告：参照库有 HgLauncherApiNews，未接」。本轮实装。

用户中途确认两条**架构边界**（已写入本仓库 `AGENTS.md`）：

1. **Arietta 不得出现任何包（游戏）的代码**——一切游戏知识只活在包目录；
2. **允许**修改 Arietta 使其具备「接入包公告」的通用能力（provider.notice 消费端），判断标准：换任何游戏包、宿主一行不用改。

因此方案定为「provider 通道」而非宿主直打鹰角 API：宿主只认协议，公告接口的端点/appcode/字段映射全在 provider.py。

## 二、实测结论（包侧，2026-11-15 真打）

```
echo '{"id": 4, "method": "notice"}' | py -X utf8 provider.py
→ ok: true
→ banners: 9 张（hg-utils-public.hycdn.cn 轮播图）
→ groups: 公告(8) / 新闻(1) / 资讯(11)
→ 样本: {"title":"「烟火邀星河」特许寻访说明","date":"2026-11-04","link":"https://endfield.hypergryph.com/news/7204"}
```

tabName 实际返回「公告 / 新闻 / 资讯」（无「活动」组时该组不出），直接透传做分组头，无需宿主分类逻辑。

## 三、实现行为

### 包侧（provider.py，+36 行）

- 常量：`LAUNCHER_CHANNELS`（按服变体码分通道，2026-11-15 起；国服参数 = `web/batch_proxy` + `6LL0KJuqHBVz33WK` + 1/1 + seq 5，国际服见第七节）——与官方启动器同源，见 Collapse 调查交接
- `method_notice(params)`：一次 POST 同时要 `get_banner` + `get_announcement`（common = appcode/language/channel/sub_channel/platform Windows/source launcher；语言与通道按 `params.lang` / `params.server` 决定），映射成对齐宿主数据模型的通用结构：
  - `banners: [{url, jump_url}]`（无 url 的丢弃）
  - `groups: [{header: tabName, items: [{title: content, date: yyyy-MM-dd(start_ts 毫秒), link: jump_url}]}]`（空组丢弃）
  - banners 与 groups 全空 → 抛「公告接口没有返回内容」
- `ping` 的 capabilities 增加 `"notice"`；METHODS 注册 `notice`
- 协议不变：仍是一次调用一个进程、一行进一行出（见 Provider 协议交接）

### 宿主侧（Arietta，4 文件，全通用、零游戏知识）

| 文件 | 改动 |
|---|---|
| `src/Features/GamePacks/GamePackService.cs` | 新增 `RunProviderAsync(pack, method, params, timeout)`：起 provider 进程（UTF-8 stdout + `PYTHONIOENCODING/PYTHONUTF8`）→ 写一行请求 → 竞速超时读一行响应 → 解析 `{ok, result/error}`。这是协议文档第六节排定的 ProviderClient，抽卡 fetch / 账号 accounts 未来同走此门 |
| `src/Features/GameLauncher/GameNoticeService.cs` | 新增 `GetPackAsync(pack)`：provider `notice` → 映射进现有 `GameBannerItem/GamePostGroup`；按包 id 分键缓存（多包共用 `GameBiz.External`，不能按 biz 缓存）；`InvalidateCache` 一并清包缓存。失败分型：**无 provider / provider 无 notice 方法（错误文案含「未知方法」）= NotSupported 静默**；其余 = Error 提示「公告加载失败」并回落旧缓存 |
| `src/Features/GameLauncher/GameBannerAndPost.xaml.cs` | 新增 `CurrentPack` 属性；`ReloadAsync` 按其非空与否走 `GetPackAsync` / 原 `GetAsync`。轮播计时、淡入、悬停缩放、跳转全部复用现有实现 |
| `src/Features/GameLauncher/LauncherPage.xaml(.cs)` | 新增 `CurrentPack` 可绑定属性（x:Bind OneWay）；`MainView_GameChanged` 里公告数据源随游戏切换（原来包游戏整个隐藏公告卡，现在放出来让它自己按数据显隐） |

行为要点：

- 换游戏即换数据源：`CurrentGameBiz`（库洛 CDN）+ `CurrentPack`（provider）一起赋值，直接赋值兜底 x:Bind 时机问题（沿用原注释的做法）
- 公告卡无数据（provider 无 notice / 网断 / 空内容）整卡自动隐藏，与库洛 B 服「官方不投放公告」同一表现
- 「显示游戏公告」设置开关、公告语言设置对包游戏同样生效（开关在 ReloadAsync 入口统一处理；语言由包自决：宿主把启动器语言 tag 与服变体码原样透传，终末地包据此决定通道与接口语言码，见第七节）

## 四、验证方式

- 包侧：上节真打命令（仓库目录下执行）；国际服多语言见第七节
- 宿主构建：`dotnet build src/Arietta.csproj -c Release` **0 错误**（2026-11-15 追加改动后重新构建仍 0 错误、51 个既有警告；先杀掉占用 Arietta.exe 的开发实例解文件锁）
- 部署副本：provider.py 已同步至 `Arietta/src/Arietta/games/arknights-endfield/` 并用 GamePackSign 重签（`valid · PaperKito`）
- 端到端目验（待用户）：Arietta 切到终末地 → 首页左下角出现轮播图 + 公告/新闻/资讯三组列表；点条目用系统浏览器打开 jump_url

## 五、已知待办

1. **并行会话正在编辑 `PackSettingsPage.xaml.cs`**（2026-11-15 00:31 仍在改动，报 `GamePackPage_GameRunning` 等半落地错误）：全量构建暂被其卡住，与本轮改动无关——本轮 4 文件在错误清单里零出现。等并行工作落地后再跑一次全量确认。
2. `RunProviderAsync` 靠错误文案含「未知方法」识别「包不支持公告」（provider 协议 error 只有 message 没有 code）——协议若加 `error.code` 换结构化判断。
3. ~~provider notice 的 language 固定 zh-cn；公告语言多语言（国际服）待接~~ **已完成（2026-11-15，见第七节）**：国际服走 gryphline 的 web/batch_proxy（实测与国服同构，不是 Yostar 的 operations/resource），语言跟随启动器；国服/B服仍固定 zh-cn。剩余：官方另投放 ru-ru / id-id / vi-vn / it-it，宿主语言下拉未列这些界面语言，故未进映射表（未识别一律回落 en-us）。
4. `get_sidebar`（社媒悬浮按钮）/ `get_main_bg_image`（启动器动态背景）接口存在且已实测（Collapse 调查交接），包侧未接——首页背景可走包 `assets.background`，社媒按钮宿主 UI 无对应槽位，均暂不做。
5. 仓库版 `signature.json` 落后于工作区（assets 半成品 + provider.py 变更，含 2026-11-15 国际服语言改动）：部署副本已重签可用（`valid · PaperKito`）；**仓库签名等 assets 收尾统一重签**，发布 zip 前必须 `verify` 通过。
6. 抽卡 `fetch` / 账号 `accounts` 的宿主消费端仍未写（与本轮同属 RunProviderAsync 的下游，最大块是 UGF 落库）。

## 六、勘误记录

- 归档交接文档状态表「更新/CDN ❌ 明确不做」系**表述错误**（2026-11-15 用户勘正）：用户从未决定不做，参照库 get_latest_game 实测可直接搬，正确口径是「未排期」。已改。

## 七、国际服公告语言跟随启动器语言（2026-11-15 追加）

### 需求与裁定

国际服（GL 变体）公告不能拿国服中文，也不该写死英文：要与 Arietta 启动器界面语言一致。
架构边界不变——宿主只把**通用上下文**（语言 tag + 服变体码）透传给包，端点 / appcode / 语言码映射全在 provider.py；换任何游戏包宿主一行不用改。

### 接口实测（2026-11-15 真打）

国际服公告与国服**同构**，仍是 `POST .../api/proxy/web/batch_proxy`（参照库 `EndfieldGlobalPresetConfig` 用的是 `HgLauncherApiNews`，不是 Yostar 的 `operations/resource`）：

| 服 | 端点 | appcode | channel/sub | seq | language |
|---|---|---|---|---|---|
| CN / BILI | `launcher.hypergryph.com/api/proxy/web/batch_proxy` | `6LL0KJuqHBVz33WK` | 1/1 | 5 | 只认 `zh-cn` |
| GL | `launcher.gryphline.com/api/proxy/web/batch_proxy` | `YDUTE5gscDZ229CW` | 6/6 | 3 | 见下表 |

- B 服自己的 channel 2/2 实测没有任何投放，继续沿用国服 1/1 的公告。
- `language` 必须是「语言-地区」小写码：`en` / `es-es` / `zz-zz` 都返回 200 但 banners/tabs 全空；国服给 `en-us` 同样全空。
- 实测有投放：`en-us` / `zh-cn` / `zh-tw` / `ja-jp` / `ko-kr` / `fr-fr` / `de-de` / `th-th` / `pt-br` / `es-mx`（西语是 **es-mx**，`es-es`、`es-419` 空）；官方另有 `ru-ru` / `id-id` / `vi-vn` / `it-it`，宿主语言下拉暂未列。
- tabName 随语言本地化（英文 Notices/Events/News、日文 お知らせ/キャンペーン/ニュース、繁中 公告/活動/新聞），直接透传做分组头。

### 实现

- 宿主 `GameNoticeService.GetPackAsync`：`notice` 请求带 `{lang, server}`；`lang = AnnouncementLanguageSettings.Selected`（设置页同一个下拉框写盘后立刻广播刷新，比 `UiLanguage.Current` 更早拿到新值），`server = pack.ServerId`（`servers[].code`，不透明）；缓存键 `<pack.Id>|<lang>|<server>`。协议文档已补 `notice` 方法行。
- 包 `provider.py`：`LAUNCHER_CHANNELS`（CN / GL）+ `NOTICE_LANG` 映射表；`notice_channel()` 按 server 选通道（未知码 / 旧宿主不传参 → 国服，行为不变），`notice_language()` 国服钉死 `zh-cn`、国际服按 tag 映射；映射不到或投放为空 → 回落 `en-us` 再试一次。
- 映射表：`zh-Hans→zh-cn`、`zh-Hant→zh-tw`、`en→en-us`、`ja→ja-jp`、`ko→ko-kr`、`fr→fr-fr`、`de→de-de`、`es→es-mx`、`th→th-th`、`pt-BR→pt-br`。

### 验证

```
echo '{"id":4,"method":"notice","params":{"lang":"ja","server":"GL"}}' | py -X utf8 provider.py
→ 9 张 banner + お知らせ/キャンペーン/ニュース，首条「特別スカウト「人煙の牽く天河」」
```

- 包侧真打 10 组：无 params / CN / BILI / GL×(en / ja / zh-Hant / zh-Hans / es / pt-BR / 未知) 全部 `ok:true`、9 张 banner，分组头与首条标题逐语言一致；未知语言回落英文生效。
- 宿主 `dotnet build src/Arietta.csproj -c Release` **0 错误**（51 个既有警告）；部署副本 provider.py 已同步 + 重签 `valid · PaperKito`。
- 端到端目验（待用户）：切到国际服 → 改设置页语言下拉 → 公告卡即时换成对应语言。
