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
from datetime import datetime, timedelta, timezone
from typing import Any

AS_HOST = "https://as.hypergryph.com"
SK_HOST = "https://zonai.skland.com"
SKLAND_APP_CODE = "4ca99fa6b56cc2ba"  # 森空岛 OAuth；与 provider.py 的抽卡 appCode 不同

UA = ("Skland/1.0.1 (com.hypergryph.skland; build:100001014; Android 31; ) "
      "Okhttp/4.11.0")
PLATFORM = "1"
DID = "de9759a5afaa634f"
VNAME = "1.0.1"
TS_OFFSET = -5

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
             headers: dict | None = None, timeout: int = 20) -> dict:
    data = None
    h = {"User-Agent": UA, "Accept": "application/json"}
    if body is not None:
        data = json.dumps(body, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        h["Content-Type"] = "application/json;charset=UTF-8"
    if headers:
        h.update(headers)
    req = urllib.request.Request(url, data=data, headers=h)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", errors="replace")
        try:
            payload = json.loads(raw)
        except Exception:
            raise SklandError(f"接口 HTTP {e.code}：{raw[:160]}")
        raise SklandError(f"接口 HTTP {e.code}：{payload.get('message') or raw[:160]}")
    except Exception as e:
        raise SklandError(f"网络请求失败：{type(e).__name__}: {e}")
    try:
        return json.loads(raw)
    except Exception:
        raise SklandError(f"接口返回的不是 JSON：{raw[:160]}")


def _login(token: str) -> tuple[str, str]:
    if not token:
        raise SklandError(
            "还没有森空岛凭证。请在「凭证设置」里填入鹰角账号 token："
            "浏览器登录 user.hypergryph.com 后打开 "
            "web-api.hypergryph.com/account/info/hg，复制 content 字段。"
        )
    grant = _request(f"{AS_HOST}/user/oauth2/v2/grant",
                     {"token": token, "appCode": SKLAND_APP_CODE, "type": 0})
    code = str((grant.get("data") or {}).get("code") or "")
    if not code:
        raise SklandError(
            "账号 token 无效或已过期。请重新登录 user.hypergryph.com，"
            "从 web-api.hypergryph.com/account/info/hg 复制 content 后重试。"
        )
    cred_rsp = _request(f"{SK_HOST}/api/v1/user/auth/generate_cred_by_code",
                        {"kind": 1, "code": code})
    data = cred_rsp.get("data") or {}
    cred, secret = str(data.get("cred") or ""), str(data.get("token") or "")
    if cred_rsp.get("code") != 0 or not cred or not secret:
        raise SklandError(f"换取森空岛凭证失败：{cred_rsp.get('message') or '接口改版'}")
    return cred, secret


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
        raise SklandError(f"森空岛接口返回 code={rsp.get('code')}："
                          f"{rsp.get('message') or '未知错误'}")
    return rsp.get("data") or {}


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


def _row(label: str, value: Any, tone: str = "") -> dict:
    return {"label": str(label), "value": str(value), "tone": tone}


def _as_list(value: Any) -> list:
    return value if isinstance(value, list) else []


def _as_dict(value: Any) -> dict:
    return value if isinstance(value, dict) else {}


# ------------------------------------------------------------------ 各模块映射


def _module_sign(att: dict, detail: dict) -> dict:
    """每日签到：只读日历，不代签。"""
    calendar = _as_list(att.get("calendar"))
    first = _as_list(att.get("first"))
    resource = _as_dict(att.get("resourceInfoMap"))
    done = sum(1 for x in calendar if _as_dict(x).get("done") is True)
    available = sum(1 for x in calendar if _as_dict(x).get("available") is True)
    has_today = bool(att.get("hasToday"))

    def award_name(award_id: Any) -> str:
        aid = str(award_id or "")
        for key in (aid, aid.split("_")[-1], "_".join(aid.split("_")[-2:])):
            info = _as_dict(resource.get(key))
            name = str(info.get("name") or info.get("itemName") or "")
            if name:
                return name
        return aid.rsplit("_", 1)[-1] if aid else "奖励"

    days = []
    for i, item in enumerate(calendar, 1):
        d = _as_dict(item)
        days.append({
            "day": i,
            "award": award_name(d.get("awardId")),
            "done": bool(d.get("done")),
            "available": bool(d.get("available")),
        })

    cards = [
        _card("本月已签", f"{done} / {len(calendar)}", "按日历 done 标记统计"),
        _card("今日可领", "是" if has_today else "否",
              "签到是写操作，本页不代为领取", "good" if has_today else "muted"),
        _card("可领奖励", available, "当前 available 的日历格数"),
    ]
    extra_rows = [
        _row(f"奖励 {i}",
             f"{award_name(x.get('awardId'))} · "
             f"{'已领' if x.get('done') else ('可领' if x.get('available') else '未解锁')}",
             "good" if x.get("done") else "")
        for i, x in enumerate((_as_dict(v) for v in first), 1)
    ][:12]
    blocks = [{
        "title": "首签 / 额外奖励",
        "rows": extra_rows or [_row("暂无", "接口没有返回额外奖励")],
    }]
    daily = _as_dict(detail.get("dailyMission"))
    credit = _as_dict(detail.get("credit"))
    weekly = _as_dict(detail.get("weeklyMission"))
    blocks.append({
        "title": "日常进度（角色卡片同源数据）",
        "rows": [
            _row("每日活跃", f"{_num(daily.get('dailyActivation'))} / {_num(daily.get('maxDailyActivation'))}"),
            _row("每周任务", f"{_num(weekly.get('score'))} / {_num(weekly.get('total'))}"),
            _row("信用", f"{_num(credit.get('count'))} / {_num(credit.get('total'))}"),
            _row("信用下次刷新", _ts(credit.get("nextRefreshTs")) or "—"),
        ],
        "bars": [
            {"label": "每日活跃", "value": _num(daily.get("dailyActivation")),
             "total": _num(daily.get("maxDailyActivation"))},
            {"label": "每周任务", "value": _num(weekly.get("score")),
             "total": _num(weekly.get("total"))},
            {"label": "信用", "value": _num(credit.get("count")),
             "total": _num(credit.get("total"))},
        ],
    })
    return {
        "title": "每日签到", "icon": "sign", "h5": H5["sign"], "calendar": days,
        "cards": cards, "blocks": blocks,
        "note": "数据来自只读接口 /web/v1/game/endfield/attendance；领取奖励需到官方 H5 完成，本页不代签。",
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
            _card("最高难度", _num(c.get("highest")), "当期合约"),
            _card("挑战次数", _num(c.get("challengeCount"))),
            _card("周常任务", f"{_num(weekly.get('count'))} / {_num(weekly.get('total'))}"),
            _card("指标任务", f"{_num(indicator.get('count'))} / {_num(indicator.get('total'))}"),
            _card("关卡任务", f"{_num(stage.get('count'))} / {_num(stage.get('total'))}"),
        ])
        blocks.append({
            "title": str(c.get("name") or "当期合约"),
            "rows": [
                _row("开放时间", _ts(c.get("startAtTs")) or "—"),
                _row("结束时间", _ts(c.get("endAtTs")) or "—"),
                _row("玩法结束", _ts(c.get("gameplayEndAtTs")) or "—"),
                _row("活动奖章", str(ach.get("name") or "—")),
                _row("奖章等级", _num(_as_dict(c.get("achieve")).get("level"))),
                _row("可镀层 / 可认证",
                     f"{'是' if _as_dict(c.get('achieve')).get('isPlated') else '否'} / "
                     f"{'是' if ach.get('canCertify') else '否'}"),
            ],
            "bars": [
                {"label": "周常", "value": _num(weekly.get("count")), "total": _num(weekly.get("total"))},
                {"label": "指标", "value": _num(indicator.get("count")), "total": _num(indicator.get("total"))},
                {"label": "关卡", "value": _num(stage.get("count")), "total": _num(stage.get("total"))},
            ],
        })
    if not items:
        cards.append(_card("当期合约", "暂无", "接口没有返回危机合约数据", "muted"))
        blocks.append({"title": "当期合约", "rows": [_row("状态", "未开放或无数据")]})
    return {
        "title": "危机合约", "icon": "data", "h5": H5["crisis"],
        "cards": cards, "blocks": blocks,
        "note": "终末地自己的危机合约玩法，与明日方舟的危机合约不是同一套。数据来自 card/detail.crisisContract。",
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
                str(normal.get("name") or hard.get("name") or "关卡"),
                ("普通 ✓" if npass else "普通 ✗") + " · " + ("苦难 ✓" if hpass else "苦难 ✗"),
                "good" if (npass and hpass) else ("muted" if not npass else ""),
            ))
        blocks.append({
            "title": str(gd.get("name") or "系列"),
            "rows": rows or [_row("暂无", "该系列没有关卡数据")],
        })
    cards = [
        _card("系列", len(groups)),
        _card("关卡", total),
        _card("普通通关", f"{normal_done} / {total}", "", "good" if normal_done else ""),
        _card("苦难通关", f"{hard_done} / {total}", "", "good" if hard_done else "muted"),
    ]
    if not groups:
        blocks.append({"title": "影拓丰碑", "rows": [_row("状态", "接口没有返回关卡组")]})
    return {
        "title": "影拓丰碑", "icon": "data", "h5": H5["monument"],
        "cards": cards, "blocks": blocks,
        "note": "数据来自 card/detail.indieHard.indieHardGroups；isPass 为服务端通关标记。",
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
        _card("赛季", len(seasons)),
        _card("累计星数", total_stars),
        _card("当前赛季星数", _num(_as_dict(seasons[0]).get("stars")) if seasons else 0),
        _card("成就", len(achieves)),
    ]
    if isinstance(best, dict):
        cards.append(_card("最佳记录", str(best.get("name") or best.get("score") or "—")))
    elif best:
        cards.append(_card("最佳记录", str(best)))

    blocks: list[dict] = []
    for s in seasons:
        sd = _as_dict(s)
        rows = [
            _row("周期", f"{_ts(sd.get('startTs')) or '—'} ~ {_ts(sd.get('endTs')) or '—'}"),
            _row("赛季星数", _num(sd.get("stars"))),
            _row("全加成", "是" if sd.get("allPlusTasks") else "否"),
        ]
        for w in _as_list(sd.get("weeks")):
            wd = _as_dict(w)
            dungeons = _as_list(wd.get("dungeonGroups"))
            plus = sum(1 for d in dungeons if _as_dict(d).get("plusTask"))
            rows.append(_row(
                str(wd.get("name") or "轮换"),
                f"★ {_num(wd.get('stars'))} · 加成 {plus}/{len(dungeons)}",
                "good" if _num(wd.get("stars")) else "",
            ))
            for d in dungeons[:8]:
                dd = _as_dict(d)
                rows.append(_row("　" + str(dd.get("name") or "关卡"),
                                 f"★ {_num(dd.get('star'))}" +
                                 (" · 加成 ✓" if dd.get("plusTask") else "")))
        blocks.append({"title": str(sd.get("name") or "赛季"), "rows": rows})
    if activity:
        blocks.append({"title": "活动", "rows": [
            _row(k, str(v)[:120]) for k, v in activity.items() if not isinstance(v, (dict, list))
        ] or [_row("状态", "接口返回了活动对象")]})
    if achieves:
        blocks.append({"title": "成就", "rows": [
            _row(str(_as_dict(a).get("name") or _as_dict(a).get("id") or "成就"),
                 str(_as_dict(a).get("desc") or _as_dict(a).get("value") or "已达成"))
            for a in achieves[:20]
        ]})
    if not blocks:
        blocks.append({"title": "战争回响", "rows": [_row("状态", "接口没有返回赛季数据")]})
    return {
        "title": "战争回响", "icon": "data", "h5": H5["echoes"],
        "cards": cards, "blocks": blocks,
        "note": "赛季/轮换/星数来自 /api/v1/game/endfield/card/war-echoes，摘要字段与 card/detail.warEchoes 同构。",
    }


# ------------------------------------------------------------------ 总入口


def overview(token: str) -> dict:
    """拉齐四个二级模块的数据，返回包侧 HTML 直接渲染的模型。宿主不解释任何字段。"""
    cred, secret = _login(token)

    binding = _signed_get("/api/v1/game/player/binding", "", cred, secret)
    app = next((a for a in _as_list(binding.get("list"))
                if _as_dict(a).get("appCode") == "endfield"), None)
    if app is None:
        raise SklandError("这个账号没有绑定《终末地》，森空岛接口没有返回 endfield 角色。")
    entries = _as_list(_as_dict(app).get("bindingList"))
    bound = _as_dict(entries[0]) if entries else {}
    roles = _as_list(bound.get("roles"))
    role = _as_dict(roles[0]) if roles else {}
    role_id = str(role.get("roleId") or "").strip()
    server_id = str(role.get("serverId") or bound.get("channelMasterId") or "").strip()
    if not role_id:
        raise SklandError("绑定列表里没有终末地 roleId，请先在森空岛绑定游戏角色。")

    teenager = _signed_get("/api/v1/user/teenager", "", cred, secret)
    user_id = str(_as_dict(teenager.get("teenager")).get("userId") or "").strip()
    if not user_id:
        raise SklandError("没有拿到森空岛 userId，接口可能已改版。")

    # 顺序参与签名，不要重排
    q = (f"roleId={urllib.parse.quote(role_id)}"
         f"&serverId={urllib.parse.quote(server_id)}"
         f"&userId={urllib.parse.quote(user_id)}")
    card = _signed_get("/web/v1/game/endfield/card/detail", q, cred, secret)
    detail = _as_dict(card.get("detail"))
    war = _signed_get("/api/v1/game/endfield/card/war-echoes", q, cred, secret)
    att = _signed_get("/web/v1/game/endfield/attendance", q, cred, secret)

    base = _as_dict(detail.get("base"))
    account = {
        "name": str(base.get("name") or bound.get("nickName") or "管理员"),
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

    return {
        "source": "live",
        "updatedAt": datetime.now(tz=CN_TZ).strftime("%Y-%m-%d %H:%M:%S"),
        "account": account,
        "modules": {
            "sign": _module_sign(att, detail),
            "crisis": _module_crisis(detail),
            "monument": _module_monument(detail),
            "echoes": _module_echoes(detail, war),
        },
        "h5": {"overview": H5["overview"], "home": H5["home"]},
    }
