# 森空岛 Wiki 图鉴图标抓取 · 交接

> 目标：拿终末地**干员（35）+ 武器（84）**的图鉴图标，国服 + 国际服多语言。
> 结论：**国服、国际服 wiki 图鉴接口全部匿名可调**（无需登录），国际服可通过 `sk-language` 头拿到内容语言；`zh_Hans` 国际服无内容（简中走国服）。
> **2026-11-17 修正**：内容语言不止四种——实测 **en / ja / ko / zh_Hant / ru_RU / th_TH** 六语全有内容；站方菜单里的 Indonesia / Tiếng Việt 只是 UI 语言，`id_ID` / `vi_VN` 内容回落英文（见 抽卡-社区账号耦合与四列自适应-交接.md §8.13）。语言码格式 `xx_XX`（裸 `ru`/`th` 会被拒）。
> 产出：`wiki_icons.py`（抓取脚本）+ `icons/wiki/`（图标）+ `assets/wiki-catalog/catalog-manifest.json`（跨服映射清单）。

---

## 1. 接口（还原自 wiki.skland.com / wiki.skport.com 前端）

| 项 | 国服 | 国际服 |
|---|---|---|
| API host | `https://zonai.skland.com` | `https://zonai.skport.com`（国内网络需代理，EdgeOne 地域拦截） |
| Referer | `https://wiki.skland.com/` | `https://wiki.skport.com/` |
| 图标 CDN | `bbs.hycdn.cn` | `static.skport.com` |
| 拿 token | `GET /web/v1/auth/refresh`（匿名） | 同左 |
| 图鉴目录 | `GET /web/v1/wiki/item/catalog?typeMainId=1&onlyOnline=true` | 同左 |
| 内容语言 | 不带 `sk-language`（默认 `zh_Hans`） | 带 `sk-language: en/ja/ko/zh_Hant` |

typeSub 分类：`1`=干员(35)、`2`=武器(84)、其余为装备/物品/任务等（国服 15 类、国际服 10 类）。

**重要细节**
- **必须带 `typeMainId=1`**：不带的话返回空壳目录（`code:0` 但 `items:[]`）。
- 连续快速请求会被**软限流**（code=0 但 items 空），脚本内已带重试 + cache-buster。
- UI 语言包只有 `en/ja/ko`（`assets.skport.com/i18n/sk-fe/skland-skport-wiki/locales/*.json`），但**内容语言**多一个 `zh_Hant`。
- 前端是同一套 SPA（`window.__CHIMERA_CONFIG__.name === "skland-skport-wiki"`），国服/国际服仅域名与 API host 不同——**切语言域名不变**，语言走请求头。

## 2. 签名算法（Web 端 platform=3，无需登录）

从前端 `vendor_src_libs-*.js` 的 `encodeParams` 还原：

```python
ts   = int(time.time())
msg  = path + (query or "") + str(ts) + json.dumps(
    {"platform": "3", "timestamp": str(ts), "dId": D_ID, "vName": "1.0.0"},
    separators=(",", ":"))          # 键序固定 platform/timestamp/dId/vName
sign = md5( hex( hmac_sha256(token, msg) ) ).hex()   # 先 HMAC-SHA256 转 hex，再对 hex 串 MD5
```

- `token` 来自 `/web/v1/auth/refresh`；**首次调用 refresh 时 token 用空串**，返回 `data.token`（匿名 token，长期稳定，实测两次请求返回同一个）。
- 必带头：`platform: 3`、`timestamp`、`dId`（32 位 hex，随便造一个即可）、`vName: 1.0.0`、`sign`、`Referer`、`Content-Type: application/json`。
- 与国服 App 端签名（`skland.py` 那套 HMAC→MD5）是**同一算法**，只是 payload 键序/取值和 token 来源不同（Web 匿名 vs App 登录）。

## 3. 数据结构要点（跨服对账）

每个 item：
```
itemId   服务端内不同（国服 2503 = 国际服 1279 都是明河/Argent Flow）
name     随 sk-language 本地化
lang     该 item 实际语言（zh_Hans/en/ja/ko/zh_Hant）
brief.cover    图标 URL（干员方形头像；武器图标）
brief.associate.id   ★ 跨服稳定 ID（两边完全一致，做映射键）
tagIds / subTypeList  职业/星级/属性标签（国际服和国服 tagId 体系一致）
```

→ **跨服映射用 `brief.associate.id`，不要用 itemId。** 清单 `catalog-manifest.json` 已按此键聚合：
```
{ associate_id: { "cn:operators:zh_Hans": {...}, "port:operators:en": {...}, ... } }
```

## 4. 产出文件

| 文件 | 说明 |
|---|---|
| `wiki_icons.py` | 抓取脚本。`--dry` 只出清单；`--langs en ja` 选国际服语言；代理由 `WIKI_PROXY` 环境变量控制（默认 `http://127.0.0.1:7897`，国际服国内网络必需） |
| `icons/wiki/cn/{operators,weapons}/zh_Hans/*.png` | 国服图标（直连） |
| `icons/wiki/port/{operators,weapons}/{en,ja,ko,zh_Hant}/*.png` | 国际服图标（走代理） |
| `assets/wiki-catalog/catalog-manifest.json` | 194 个实体 × 5 语言版本的名称/图标/URL 映射 |

命名：`{itemId}_{安全化名称}.png`。

## 5. 语言体系实测（切语言域名不变）

- 站点切换语言**只改请求，不改域名/URL**：语言走请求头 `sk-language`，存储在 localStorage 键 `SK_THEME_INFO`（`{"region": "zh_Hans"}` 等），写完强制刷新页面重新拉数据。
- 前端语言枚举共 14 种（`wiki-entry.js` 里的语言清单）：`zh_Hans / zh_Hant / de_DE / en / es_MX / fr_FR / id_ID / it_IT / ja / ko / pt_BR / ru_RU / th_TH / vi_VN`。
- **直连 API 实测**（同一 URL，仅换 `sk-language` 头）：

| sk-language | 干员 | 武器 | 示例（itemId 1279 = 明河） |
|---|---|---|---|
| `en` | 35 | 84 | Argent Flow |
| `ja` | 35 | 84 | ミンホ |
| `ko` | 35 | 84 | 명하 |
| `zh_Hant` | 35 | 84 | 明河（繁体词条） |
| `de_DE / fr_FR / es_MX / pt_BR / ru_RU / th_TH / vi_VN / id_ID / it_IT` | code:0 但 items 空 | 同 | — |
| `zh_Hans` | 空 | 空 | （简中内容只在国服） |

- 结论：**接口支持按枚举取任意语言，但 wiki 是社区共建**，其它语言目前没有词条内容，不是接口限制。多语言图标方案就用 en/ja/ko/zh_Hant + 国服 zh_Hans。
- UI 语言包（`assets.skport.com/i18n/sk-fe/skland-skport-wiki/locales/`）只有 `en/ja/ko` 三个文件，与内容语言是两回事。

## 6. 已知限制

- 国际服 `zh_Hans` 无内容；若要简中图标直接用国服的。
- 国际服线路依赖本机代理（7897 端口，Clash 类）；代理关闭时国际服抓取会失败，国服不受影响。
- 图标 URL 是 wiki CDN（`bbs.hycdn.cn` / `static.skport.com`），会随图鉴更新失效，需要时可重跑脚本。
- 森空岛 wiki 的图片链接无签名要求，但带 `Referer` 更稳。
