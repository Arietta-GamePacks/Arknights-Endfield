# 森空岛 Wiki 图鉴图标 · 运行时按需接入抽卡模块 · 交接

> 接续 `森空岛Wiki-图鉴图标抓取-交接.md`。Alpha 2026-11-16 定向：
> **图标只服务抽卡界面，抽到什么才获取什么**，不往包里塞图库；国际服多语言不再需要（国服简中一套就够）。
> 并按 Alpha 指示借鉴了鸣潮 WutheringWavesTool 的抽卡头像方案（本地源码 `D:\Work\Github\leck995_WutheringWavesTool`）。

---

## 1. 定向结论

- **删掉了批量图库** `icons/wiki/`（595 张 / 141MB，全部是调查期中间产物）。
- **运行时按需取图**：抽卡记录里出现什么名字，才下载什么图标，缓存在宿主数据目录。
- 图标来源只用**国服 zh_Hans**：简中走国服（直连、无代理），国际服的 en/ja/ko/zh_Hant 实测结论仍保留在上一份交接文档第 5 节备查。

## 2. 鸣潮方案对照（借鉴依据）

| 鸣潮 WutheringWavesTool | 我们 wiki_catalog.py | 说明 |
|---|---|---|
| 记录带 `resource_id`，图标按 id 索引 | 按 **name** 匹配 | 终末地 UGF 的 `item_id` 是游戏物品 id，与 wiki 目录的 itemId / associate.id 都不是一个体系；而记录里的 `name`（简中）与图鉴目录名完全一致（官方名带前导空格的已统一 strip），name 是当前唯一可靠匹配键 |
| 社区维护 `header.json`（id→URL）随程序分发 | 包内 `assets/wiki-catalog/catalog-manifest.json`（name→URL） | 我们的优势：manifest 由 `wiki_icons.py` 从官方接口生成，还能在线刷新 |
| `assets/header/<id>.png` 缓存、存在即跳过 | `<data_dir>/gacha-icons/<名称>.png`，`\x89PNG` 魔数校验后跳过 | 一致 |
| 缓存未命中 → 头像空着，显示名字 | icon=null → 宿主名称占位回落（NameVisibility） | 一致 |
| 缓存命中直接 `new Image(file)`，绝不联网 | cache 模式 `resolve_cached` 只读盘 | 一致 |
| 虚拟线程并发加载，不卡 UI | `resolve_many` 线程池并发下载（6 并发） | 已借鉴：10 张 0.5s |

## 3. 包内改动（三个文件）

### `wiki_catalog.py`（新增，运行时模块）

三层取图，逐层回落，任何失败返回 None、绝不抛异常打断统计页：

1. **宿主数据目录缓存** `<data_dir>/gacha-icons/<安全化名称>.png`（有效 PNG 直接用）
2. **包内离线索引** `assets/wiki-catalog/catalog-manifest.json`（name → bbs.hycdn.cn URL）
3. **在线刷新**：直连 `zonai.skland.com/web/v1/wiki/item/catalog`（匿名 + Web 签名，内存缓存 24h）——manifest 过期/图鉴新增条目时兜底

签名（与 skland.py 的 App 端同源、Web 端参数不同）：
```
msg  = path + query + ts + JSON({"platform":"3","timestamp","dId","vName":"1.0.0"}, 紧凑)
sign = md5(hex(hmac_sha256(token, msg)))     # 首次 refresh 用空 token 签名拿真 token
```
下载注意：**hycdn 拒绝别的 Referer**（带 `wiki.skport.com` 会返回 304 字节 HTML），必须用 `https://wiki.skland.com/` 或不带。

### `gacha.py`（winui_model）

- 新增参数 `icon_resolver=None`（回调或带 `resolve_many` 的对象）。
- 6★/5★ 历史行（`pools[].tabs[].items[]`，跳过「已垫」行）和右侧物品卡（`items[]`）补 `icon` 字段：本地文件路径 | None。
- 先收集全部出现过的名称 → `resolve_many` 批量并发 → 逐行填 icon。

### `provider.py`

- `_icon_resolver(params, allow_download)` 工厂：
  - `mode=cache`（打开页面，只读盘）：`resolve_cached` —— **绝不联网**（Alpha 钦定「同步一律手动」，与抽卡记录缓存同一条红线），缺图走名称占位；
  - 手动「更新记录」后：`resolve` / `resolve_many` —— 允许下载，图标落缓存后以后永远离线命中。
- demo 模式不解析（演示数据里一半是假名）。

## 4. manifest 修复（真实 bug）

`wiki_icons.py` 原来 `manifests.update(collect(...))` 两次调用**整体覆盖**：国服/国际服共用 `associate_id`，后收的一方把先收的冲掉了（cn:operators 全丢，cn:weapons 只剩 4 条）。已改为逐条目合并。重新生成后：
```
cn:operators:zh_Hans=34  cn:weapons:zh_Hans=84  （+ 国际服 4 语言备查）
```
干员差的那 1 个是「管理员 (男)」——玩家形象，不进卡池，无影响。

## 5. 部署副本

已同步 `provider.py / gacha.py / wiki_catalog.py / wiki_icons.py / assets/wiki-catalog/catalog-manifest.json` 到 `Arietta/src/Arietta/games/arknights-endfield/` 并重签（`PaperKito`）。仓库 `signature.json` 按约定仍等 assets 收尾统一重签。

## 6. 宿主侧接线（2026-11-16 补，Arietta 仓库）

首版只改了包侧，宿主没人消费 `icon` 字段 → **界面看不到图标**。已在 Arietta 宿主补上（`Features/GamePacks/PackGachaPage.xaml.cs` + `.xaml`）：

- `PackBarItem` / `PackItemCard` 新增 `IconPath`（读模型 `icon` 键）与 `Icon` 属性 —— 复用 `GachaLog.GachaIcon.FromFile`（DecodePixelWidth=160 解码缓存）。
- 6★/5★ 行头像位：Image 盖在原占位底色上（无图露出底色），物品卡：Image 铺满格子 + `NameVisibility`（有图藏名称，与鸣潮 GachaLogPage 一致）。
- 宿主调 `gacha-model` 时已传 `data_dir`（`PackCommunityPage.DataDir(_pack)`），provider 的图标缓存落在 `<data_dir>/gacha-icons/`。

**生效路径**：改完已 `dotnet build -c Release` 通过。用户侧第一次必须**手动点一次「更新记录」**——cache 模式（打开页面）按红线绝不联网，而图标缓存彼时还是空的；下载过一次之后，打开页面全部离线命中。

## 7. 遗留 / 边界

- 宿主侧（WinUI3 抽卡页）消费 `icon` 字段的渲染是否就绪，以宿主实现为准（模型侧已按契约给 `icon: null` 兜底）。
- `wiki_icons.py` 保留为 manifest 再生成工具（国际服抓取需 `WIKI_PROXY`，默认 `http://127.0.0.1:7897`）；平时不用跑，manifest 自带在线刷新兜底。
- 抽卡记录的 `name` 若为非简中账号语言（UGF 国际服导出），匹配会 miss → 名称占位，不报错。要支持国际服账号时再按 `meta.lang` 选 `sk-language` 取对应语言目录（机制已验证，见上份交接第 5 节）。
- 图鉴 CDN URL 会随图鉴改版失效；在线刷新层（24h TTL）会自动补新地址，缓存里失效的旧文件需手动清 `<data_dir>/gacha-icons/`。
