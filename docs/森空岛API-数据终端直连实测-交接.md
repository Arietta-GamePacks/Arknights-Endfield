# 森空岛 API · 数据终端直连实测交接

> 时间：2026-11-15 凌晨
> 性质：**真打验证通过**（用户提供的账号 token，本机 PC 直连），结论可直接用于后续包侧接入。
> 关联：`docs/游戏包-公告provider接入-交接.md`（launcher batch_proxy）、`provider.py`（鹰角账号链 + ef-webview 抽卡）。

## 一、要回答的问题

「干员详情这类东西不是要在森空岛 App 里看的吗，不逆向 App 能拿到？」

准确答案要拆成两件事：

| | 是否需要 App / root / 抓包 |
|---|---|
| **接口与字段的发现** | 需要。端点与 `data.chars` / `data.building` 等字段本来就来自 2023 年对森空岛 App 游戏数据页的抓包（`TyrantG/Skland_API` 开篇明写「基于森空岛 APP 中的游戏数据页面」）。本轮是**复用已公开的逆向成果**，不是跳过逆向。 |
| **接口的调用** | 不需要。知道端点 + 签名算法后就是标准 HTTPS + JSON，纯 PC。签名是软件算法，`dId` 可自造，服务端不校验真机。 |

现役旁证：`FrostN0v0/nonebot-plugin-skland` 靠 token 绑定即可渲染方舟干员 box / 肉鸽战绩 / 战争回响 / 终末地角色卡片 / 两游戏抽卡，不跑 App、不要求 root。

本轮实测把这条结论从「看别人代码」变成「本机打出来的 200」。

## 二、鉴权链（全在 PC，与包内 `provider.py` 是两套）

```
浏览器登录 user.hypergryph.com
  → web-api.hypergryph.com/account/info/hg 的 content = 鹰角账号 token
  → POST as.hypergryph.com/user/oauth2/v2/grant
       {"token": <token>, "appCode": "4ca99fa6b56cc2ba", "type": 0}
       → data.code
  → POST zonai.skland.com/api/v1/user/auth/generate_cred_by_code
       {"kind": 1, "code": <code>}
       → data.cred (32) + data.token (32，即签名密钥)
  → GET zonai.skland.com/...  头带 cred + sign + platform/timestamp/dId/vName
```

对照 `provider.py`：它用 `HG_APP_CODE = "be36d44aa36bfb5b"` / `type: 1` 换 u8_token，再打 `binding-api-account-prod` + `ef-webview.hypergryph.com`。**森空岛链的 appCode、type、后续域名全部不同**，不要混用常量。

### sign 算法（实测一次通过，无需校正）

```
ts    = 当前 Unix 秒 - 5        // 回拨避免「请勿修改设备时间」
four  = {"platform":"1", "timestamp": <ts>, "dId": <自造>, "vName":"1.0.1"}
str   = path + (GET 的 query 原串 / POST 的 body JSON 串) + ts
        + json.dumps(four, separators=(",", ":"))     // 四头顺序不可变
sign  = MD5( HMAC-SHA256(key = data.token, msg = str).hexdigest() 的头 )
```

- `path` 不含协议/域名/`?`；GET 的 query 是 `?` 后面的**原始字符串**，参数顺序参与签名，不要重排。
- `platform` / `dId` / `vName` 随便填，但要与发出去的头一致；四个头都必须带。
- `POST` 用 body JSON 串；终末地签到 `query_body=None` 时用空串。
- 变体兜底：若校验失败，HMAC 结果改走原始字节再 MD5（`--sign-variant raw`）。本轮 hex 变体直接通过。

## 三、实测结果（2026-11-15）

无凭证基线：`player/binding`、`player/info`、`user/check` 均返回
`HTTP 401 {"code":10002,"message":"用户未登录"}` —— 端点活着，缺的只是 cred + sign。

带凭证全流程：

| 步骤 | 端点 | 结果 |
|---|---|---|
| grant | `as.hypergryph.com/user/oauth2/v2/grant` | 200 / status 0 / 拿到 code |
| cred | `/api/v1/user/auth/generate_cred_by_code` | 200 / code 0 / cred 32 + 密钥 32 |
| 验 cred | `/api/v1/user/check` | 200 / code 0 |
| 角色列表 | `/api/v1/game/player/binding` | 200 / `data.list` 含 arknights + endfield |
| 方舟数据终端 | `/api/v1/game/player/info?uid=<方舟 uid>` | 200 / `data` 30 键 |
| 森空岛 userId | `/api/v1/user/teenager` | 200 / `data.teenager.userId` |
| 终末地角色卡 | `/web/v1/game/endfield/card/detail?roleId=…&serverId=…&userId=…` | 200 / `data.detail` |
| 终末地战争回响 | `/api/v1/game/endfield/card/war-echoes?<同上>` | 200 / `data.warEchoes` |

**方舟 `player/info` 实测字段**（这就是 App「数据终端」渲染用的那份 JSON）：
`data` 顶层 30 键 —— `currentTs / showConfig / status / medal / assistChars / chars / skins / building / recruit / campaign / tower / rogue / routine / activity` 等；
`chars` 219 项、`skins` 31 项、`assistChars` 2 项、`recruit` 4 项；`building` 含 `tiredChars/powers/manufactures/tradings/dormitories/meeting/hire/training/labor/furniture`；`status` 含 `uid/name/level/avatar/registerTs/mainStageProgress/secretary/resume/subscriptionEnd/ap`。

**终末地 `card/detail` 实测字段**：`data.detail` 含 `base / chars / achieve / spaceShip / domain / dungeon / bpSystem / dailyMission / weeklyMission / config / currentTs / quickaccess`。
**`war-echoes`**：`data.warEchoes` 含 `seasons / achieves / activity`。

### 关键差异（踩过的坑）

`game/player/info` **只认明日方舟 uid**。拿终末地 uid 去打会返回
`HTTP 404 {"code":10001,"message":"未找到已绑定的游戏账号信息"}`。
终末地必须走 `/web/v1/game/endfield/card/detail`，且要三个参数：

| 参数 | 来源 |
|---|---|
| `roleId` | `player/binding` → `appCode=endfield` → `bindingList[].roles[0].roleId` |
| `serverId` | 同上 `roles[0].serverId`（兜底 `channelMasterId`） |
| `userId` | `/api/v1/user/teenager` → `data.teenager.userId`（**不是**游戏 uid） |

`binding` 的终末地条目比方舟多一层 `roles[]` / `defaultRole`（方舟 `roles` 为空），写解析时别只按方舟结构取 `uid`。

## 四、其他端点（来自现役插件源码，本轮未逐一真打）

| 用途 | 端点 | 签名 |
|---|---|---|
| 方舟签到（**写**） | `POST /api/v1/game/attendance` | 是 |
| 终末地签到（**写**） | `POST /web/v1/game/endfield/attendance` + 头 `sk-game-role` | 是 |
| 方舟肉鸽战绩 | `GET /api/v1/game/arknights/rogue?uid=&targetUserId=&topicId=` | 是 |
| 终末地抽卡记录 | `GET ef-webview.hypergryph.com/api/record/{char\|weapon}` | **否**，走 token + server_id |
| 终末地卡池内容 | `GET ef-webview.hypergryph.com/api/content` | **否** |

即 `zonai.skland.com` 走 sign，`ef-webview.hypergryph.com` 走 query 里的 token —— 后者与包内 `provider.py` 的 fetch 链同源。

插件文档另提示：**仅用 cred 绑定无法查方舟抽卡 / 同步终末地抽卡记录**，需要原始鹰角 token。若要接抽卡，凭证要保留 token 而非只留 cred。

## 五、可复用工具

`D:/Work/Code Project/Arietta-GamePacks/build-out/skland_probe.py` —— **包外**（不进游戏包目录、不计入 `signature.json` 哈希）。标准库无依赖，覆盖上表全部只读步骤；**不含签到等任何写操作**。

```
set SKLAND_TOKEN=...   或把 token 存成 txt 用 --token-file
py -X utf8 ".../build-out/skland_probe.py" --token-file C:/path/token.txt --save result.json
```

默认只打印结构摘要不落盘；`--sign-variant raw` / `--ts-offset` 用于算法校正；`--raw` 打完整响应。

## 六、安全与待办

- 本轮 token 由用户在对话中提供，**未写入任何文件 / 文档 / 日志**。凭证等同登录态：建议用户测完重新登录使其失效，且不要在网页端点「退出登录 / 清理会话」（会清掉其它端会话）。
- 本文件位于包目录内，**仓库 `signature.json` 待 assets 收尾时统一重签**（沿用 `docs/游戏包-公告provider接入-交接.md` 的口径）。
- 若要落进包：按 AGENTS.md 红线，端点/appCode/字段映射全部放 `provider.py`（或包侧新模块），宿主零游戏知识；「数据终端」若做 UI，由包自己渲染，宿主只提供通用槽位。
- 未验：签到类写接口（不做）、`arknights/rogue`、`ef-webview` 抽卡在本轮凭证下的返回、cred/token 有效期与刷新策略、国际服口径。

## 七、参考

- `TyrantG/Skland_API`（2023，端点与字段文档，已停更）
- `U537/skyland-auto-sign`（sign 算法与四头顺序）
- `Joe-Bao/skland-daily-attendance`（token 获取路径）
- `FrostN0v0/nonebot-plugin-skland`（现役，终末地端点与 binding 结构解析）
