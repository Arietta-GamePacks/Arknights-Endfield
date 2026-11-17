# 森空岛 Wiki 图鉴图标 · 归档（2026-11-16 终态）

> 归档时间：2026-11-16 23:00
> 状态：**抓取链路 + 运行时按需获取 + 宿主消费 全部实装**；抽卡界面头像已上线（缓存预热 22 张）。
> 过程记录见 `森空岛Wiki-图鉴图标抓取-交接.md`（接口逆向）与 `森空岛Wiki-图鉴图标运行时按需接入-交接.md`（接线细节），冲突时以本文件为准。

## 一、终态一句话

抽卡界面的干员/武器头像 = **运行时按需获取**：抽卡记录里出现什么名字，才从森空岛 Wiki 图鉴下载什么图标，缓存在宿主数据目录（`<data_dir>/gacha-icons/`），之后永远离线命中。包内零图库（调查期 141MB 批量产物已全部删除）。

## 二、数据链（全部在包内 `wiki_catalog.py`，宿主零游戏知识）

```
匹配键：抽卡记录 name（简中，strip 后与图鉴目录同名；官方名带前导空格的已处理）
  ① 宿主缓存  <data_dir>/gacha-icons/<安全化名称>.png   有效 PNG 直接用
  ② 包内离线索引  assets/wiki-catalog/catalog-manifest.json（name → bbs.hycdn.cn URL）
  ③ 在线刷新  GET zonai.skland.com/web/v1/wiki/item/catalog?typeMainId=1&onlyOnline=true
       （匿名 + Web 签名，platform=3；内存缓存 24h；偶发软限流 code:0 空 items 需重试）
  下载带 Referer: https://wiki.skland.com/   ← hycdn 拒绝其它 Referer（返回 304B HTML）
  任何一层失败 → icon=null → 宿主名称占位回落，绝不抛异常
```

签名（与 skland.py 的 App 端同源、Web 端参数不同）：
`msg = path + query + ts + JSON({"platform":"3","timestamp","dId","vName":"1.0.0"}, 紧凑)`；
`sign = md5(hex(hmac_sha256(token, msg)))`；token 由 `/web/v1/auth/refresh` 匿名获取（首次用空串签名）。

## 三、包侧（Arknights-Endfield 仓库）

| 文件 | 角色 |
|---|---|
| `wiki_catalog.py` | 运行时模块：`IconResolver.resolve_many`（6 并发下载，借鉴鸣潮 WutheringWavesTool）+ `resolve_cached`（只读盘，cache 模式专用） |
| `wiki_icons.py` | manifest 再生成工具（平时不用跑；国际服抓取需 `WIKI_PROXY`，默认 127.0.0.1:7897） |
| `assets/wiki-catalog/catalog-manifest.json` | 194 实体 × 5 语言索引；运行时只读 `cn:operators/weapons:zh_Hans`（干员 34 + 武器 84，缺的 1 个是「管理员 (男)」不进卡池） |
| `gacha.py` | `winui_model(icon_resolver=…)`：6★/5★ 历史行（跳过「已垫」）+ 物品卡补 `icon` 字段，批量解析 |
| `provider.py` | `_icon_resolver(params, allow_download)`：**mode=cache 只读缓存绝不联网**（「同步一律手动」红线）；手动「更新记录」后才允许下载 |

语言实测结论（备查）：国际服 `sk-language` 头支持 `en/ja/ko/zh_Hant` 有内容，其余语言枚举存在但社区未共建词条；`zh_Hans` 只在国服。国际服域名国内被 EdgeOne 拦截，走本机代理（7897）可通。

## 四、宿主侧（Arietta 仓库，已构建进运行实例）

`Features/GamePacks/PackGachaPage.xaml.cs` + `.xaml`：
- `PackBarItem` / `PackItemCard` 增 `IconPath`（读模型 `icon`）+ `Icon`（复用 `GachaLog.GachaIcon.FromFile`，DecodePixelWidth=160 解码缓存）；
- 6★/5★ 头像位：Image 盖在原占位底色上，无图露底色；物品卡：Image 铺格 + 有图藏名称（与鸣潮 GachaLogPage 一致）；
- 宿主调 `gacha-model` 已传 `data_dir`，图标缓存落 `<data_dir>/gacha-icons/`。

鸣潮方案对照（借鉴依据，源码 `D:\Work\Github\leck995_WutheringWavesTool`）：社区 `header.json`（id→URL）↔ 我们 manifest；`assets/header/<id>.png` skip-if-exists ↔ 同款；未命中显示名字 ↔ 同款。唯一差异：鸣潮按 `resource_id` 索引，终末地 UGF 的 `item_id` 与 wiki ID 不同体系，**name 是唯一可靠匹配键**。

## 五、部署与签名状态

- 部署副本已同步（provider.py / gacha.py / wiki_catalog.py / wiki_icons.py / manifest）并重签（PaperKito，2026-11-16 14:07）。
- 宿主 `Arietta.dll`（bin/x64/Debug，14:17 构建）已含 icon 消费代码，运行实例为新构建。
- **仓库 `signature.json` 仍按约定等 assets 半成品收尾统一重签。**

## 六、遗留 / 边界

1. 「寻访情报书」（抽卡副产物）图鉴无条目 → 名称占位，预期行为。
2. 非简中账号的 UGF 记录（meta.lang ≠ zh）名字匹配会 miss → 占位；要支持时按 `meta.lang` 选 `sk-language` 拉对应语言目录即可（机制已验证）。
3. 图鉴 CDN URL 会随图鉴改版失效：在线刷新层会补新地址；缓存里失效旧文件需手动清 `gacha-icons/`。
4. 图标下载发生在手动「更新记录」流程内；新抽到的卡池内容需同步一次才有图（打开页面不会自动补）。
