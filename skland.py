#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
森空岛（Skland）数据终端 —— 终末地游戏包的私有数据层。

**全部游戏知识都在这里**：端点、appCode、sign 算法、字段映射、官方 H5 链接。
宿主和 provider.py 只负责把方法名转发过来，不认识任何森空岛的东西。

链路（2026-11-15 真打验证，全程 HTTPS，不需要 App / root / 抓包）：
    鹰角账号 token
      → POST as.hypergryph.com/user/oauth2/v2/grant {appCode, type:0}  → code
      → POST zonai.skland.com/api/v1/user/auth/generate_cred_by_code    → cred + 签名密钥
      → GET  zonai.skland.com/... （cred + sign 头）
        /api/v1/game/player/binding                     绑定角色 → roleId / serverId
        /api/v1/user/teenager                          森空岛 userId（不是游戏 uid）
        /web/v1/game/endfield/card/detail              角色卡片（四个模块主数据）
        /api/v1/game/endfield/card/war-echoes          战争回响完整赛季
        /web/v1/game/endfield/attendance               签到日历（**只读 GET**）

sign = MD5( HMAC-SHA256(path + query + timestamp + 四头紧凑JSON, key=签名密钥).hexdigest() )
四头 platform / timestamp / dId / vName 参与签名，值可自造；query 拼接顺序必须原样保留。
时间戳回拨 5 秒，避开服务端的「请勿修改设备时间」校验。

**本模块不含任何写操作**：签到只读取日历状态，不代为签到。
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from typing import Any

import l10n  # 同包目录：用户可见文案翻译表（assets/l10n.json，语言来自 params.ui_lang）

AS_HOST = "https://as.hypergryph.com"
SK_HOST = "https://zonai.skland.com"
SKLAND_APP_CODE = "4ca99fa6b56cc2ba"  # 森空岛 OAuth；与 provider.py 的抽卡 appCode 不同

UA = ("Skland/1.0.1 (com.hypergryph.skland; build:100001014; Android 31; ) "
      "Okhttp/4.11.0")
PLATFORM = "1"
DID = "de9759a5afaa634f"
VNAME = "1.0.1"
TS_OFFSET = -5

# 通行证登录接口（as.hypergryph.com，免始空岛 sign）用的头
LOGIN_HEADERS = {"Origin": "https://ak.hypergryph.com",
                 "Referer": "https://ak.hypergryph.com/"}

CN_TZ = timezone(timedelta(hours=8))

# 官方 H5：从 game.skland.com 的 JS 路由表提取，逐个实测 HTTP 200
H5 = {
    "sign": "https://game.skland.com/endfield/sign-in?header=0",
    "crisis": "https://game.skland.com/endfield/game-data/crisis-contract?header=0",
    "monument": "https://game.skland.com/endfield/game-data/umbral-monument?header=0",
    "echoes": "https://game.skland.com/endfield/game-data/war-echoes?header=0",
    "overview": "https://game.skland.com/endfield/game-data?header=0",
    "home": "https://www.skland.com/",
}


class SklandError(Exception):
    """消息可直接展示给用户。"""


# ------------------------------------------------------------------ HTTP / 签名


def _request(url: str, body: dict | None = None,
             headers: dict | None = None, timeout: int = 20,
             method: str = "", raw_body: bytes | None = None) -> dict:
    data = None
    h = {"User-Agent": UA, "Accept": "application/json"}
    if raw_body is not None:
        data = raw_body
        h["Content-Type"] = "application/json;charset=UTF-8"
    elif body is not None:
        data = json.dumps(body, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        h["Content-Type"] = "application/json;charset=UTF-8"
    if headers:
        h.update(headers)
    req = urllib.request.Request(url, data=data, headers=h, method=method or None)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", errors="replace")
        try:
            payload = json.loads(raw)
        except Exception:
            raise SklandError(l10n.t("k.err.http", e.code, raw[:160]))
        raise SklandError(l10n.t("k.err.http", e.code, payload.get("message") or raw[:160]))
    except Exception as e:
        raise SklandError(l10n.t("err.network", f"{type(e).__name__}: {e}"))
    try:
        return json.loads(raw)
    except Exception:
        raise SklandError(l10n.t("k.err.notJson", raw[:160]))


def _login(token: str) -> tuple[str, str]:
    if not token:
        raise SklandError(l10n.t("k.err.noCred"))
    grant = _request(f"{AS_HOST}/user/oauth2/v2/grant",
                     {"token": token, "appCode": SKLAND_APP_CODE, "type": 0})
    code = str((grant.get("data") or {}).get("code") or "")
    if not code:
        raise SklandError(l10n.t("k.err.credInvalid"))
    cred_rsp = _request(f"{SK_HOST}/api/v1/user/auth/generate_cred_by_code",
                        {"kind": 1, "code": code})
    data = cred_rsp.get("data") or {}
    cred, secret = str(data.get("cred") or ""), str(data.get("token") or "")
    if cred_rsp.get("code") != 0 or not cred or not secret:
        raise SklandError(l10n.t("k.err.credExchange",
                                 cred_rsp.get("message") or l10n.t("k.err.apiChanged")))
    return cred, secret


def send_phone_code(phone: str, captcha: dict | None = None) -> dict:
    """
    鹰角通行证短信发码（as.hypergryph.com，免森空岛 sign）。

    type=2 是「登录验证码」。风控命中时服务端回 status=1 + 极验 v3 的
    gt/challenge，必须走完滑块后用 captcha 重发（字段名
    geetest_challenge / geetest_validate / geetest_seccode）。
    返回 {ok, message, needCaptcha?, gt?, challenge?, newCaptcha?}，不抛错。
    """
    body: dict[str, Any] = {"phone": phone, "type": 2}
    if captcha:
        body["captcha"] = captcha
    rsp = _request(f"{AS_HOST}/general/v1/send_phone_code", body, headers=LOGIN_HEADERS)
    status = rsp.get("status")
    if status == 0:
        return {"ok": True, "message": l10n.t("k.login.codeSent")}
    if status == 1:
        cap = (rsp.get("data") or {}).get("captcha") or {}
        return {"ok": False, "needCaptcha": True,
                "gt": str(cap.get("gt") or ""),
                "challenge": str(cap.get("challenge") or ""),
                "newCaptcha": bool(cap.get("new_captcha", True)),
                "message": l10n.t("k.login.needCaptcha")}
    return {"ok": False,
            "message": str(rsp.get("msg") or l10n.t("k.login.codeSendFailed", status))}


def token_by_phone_code(phone: str, code: str) -> str:
    """短信验证码换鹰角账号 token（与浏览器 content 拿到的同一物，凭证格式不变）。"""
    rsp = _request(f"{AS_HOST}/user/auth/v2/token_by_phone_code",
                   {"phone": phone, "code": code}, headers=LOGIN_HEADERS)
    if rsp.get("status") != 0:
        raise SklandError(str(rsp.get("msg") or l10n.t("k.login.failedStatus", rsp.get("status"))))
    token = str(((rsp.get("data") or {}).get("token")) or "")
    if not token:
        raise SklandError(l10n.t("k.login.noToken"))
    return token


def token_by_phone_password(phone: str, password: str) -> str:
    """手机号 + 密码换鹰角账号 token（与短信/扫码同物）。账号密码错误也回 200，看 status。"""
    rsp = _request(f"{AS_HOST}/user/auth/v1/token_by_phone_password",
                   {"phone": phone, "password": password}, headers=LOGIN_HEADERS)
    if rsp.get("status") != 0:
        raise SklandError(str(rsp.get("msg") or l10n.t("k.login.wrongPassword")))
    token = str(((rsp.get("data") or {}).get("token")) or "")
    if not token:
        raise SklandError(l10n.t("k.login.noToken"))
    return token


# scan_status 状态码 → 语义（0 已确认，换取 token；100 待扫；101 已扫待确认；102 已过期）
_SCAN_STATES = {0: "confirmed", 100: "pending", 101: "scanned", 102: "expired"}


def qrcode_login_create() -> dict:
    """
    创建扫码登录二维码（as.hypergryph.com，免 sign）。
    返回 {ok, scanId, url}；url 是手机 App 可识别的深链，交宿主渲染成二维码。
    失败返回 {ok: False, message}，不抛错。
    """
    rsp = _request(f"{AS_HOST}/general/v1/gen_scan/login",
                   {"appCode": SKLAND_APP_CODE}, headers=LOGIN_HEADERS)
    if rsp.get("status") != 0:
        return {"ok": False, "message": str(rsp.get("msg") or l10n.t("k.login.qrFailed"))}
    data = rsp.get("data") or {}
    scan_id = str(data.get("scanId") or "")
    if not scan_id:
        return {"ok": False, "message": str(rsp.get("msg") or l10n.t("k.login.qrFailed"))}
    url = str(data.get("scanUrl") or "") or \
        f"hypergryph://scan_login?scanId={urllib.parse.quote(scan_id)}"
    return {"ok": True, "scanId": scan_id, "url": url}


def qrcode_login_poll(scan_id: str) -> dict:
    """
    轮询扫码状态（免 sign）。pending/scanned 让宿主继续等；
    confirmed 时在包内直接换好 token，返回 {ok, state, credential}。
    接口级失败抛 SklandError（宿主当一次失败重试）。
    """
    q = urllib.parse.quote(scan_id or "")
    rsp = _request(f"{AS_HOST}/general/v1/scan_status?scanId={q}",
                   headers=LOGIN_HEADERS, method="GET")
    state = _SCAN_STATES.get(rsp.get("status"))
    if state is None:
        raise SklandError(str(rsp.get("msg") or l10n.t("k.login.qrPollFailed", rsp.get("status"))))
    if state != "confirmed":
        return {"ok": True, "state": state}
    scan_code = str((rsp.get("data") or {}).get("scanCode") or "")
    if not scan_code:
        raise SklandError(l10n.t("k.login.qrNoAuthCode"))
    tok = _request(f"{AS_HOST}/user/auth/v1/token_by_scan_code",
                   {"scanCode": scan_code}, headers=LOGIN_HEADERS)
    if tok.get("status") != 0:
        raise SklandError(str(tok.get("msg") or l10n.t("k.login.qrExchangeFailed")))
    token = str(((tok.get("data") or {}).get("token")) or "")
    if not token:
        raise SklandError(l10n.t("k.login.qrNoToken"))
    return {"ok": True, "state": "confirmed", "credential": token}


def _signed_get(path: str, query: str, cred: str, secret: str) -> dict:
    ts = str(int(time.time()) + TS_OFFSET)
    four = {"platform": PLATFORM, "timestamp": ts, "dId": DID, "vName": VNAME}
    four_json = json.dumps(four, separators=(",", ":"), ensure_ascii=False)
    mac = hmac.new(secret.encode("utf-8"),
                   (path + query + ts + four_json).encode("utf-8"),
                   hashlib.sha256)
    sign = hashlib.md5(mac.hexdigest().encode("utf-8")).hexdigest()
    headers = {**four, "cred": cred, "sign": sign}
    url = SK_HOST + path + ("?" + query if query else "")
    rsp = _request(url, headers=headers)
    if rsp.get("code") != 0:
        raise SklandError(l10n.t("k.err.sklandCode", rsp.get("code"),
                                 rsp.get("message") or l10n.t("k.err.unknown")))
    return rsp.get("data") or {}


def _signed_post(path: str, body: str, cred: str, secret: str,
                 extra_headers: dict | None = None) -> dict:
    """POST 签名：sign 串里的 query 槽位用 body JSON 串（无 body 用空串，见交接文档第二节）。"""
    ts = str(int(time.time()) + TS_OFFSET)
    four = {"platform": PLATFORM, "timestamp": ts, "dId": DID, "vName": VNAME}
    four_json = json.dumps(four, separators=(",", ":"), ensure_ascii=False)
    mac = hmac.new(secret.encode("utf-8"),
                   (path + body + ts + four_json).encode("utf-8"), hashlib.sha256)
    sign = hashlib.md5(mac.hexdigest().encode("utf-8")).hexdigest()
    headers = {**four, "cred": cred, "sign": sign, **(extra_headers or {})}
    rsp = _request(SK_HOST + path, headers=headers, method="POST",
                   raw_body=body.encode("utf-8") if body else b"")
    if rsp.get("code") != 0:
        raise SklandError(l10n.t("k.err.sklandCode", rsp.get("code"),
                                 rsp.get("message") or l10n.t("k.err.unknown")))
    return rsp.get("data") or {}


def _binding_q(cred: str, secret: str) -> tuple[str, str, str]:
    """binding + teenager → (签名 query 串, roleId, serverId)。overview 与 sign_in 共用。

    注意：终末地的**游戏 UID 就是 roleId**（App 个人主页显示的那个 9~10 位数字）；
    `bindingList[].uid` 是鹰角通行证账号级 uid（和明日方舟共用同一个数字），别拿它当终末地 UID。
    """
    binding = _signed_get("/api/v1/game/player/binding", "", cred, secret)
    app = next((a for a in _as_list(binding.get("list"))
                if _as_dict(a).get("appCode") == "endfield"), None)
    if app is None:
        raise SklandError(l10n.t("k.err.noRole"))
    entries = _as_list(_as_dict(app).get("bindingList"))
    bound = _as_dict(entries[0]) if entries else {}
    roles = _as_list(bound.get("roles"))
    role = _as_dict(roles[0]) if roles else {}
    role_id = str(role.get("roleId") or "").strip()
    server_id = str(role.get("serverId") or bound.get("channelMasterId") or "").strip()
    if not role_id:
        raise SklandError(l10n.t("k.err.noRoleId"))
    teenager = _signed_get("/api/v1/user/teenager", "", cred, secret)
    user_id = str(_as_dict(teenager.get("teenager")).get("userId") or "").strip()
    if not user_id:
        raise SklandError(l10n.t("k.err.noUserId"))
    # 顺序参与签名，不要重排
    q = (f"roleId={urllib.parse.quote(role_id)}"
         f"&serverId={urllib.parse.quote(server_id)}"
         f"&userId={urllib.parse.quote(user_id)}")
    return q, role_id, server_id


def _calendar_signed(att: dict) -> bool:
    """日历口径的「今天已签」：available==0 且 done>0。
    hasToday 签到后是 True，语义反直觉，别单独用它（2026-11-15 真打校准）。"""
    calendar = _as_list(att.get("calendar"))
    done = sum(1 for x in calendar if _as_dict(x).get("done") is True)
    available = sum(1 for x in calendar if _as_dict(x).get("available") is True)
    return available == 0 and done > 0


def sign_in(token: str) -> dict:
    """每日签到（**写操作**）：POST /web/v1/game/endfield/attendance。

    头 sk-game-role = "3_<roleId>_<serverId>"（nonebot-plugin-skland 同款，缺 serverId 会 400）。
    返回 {ok, message} 供宿主直接弹提示。
    官方回「已签过」不直接算成功：2026-11-17 实测跨零点时端点的「已签过」与日历的「今天」
    边界错位（端点说已签、日历当天的格子还是 available），宿主会把当天记成已做、锁死整天
    漏签。所以先 GET 日历核实，日历确认才 ok=True；错位时 ok=False 让宿主下次触发自动补。
    """
    cred, secret = _login(token)
    q, role_id, server_id = _binding_q(cred, secret)
    game_role = f"3_{role_id}_{server_id}"

    def already_signed() -> bool:
        return _calendar_signed(_signed_get("/web/v1/game/endfield/attendance", q, cred, secret))

    try:
        _signed_post("/web/v1/game/endfield/attendance", "", cred, secret,
                     extra_headers={"sk-game-role": game_role})
        return {"ok": True, "message": l10n.t("k.sign.success")}
    except SklandError as e:
        msg = str(e)
        if "已签" in msg or "重复" in msg or "已领取" in msg:
            return ({"ok": True, "message": l10n.t("k.sign.already")} if already_signed()
                    else {"ok": False, "message": l10n.t("k.sign.mismatch")})
        # 兜底：有的口径要求空 JSON 对象体，重试一次
        try:
            _signed_post("/web/v1/game/endfield/attendance", "{}", cred, secret,
                         extra_headers={"sk-game-role": game_role})
            return {"ok": True, "message": l10n.t("k.sign.success")}
        except SklandError as e2:
            msg2 = str(e2)
            if "已签" in msg2 or "重复" in msg2 or "已领取" in msg2:
                return ({"ok": True, "message": l10n.t("k.sign.already")} if already_signed()
                        else {"ok": False, "message": l10n.t("k.sign.mismatch")})
            raise SklandError(msg2 if msg2 != msg else msg) from e2


def web_terminal(token: str) -> dict:
    """官方 H5 数据终端（game.skland.com/endfield/game-data）的打开参数。

    H5 的 App 内嵌机制（2026-11-17 从页面 JS bundle 逆向，entry_index / vendor_sk_bridge）：
      - UA 含 `skland/<版本>` + `android` → 页面判定 App 流（裸开是下载引导墙，等价未登录）
      - 桥协议（AndroidNative）：页面调 window.<SK目标>.<method>(params, callbackId)，
        **第二参是 callbackId 字符串不是函数**；应答必须经原生回调通道
        window.skland.callBack(callbackId, JSON串) 送回（ABaseNative 构造时注册），
        页面侧 JSON.parse 后 resolve，15s 不回即 bridge.call timeout。
      - SKPage.userInfo 回 {code:0, cred}（页面只取 cred 一个字段），其余 SK* 回 {code:0}
      - 签名四头与会话 token 页面自己算、自己经 /web/v1/auth/refresh 续，宿主只需喂 cred
      - 布局判定：页面 try{IS_PC=!createEvent('TouchEvent')}catch{IS_PC=!0}，无触屏桌面内核
        必抛异常 → PC 布局；注入脚本垫一层 createEvent 让 TouchEvent 返回普通事件对象，
        页面即按手机布局渲染（窗口 620 物理px ÷ 150% DPI = 413 CSS px，本就是手机宽度）
    cred 与 overview() 同源（_login），数据端点也同源（zonai /web/v1/...）。
    返回宿主通用 webWindow 形状：{ok, webWindow:{title, url, ua, script}}。
    """
    cred, _secret = _login(token)
    # 版本号要 ≥ 桥目标的最低版本门（environmentInfo 2.0.0 / openAuthenticationPage 1.28.0）
    ua = ("Mozilla/5.0 (Linux; Android 13; 23049RAD8C Build/TQ3A.230805.001; wv) "
          "AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/124.0.0.0 Mobile "
          "Safari/537.36 skland/2.4.0")
    targets = ["SKPage", "SKEnvironment", "SKNavigation", "SKModal", "SKMessage",
               "SKHandle", "SKShare", "SKPermission", "SKNetwork", "SKGame"]
    script = (
        # 垫一层 createEvent：无触屏的桌面内核里 createEvent('TouchEvent') 抛异常
        # （IAB 实测 "The provided event type ('TouchEvent') is invalid"），页面
        # try{IS_PC=!createEvent('TouchEvent')}catch{IS_PC=!0} 就判成 PC 走 PC 紧凑布局
        # ——手机窗口里看就是「缩小版 PC 页」（2026-11-17 首打截图 p1 vs App p2 的差异）。
        # 返回一个普通事件对象凑过真值检查，页面即按手机布局渲染。必须在页面脚本前执行。
        "(() => {\n"
        "  const orig = document.createEvent.bind(document);\n"
        "  document.createEvent = function (type) {\n"
        "    if (String(type).toLowerCase() === 'touchevent') { return orig('Event'); }\n"
        "    return orig(type);\n"
        "  };\n"
        "})();\n"
        # 桥 + 跳转语义：App 流里「全部/更多」这类入口不走页面内路由，而是经桥
        # （schema$2：http 网址包成 skland://web?url=<encodeURIComponent>）让 App 开内嵌
        # 子页；假桥只回 {code:0} 就表现为「点了没反应」（2026-11-17 三打反馈）。
        # 这里解码深链：同源子页直接整页跳（注入脚本随文档重装，登录态不掉），外域交系统浏览器。
        "(() => {\n"
        "  const CRED = %s;\n"
        "  const body = (extra) => JSON.stringify(Object.assign({ code: 0 }, extra || {}));\n"
        "  const jump = (raw) => {\n"
        "    let url = String(raw || '');\n"
        "    const wrap = 'skland://web?url=';\n"
        "    if (url.startsWith(wrap)) { try { url = decodeURIComponent(url.slice(wrap.length)); } catch {} }\n"
        "    if (!/^https?:\\/\\//.test(url)) { return; }\n"
        "    if (url.startsWith(location.origin)) { location.assign(url); }\n"
        "    else { window.open(url, '_blank'); }\n"
        "  };\n"
        "  const send = (id, text, tries) => {\n"
        "    const f = window.skland && window.skland.callBack;\n"
        "    if (f) { f(id, text); return; }\n"
        "    if (tries > 0) { setTimeout(() => send(id, text, tries - 1), 50); }\n"
        "  };\n"
        "  const handle = (t, m, p, id) => {\n"
        "    let obj = null;\n"
        "    try { obj = typeof p === 'string' && p.charAt(0) === '{' ? JSON.parse(p) : null; } catch {}\n"
        "    let extra = null;\n"
        "    if (t === 'SKPage' && m === 'userInfo') { extra = { cred: CRED }; }\n"
        # pageInfo 必须带全字段：页面拿到 code==0 后算 top = Math.max(top, status_bar_height)，
        # undefined 参与就是 NaN，NaN 样式被 React 丢弃 → 粘性标签栏和标题栏叠在一起
        # （2026-11-17 四打：影拓丰碑详情页顶部切换被标题栏挡住）。形状照抄页面自己的
        # web 兜底（init_web$8 的 getPageInfo），页面对它有现成处理路径。
        "    if (t === 'SKPage' && m === 'pageInfo') { extra = {\n"
        "      screen_width: window.innerWidth, screen_height: window.innerHeight,\n"
        "      has_navigation_bar: false, navigation_bar_height: 0,\n"
        "      status_bar_height: 0, top: 0, left: 0, bottom: 0, right: 0 };\n"
        "    }\n"
        "    if (t === 'SKNavigation' && m === 'openURL' && obj && obj.url) { jump(obj.url); }\n"
        "    if (t === 'SKNavigation' && m === 'dispatch' && typeof p === 'string') { jump(p); }\n"
        "    if (t === 'SKPage' && m === 'pop') { try { history.length > 1 && history.back(); } catch {} }\n"
        "    send(id, body(extra), 20);\n"
        "  };\n"
        "  for (const t of %s) {\n"
        "    window[t] = new Proxy({}, { get: (_o, m) => typeof m === 'symbol' ? undefined :\n"
        "      (p, id) => handle(t, m, p, id) });\n"
        "  }\n"
        "})();\n"
    ) % (json.dumps(cred), json.dumps(targets))
    return {
        "ok": True,
        "webWindow": {"title": l10n.t("menu.gamedata"), "url": H5["overview"], "ua": ua, "script": script},
    }


# ------------------------------------------------------------------ 小工具


def _num(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _ts(value: Any) -> str:
    try:
        n = int(str(value).strip())
    except (TypeError, ValueError):
        return ""
    if n <= 0:
        return ""
    try:
        return datetime.fromtimestamp(n, tz=CN_TZ).strftime("%Y-%m-%d %H:%M")
    except (OSError, OverflowError, ValueError):
        return ""


def _card(label: str, value: Any, hint: str = "", tone: str = "") -> dict:
    return {"label": label, "value": str(value), "hint": hint, "tone": tone}


def _row(label: str, value: Any, tone: str = "", icon: str = "") -> dict:
    row = {"label": str(label), "value": str(value), "tone": tone}
    if icon:
        row["icon"] = icon
    return row


def _as_list(value: Any) -> list:
    return value if isinstance(value, list) else []


def _as_dict(value: Any) -> dict:
    return value if isinstance(value, dict) else {}


# ------------------------------------------------------------------ 各模块映射


def _module_sign(att: dict, detail: dict) -> dict:
    """每日签到：日历 + 额外奖励 + 状态；立即签到/自动签到由宿主通用渲染（写接口见 sign_in）。"""
    calendar = _as_list(att.get("calendar"))
    first = _as_list(att.get("first"))
    resource = _as_dict(att.get("resourceInfoMap"))
    done = sum(1 for x in calendar if _as_dict(x).get("done") is True)
    available = sum(1 for x in calendar if _as_dict(x).get("available") is True)
    has_today = bool(att.get("hasToday"))

    def award_info(award_id: Any) -> dict:
        aid = str(award_id or "")
        for key in (aid, aid.split("_")[-1], "_".join(aid.split("_")[-2:])):
            info = _as_dict(resource.get(key))
            if info:
                return info
        return {}

    def award_name(award_id: Any) -> str:
        info = award_info(award_id)
        name = str(info.get("name") or info.get("itemName") or "")
        if name:
            return name
        aid = str(award_id or "")
        return aid.rsplit("_", 1)[-1] if aid else l10n.t("k.sign.awardFallback")

    days = []
    for i, item in enumerate(calendar, 1):
        d = _as_dict(item)
        info = award_info(d.get("awardId"))
        days.append({
            "day": i,
            "award": award_name(d.get("awardId")),
            "icon": str(info.get("icon") or ""),
            "done": bool(d.get("done")),
            "available": bool(d.get("available")),
        })

    # 状态语义（2026-11-15 真打校准）：available = 今日待领格；签完它清零、hasToday 翻 True。
    # 用 available==0 且 done>0 判「已签」，别用 hasToday 单独判（它签到后是 True，语义和直觉相反）。
    signed_today = available == 0 and done > 0
    return {
        "title": l10n.t("k.sign.title"), "icon": "sign",
        "calendar": days,
        "header": {
            "status": {"text": l10n.t("k.sign.already") if signed_today else l10n.t("k.sign.notSigned"),
                       "tone": "" if signed_today else "good"},
            "progress": l10n.t("k.sign.progress", done, len(calendar)),
            "extra": {"label": l10n.t("k.sign.extra"), "items": [
                {"name": award_name(x.get("awardId")),
                 "icon": str(award_info(x.get("awardId")).get("icon") or ""),
                 "done": bool(x.get("done")),
                 "available": bool(x.get("available"))}
                for x in (_as_dict(v) for v in first)
            ]},
            "toggles": [{"id": "auto", "label": l10n.t("k.sign.auto")}],
            "actions": [{"id": "signin", "label": l10n.t("k.sign.now"),
                         "disabled": signed_today}],
        },
    }


def _module_crisis(detail: dict) -> dict:
    items = _as_list(detail.get("crisisContract"))
    cards: list[dict] = []
    blocks: list[dict] = []
    for it in items:
        c = _as_dict(it)
        ach = _as_dict(_as_dict(c.get("achieve")).get("achievementData"))
        weekly = _as_dict(c.get("weeklyMission"))
        indicator = _as_dict(c.get("indicatorMission"))
        stage = _as_dict(c.get("stageMission"))
        cards.extend([
            _card(l10n.t("k.crisis.highest"), _num(c.get("highest")), l10n.t("k.crisis.current")),
            _card(l10n.t("k.crisis.challenges"), _num(c.get("challengeCount"))),
            _card(l10n.t("k.crisis.weekly"), f"{_num(weekly.get('count'))} / {_num(weekly.get('total'))}"),
            _card(l10n.t("k.crisis.indicator"), f"{_num(indicator.get('count'))} / {_num(indicator.get('total'))}"),
            _card(l10n.t("stage"), f"{_num(stage.get('count'))} / {_num(stage.get('total'))}"),
        ])
        blocks.append({
            "title": str(c.get("name") or l10n.t("k.crisis.current")),
            "rows": [
                _row(l10n.t("k.crisis.start"), _ts(c.get("startAtTs")) or "—"),
                _row(l10n.t("k.crisis.end"), _ts(c.get("endAtTs")) or "—"),
                _row(l10n.t("k.crisis.gameplayEnd"), _ts(c.get("gameplayEndAtTs")) or "—"),
                _row(l10n.t("k.crisis.medal"), str(ach.get("name") or "—")),
                _row(l10n.t("k.crisis.medalLevel"), _num(_as_dict(c.get("achieve")).get("level"))),
                _row(l10n.t("k.crisis.plateCert"),
                     f"{l10n.t('yes') if _as_dict(c.get('achieve')).get('isPlated') else l10n.t('no')} / "
                     f"{l10n.t('yes') if ach.get('canCertify') else l10n.t('no')}"),
            ],
            "bars": [
                {"label": l10n.t("k.crisis.weeklyShort"), "value": _num(weekly.get("count")), "total": _num(weekly.get("total"))},
                {"label": l10n.t("k.crisis.indicatorShort"), "value": _num(indicator.get("count")), "total": _num(indicator.get("total"))},
                {"label": l10n.t("stage"), "value": _num(stage.get("count")), "total": _num(stage.get("total"))},
            ],
        })
    if not items:
        cards.append(_card(l10n.t("k.crisis.current"), l10n.t("none"), l10n.t("k.crisis.noData"), "muted"))
        blocks.append({"title": l10n.t("k.crisis.current"), "rows": [_row(l10n.t("k.crisis.status"), l10n.t("k.crisis.closed"))]})
    return {
        "title": l10n.t("k.crisis.title"), "icon": "data", "h5": H5["crisis"],
        "cards": cards, "blocks": blocks,
        "note": l10n.t("k.crisis.note"),
    }


def _module_monument(detail: dict) -> dict:
    groups = _as_list(_as_dict(detail.get("indieHard")).get("indieHardGroups"))
    normal_done = hard_done = total = 0
    blocks: list[dict] = []
    for g in groups:
        gd = _as_dict(g)
        rows = []
        for dg in _as_list(gd.get("dungeonGroups")):
            pair = _as_dict(dg)
            normal = _as_dict(pair.get("normalDungeon"))
            hard = _as_dict(pair.get("hardDungeon"))
            total += 1
            npass, hpass = bool(normal.get("isPass")), bool(hard.get("isPass"))
            normal_done += int(npass)
            hard_done += int(hpass)
            rows.append(_row(
                str(normal.get("name") or hard.get("name") or l10n.t("stage")),
                (f"{l10n.t('k.mon.normal')} ✓" if npass else f"{l10n.t('k.mon.normal')} ✗")
                + " · " + (f"{l10n.t('k.mon.hard')} ✓" if hpass else f"{l10n.t('k.mon.hard')} ✗"),
                "good" if (npass and hpass) else ("muted" if not npass else ""),
            ))
        blocks.append({
            "title": str(gd.get("name") or l10n.t("k.mon.series")),
            "rows": rows or [_row(l10n.t("none"), l10n.t("k.mon.seriesNoData"))],
        })
    cards = [
        _card(l10n.t("k.mon.series"), len(groups)),
        _card(l10n.t("stage"), total),
        _card(l10n.t("k.mon.normalDone"), f"{normal_done} / {total}", "", "good" if normal_done else ""),
        _card(l10n.t("k.mon.hardDone"), f"{hard_done} / {total}", "", "good" if hard_done else "muted"),
    ]
    if not groups:
        blocks.append({"title": l10n.t("k.mon.title"), "rows": [_row(l10n.t("k.crisis.status"), l10n.t("k.mon.noGroups"))]})
    return {
        "title": l10n.t("k.mon.title"), "icon": "data", "h5": H5["monument"],
        "cards": cards, "blocks": blocks,
        "note": l10n.t("k.mon.note"),
    }


def _module_echoes(detail: dict, war: dict) -> dict:
    # 完整赛季优先用独立接口，缺字段时回落 card/detail 里的摘要
    seasons = _as_list(war.get("seasons")) or _as_list(
        _as_dict(detail.get("warEchoes")).get("seasons"))
    achieves = _as_list(war.get("achieves"))
    activity = _as_dict(war.get("activity"))
    best = war.get("bestRecord") or _as_dict(detail.get("warEchoes")).get("bestRecord")

    total_stars = sum(_num(_as_dict(s).get("stars")) for s in seasons)
    cards = [
        _card(l10n.t("k.echo.seasons"), len(seasons)),
        _card(l10n.t("k.echo.totalStars"), total_stars),
        _card(l10n.t("k.echo.seasonStars"), _num(_as_dict(seasons[0]).get("stars")) if seasons else 0),
        _card(l10n.t("k.echo.achievements"), len(achieves)),
    ]
    if isinstance(best, dict):
        cards.append(_card(l10n.t("k.echo.best"), str(best.get("name") or best.get("score") or "—")))
    elif best:
        cards.append(_card(l10n.t("k.echo.best"), str(best)))

    blocks: list[dict] = []
    for s in seasons:
        sd = _as_dict(s)
        rows = [
            _row(l10n.t("k.echo.period"), f"{_ts(sd.get('startTs')) or '—'} ~ {_ts(sd.get('endTs')) or '—'}"),
            _row(l10n.t("k.echo.seasonStarCount"), _num(sd.get("stars"))),
            _row(l10n.t("k.echo.allBonus"), l10n.t("yes") if sd.get("allPlusTasks") else l10n.t("no")),
        ]
        for w in _as_list(sd.get("weeks")):
            wd = _as_dict(w)
            dungeons = _as_list(wd.get("dungeonGroups"))
            plus = sum(1 for d in dungeons if _as_dict(d).get("plusTask"))
            rows.append(_row(
                str(wd.get("name") or l10n.t("k.echo.rotation")),
                f"★ {_num(wd.get('stars'))} · {l10n.t('k.echo.bonus', plus, len(dungeons))}",
                "good" if _num(wd.get("stars")) else "",
            ))
            for d in dungeons[:8]:
                dd = _as_dict(d)
                rows.append(_row("　" + str(dd.get("name") or l10n.t("stage")),
                                 f"★ {_num(dd.get('star'))}" +
                                 (" · " + l10n.t("k.echo.bonusOk") if dd.get("plusTask") else "")))
        blocks.append({"title": str(sd.get("name") or l10n.t("k.echo.season")), "rows": rows})
    if activity:
        blocks.append({"title": l10n.t("k.echo.activity"), "rows": [
            _row(k, str(v)[:120]) for k, v in activity.items() if not isinstance(v, (dict, list))
        ] or [_row(l10n.t("k.crisis.status"), l10n.t("k.echo.activityObj"))]})
    if achieves:
        blocks.append({"title": l10n.t("k.echo.achievements"), "rows": [
            _row(str(_as_dict(a).get("name") or _as_dict(a).get("id") or l10n.t("k.echo.achievements")),
                 str(_as_dict(a).get("desc") or _as_dict(a).get("value") or l10n.t("k.echo.achieved")))
            for a in achieves[:20]
        ]})
    if not blocks:
        blocks.append({"title": l10n.t("k.echo.title"), "rows": [_row(l10n.t("k.crisis.status"), l10n.t("k.echo.noSeasons"))]})
    return {
        "title": l10n.t("k.echo.title"), "icon": "data", "h5": H5["echoes"],
        "cards": cards, "blocks": blocks,
        "note": l10n.t("k.echo.note"),
    }


# 「游戏数据」WinUI 面板已删（2026-11-17）：导航项改 action 直接开官方 H5 手机窗口
# （web_terminal），card/detail 的字段渲染由 H5 自己完成，包侧不再造面板模型。


# ------------------------------------------------------------------ 总入口


def overview(token: str, modules: tuple[str, ...] | None = None) -> dict:
    """拉齐数据，返回包侧模型。宿主不解释任何字段。

    modules 指定要构建的二级模块；None = 全部（skland-overview 调试直通用）。
    社区页（2026-11-17 起）只要 sign，传 ("sign",)：不请求 war-echoes 独立接口、
    也不构建三玩法面板。三个 _module_* 解析实现仍保留，调试直连与后续开发可复用。

    请求分两批并行（binding‖teenager、card‖war‖att），把 7 个串行 RTT 压到 4 个。
    """
    want = set(modules) if modules is not None else {"sign", "crisis", "monument", "echoes"}
    cred, secret = _login(token)

    q, role_id, _server_id = _binding_q(cred, secret)

    with ThreadPoolExecutor() as ex:
        fc = ex.submit(_signed_get, "/web/v1/game/endfield/card/detail", q, cred, secret)
        fa = ex.submit(_signed_get, "/web/v1/game/endfield/attendance", q, cred, secret)
        fw = (ex.submit(_signed_get, "/api/v1/game/endfield/card/war-echoes", q, cred, secret)
              if "echoes" in want else None)
        card = fc.result()
        att = fa.result()
        war = fw.result() if fw is not None else {}
    detail = _as_dict(card.get("detail"))

    base = _as_dict(detail.get("base"))
    account = {
        # 不引 _binding_q 里的局部变量 bound：它在 overview 作用域不存在，
        # name 为空时会抛 NameError（2026-11-17 顺手修）。
        "name": str(base.get("name") or l10n.t("k.account.fallbackName")),
        # 终末地 UID = roleId（App 个人主页那个数字），不是鹰角账号级 uid
        "uid": role_id,
        "level": _num(base.get("level")),
        "worldLevel": _num(base.get("worldLevel")),
        "roleId": role_id,
        "serverName": str(base.get("serverName") or ""),
        "charNum": _num(base.get("charNum")),
        "weaponNum": _num(base.get("weaponNum")),
        "docNum": _num(base.get("docNum")),
        "avatar": str(base.get("avatarUrl") or ""),
        "createTime": _ts(base.get("createTime")),
        "lastLogin": _ts(base.get("lastLoginTime")),
        "saveTime": _ts(base.get("saveTime")),
        "currentTs": _ts(card.get("currentTs")),
    }

    built: dict[str, dict] = {}
    if "sign" in want:
        built["sign"] = _module_sign(att, detail)
    if "crisis" in want:
        built["crisis"] = _module_crisis(detail)
    if "monument" in want:
        built["monument"] = _module_monument(detail)
    if "echoes" in want:
        built["echoes"] = _module_echoes(detail, war)

    return {
        "source": "live",
        "updatedAt": datetime.now(tz=CN_TZ).strftime("%Y-%m-%d %H:%M:%S"),
        "account": account,
        "modules": built,
        "h5": {"overview": H5["overview"], "home": H5["home"]},
    }
