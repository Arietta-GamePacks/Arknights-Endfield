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

响应：
    {"id": 1, "ok": true,  "result": {...}}
    {"id": 2, "ok": false, "error": {"message": "可直接展示给用户的中文提示"}}

设计要点：**fetch 直接返回 UGF 文件内容**（format/version/accounts/records）。
宿主不需要认识终末地，只要会读 UGF——增删任何游戏都不必动宿主代码。
"""

from __future__ import annotations

import json
import random
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from typing import Any

PROTOCOL = 1
PACK_ID = "arknights-endfield"
PACK_VERSION = "0.1.0"

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")

AS_HOST = "https://as.hypergryph.com"
BINDING_HOST = "https://binding-api-account-prod.hypergryph.com"
WEBVIEW_HOST = "https://ef-webview.hypergryph.com"

# 鹰角账号授权用的应用码；森空岛的授权码换不到寻访记录
HG_APP_CODE = "be36d44aa36bfb5b"
GAME_APP_CODE = "endfield"

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


def fetch_pages(path: str, u8: str, server: str, extra: dict[str, str]) -> list[dict]:
    rows: list[dict] = []
    next_seq = ""
    for _ in range(MAX_PAGES):
        q = {"lang": "zh-cn", "token": u8, "server_id": server, **extra}
        if next_seq:
            q["seq_id"] = next_seq
        res = http_json(f"{WEBVIEW_HOST}{path}?{urllib.parse.urlencode(q)}")
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


def char_pool_types(u8: str, server: str) -> list[str]:
    try:
        res = http_json(
            f"{WEBVIEW_HOST}/api/record/char/meta?"
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


def weapon_pools(u8: str, server: str) -> list[dict]:
    try:
        res = http_json(
            f"{WEBVIEW_HOST}/api/record/weapon/pool?"
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
        "capabilities": ["accounts", "fetch"],
    }


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
    cred = resolve_credential(str(params.get("token") or ""))
    u8, server = cred["u8_token"], cred["server_id"]

    char: dict[str, list[dict]] = {}
    for pool_type in char_pool_types(u8, server):
        try:
            char[pool_type] = fetch_pages(
                "/api/record/char", u8, server, {"pool_type": pool_type}
            )
        except ProviderError:
            char[pool_type] = []

    weapon: dict[str, list[dict]] = {}
    weapon_meta: dict[str, str] = {}
    rerun_ids: list[str] = []
    for p in weapon_pools(u8, server):
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
                "/api/record/weapon", u8, server, {"pool_id": pid}
            )
        except ProviderError:
            weapon[pid] = []

    if rerun_ids:
        try:
            merged = fetch_pages(
                "/api/record/weapon", u8, server, {"pool_ids": ",".join(rerun_ids)}
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
    return {
        "ugf": ugf,
        "summary": {
            "uid": cred["uid"],
            "server": cred["server_id"],
            "channel": cred["channel"],
            "nickname": cred["nickname"],
            "records": pulls,
        },
    }


METHODS = {
    "ping": method_ping,
    "accounts": method_accounts,
    "fetch": method_fetch,
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
