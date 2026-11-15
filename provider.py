#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Arietta 游戏包 provider —— 明日方舟：终末地（protocol 1）

宿主要求：本文件不住在仓库里，只随游戏包放在 <数据目录>/games/<id>/ 下。
宿主启动本进程 → stdin 写一行 JSON 请求 → stdout 读一行 JSON 响应 → 进程退出。

请求：
    {"id": 1, "method": "ping"}
    {"id": 2, "method": "accounts", "params": {"token": "<账号令牌>"}}
    {"id": 3, "method": "fetch",    "params": {"token": "<账号令牌>", "lang": "zh-cn"}}
    {"id": 4, "method": "notice",   "params": {"lang": "en", "server": "GL"}}
    {"id": 5, "method": "gacha-stats", "params": {"ugf": {...}, "pool_info": {...}, "rerun_counts": {...}}}
    {"id": 6, "method": "gacha-url",   "params": {}}

方法说明：
    fetch        账号 token 走鹰角授权链；也可直接给 u8_token + server_id + provider
                 （来自客户端日志的 gacha-url），跳过授权链并支持国际服域名。
                 summary 附带 pool_info / rerun_counts 供统计使用，UGF 本体保持规范纯净。
    gacha-stats  UGF → 通用渲染模型（cards / tabs / notes），口径在 gacha.py。
    gacha-url    读客户端 SDK 日志里最近一条寻访记录页链接，只在用户点按钮时调用。

响应：
    {"id": 1, "ok": true,  "result": {...}}
    {"id": 2, "ok": false, "error": {"message": "可直接展示给用户的中文提示"}}

设计要点：**fetch 直接返回 UGF 文件内容**（format/version/accounts/records）。
宿主不需要认识终末地，只要会读 UGF——增删任何游戏都不必动宿主代码。
"""

from __future__ import annotations

import json
import random
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

# 包目录内每个文件都计入签名哈希：import 同目录模块默认会写 __pycache__/*.pyc，
# 那会让下一次验签失败。宿主启动的 provider 一律不落字节码。
sys.dont_write_bytecode = True
import gacha   # 同包目录：终末地抽卡统计引擎（gacha.py）
import skland  # 同包目录：森空岛数据终端（skland.py，端点/签名/字段映射全在包内）

PROTOCOL = 1
PACK_ID = "arknights-endfield"
PACK_VERSION = "0.2.0"

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")

AS_HOST = "https://as.hypergryph.com"
BINDING_HOST = "https://binding-api-account-prod.hypergryph.com"
WEBVIEW_HOST = "https://ef-webview.hypergryph.com"

# 抽卡记录域：国服 hypergryph / 国际服 gryphline。账号 token 链仍走国服（已实测）；
# 客户端日志里的 u8_token 可直接打对应域，因此国际服走日志链接路径。
WEBVIEW_HOSTS = {
    "hypergryph": WEBVIEW_HOST,
    "gryphline": "https://ef-webview.gryphline.com",
}
# 客户端把寻访记录页 URL 写进 SDK 日志，内含 u8_token（参考 endfield-gacha 的 useGachaAuth.ts）
GACHA_LOG_PATHS = {
    "hypergryph": "AppData/LocalLow/Hypergryph/Endfield/sdklogs/HGWebview.log",
    "gryphline": "AppData/LocalLow/Gryphline/Endfield/sdklogs/HGWebview.log",
}
GACHA_URL_RE = re.compile(r"https://ef-webview\.(hypergryph|gryphline)\.com/page/gacha_[^\s\"'<>\\]*")
MAX_POOL_INFO = 24

# 鹰角账号授权用的应用码；森空岛的授权码换不到寻访记录
HG_APP_CODE = "be36d44aa36bfb5b"
GAME_APP_CODE = "endfield"

# 官方启动器公告接口（batch_proxy），无需鉴权；参数与官方启动器同源，
# 见 Collapse 终末地插件调查交接文档（2026-11-14 国服、2026-11-15 国际服实测通过）。
# 宿主透传的 server 是 game.json servers[].code，包自己决定它对应哪条通道。
LAUNCHER_CHANNELS = {
    # 国服官服；B 服的 channel 2/2 实测没有投放公告，仍沿用官服 1/1
    "CN": {
        "url": "https://launcher.hypergryph.com/api/proxy/web/batch_proxy",
        "appcode": "6LL0KJuqHBVz33WK",
        "channel": "1", "sub_channel": "1", "seq": "5",
        "language": "zh-cn",  # 国服只投放简中，别的语言码返回 200 但内容全空
    },
    # 国际服 GRYPHLINE：与国服同构的 web/batch_proxy，端点/码/通道不同
    "GL": {
        "url": "https://launcher.gryphline.com/api/proxy/web/batch_proxy",
        "appcode": "YDUTE5gscDZ229CW",
        "channel": "6", "sub_channel": "6", "seq": "3",
        "language": None,  # 跟随启动器语言
    },
}
DEFAULT_NOTICE_CHANNEL = "CN"

# 启动器界面语言 tag（宿主 UiLanguage / game.json names 同一套）→ 国际服接口语言码。
# 接口只认「语言-地区」小写码：en / zz-zz 之类会返回 200 但内容全空（2026-11-15 实测）。
# 西语投放的是 es-mx（es-es / es-419 为空）；官方另有 ru-ru / id-id / vi-vn / it-it，
# 宿主语言下拉尚未列出，暂不进映射表。
NOTICE_LANG = {
    "zh-hans": "zh-cn",
    "zh-hant": "zh-tw",
    "en": "en-us",
    "ja": "ja-jp",
    "ko": "ko-kr",
    "fr": "fr-fr",
    "de": "de-de",
    "es": "es-mx",
    "th": "th-th",
    "pt-br": "pt-br",
}
NOTICE_LANG_FALLBACK = "en-us"

CHAR_POOL_NAMES = {
    "E_CharacterGachaPoolType_Special": "特许寻访",
    "E_CharacterGachaPoolType_Rerun": "重构寻访",
    "E_CharacterGachaPoolType_Joint": "辉光庆典",
    "E_CharacterGachaPoolType_Standard": "基础寻访",
    "E_CharacterGachaPoolType_Beginner": "启程寻访",
}
FALLBACK_CHAR_POOLS = list(CHAR_POOL_NAMES.keys())

MAX_PAGES = 500
MAX_RETRY = 3


class ProviderError(Exception):
    """消息直接展示给用户。"""


# ------------------------------------------------------------------ HTTP


def http_json(url: str, body: dict | None = None, timeout: int = 20) -> Any:
    data = None
    headers = {"User-Agent": UA, "Accept": "application/json"}
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json;charset=UTF-8"

    last: Exception | None = None
    for attempt in range(1, MAX_RETRY + 1):
        try:
            req = urllib.request.Request(url, data=data, headers=headers)
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode("utf-8", errors="replace"))
        except urllib.error.HTTPError as e:
            payload = ""
            try:
                payload = e.read().decode("utf-8", errors="replace")
            except Exception:
                pass
            # 4xx 也可能带可读的 JSON 消息，先尝试解析
            try:
                return json.loads(payload)
            except Exception:
                last = RuntimeError(f"HTTP {e.code}: {payload[:200]}")
        except Exception as e:
            last = e
        if attempt < MAX_RETRY:
            time.sleep(random.uniform(0.4, 0.9))
    raise ProviderError(f"网络请求失败：{last}")


# ------------------------------------------------------------------ 凭证链


def resolve_credential(account_token: str) -> dict[str, str]:
    """
    账号令牌 → 授权令牌 → uid / serverId → 角色令牌。
    账号令牌**不能**直接打记录接口，会返回 40100。
    """
    token = (account_token or "").strip()
    if not token:
        raise ProviderError("令牌为空。")

    granted = http_json(
        f"{AS_HOST}/user/oauth2/v2/grant",
        {"token": token, "appCode": HG_APP_CODE, "type": 1},
    )
    if granted.get("status") != 0:
        raise ProviderError(
            "账号令牌无效或已过期。请浏览器登录 user.hypergryph.com，"
            "再打开 web-api.hypergryph.com/account/info/hg，复制整段内容重试。"
        )
    oauth = (granted.get("data") or {}).get("token") or ""
    if not oauth:
        raise ProviderError("账号授权没有返回令牌，接口可能已改版。")

    listing = http_json(
        f"{BINDING_HOST}/account/binding/v1/binding_list"
        f"?token={urllib.parse.quote(oauth)}&appCode={GAME_APP_CODE}"
    )
    if listing.get("status") != 0:
        raise ProviderError(f"查询绑定角色失败：{listing.get('msg') or ''}")

    binding = None
    for app in (listing.get("data") or {}).get("list") or []:
        if app.get("appCode") != GAME_APP_CODE:
            continue
        for b in app.get("bindingList") or []:
            uid = str(b.get("uid") or "").strip()
            if uid.isdigit():
                binding = b
                break
        if binding:
            break

    if binding is None:
        raise ProviderError(
            "这个账号下没有绑定《终末地》。请先在游戏里建号，或在鹰角用户中心绑定角色。"
        )

    roles = [r for r in (binding.get("roles") or []) if isinstance(r, dict)]
    server_id = str(roles[0].get("serverId") or "") if roles else "1"

    exchanged = http_json(
        f"{BINDING_HOST}/account/binding/v1/u8_token_by_uid",
        {"token": oauth, "uid": str(binding.get("uid"))},
    )
    if exchanged.get("status") != 0:
        raise ProviderError(f"换取角色令牌失败：{exchanged.get('msg') or ''}")
    u8 = (exchanged.get("data") or {}).get("token") or ""
    if not u8:
        raise ProviderError("没有拿到角色令牌，接口可能已改版。")

    return {
        "u8_token": u8,
        "uid": str(binding.get("uid") or ""),
        "server_id": server_id or "1",
        "channel": str(binding.get("channelName") or ""),
        "nickname": str(binding.get("nickName") or ""),
    }


# ------------------------------------------------------------------ 拉取


def fetch_pages(path: str, u8: str, server: str, extra: dict[str, str],
                host: str | None = None) -> list[dict]:
    rows: list[dict] = []
    next_seq = ""
    base = host or WEBVIEW_HOST
    for _ in range(MAX_PAGES):
        q = {"lang": "zh-cn", "token": u8, "server_id": server, **extra}
        if next_seq:
            q["seq_id"] = next_seq
        res = http_json(f"{base}{path}?{urllib.parse.urlencode(q)}")
        if res.get("code") != 0:
            raise ProviderError(
                f"接口返回 code={res.get('code')} msg={res.get('msg') or ''}"
            )
        data = res.get("data") or {}
        items = data.get("list") or []
        if not items:
            break
        rows.extend(items)
        if not data.get("hasMore"):
            break
        next_seq = str(items[-1].get("seqId") or "")
        if not next_seq:
            break
        time.sleep(random.uniform(0.28, 0.65))
    return rows


def char_pool_types(u8: str, server: str, host: str | None = None) -> list[str]:
    try:
        res = http_json(
            f"{host or WEBVIEW_HOST}/api/record/char/meta?"
            + urllib.parse.urlencode({"lang": "zh-cn", "token": u8, "server_id": server})
        )
        tabs = ((res.get("data") or {}).get("tabs")) or []
        types: list[str] = []
        for tab in tabs:
            pt = str(tab.get("poolType") or "").strip()
            if pt and pt not in types:
                types.append(pt)
        return types or list(FALLBACK_CHAR_POOLS)
    except Exception:
        return list(FALLBACK_CHAR_POOLS)


def weapon_pools(u8: str, server: str, host: str | None = None) -> list[dict]:
    try:
        res = http_json(
            f"{host or WEBVIEW_HOST}/api/record/weapon/pool?"
            + urllib.parse.urlencode({"lang": "zh-cn", "token": u8, "server_id": server})
        )
        data = res.get("data")
        return data if isinstance(data, list) else []
    except Exception:
        return []


# ------------------------------------------------------------------ UGF


def parse_offset(text: str) -> timezone:
    s = (text or "").strip()
    if len(s) == 6 and s[0] in "+-" and s[3] == ":":
        sign = 1 if s[0] == "+" else -1
        try:
            return timezone(sign * timedelta(hours=int(s[1:3]), minutes=int(s[4:6])))
        except ValueError:
            pass
    return timezone.utc


def to_iso(ms: str, offset: str) -> str:
    """13 位毫秒时间戳 → ISO。绝对时刻按账号展示时区渲染（国服 +08:00）。"""
    try:
        seconds = int(str(ms).strip()) / 1000.0
    except (TypeError, ValueError):
        return ""
    return datetime.fromtimestamp(seconds, tz=parse_offset(offset)).isoformat(
        timespec="seconds"
    )


def pity_group(kind: str, pool_type: str, pool_id: str) -> str:
    if kind == "char":
        if pool_type in (
            "E_CharacterGachaPoolType_Special",
            "E_CharacterGachaPoolType_Rerun",
        ):
            return pool_type
        return pool_id
    if pool_type == "rerun":
        return "weapon-rerun"
    return pool_id


def build_ugf(
    cred: dict[str, str],
    char: dict[str, list[dict]],
    weapon: dict[str, list[dict]],
    weapon_meta: dict[str, str],
    lang: str,
) -> dict[str, Any]:
    """把原始记录映射成 UGF v1.3（映射规则见 UGF 仓库的规范与提案）。"""
    records: list[dict[str, Any]] = []

    def push(
        pool_id: str,
        pool_type: str,
        item_id: str,
        name: str,
        item_type: str,
        rarity: Any,
        gacha_ts: Any,
        seq_id: str,
        extra: dict[str, Any],
        kind: str,
    ) -> None:
        try:
            rarity_num: int | None = int(rarity)
        except (TypeError, ValueError):
            rarity_num = None
        rec: dict[str, Any] = {
            "pool": pool_id,
            "time": to_iso(gacha_ts, "+08:00"),
            "item_id": item_id or None,
            "name": name or None,
            "item_type": item_type,
            "rarity": rarity_num,
            "count": 1,
            "pity_group": pity_group(kind, pool_type, pool_id),
            "id": seq_id or None,
            "x_endfield": {
                **{k: v for k, v in extra.items() if v is not None},
                "pool_type": pool_type,
            },
        }
        records.append({k: v for k, v in rec.items() if v is not None or k == "time"})

    for pool_type, items in char.items():
        for it in items:
            k = str(it.get("kind") or "")
            is_gift = k.startswith("gift")
            if is_gift:
                # 赠礼不是抽取，宿主侧也不应计入 pity；直接不进 records
                continue
            name_text = str(it.get("nameText") or "").strip()
            push(
                pool_id=str(it.get("poolId") or "").strip(),
                pool_type=pool_type,
                item_id=str(it.get("charId") or "").strip(),
                name=name_text or str(it.get("charName") or "").strip(),
                item_type="角色",
                rarity=it.get("rarity"),
                gacha_ts=it.get("gachaTs"),
                seq_id=str(it.get("seqId") or "").strip(),
                extra={
                    "is_free": bool(it.get("isFree")),
                    "is_new": bool(it.get("isNew")),
                    "pool_name": str(it.get("poolName") or "").strip() or None,
                    "pool_version": it.get("poolVersion"),
                },
                kind="char",
            )

    for pool_id, items in weapon.items():
        wt = weapon_meta.get(pool_id, "normal")
        for it in items:
            if str(it.get("kind") or "").startswith("gift"):
                continue
            name_text = str(it.get("nameText") or "").strip()
            push(
                pool_id=str(it.get("poolId") or pool_id).strip(),
                pool_type=wt,
                item_id=str(it.get("weaponId") or "").strip(),
                name=name_text or str(it.get("weaponName") or "").strip(),
                item_type="武器",
                rarity=it.get("rarity"),
                gacha_ts=it.get("gachaTs"),
                seq_id=str(it.get("seqId") or "").strip(),
                extra={
                    "is_new": bool(it.get("isNew")),
                    "weapon_type": str(it.get("weaponType") or "").strip() or None,
                    "pool_name": str(it.get("poolName") or "").strip() or None,
                    "pool_version": it.get("poolVersion"),
                },
                kind="weapon",
            )

    records.sort(key=lambda r: (str(r.get("time") or ""), str(r.get("id") or "")))

    account: dict[str, Any] = {
        "game": PACK_ID,
        "uid": cred["uid"],
        "server": cred["server_id"],
        # 接口不返回时区；server=1 为国服，按 +08:00 展示（国际服待实测）
        "timezone": "+08:00" if cred["server_id"] == "1" else None,
        "lang": lang,
        "records": records,
    }
    if account["timezone"] is None:
        account.pop("timezone")

    return {
        "format": "UGF",
        "version": "1.3",
        "exporter": {
            "name": f"{PACK_ID}-provider",
            "version": PACK_VERSION,
            "exported_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        },
        "accounts": [account],
    }


# ------------------------------------------------------------------ 方法


def method_ping(_params: dict) -> dict[str, Any]:
    return {
        "pack": PACK_ID,
        "protocol": PROTOCOL,
        "version": PACK_VERSION,
        "capabilities": ["accounts", "fetch", "notice", "background",
                         "gacha-stats", "gacha-url", "skland-overview"],
    }


def notice_channel(server: str) -> dict:
    """按宿主透传的服变体码选公告通道；未知码 / 旧宿主不传参数一律国服（行为不变）。"""
    return LAUNCHER_CHANNELS.get(server.strip().upper(), LAUNCHER_CHANNELS[DEFAULT_NOTICE_CHANNEL])


def notice_language(channel: dict, lang: str) -> str:
    """国服固定简中；国际服跟随启动器语言，未识别的语言回落英文。"""
    fixed = channel["language"]
    if fixed:
        return fixed
    return NOTICE_LANG.get(lang.strip().lower(), NOTICE_LANG_FALLBACK)


def fetch_notice(channel: dict, language: str) -> tuple[list[dict], list[dict]]:
    """一次 POST 拿轮播图 + 公告列表，映射成宿主通用的 banners / groups。"""
    common = {"appcode": channel["appcode"], "language": language,
              "channel": channel["channel"], "sub_channel": channel["sub_channel"],
              "platform": "Windows", "source": "launcher"}
    body = {"seq": channel["seq"], "proxy_reqs": [
        {"kind": "get_banner", "get_banner_req": common},
        {"kind": "get_announcement", "get_announcement_req": common},
    ]}
    rsp = http_json(channel["url"], body)
    if not isinstance(rsp, dict):
        raise ProviderError("公告接口返回异常。")
    reqs = rsp.get("proxy_rsps") or []

    banners: list[dict[str, str]] = []
    banner_rsp = next((r.get("get_banner_rsp") for r in reqs
                       if r.get("kind") == "get_banner"), None) or {}
    for b in banner_rsp.get("banners") or []:
        if b.get("url"):
            banners.append({"url": b["url"], "jump_url": b.get("jump_url") or ""})

    groups: list[dict[str, Any]] = []
    ann_rsp = next((r.get("get_announcement_rsp") for r in reqs
                    if r.get("kind") == "get_announcement"), None) or {}
    for tab in ann_rsp.get("tabs") or []:
        items = []
        for a in tab.get("announcements") or []:
            try:
                date = datetime.fromtimestamp(int(a.get("start_ts")) / 1000).strftime("%Y-%m-%d")
            except (TypeError, ValueError, OSError):
                date = ""
            items.append({"title": a.get("content") or "",
                          "date": date,
                          "link": a.get("jump_url") or ""})
        if items:
            groups.append({"header": tab.get("tabName") or "", "items": items})
    return banners, groups


def method_notice(params: dict) -> dict[str, Any]:
    """
    启动器公告：params.lang = 启动器语言 tag、params.server = 服变体码，均由宿主原样透传。
    返回结构对齐宿主 GameBannerAndPost 的数据模型（banners / groups），
    宿主不需要认识鹰角的 batch_proxy 字段，也不需要知道哪个服用哪条通道。
    """
    channel = notice_channel(str(params.get("server") or ""))
    language = notice_language(channel, str(params.get("lang") or ""))
    banners, groups = fetch_notice(channel, language)
    # 某语言临时没投放（接口 200 但内容全空）：国际服回落英文再试一次
    if not banners and not groups and channel["language"] is None and language != NOTICE_LANG_FALLBACK:
        banners, groups = fetch_notice(channel, NOTICE_LANG_FALLBACK)
    if not banners and not groups:
        raise ProviderError("公告接口没有返回内容。")
    return {"banners": banners, "groups": groups}


def method_background(params: dict) -> dict[str, Any]:
    """
    启动器主界面动态背景（batch_proxy get_main_bg_image，2026-11-15 双服实测）：
    官方启动器主页同款视频 + 海报，无需鉴权。
    params.server = 服变体码（宿主原样透传）；params.lang 与公告同源（背景本身无语言，
    仅国际服请求体的 language 字段需要合法码，填什么不影响返回内容）。
    返回通用字段 video / poster——宿主只认这两个 URL，不认识鹰角接口。
    """
    channel = notice_channel(str(params.get("server") or ""))
    language = notice_language(channel, str(params.get("lang") or ""))
    common = {"appcode": channel["appcode"], "language": language,
              "channel": channel["channel"], "sub_channel": channel["sub_channel"],
              "platform": "Windows", "source": "launcher"}
    body = {"seq": channel["seq"], "proxy_reqs": [
        {"kind": "get_main_bg_image", "get_main_bg_image_req": common},
    ]}
    rsp = http_json(channel["url"], body)
    reqs = rsp.get("proxy_rsps") or [] if isinstance(rsp, dict) else []
    bg = next((r.get("get_main_bg_image_rsp", {}).get("main_bg_image")
               for r in reqs if r.get("kind") == "get_main_bg_image"), None) or {}
    video = bg.get("video_url") or ""
    if not video:
        # 与公告同一表现：接口 200 但内容空（通道码不对 / 未投放），报给用户而不是静默
        raise ProviderError("背景接口没有返回视频地址。")
    return {"video": video, "poster": bg.get("url") or ""}


def method_accounts(params: dict) -> dict[str, Any]:
    cred = resolve_credential(str(params.get("token") or ""))
    return {
        "accounts": [
            {
                "uid": cred["uid"],
                "server": cred["server_id"],
                "channel": cred["channel"],
                "nickname": cred["nickname"],
                "display": f"{cred['nickname']}({cred['uid']})"
                if cred["nickname"]
                else cred["uid"],
            }
        ]
    }


def method_fetch(params: dict) -> dict[str, Any]:
    lang = str(params.get("lang") or "zh-cn")

    # 两条凭证路径：
    #  1) 账号 token（用户粘贴）→ 鹰角授权链 → u8_token（国服，已实测）；
    #  2) 客户端日志里的 u8_token（gacha-url 提供）→ 直接打 ef-webview（含国际服）。
    direct_u8 = str(params.get("u8_token") or "").strip()
    provider_name = str(params.get("provider") or "").strip().lower()
    if provider_name not in WEBVIEW_HOSTS:
        provider_name = "hypergryph"
    if direct_u8:
        server = str(params.get("server_id") or "1").strip() or "1"
        uid = str(params.get("uid") or "").strip()
        if not uid:
            uid = query_uid_from_u8(direct_u8, provider_name, server) or "local-log"
        cred = {
            "u8_token": direct_u8,
            "uid": uid,
            "server_id": server,
            "channel": str(params.get("channel") or "").strip(),
            "nickname": "",
        }
        host = WEBVIEW_HOSTS[provider_name]
    else:
        cred = resolve_credential(str(params.get("token") or ""))
        host = WEBVIEW_HOST
        provider_name = "hypergryph"
    u8, server = cred["u8_token"], cred["server_id"]

    char: dict[str, list[dict]] = {}
    for pool_type in char_pool_types(u8, server, host):
        try:
            char[pool_type] = fetch_pages(
                "/api/record/char", u8, server, {"pool_type": pool_type}, host
            )
        except ProviderError:
            char[pool_type] = []

    weapon: dict[str, list[dict]] = {}
    weapon_meta: dict[str, str] = {}
    rerun_ids: list[str] = []
    for p in weapon_pools(u8, server, host):
        pid = str(p.get("poolId") or "").strip()
        if not pid:
            continue
        pt = str(p.get("poolType") or "").strip() or "normal"
        weapon_meta[pid] = pt
        if pt == "rerun":
            rerun_ids.append(pid)
            continue
        try:
            weapon[pid] = fetch_pages(
                "/api/record/weapon", u8, server, {"pool_id": pid}, host
            )
        except ProviderError:
            weapon[pid] = []

    if rerun_ids:
        try:
            merged = fetch_pages(
                "/api/record/weapon", u8, server, {"pool_ids": ",".join(rerun_ids)}, host
            )
        except ProviderError:
            merged = []
        for pid in rerun_ids:
            weapon[pid] = []
        for item in merged:
            pid = str(item.get("poolId") or "").strip()
            weapon.setdefault(pid, []).append(item)

    ugf = build_ugf(cred, char, weapon, weapon_meta, lang)
    pulls = len(ugf["accounts"][0]["records"])

    # 统计辅助数据单独放 summary，不污染 UGF 规范文档本体：
    #   pool_info    = /api/content 的 UP 6★ 名单（UP / 歪判定）
    #   rerun_counts = 官方累计寻访次数（重构池大保底以服务器为准）
    pool_ids = list(dict.fromkeys(
        str(r.get("pool") or "").strip()
        for r in ugf["accounts"][0]["records"]
        if str(r.get("pool") or "").strip()
    ))
    want_pool_info = str(params.get("with_pool_info", "true")).strip().lower() not in ("false", "0", "no")
    pool_info = fetch_pool_info(server, host, pool_ids) if want_pool_info else {}
    rerun_counts = fetch_rerun_counts(u8, server, host)

    return {
        "ugf": ugf,
        "summary": {
            "uid": cred["uid"],
            "server": cred["server_id"],
            "channel": cred["channel"],
            "nickname": cred["nickname"],
            "records": pulls,
            "provider": provider_name,
            "pool_info": pool_info,
            "rerun_counts": rerun_counts,
        },
    }


# ------------------------------------------------- 抽卡统计 / 日志链接（包侧游戏知识）


def query_uid_from_u8(u8: str, provider: str, server: str) -> str:
    """日志链接模式：用 u8_token 反查 uid（参考 endfield-gacha 的 query_role_list）。失败静默。"""
    try:
        res = http_json(
            f"https://u8.{provider}.com/game/role/v1/query_role_list",
            {"token": u8, "serverId": server},
        )
        return str((res.get("data") or {}).get("uid") or "").strip()
    except Exception:
        return ""


def fetch_rerun_counts(u8: str, server: str, host: str) -> dict[str, dict]:
    """官方累计寻访 / 申领次数：重构池大保底以服务器累计为准（官方只保留 90 天明细）。"""
    out: dict[str, dict] = {"char": {}, "weapon": {}}
    for kind in ("char", "weapon"):
        try:
            q = urllib.parse.urlencode({"lang": "zh-cn", "token": u8, "server_id": server})
            res = http_json(f"{host}/api/record/{kind}/rerun-counts?{q}")
            data = res.get("data")
            entries = data if isinstance(data, list) else []
            for entry in entries:
                if not isinstance(entry, dict):
                    continue
                pid = str(entry.get("poolId") or "").strip()
                count = entry.get("totalPullCount")
                if pid and isinstance(count, (int, float)):
                    out[kind][pid] = max(int(out[kind].get(pid, 0)), int(count))
        except Exception:
            continue
    return out


def fetch_pool_info(server: str, host: str, pool_ids: list[str]) -> dict[str, dict]:
    """/api/content 拿每池 UP 6★ 名单，用于「UP / 歪」判定；缺失的池不下结论。"""
    info: dict[str, dict] = {}
    for pid in pool_ids[:MAX_POOL_INFO]:
        try:
            q = urllib.parse.urlencode({"lang": "zh-cn", "pool_id": pid, "server_id": server})
            res = http_json(f"{host}/api/content?{q}")
            pool = (res.get("data") or {}).get("pool") or {}
            if not isinstance(pool, dict):
                continue
            items = pool.get("all") or []
            up6_name = str(pool.get("up6_name") or "").strip()
            is_extra = str(pool.get("pool_type") or "").strip() == "extra"
            ids = [
                str(it.get("id") or "").strip()
                for it in items if isinstance(it, dict)
                and str(it.get("rarity") or "") == "6"
                and (is_extra or str(it.get("name") or "").strip() == up6_name)
            ]
            info[pid] = {
                "up6_ids": [x for x in ids if x],
                "pool_name": str(pool.get("pool_name") or "").strip() or pid,
                "pool_type": str(pool.get("pool_type") or "").strip(),
            }
            time.sleep(random.uniform(0.12, 0.28))
        except Exception:
            continue
    return info


def method_gacha_stats(params: dict) -> dict[str, Any]:
    """UGF → 通用渲染模型。统计口径全在包内 gacha.py，宿主只负责把模型交给页面。"""
    ugf = params.get("ugf") or {}
    if not isinstance(ugf, dict) or not (ugf.get("accounts") or []):
        raise ProviderError("没有可统计的寻访记录，请先执行一次「更新记录」。")
    model = gacha.analyze(
        ugf,
        pool_info=params.get("pool_info") or {},
        rerun_counts=params.get("rerun_counts") or {},
        source=str(params.get("source") or "live"),
    )
    return {"model": model}


def method_gacha_url(params: dict) -> dict[str, Any]:
    """读客户端 SDK 日志里最近一条寻访记录页链接；只有用户主动点按钮才会读本机文件。"""
    prefer = str(params.get("provider") or "").strip().lower()
    order = [prefer] if prefer in GACHA_LOG_PATHS else list(GACHA_LOG_PATHS)
    for provider in order:
        path = Path.home() / GACHA_LOG_PATHS[provider]
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        match = None
        for line in reversed(text.splitlines()[-4000:]):
            match = GACHA_URL_RE.search(line)
            if match:
                break
        if not match:
            continue
        parsed = urllib.parse.urlparse(match.group(0))
        q = urllib.parse.parse_qs(parsed.query)

        def pick(*keys: str) -> str:
            for k in keys:
                v = (q.get(k) or [""])[0]
                if v:
                    return v.strip()
            return ""

        u8 = pick("u8_token", "token")
        if not u8:
            continue
        provider = match.group(1) or provider
        server = pick("server_id", "serverId", "serverid", "server") or "1"
        return {
            "provider": provider,
            "u8_token": u8,
            "server_id": server,
            "channel": pick("channel"),
            "uid": query_uid_from_u8(u8, provider, server),
        }
    raise ProviderError(
        "没有找到客户端的寻访记录链接。请先在游戏内打开一次寻访记录页面，"
        "或直接粘贴鹰角账号 token。"
    )


def method_skland_overview(params: dict) -> dict[str, Any]:
    """
    森空岛「数据终端」：一次拿齐每日签到 / 危机合约 / 影拓丰碑 / 战争回响的 API 数据。
    params.token = 鹰角账号 token（由 ui/community.html 存在宿主 state 里，包目录不落凭证）。
    端点、appCode、sign 签名、字段映射、官方 H5 链接全部在包内 skland.py。
    """
    token = str(params.get("token") or "").strip()
    try:
        return skland.overview(token)
    except skland.SklandError as e:
        raise ProviderError(str(e))


METHODS = {
    "ping": method_ping,
    "skland-overview": method_skland_overview,
    "accounts": method_accounts,
    "fetch": method_fetch,
    "notice": method_notice,
    "background": method_background,
    "gacha-stats": method_gacha_stats,
    "gacha-url": method_gacha_url,
}


# ------------------------------------------------------------------ 入口


def main() -> int:
    try:
        raw = sys.stdin.readline()
        if not raw.strip():
            print(json.dumps({"id": None, "ok": False,
                              "error": {"message": "请求为空"}}, ensure_ascii=False))
            return 1
        req = json.loads(raw)
    except Exception as e:
        print(json.dumps({"id": None, "ok": False,
                          "error": {"message": f"请求不是合法 JSON：{e}"}},
                         ensure_ascii=False))
        return 1

    req_id = req.get("id")
    method = str(req.get("method") or "")
    params = req.get("params") or {}

    handler = METHODS.get(method)
    if handler is None:
        print(json.dumps({"id": req_id, "ok": False,
                          "error": {"message": f"未知方法：{method}"}},
                         ensure_ascii=False))
        return 1

    try:
        result = handler(params)
        print(json.dumps({"id": req_id, "ok": True, "result": result},
                         ensure_ascii=False))
        return 0
    except ProviderError as e:
        print(json.dumps({"id": req_id, "ok": False,
                          "error": {"message": str(e)}}, ensure_ascii=False))
        return 1
    except Exception as e:  # 兜底：任何异常都要变成一行可读响应
        print(json.dumps({"id": req_id, "ok": False,
                          "error": {"message": f"{type(e).__name__}: {e}"}},
                         ensure_ascii=False))
        return 1


if __name__ == "__main__":
    sys.exit(main())
