# 森空岛国际服（SKPORT 1.8.0）API 逆向 · 交接

> 目标：为 Arietta 的终末地游戏包摸清「森空岛国际服」的可用 API，判断能对齐国服 `skland.py` 的哪些能力。
> 样本：`SKPORT_1.8.0.apk`（包名 `com.gryphline.skport`，versionName 1.8.0，split APK，6 个 dex）。
> 结论：**国际服只有账号 + 社区 + 角色卡，没有国服的 签到 / 角色绑定 / 抽卡记录 / 终末地练度详情**。详见第 8 节。

---

## 1. 宿主与常量

| 项 | 值 | 证据 |
|---|---|---|
| 社区 / 游戏 API | `https://zonai.skport.com` | `Lcd8;->a()` 字面量 |
| 账号服务 API | `https://as.gryphline.com` | `Lh35;->i()` prod 分支 |
| 账号环境（测试） | `as-dev` / `as-staging` / `as-stable.gryphline.com` | `Lh35;->i()` |
| **appCode** | `6eb76d4e13aa36e6` | `Ll27;->h()` → `SKPortConfig(appCode=…)` |
| H5 用户中心 | `https://user.gryphline.com` | 协议页 / `pcSdk/userInfo` |
| 三方登录回调页 | `https://web-api.gryphline.com/callback/thirdPartyAuth.html` | |
| 静态资源 | `https://assets.skport.com/protocols/{lang}/…` | 协议/隐私政策 |

版本参数（UA 里要用）：`versionName=1.8.0`、`versionCode=100800014`、`minSdk=32`、`targetSdk=37`。
完整 UA 实测形态：`Skport/1.8.0 (com.gryphline.skport; build:100800014; Android 34; ) Okhttp/5.1.0`

`SKPortConfig` = `Lt3b;`，`toString()` 直接暴露 `SKPortConfig(appCode=…, env=…, language=…, uiMode=…)`。

> 别被 `6g74c7j9hfa5rbax0t1f9wav` 误导：它是 **EventLog 埋点 SDK 的 appId**（`Ltpd;->k()` → `Lbo3;->o(ctx,"sg",appId)`），与 API 鉴权无关。

---

## 2. 鉴权链路（国际服）

```
① 登录        POST https://as.gryphline.com/user/auth/v1/token_by_email_password
              body {"email","password","from"}
   → as_token

② 换 code     POST https://as.gryphline.com/user/oauth2/v2/grant
              body {"token": as_token, "type": 0, "appCode": "6eb76d4e13aa36e6"}
   → code

③ 换 cred     POST https://zonai.skport.com/api/v1/user/auth/generate_cred_by_code
              body {"kind": 1, "code": code}
   → { cred, token, userId }

④ token（签名密钥）
   优先用 ③ 返回的 token；也可 GET https://zonai.skport.com/api/v1/auth/refresh
   （header cred）→ { token }
```

- ③ 的 `kind` 固定 `1`：`login/b$d;->invokeSuspend` 里 `new CredRequest(1, code)`。
- `CredRequest` 只有两个字段：`kind: Int`、`code: String`。
- ② 的 `type` 固定 `0`（`Integer.valueOf(0)` 直接字面量）。
- 国际服**没有手机号登录**：只有 `/general/v1/send_email_code`，无 `send_phone_code`。
- 人机验证走极验 v4（`assets/gt4.js`、`libgtc4core.so`、`riskct.geetest.com`），失败文案「用户人机检验失败 / 用户取消人机检验」；相关字段 `captcha`、`verify_code_scene`。

---

## 3. 社区 API 请求头（zonai.skport.com）

来源：`Lqs4;->h(Request.Builder)`（HeaderInterceptor）。

| Header | 值 |
|---|---|
| `cred` | ③ 的 cred |
| `platform` | `"1"` |
| `dId` | `Settings.Secure.getString(cr,"android_id")` |
| `nId` | `"1"` |
| `rid` | 设备 rid（App 内部生成） |
| `vName` | versionName `1.8.0` |
| `vCode` | versionCode |
| `os` | `Build.VERSION.SDK_INT` 字符串 |
| `sk-language` | 本地化语言（先写 `zh-cn`，随后被覆盖为实际 locale） |
| `x-time-zone` | `ZoneId.systemDefault().getId()` |
| `manufacturer` | `Build.MANUFACTURER` |
| `Content-Type` | `application/json` |
| `User-Agent` | `Skport/{vName} (com.gryphline.skport; build:{vCode}; Android {SDK_INT}; ) Okhttp/5.1.0` |

---

## 4. 签名算法（zonai.skport.com）

来源：`Lv9c;`（SignInterceptor） + `Lt9c;`（HmacSHA256 / MD5 / hex）。

```python
ts   = int(time.time())            # 秒；App 用 currentTimeMillis()/1000 + 服务器时差
body = "" if method == "GET" else raw_query_or_body_text

payload = {
    "platform": "1",
    "timestamp": str(ts),
    "dId": android_id,
    "vName": "1.8.0",
}   # 顺序固定：platform, timestamp, dId, vName（Android org.json 用 LinkedHashMap，保序）

msg  = path + query_or_body + str(ts) + json.dumps(payload, separators=(",", ":"), ensure_ascii=False)
sign = md5(hmac_sha256(token, msg)).hex()       # ← 两层：先 HMAC 十六进制，再对十六进制串做 MD5
headers["timestamp"] = str(ts)
headers["sign"] = sign
```

细节（都来自 smali）：

- `e(req)` = `req.url().uri().getPath()` —— **只取 path，不含域名**。
- `f(req)`：若 method == `GET` → `uri.getRawQuery()`（无 query 则 `""`）；否则读 body 的 UTF-8 文本。
- `h()` 里的拼接顺序严格是 `path` → `query/body` → `timestamp` → `json`。
- `t9c.b(key,msg)` = `hex(hmac_sha256(key, msg))`（`%02x` 小写）。
- `t9c.c(s)` = `hex(md5(s))`（`%02x` 小写）。
- 401 且非「token 失效」错误时，会重试一次；收到业务码 `10000` / `10003` 会刷新 token 后重放。`token` 缓存 30s 内不重复刷新。

---

## 5. 账号 API 请求头（as.gryphline.com）

来源：`Lrs4;`（Interceptor），值全部 `URLEncoder.encode(v,"UTF-8")`，**只有 X-DeviceId 不编码**。

```
X-Language:    <lang>
X-DeviceModel: <Build.MODEL>
X-DeviceType:  "1"
X-OSVer:       <Build.VERSION.RELEASE>
X-DeviceId:    <device id>
```

账号 API **不签名**（无 timestamp/sign），体是 `Map` → JSON。

---

## 6. 账号接口全表（https://as.gryphline.com）

| 方法 | 路径 | 参数 |
|---|---|---|
| POST | `/user/auth/v1/token_by_email_password` | body `{email, password, from}` |
| POST | `/general/v1/send_email_code` | body `{email, type}` |
| POST | `/user/auth/v1/register` | body `{email, password, code, from, appCode}` |
| POST | `/user/auth/v1/forget_password` | body `{email, password, code}` |
| POST | `/user/auth/v1/token_by_third_party_token` | body（三方 token） |
| POST | `/user/oauth2/v2/grant` | body `{token, type:0, appCode}` |
| POST | `/user/oauth2/v1/can_unbind_grant` | body `{appCode, token}` |
| POST | `/user/oauth2/v1/request_unbind_grant` | body（解绑申请） |
| POST | `/user/oauth2/v1/cancel_unbind_grant` | body（撤销解绑） |
| POST | `/user/info/v1/send_email` | body |
| POST | `/user/info/v1/validate_email_code` | body |
| POST | `/user/info/v1/validate_third_party` | body |
| POST | `/user/info/v1/update_agreement_version` | body |
| POST | `/user/info/v1/cancel_deactivate` | body `{appCode, token}` |
| POST | `/third_party/v1/apple_login` | body |
| GET | `/app/v1/config` | `?appCode=&platform=` |
| GET | `/user/info/v1/basic` | `?token=` |
| GET | `/user/info/v1/third_party` | `?token=` |

接口类：`Lb35;`（19 个方法）。base 选择：`Lh35;->i()`。

---

## 7. 社区 / 游戏接口全表（https://zonai.skport.com）

> `@GET` = `Lcj4;`，`@POST` = `Lku8;`，`@Query` = `Lk5a;`，`@Body` = `Lmo0;`（注解名被混淆，需按此映射）。
> 下表已把 `Lmo0;`（body）与 `Lk5a;{value:...}`（query）解出。

### 7.1 登录 / 用户

| 方法 | 路径 | 参数 | 类 |
|---|---|---|---|
| POST | `/api/v1/user/auth/generate_cred_by_code` | body `{kind,code}` | `Ly07;->c` |
| POST | `/api/v1/user/auth/logout` | — | `Ly07;->d` |
| GET | `/api/v1/user/check` | — | `Ly07;->b` |
| GET | `/api/v1/user/unregistration/precheck` | — | `Ly07;->a` |
| POST | `/api/v1/user/policy/agree` | body | `Lc87;->a` |
| GET | `/api/v1/auth/refresh` | —（header `cred`） | `Lq9c;->a` |
| POST | `/api/v1/user/init` | body `UserInfoRequest` | `Lv8e;->g` |
| GET | `/api/v2/user` | `?id=` | `Lv8e;->s` |
| GET | `/api/v2/user` | — | `Le7;->a` |
| POST | `/api/v2/user/edit` | body `UserEditRequestBody` | `Lv8e;->u` |
| GET | `/api/v2/user/config` | `?userId=` | `Lv8e;->b` |
| POST | `/api/v2/user/privacy` | body `Privacy` | `Lv8e;->a` |
| POST | `/api/v2/user/config/push` | body `NotificationConfig` | `Lm1c;->e` |

### 7.2 角色卡 / 游戏（**模块重点**）

| 方法 | 路径 | 参数 | 类 |
|---|---|---|---|
| GET | `/api/v1/game/cards` | `?uid=&gameId=` | `Lv8e;->j` |
| GET | `/api/v1/game` | — | `Lyu4;->d` |
| GET | `/api/v1/game/endfield/statistic` | — | `Lg0f;->a` |

`gameId` 为 `Integer`，可空（不带 = 全部游戏）。

### 7.3 动态 / 内容

| 方法 | 路径 | 参数 |
|---|---|---|
| GET | `/api/v1/home/index` | `?gameId=&cateId=&sortType=&pageToken=&pageSize=&listId=` |
| GET | `/api/v1/feed/index` | `?pageSize=&pageToken=&listId=` |
| GET | `/api/v1/bulletins/list` | `?gameId=&cateId=` |
| GET | `/api/v1/item` | `?id=` |
| POST | `/api/v1/item/set` | body map |
| POST | `/api/v1/item/upd` | body `UpdRequest` |
| POST | `/api/v1/item/del` | body `PostDelete` |
| GET | `/api/v1/item/more` | `?pageToken=` |
| POST | `/api/v1/item/sub` | body `SubRequest` |
| POST | `/api/v1/item/translate` | body |
| POST | `/api/v1/item/top/pin` / `top/unpin` | body map |
| POST | `/api/v1/link/solve` | body `LinkSolveRequest` |

### 7.4 互动

| 方法 | 路径 | 参数 |
|---|---|---|
| POST | `/api/v1/action/item/like` / `cancel-like` | body map |
| POST | `/api/v1/action/item/collect` / `cancel-collect` | body map |
| GET | `/api/v1/action/collected-items` | `?userId=&pageToken=&pageSize=` |
| POST | `/api/v1/comment/submit` | body `SubmitComment` |
| POST | `/api/v1/comment/delete` / `like` / `cancel-like` / `pin` / `unpin` | body map |
| POST | `/api/v1/comment/translate` | body |
| GET | `/api/v1/comment/list-by-item` | 8 个 query（详见 smali `Ljg1;->e`） |
| GET | `/api/v1/comment/list-by-comment` | 7 个 query |
| GET | `/api/v1/comment/list-by-user` | `?userId=&pageToken=&pageSize=` |
| GET | `/api/v1/comment/pinned` | `?id=` |

### 7.5 用户关系 / 搜索 / 通知 / 其它

| 方法 | 路径 | 参数 |
|---|---|---|
| POST | `/api/v1/user-relation/follow` / `unfollow` / `block` / `unblock` | body map |
| POST | `/api/v1/user-relation/batch-follow` | body `FollowOfficialAccountRequest` |
| GET | `/api/v1/user-relation/list` | `?kind=&userId=&pageToken=&pageSize=` |
| GET | `/api/v1/user/items` | `?userId=&viewKind=&pageToken=&pageSize=` |
| GET | `/api/v1/user/item/browse-record` | `?pageSize=&pageToken=` |
| GET | `/api/v1/user/search` | `?keyword=&pageToken=&pageSize=` |
| GET | `/api/v1/user/recommend` | `?userId=&pageToken=&pageSize=` |
| GET | `/api/v1/user/recommend/official` | — |
| GET | `/api/v1/search/general` | `?keyword&…`（6 参） |
| GET | `/api/v1/search/guide` | `?keyword&…`（5 参） |
| GET | `/api/v1/search/user` | `?keyword=&pageToken=&pageSize=` |
| GET | `/api/v1/search/hot` / `/api/v1/search/tag` / `/api/v1/tag/hot/list` | — |
| GET | `/api/v1/notification/unread` | — |
| GET | `/api/v1/notification/list` / `brief/list` | `?pageToken=&pageSize=` |
| GET | `/api/v1/avatar/categories` | — |
| GET | `/api/v1/avatar/avatars-by-category` | `?userId=&categoryId=` |
| POST | `/api/v1/avatar/configure` | body map |
| GET | `/api/v1/pendant/all` | — |
| POST | `/api/v1/pendant/configure` | body |
| GET | `/api/v1/personal-center/resource` | — |
| GET | `/api/v1/sticker-category/list` | — |
| GET | `/api/v1/app/version` | — |
| GET | `/api/v2/video/external/get-by-url` | `?url=` |
| POST | `/api/v1/image/sts` | body `FetchRequest` |
| POST | `/api/v1/report/user` / `comment` / `item` | body |
| GET | `/api/v1/report/reason/list` | — |

### 7.6 版主（moderator，普通账号无权限，列全便于排除）

`/api/v2/moderator/item/del`、`/item/cate/adjust`、`/user/sanction`、`/user/sanction/revoke`、`/comment/del`、`/comment/mark`、`/api/v1/moderator/operation/log/waterfall`。

---

## 8. 与国服的差异（**做模块前必须知道**）

在 SKPORT 1.8.0 的 6 个 dex 里，全量字符串 + 全量 Retrofit 注解都扫过，**不存在**以下国服端点：

- `/api/v1/game/player/binding`（角色绑定）→ 0 命中
- `/api/v1/game/attendance`（签到）→ 0 命中
- `/api/v1/user/teenager` → 0 命中
- `/api/v1/game/endfield/card/detail`、`/card/war-echoes` → 0 命中
- 任何 `gacha` / 抽卡记录端点 → 0 命中

**因此国际服模块能做到的天花板：**

| 能力 | 国服（skland.py 现状） | 国际服 SKPORT |
|---|---|---|
| 邮箱登录 → cred → token | ✅（手机验证码） | ✅（邮箱密码；**无手机**） |
| 角色卡（等级/干员数/主线进度/秘书/注册时间…） | ✅ `/game/cards` 等 | ✅ `/api/v1/game/cards` |
| 终末地统计 | ✅ | ✅ `/api/v1/game/endfield/statistic` |
| 签到 | ✅ `/game/attendance` | ❌ 无端点 |
| 角色绑定列表 | ✅ `/game/player/binding` | ❌ |
| 终末地练度详情（危机/纪念碑/回响） | ✅ `/endfield/card/*` | ❌ |
| 抽卡记录 | ✅（独立 appCode） | ❌ |

> 国际服的「游戏数据」全部内嵌在 `/api/v1/game/cards` 的 `GameCardEntity` 里，没有二级详情接口。

### 8.1 对照 `skland.py` 五个面板的精确依赖

`skland.py` 的 `overview()` 一共只打 5 个端点，逐项核对 SKPORT 1.8.0（字符串池 126k + 注解 4043 类，双向确认）：

| 面板 / 用途 | 依赖端点 | SKPORT 命中 |
|---|---|---|
| 前置：角色绑定 → roleId/serverId | `GET /api/v1/game/player/binding` | **0** |
| 前置：森空岛 userId | `GET /api/v1/user/teenager` | **0** |
| 签到（读+写） | `GET/POST /web/v1/game/endfield/attendance` | **0** |
| 游戏数据 / 干员列表 | `GET /web/v1/game/endfield/card/detail` | **0** |
| 危机合约（`crisisContract`） | 同上 `card/detail` 的子对象 | **0** |
| 纪念碑（`indieHard`） | 同上 `card/detail` 的子对象 | **0** |
| 战争回响 | `GET /api/v1/game/endfield/card/war-echoes` | **0** |

国际服 `endfield` 相关路径**只有一条**：`/api/v1/game/endfield/statistic`。

**断链点在第一步**：拿不到 `roleId` / `serverId` / `userId`，后面 `card/detail` 就算服务端存在也调不了。
而且 `EndfieldGame` 数据类只有 `name / level / serverName / charCount / achievementCount / createdAtTs`，**没有 uid / roleId / serverId**（`ArknightsGame` 反倒有 `uid`）。客户端模型没有字段 ≠ 接口不返回（kotlinx 默认 ignoreUnknownKeys），但意味着 App 自己不做终末地练度面板。

---

## 9. 数据模型

```text
ApiResponse           (com.gryphline.skport.comm.network.core.ApiResponse)
  code: Int        // 0 = 成功；10000/10003 = token 相关
  message: String
  timestamp: String
  data: T
  isSuccessful()

CredResponse          (feature.login.impl.api.CredResponse)
  cred: String
  token: String
  userId: String

Token                 (middleware.networkext.sign.Token)
  token: String

GameCardEntity        (feature.user.impl.api.data.GameCardEntity)
  id, name, icon, bgUrl, link, gameChar, iconBorderColor, channelId
  privacy: GamePrivacy
  decoration: GameCardDecoration
  arknights: ArknightsGame      // 明日方舟卡
  endfield: EndfieldGame        // 终末地卡

ArknightsGame
  uid, name, level, serverName, charCnt, skinCnt, furnitureCnt,
  mainStageProgress, secretary{...}, exp{...}, ap{...}, avatar{...},
  registerTs, lastOnlineTs, storeTs, subscriptionEnd, resume

EndfieldGame
  name, level, serverName, charCount, achievementCount, createdAtTs
```

---

## 10. 参考实现（可直接接进模块）

```python
import hashlib, hmac, json, time, urllib.parse

AS_HOST   = "https://as.gryphline.com"
SK_HOST   = "https://zonai.skport.com"
APP_CODE  = "6eb76d4e13aa36e6"

def _hex(b: bytes) -> str:
    return "".join(f"{x:02x}" for x in b)

def _hmac_hex(key: str, msg: str) -> str:
    return _hex(hmac.new(key.encode(), msg.encode(), hashlib.sha256).digest())

def sign_headers(path: str, query_or_body: str, token: str, device: dict, ts: int) -> dict:
    payload = {                                  # 顺序必须一致
        "platform": "1",
        "timestamp": str(ts),
        "dId": device["dId"],
        "vName": device["vName"],
    }
    msg = path + query_or_body + str(ts) + json.dumps(payload, separators=(",", ":"), ensure_ascii=False)
    return {"timestamp": str(ts), "sign": _hex(hashlib.md5(_hmac_hex(token, msg).encode()).digest())}

def login(email: str, password: str, device: dict) -> dict:
    as_token = post(AS_HOST + "/user/auth/v1/token_by_email_password",
                    {"email": email, "password": password, "from": 1})["data"]["token"]
    code = post(AS_HOST + "/user/oauth2/v2/grant",
                {"token": as_token, "type": 0, "appCode": APP_CODE})["data"]["code"]
    return post(SK_HOST + "/api/v1/user/auth/generate_cred_by_code",
                {"kind": 1, "code": code})["data"]      # {cred, token, userId}
```

调用示例（角色卡）：

```python
q = f"uid={user_id}&gameId=2"
h = sign_headers("/api/v1/game/cards", q, cred["token"], device, int(time.time()))
# GET https://zonai.skport.com/api/v1/game/cards?uid=…&gameId=…  with headers: cred + h + 第 3 节全套
```

---

## 11. 取证路径与复现方式

样本解包在包目录之外：`Arietta-GamePacks/build-out/rea-skport/apk/`（base + arm64_v8a + zh + xxhdpi），dex 解到同目录 `dex/`。186MB，别移回包内（签名会哈希包内每个文件）。

因为 R8 把 **Retrofit 注解类也重命名了**（`retrofit2.http.GET` → `Lcj4;`、`@POST` → `Lku8;`、`@Query` → `Lk5a;`、`@Body` → `Lmo0;`），常规字符串搜索拿不到路径 —— 路径只存在于 `annotations_directory_item` 里，字节码中零引用（已用 `0x1a`/`0x1b` 穷举确认）。

产出物：

| 文件 | 内容 |
|---|---|
| `../build-out/rea-skport/dex/ann4.json` | 全部 4043 个类的方法注解（类型 + 元素） |
| `../build-out/rea-skport/dex/params.json` | 276 个类的参数注解（`@Query` 名） |
| `../build-out/rea-skport/dex/classdb.json` | 34455 个类的 const-string + 调用边 |
| `../build-out/rea-skport/all_strings.txt` | 6 个 dex 的完整字符串池（126k） |
| `../build-out/rea-skport/smali.txt` | 关键类反汇编（SignInterceptor / HeaderInterceptor / 账号 SDK / cred 调用点） |

工具链：`androguard 4.1.4`（注：`inspect_android_package` 需要 `REA_JADX_MCP_JAR`，本机未配置，且 GitHub 不可达无法下载 jadx；REA 的 `open_binary` 不接受 dex → 该分支走不通，改用 androguard 的 `DEX.CM` 对象模型）。

---

## 12. 联调验证状态（2026-11-15 本机实测）

**账号侧：已验证通过。**

```
GET https://as.gryphline.com/app/v1/config?appCode=6eb76d4e13aa36e6&platform=1
→ 200
{"data":{"agreementUrl":{...},"app":{"googleAndroidClientId":"373936584020-...(与 dex 内 Ljka; 一致)",
 "enableAutoLogin":true,"enableGuestRegister":false,"enablePayment":false,
 "displayName":{"de-de":"SKPORT","en-us":"SKPORT",...,"vi-vn":"SKPORT"...
```

即：**appCode `6eb76d4e13aa36e6` 有效**，`as.gryphline.com` + `/app/v1/config?appCode=&platform=` 路径完全正确。支持语言：de-de / en-us / es-mx / fr-fr / id-id / it-it / ja-jp / ko-kr / pt-br / ru-ru / th-th / vi-vn。

**社区侧：本机网络下无法验证（不是路径错）。**

| 探测 | 结果 |
|---|---|
| `zonai.skport.com/api/v1/game`（带全套客户端头） | 404，`Server: TencentEdgeOne` + SKPORT 404 页 |
| `zonai.skport.com/`（根路径、随机路径） | 同样 404 → 该 hostname 在此网络无任何路由 |
| `www.skport.com/`、`skport.com/` | 同样 404（同一张 404 页） |
| `assets.skport.com/assets/clear.css` | 200 |
| `as.gryphline.com/...` | 200 |

对照实验（证明路径风格没问题）：

```
GET https://zonai.skland.com/api/v1/game          → 200 {"code":0,"data":{"list":[{"game":{"gameId":1,"name":"明日方舟"...
GET https://zonai.skland.com/api/v1/app/version   → 401 {"code":10002,"message":"用户未登录"}
```

国服同族 hostname 匿名就返回业务 JSON，说明「`/api/v1/...` 直连根域」这个形态是对的；`skport.com` 主区（含 `zonai`）在国内网络被 EdgeOne 统一回落到 404（`assets` 子域没被封）。**社区侧要落地必须用境外网络或真机抓包复核一次**，重点确认三件事：① 路径前缀是否就是 `/api/v1/...`；② `cred` 为首个 header 时 `generate_cred_by_code` 是否直通；③ WAF 是否要求额外指纹（`Lkd8;->g()` 里专门上报 `waf_error_event`，说明 WAF 拦截是已知情况）。

> 顺带一提：`assets.skport.com/protocols/en-us/privacy.html` 会 302 到带签名的 OSS 错误 XML —— 协议页要走 `Lrs4`/`Ltpd` 那套 URL 签名，直接拼路径拿不到。

---

## 13. 参照仓库复核：谁有国际服的料

本地两份可直接对照的库（路径已实测，注意 `Hi3Helper.Plugin.Hypergryph-main` 在 `Endfield/` 子目录下，不在 `Github/` 根）：

### 13.1 `D:\Work\Github\Endfield\Hi3Helper.Plugin.Hypergryph-main`

**有国际服，但只在「启动器 + 公告」层，没有森空岛 API。** 全库 `skport` / `zonai` 零命中。

| 用途 | 国际服端点 |
|---|---|
| 终末地国际服公告 | `https://launcher.gryphline.com/api/proxy/batch_proxy` |
| 终末地国际服 Web 公告 | `https://launcher.gryphline.com/api/proxy/web/batch_proxy` |
| 终末地国际服官网 | `https://endfield.gryphline.com/` |
| 明日方舟国际服官网 | `https://www.arknights.global/` |
| Yostar 三服启动器 | `api-launcher-{en,jp,kr}.yo-star.com`、`arknights.jp`、`arknights.kr` |
| 国服对应 | `launcher.hypergryph.com`、`endfield.hypergryph.com`、`ak.hypergryph.com` |

对我们的价值：公告 provider 可以直接借 `launcher.gryphline.com` 这一层（`gryphline.com` 国内可通，已实测 `as.gryphline.com` 200）。

### 13.2 `D:\Work\Github\Endfield\nonebot-plugin-skland-master`（纯国服，但更全）

比我们的 `skland.py` 多出一整套 **`/web/v1/` 前缀端点**，且用的是**同一套 sign 签名**（`get_sign_header(cred, url, method)`）：

| 方法 | 路径 |
|---|---|
| POST | `https://zonai.skland.com/web/v1/game/endfield/attendance`（header `sk-game-role: 3_{roleId}_{serverId}`） |
| GET | `https://zonai.skland.com/web/v1/game/endfield/card/detail?roleId=&serverId=&userId=` |
| GET | `https://zonai.skland.com/web/v1/auth/refresh` |
| GET | `https://zonai.skland.com/web/v1/wiki/item/catalog?typeMainId=&typeSubId=` |

**推论（待验证）**：国服是 `/api/v1/*`（App）+ `/web/v1/*`（Web）双前缀同签名，国际服服务端很可能也挂了 `/web/v1/*`，只是 SKPORT App 没接。

等拿到境外网络，建议优先试：

```
POST https://zonai.skport.com/web/v1/game/endfield/attendance      (header sk-game-role: 3_{roleId}_{serverId})
GET  https://zonai.skport.com/web/v1/game/endfield/card/detail?roleId=&serverId=&userId=
```

如果这条通，**国际服模块就能拿到终末地练度详情，能力直接对齐国服**，不再是「只有角色卡」——这条比文档第 8 节的悲观结论优先级更高。注意国际服的 `gameId` 体系可能和国服（明日方舟=1、终末地=3）不一致，要先探 `/api/v1/game` 或 `/web/v1/...` 的枚举。

