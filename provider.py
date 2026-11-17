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

import hashlib
import json
import random
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

# 包目录内每个文件都计入签名哈希：import 同目录模块默认会写 __pycache__/*.pyc，
# 那会让下一次验签失败。宿主启动的 provider 一律不落字节码。
sys.dont_write_bytecode = True
import gacha   # 同包目录：终末地抽卡统计引擎（gacha.py）
import l10n    # 同包目录：用户可见文案翻译表（assets/l10n.json，语言来自 params.ui_lang）
import skland  # 同包目录：森空岛数据终端（skland.py，端点/签名/字段映射全在包内）
import wiki_catalog  # 同包目录：森空岛 Wiki 图鉴图标按需解析（抽卡界面用）

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

# 森空岛社区模块的服隔离：GL（国际服）与 CN / BILI 不是同一套 API。
# 宿主透传的 server 是 game.json servers[].code 的通用变体码，包自己决定语义；
# 缺省（老宿主 / 包内探针不传 server）按 CN 走，保持旧行为。
COMMUNITY_WIP_SERVERS = {"GL"}


def community_is_wip(params: dict) -> bool:
    return str(params.get("server") or "").strip().upper() in COMMUNITY_WIP_SERVERS

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
    raise ProviderError(l10n.t("err.network", last))


# ------------------------------------------------------------------ 凭证链


def credential_param(params: dict) -> str:
    """
    宿主通用契约：社区已登录的凭证走 `credential`；
    `token` 是早期参数名，保留兼容（旧调用方 / 外部脚本）。
    """
    for key in ("credential", "token"):
        value = str(params.get(key) or "").strip()
        if value:
            return value
    return ""


def resolve_credential(account_token: str) -> dict[str, str]:
    """
    账号令牌 → 授权令牌 → uid / serverId → 角色令牌。
    账号令牌**不能**直接打记录接口，会返回 40100。
    """
    token = (account_token or "").strip()
    if not token:
        raise ProviderError(l10n.t("p.err.emptyToken"))

    granted = http_json(
        f"{AS_HOST}/user/oauth2/v2/grant",
        {"token": token, "appCode": HG_APP_CODE, "type": 1},
    )
    if granted.get("status") != 0:
        raise ProviderError(l10n.t("p.err.credInvalid"))
    oauth = (granted.get("data") or {}).get("token") or ""
    if not oauth:
        raise ProviderError(l10n.t("p.err.grantNoToken"))

    listing = http_json(
        f"{BINDING_HOST}/account/binding/v1/binding_list"
        f"?token={urllib.parse.quote(oauth)}&appCode={GAME_APP_CODE}"
    )
    if listing.get("status") != 0:
        raise ProviderError(l10n.t("p.err.bindingList", listing.get("msg") or ""))

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
        raise ProviderError(l10n.t("p.err.noBinding"))

    roles = [r for r in (binding.get("roles") or []) if isinstance(r, dict)]
    role = roles[0] if roles else {}
    server_id = str(role.get("serverId") or "") or "1"
    # 终末地的 UID = roles[].roleId（App 个人主页那个数字）；
    # bindingList[].uid 是**鹰角通行证账号级 uid**（跟明日方舟同一个数字），不能拿来当终末地 UID。
    role_id = str(role.get("roleId") or "").strip()

    exchanged = http_json(
        f"{BINDING_HOST}/account/binding/v1/u8_token_by_uid",
        # 这个接口要的是账号级 uid（bindingList[].uid），不是 roleId
        {"token": oauth, "uid": str(binding.get("uid"))},
    )
    if exchanged.get("status") != 0:
        raise ProviderError(l10n.t("p.err.u8Exchange", exchanged.get("msg") or ""))
    u8 = (exchanged.get("data") or {}).get("token") or ""
    if not u8:
        raise ProviderError(l10n.t("p.err.noU8"))

    return {
        "u8_token": u8,
        "uid": role_id or str(binding.get("uid") or ""),
        "role_id": role_id,
        "server_id": server_id,
        "channel": str(binding.get("channelName") or ""),
        "nickname": str(binding.get("nickName") or ""),
    }


# ------------------------------------------------------------------ 拉取


def seq_int(value: Any) -> int:
    try:
        return int(str(value or "").strip())
    except (TypeError, ValueError):
        return 0


def fetch_pages(path: str, u8: str, server: str, extra: dict[str, str],
                host: str | None = None, stop_seq: int = 0) -> list[dict]:
    """
    翻页拉取某个卡池的寻访记录（接口每页 5 条，靠 `seq_id` 游标往后翻）。

    `stop_seq` > 0 = 增量模式：seqId 在账号内单调递增、列表新到旧返回，
    所以一遇到 `seqId <= stop_seq` 就说明后面全是本地已有的，立刻停 ——
    已同步过的账号通常每池只花 1 个请求。
    """
    rows: list[dict] = []
    next_seq = ""
    base = host or WEBVIEW_HOST
    for _ in range(MAX_PAGES):
        q = {"lang": "zh-cn", "token": u8, "server_id": server, **extra}
        if next_seq:
            q["seq_id"] = next_seq
        res = http_json(f"{base}{path}?{urllib.parse.urlencode(q)}")
        if res.get("code") != 0:
            raise ProviderError(l10n.t("p.err.codeMsg", res.get("code"), res.get("msg") or ""))
        data = res.get("data") or {}
        items = data.get("list") or []
        if not items:
            break
        if stop_seq:
            fresh: list[dict] = []
            caught_up = False
            for item in items:
                if seq_int(item.get("seqId")) <= stop_seq:
                    caught_up = True
                    break
                fresh.append(item)
            rows.extend(fresh)
            if caught_up:
                break
        else:
            rows.extend(items)
        if not data.get("hasMore"):
            break
        next_seq = str(items[-1].get("seqId") or "")
        if not next_seq:
            break
        # 只做最低限度的节流；真正的吞吐来自「多卡池并发」，不再逐页 sleep 半秒
        time.sleep(random.uniform(0.04, 0.1))
    return rows


def fetch_all_pools(u8: str, server: str, host: str | None,
                    stop_char: int = 0, stop_weapon: int = 0
                    ) -> tuple[dict[str, list[dict]], dict[str, list[dict]], dict[str, str]]:
    """
    并发拉全部卡池：池子清单先并发取，再按池并发翻页。
    接口每页只给 5 条，串行翻页是之前「更新记录」慢到分钟级的主因。
    """
    with ThreadPoolExecutor(max_workers=4) as pool:
        types_future = pool.submit(char_pool_types, u8, server, host)
        weapons_future = pool.submit(weapon_pools, u8, server, host)
        char_types = types_future.result()
        weapon_list = weapons_future.result()

    char: dict[str, list[dict]] = {}
    weapon: dict[str, list[dict]] = {}
    weapon_meta: dict[str, str] = {}
    rerun_ids: list[str] = []

    jobs: dict[Any, tuple[str, str]] = {}
    with ThreadPoolExecutor(max_workers=8) as pool:
        for pool_type in char_types:
            jobs[pool.submit(
                fetch_pages, "/api/record/char", u8, server,
                {"pool_type": pool_type}, host, stop_char,
            )] = ("char", pool_type)

        for entry in weapon_list:
            pid = str(entry.get("poolId") or "").strip()
            if not pid:
                continue
            pool_type = str(entry.get("poolType") or "").strip() or "normal"
            weapon_meta[pid] = pool_type
            if pool_type == "rerun":
                rerun_ids.append(pid)
                continue
            jobs[pool.submit(
                fetch_pages, "/api/record/weapon", u8, server,
                {"pool_id": pid}, host, stop_weapon,
            )] = ("weapon", pid)

        if rerun_ids:
            jobs[pool.submit(
                fetch_pages, "/api/record/weapon", u8, server,
                {"pool_ids": ",".join(rerun_ids)}, host, stop_weapon,
            )] = ("rerun", ",".join(rerun_ids))

        for future, (family, key) in jobs.items():
            try:
                rows = future.result()
            except Exception:
                rows = []
            if family == "char":
                char[key] = rows
            elif family == "weapon":
                weapon[key] = rows
            else:
                for pid in rerun_ids:
                    weapon.setdefault(pid, [])
                for item in rows:
                    pid = str(item.get("poolId") or "").strip()
                    weapon.setdefault(pid, []).append(item)

    return char, weapon, weapon_meta


# ------------------------------------------------------------- 本地缓存


CACHE_VERSION = 2   # v2：uid 口径从「鹰角账号级 uid」改成「终末地 roleId」，旧缓存直接作废


def cache_key(params: dict) -> str:
    """
    缓存按**凭证指纹**分文件，不按 uid —— 因为 uid 要联网才换得出来，
    而「打开页面只读盘」这一档必须一个请求都不打。
    """
    seed = credential_param(params) or str(params.get("u8_token") or "").strip()
    if not seed:
        return ""
    return hashlib.sha1(seed.encode("utf-8")).hexdigest()[:16]


def cache_file(data_dir: str, key: str) -> Path | None:
    if not data_dir or not key:
        return None
    return Path(data_dir) / f"gacha-{key}.json"


def _read_cache_file(path: Path) -> dict[str, Any] | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) and data.get("version") == CACHE_VERSION else None


def load_cache(data_dir: str, key: str) -> dict[str, Any] | None:
    path = cache_file(data_dir, key)
    if path is None or not path.is_file():
        return None
    return _read_cache_file(path)


def load_only_cache(data_dir: str) -> dict[str, Any] | None:
    """凭证指纹对不上时的兜底（例如只在日志通道同步过）：目录里只有一份就用它。"""
    try:
        files = sorted(Path(data_dir).glob("gacha-*.json"))
    except OSError:
        return None
    if len(files) != 1:
        return None
    return _read_cache_file(files[0])


def save_cache(data_dir: str, key: str, cache: dict[str, Any]) -> None:
    path = cache_file(data_dir, key)
    if path is None:
        return
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")
        tmp.replace(path)
    except OSError:
        pass       # 缓存写不进去不影响本次结果


def max_seq(pools: dict[str, list[dict]]) -> int:
    return max(
        (seq_int(item.get("seqId")) for items in pools.values() for item in items),
        default=0,
    )


def merge_pools(old: dict[str, list[dict]] | None,
                new: dict[str, list[dict]] | None) -> dict[str, list[dict]]:
    """按 seqId 去重合并：缓存里的老记录 + 本次新拉到的记录。"""
    merged = {key: list(items) for key, items in (old or {}).items()}
    for key, items in (new or {}).items():
        bucket = merged.setdefault(key, [])
        seen = {str(item.get("seqId") or "") for item in bucket}
        for item in items:
            sid = str(item.get("seqId") or "")
            if sid and sid in seen:
                continue
            bucket.append(item)
            if sid:
                seen.add(sid)
    return merged


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
                         "gacha-stats", "gacha-url", "gacha-model", "skland-overview",
                         "community-model", "community-action"],
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
        raise ProviderError(l10n.t("p.err.noticeBad"))
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
        raise ProviderError(l10n.t("p.err.noticeEmpty"))
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
        raise ProviderError(l10n.t("p.err.bgEmpty"))
    return {"video": video, "poster": bg.get("url") or ""}


def method_accounts(params: dict) -> dict[str, Any]:
    cred = resolve_credential(credential_param(params))
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

    # 取数模式（宿主决定）：
    #   cache       打开页面：**只读本地盘**，一个网络请求都不打；没有缓存就回 needs_sync
    #   incremental 「更新记录」增量补拉，靠 seqId 游标遇到旧记录即停
    #   full        全量重拉（换账号 / 清过缓存 / 用户主动点）
    # 同步一律手动触发（Alpha 2026-11-16）：打开页面不打卡、不自动联网。
    mode = str(params.get("mode") or "cache").strip().lower()
    if mode not in ("cache", "incremental", "full"):
        mode = "cache"
    data_dir = str(params.get("data_dir") or "").strip()
    key = cache_key(params)

    if mode == "cache":
        cache = load_cache(data_dir, key) or load_only_cache(data_dir)
        if cache is None:
            # 故意不联网：没同步过就老老实实回空态，等用户点「更新记录」
            return {"needs_sync": True}
        cred = {
            "uid": str(cache.get("uid") or ""),
            "server_id": str(cache.get("server") or "1"),
            "channel": str(cache.get("channel") or ""),
            "nickname": str(cache.get("nickname") or ""),
        }
        ugf = build_ugf(cred, cache.get("char") or {}, cache.get("weapon") or {},
                        cache.get("weapon_meta") or {}, lang)
        return {
            "ugf": ugf,
            "summary": {
                "uid": cred["uid"],
                "server": cred["server_id"],
                "channel": cred["channel"],
                "nickname": cred["nickname"],
                "records": len(ugf["accounts"][0]["records"]),
                "provider": "cache",
                "source": "cache",
                "cached_at": cache.get("updated") or "",
                "pool_info": cache.get("pool_info") or {},
                "rerun_counts": cache.get("rerun_counts") or {},
            },
        }

    # ---- 以下都会联网：只有「更新记录 / 全量重拉」才会走到这里 ----

    # 两条凭证路径：
    #  1) 社区登录的凭证（`credential`，旧参数名 `token`）→ 鹰角授权链 → u8_token（国服，主路径）；
    #  2) 客户端日志里的 u8_token（gacha-url 提供）→ 直接打 ef-webview（含国际服；
    #     1.1 起官方不再把寻访页链接写进 HGWebview.log，只剩旧客户端 / 国际服可用）。
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
        cred = resolve_credential(credential_param(params))
        host = WEBVIEW_HOST
        provider_name = "hypergryph"
    u8, server = cred["u8_token"], cred["server_id"]

    cache = load_cache(data_dir, key)
    stop_char = seq_int(cache.get("max_seq_char")) if (cache and mode == "incremental") else 0
    stop_weapon = seq_int(cache.get("max_seq_weapon")) if (cache and mode == "incremental") else 0
    char, weapon, weapon_meta = fetch_all_pools(u8, server, host, stop_char, stop_weapon)
    if cache and mode == "incremental":
        char = merge_pools(cache.get("char"), char)
        weapon = merge_pools(cache.get("weapon"), weapon)
        if not weapon_meta:
            weapon_meta = cache.get("weapon_meta") or {}

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
    want_pool_info = str(params.get("with_pool_info", "true")).strip().lower() \
        not in ("false", "0", "no")
    pool_info = fetch_pool_info(server, host, pool_ids) if want_pool_info else {}
    rerun_counts = fetch_rerun_counts(u8, server, host)
    save_cache(data_dir, key, {
        "version": CACHE_VERSION,
        "uid": cred["uid"],
        "server": server,
        "channel": cred["channel"],
        "nickname": cred["nickname"],
        "updated": datetime.now().astimezone().isoformat(timespec="seconds"),
        "max_seq_char": max_seq(char),
        "max_seq_weapon": max_seq(weapon),
        "char": char,
        "weapon": weapon,
        "weapon_meta": weapon_meta,
        "pool_info": pool_info,
        "rerun_counts": rerun_counts,
    })

    return {
        "ugf": ugf,
        "summary": {
            "uid": cred["uid"],
            "server": cred["server_id"],
            "channel": cred["channel"],
            "nickname": cred["nickname"],
            "records": pulls,
            "provider": provider_name,
            "source": mode,
            "cached_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            "pool_info": pool_info,
            "rerun_counts": rerun_counts,
        },
    }


# ------------------------------------------------- 抽卡统计 / 日志链接（包侧游戏知识）


def query_uid_from_u8(u8: str, provider: str, server: str) -> str:
    """
    日志链接模式：用 u8_token 反查终末地 UID。
    **UID = roles[].roleId**（不是 `data.uid`，那是鹰角账号级 uid，和方舟同一个数字）。失败静默。
    """
    try:
        res = http_json(
            f"https://u8.{provider}.com/game/role/v1/query_role_list",
            {"token": u8, "serverId": server},
        )
        data = res.get("data") or {}
        roles = [r for r in (data.get("roles") or []) if isinstance(r, dict)]
        for role in roles:
            if str(role.get("serverId") or "") == str(server):
                role_id = str(role.get("roleId") or "").strip()
                if role_id:
                    return role_id
        for role in roles:
            role_id = str(role.get("roleId") or "").strip()
            if role_id:
                return role_id
        return str(data.get("uid") or "").strip()
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


def _icon_resolver(params: dict, allow_download: bool):
    """
    抽卡图标解析器：数据目录在才建；cache 模式只读缓存（绝不联网，Alpha 钦定
    「同步一律手动」），手动同步后放行下载。缺图/无数据目录返回 None → 名称占位。
    """
    data_dir = str(params.get("data_dir") or "").strip()
    if not data_dir:
        return None
    resolver = wiki_catalog.IconResolver(data_dir)
    return resolver.resolve if allow_download else resolver.resolve_cached


def method_gacha_stats(params: dict) -> dict[str, Any]:
    """UGF → 通用渲染模型。统计口径全在包内 gacha.py，宿主只负责把模型交给页面。"""
    ugf = params.get("ugf") or {}
    if not isinstance(ugf, dict) or not (ugf.get("accounts") or []):
        raise ProviderError(l10n.t("p.err.noStats"))
    model = gacha.analyze(
        ugf,
        pool_info=params.get("pool_info") or {},
        rerun_counts=params.get("rerun_counts") or {},
        source=str(params.get("source") or "live"),
    )
    return {"model": model}


# 空态提示文案（跟抽卡语言走；池列名等服务端术语保持简中，不在此列）
_GACHA_HINTS: dict[str, dict[str, str]] = {
    "zh-cn": {"needs_sync": "还没有本地寻访记录。点「更新记录」手动同步一次"
                            "（首次要翻完所有卡池，会慢一点。）",
              "auth": "寻访记录与森空岛账号共用同一份登录凭证。"
                      "先在社区页登录账号，再回来点「更新记录」。"},
    "zh-TW": {"needs_sync": "還沒有本地尋訪記錄。點「更新記錄」手動同步一次"
                            "（首次要翻完所有卡池，會慢一點。）",
              "auth": "尋訪記錄與森空島帳號共用同一份登入憑證。"
                      "先在社群頁登入帳號，再回來點「更新記錄」。"},
    "en": {"needs_sync": "No local records yet. Click Refresh to sync once "
                         "(the first run walks through every pool, so it can take a while).",
           "auth": "Records share the login with your community account. "
                   "Log in on the Community page first, then click Refresh."},
    "ja": {"needs_sync": "ローカルの記録がまだありません。「記録を更新」で一度同期してください"
                         "（初回は全プールを巡回するため時間がかかります）。",
           "auth": "記録はコミュニティアカウントのログインと共通です。"
                   "先にコミュニティページでログインしてから「記録を更新」してください。"},
    "ko": {"needs_sync": "아직 로컬 기록이 없습니다. 「기록 업데이트」를 눌러 한 번 동기화하세요"
                         "(첫 실행은 모든 카드풀을 순회해 시간이 걸립니다).",
           "auth": "기록은 커뮤니티 계정 로그인과 공유됩니다. "
                   "먼저 커뮤니티 페이지에서 로그인한 뒤 「기록 업데이트」를 누르세요."},
    "ru": {"needs_sync": "Локальных записей пока нет. Нажмите «Обновить» для синхронизации "
                         "(первый раз обходит все пулы — это долго).",
           "auth": "Записи используют тот же вход, что и аккаунт сообщества. "
                   "Сначала войдите на странице сообщества, затем нажмите «Обновить»."},
    "th": {"needs_sync": 'ยังไม่มีบันทึกในเครื่อง กด "อัปเดต" เพื่อซิงก์ครั้งแรก '
                         '(ครั้งแรกจะวนทุกพูล ใช้เวลานาน)',
           "auth": 'บันทึกใช้การเข้าสู่ระบบร่วมกับบัญชีชุมชน โปรดเข้าสู่ระบบที่หน้าชุมชนก่อนแล้วกด "อัปเดต"'},
}


def _gacha_hints(lang: str) -> dict[str, str]:
    return _GACHA_HINTS.get(gacha.canonical_language(lang)) or _GACHA_HINTS["zh-cn"]


def method_gacha_model(params: dict) -> dict[str, Any]:
    """
    原生 WinUI3 抽卡页的数据源：宿主一次调用拿到通用列模型。

    同步**一律手动**（Alpha 2026-11-16）：`mode=cache` 是打开页面用的，只读本地盘，
    没有缓存就回 `needsSync`，绝不自己联网补数据。

    联网只在用户点「更新记录 / 全量重拉」时发生，且两条凭证通道**都走**：
      1) 社区登录的凭证 `credential` → 授权链换 u8_token（国服，与社区同一份 token）；
      2) 客户端日志里的 u8_token（`gacha-url`）→ 直接打 ef-webview（国际服 / 旧客户端）。
    先试 1，失败或拉不到记录就自动切 2；两条都挂才报错，并把两边的原因一起吐出来。
    两者都没有时返回 `authRequired`，宿主据此画「去登录社区账号」的空态。
    """
    credential = credential_param(params)
    u8 = str(params.get("u8_token") or "").strip()
    mode = str(params.get("mode") or "cache").strip().lower()
    # 物品名显示语言（设置面板「语言」）：显示层翻译，缓存重渲染即可生效，不联网
    lang = str(params.get("lang") or "zh-cn").strip()

    def payload(fetched: dict, source: str = "", channels: int = 0,
                allow_icons: bool = True) -> dict:
        summary = fetched.get("summary") or {}
        model = gacha.winui_model(
            fetched["ugf"],
            pool_info=summary.get("pool_info") or {},
            demo=False,
            uid=str(summary.get("uid") or ""),
            icon_resolver=_icon_resolver(params, allow_icons),
            lang=lang,
        )
        model["source"] = source or summary.get("source") or ""
        model["cachedAt"] = summary.get("cached_at") or ""
        model["languages"] = gacha.available_languages()
        if channels > 1:
            model["channels"] = channels
        return model

    if mode == "cache":
        try:
            cached = method_fetch(params)
        except ProviderError:
            cached = {"needs_sync": True}
        if cached.get("needs_sync"):
            hint = _gacha_hints(lang)
            return {
                "needsSync": True,
                "syncHint": hint["needs_sync"],
                "account": {"uid": "", "display": "", "subtitle": ""},
                "pools": [],
                "items": [],
            }
        return payload(cached, allow_icons=False)

    if not (credential or u8):
        if str(params.get("demo") or "").strip().lower() in ("1", "true", "yes"):
            model = gacha.winui_model(
                gacha.demo_ugf(), pool_info=gacha.demo_pool_info(), demo=True,
                uid="10000001", lang=lang,
            )
            model["languages"] = gacha.available_languages()
            return model
        return {
            "authRequired": True,
            "authHint": _gacha_hints(lang)["auth"],
            "account": {"uid": "", "display": "", "subtitle": ""},
            "pools": [],
            "items": [],
        }

    channels: list[tuple[str, str, dict]] = []
    if credential:
        channels.append((
            "community",
            l10n.t("p.channel.community"),
            {k: v for k, v in params.items() if k != "u8_token"},
        ))
    if u8:
        log_params = dict(params)
        log_params["credential"] = ""
        log_params["token"] = ""
        channels.append(("log", l10n.t("p.channel.log"), log_params))

    fetched: dict | None = None
    source = ""
    reasons: list[str] = []
    for key, label, channel_params in channels:
        try:
            data = method_fetch(channel_params)
        except ProviderError as exc:
            reasons.append(l10n.t("p.reasonItem", label, exc))
            continue
        records = data["ugf"]["accounts"][0]["records"]
        if fetched is None or records:
            fetched, source = data, key
        if records:
            break

    if fetched is None:
        raise ProviderError(l10n.t("p.err.bothChannels", l10n.t("p.joiner").join(reasons)))

    return payload(fetched, source, len(channels))


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
    raise ProviderError(l10n.t("p.err.noLogUrl"))


def method_skland_overview(params: dict) -> dict[str, Any]:
    """
    森空岛「数据终端」原始数据（skland.overview 直通，供包外探针 / 调试用）。
    params.token = 鹰角账号 token。端点、appCode、sign 签名、字段映射、官方 H5 链接
    全部在包内 skland.py。
    """
    token = str(params.get("token") or "").strip()
    try:
        return skland.overview(token)
    except skland.SklandError as e:
        raise ProviderError(str(e))


def method_community_action(params: dict) -> dict[str, Any]:
    """
    通用社区动作（宿主调用；动作语义全在包内 skland.py/登录链）：
      action="signin"          签到，params.credential 同 community-model
      action="login-send-code" 短信发码，params.phone [+ params.captcha]
                               风控命中返回 {ok:false, needCaptcha:true, gt, challenge, newCaptcha}
      action="login-phone"     短信验证码登录，params.phone + params.code
                               成功返回 {ok:true, credential:<鹰角 token>}
      action="login-password"  手机号密码登录，params.phone + params.password
                               成功返回 {ok:true, credential:<鹰角 token>}
      action="login-qrcode-create" 创建扫码二维码 → {ok, scanId, url}
      action="login-qrcode-poll"   轮询扫码，params.scanId
                               等待 {ok:true, state:pending|scanned}；过期 {ok:true, state:expired}
                               成功 {ok:true, state:confirmed, credential:<鹰角 token>}
      action="h5-terminal"     官方 H5 数据终端打开参数 → {ok, webWindow:{title,url,ua,script}}
                               cred 现算现嵌进注入脚本，不进模型缓存
    params.server = 宿主变体码（GL / CN / BILI）；GL 的所有动作直接返回未开发提示，
    不触碰国服森空岛接口。故意不抛错：返回 {ok, message, ...} 供宿主处理。
    """
    action = str(params.get("action") or "").strip()

    # 国际服与国服不走同一套森空岛 API：GL 的所有社区动作一律不下发请求。
    if community_is_wip(params):
        return {"ok": False, "message": l10n.t("p.panel.wip")}

    if action == "login-send-code":
        phone = str(params.get("phone") or "").strip()
        captcha = params.get("captcha") or None
        try:
            return skland.send_phone_code(phone, captcha)
        except skland.SklandError as e:
            return {"ok": False, "message": str(e)}

    if action == "login-phone":
        phone = str(params.get("phone") or "").strip()
        code = str(params.get("code") or "").strip()
        try:
            return {"ok": True, "credential": skland.token_by_phone_code(phone, code)}
        except skland.SklandError as e:
            return {"ok": False, "message": str(e)}

    if action == "login-password":
        phone = str(params.get("phone") or "").strip()
        password = str(params.get("password") or "")
        try:
            return {"ok": True, "credential": skland.token_by_phone_password(phone, password)}
        except skland.SklandError as e:
            return {"ok": False, "message": str(e)}

    if action == "login-qrcode-create":
        try:
            return skland.qrcode_login_create()
        except skland.SklandError as e:
            return {"ok": False, "message": str(e)}

    if action == "login-qrcode-poll":
        scan_id = str(params.get("scanId") or "").strip()
        try:
            return skland.qrcode_login_poll(scan_id)
        except skland.SklandError as e:
            return {"ok": False, "message": str(e)}

    token = str(params.get("credential") or params.get("token") or "").strip()
    if action == "h5-terminal":
        if not token:
            return {"ok": False, "message": l10n.t("p.err.noCredShort")}
        try:
            return skland.web_terminal(token)
        except skland.SklandError as e:
            return {"ok": False, "message": str(e)}
    if action != "signin":
        return {"ok": False, "message": l10n.t("p.err.unknownAction", action or "-")}
    if not token:
        return {"ok": False, "message": l10n.t("p.err.noCredShort")}
    try:
        return skland.sign_in(token)
    except skland.SklandError as e:
        return {"ok": False, "message": str(e)}


def method_community_model(params: dict) -> dict[str, Any]:
    """
    原生社区模块模型（宿主 PackCommunityPage 渲染，字段语义全在包内）：
      account    账号栏（头像 / 昵称 / 等级）
      items      左侧菜单（id / label / icon；带 url = 外链，宿主交系统浏览器）
      credential 凭证含义（宿主只管存取，调用时经 params.credential 透传回来）
      accountSwitcher {enabled:bool} 顶部账号切换器是否可交互（通用字段，宿主消费）
      panels     panels.<id> = title/cards/blocks/calendar/links/note 通用块，
                 或 placeholder（宿主在内容区正中显示的一句占位文案）
      error      模型级错误文案（凭证缺失 / 接口失败）。故意不抛错：
                 让菜单骨架照常显示，用户才有地方去改凭证。

    params.server = 宿主变体码（GL / CN / BILI）。2026-11-17：
    - CN / BILI：危机合约 / 影拓丰碑 / 战争回响三页只留本地化的「未开发完成」占位；
    - GL（国际服）：导航栏原样，五个页面全部占位，一个森空岛请求都不发，
      账号切换器禁用。两套服务器彻底隔离。
    """
    token = str(params.get("credential") or params.get("token") or "").strip()
    wip_server = community_is_wip(params)
    # 三玩法占位面板是静态的：没凭证 / 接口失败时也照常显示，宿主才不会给出
    # 「这个面板没有返回数据」的空态。文案按 params.ui_lang 走 l10n.t。
    # GL 与国际服不是同一套 API：五个页面全部占位，且一个请求都不往 CN 森空岛发。
    unfinished = ("sign", "crisis", "monument", "echoes", "gamedata") if wip_server \
        else ("crisis", "monument", "echoes")
    wip_text = l10n.t("p.panel.wip")

    # 导航栏原样保留（id / 标题 / 图标 / 顺序 / 分割线都不动）；GL 只摘掉动作，
    # 让「游戏数据」点击后也走面板占位，而不是开 CN 的 H5 手机窗口。
    gamedata: dict[str, Any] = {
        "id": "gamedata", "label": l10n.t("menu.gamedata"),
        "icon": "assets/toolbox/游戏数据.png", "separator": True,
    }
    if not wip_server:
        # 游戏数据不再走 WinUI 面板：点击直接开官方 H5 手机窗口（community-action
        # 的 h5-terminal 动作，webWindow 结果），separator = 项上画一条分割线
        gamedata["action"] = "h5-terminal"

    model: dict[str, Any] = {
        "account": None,
        "items": [
            {"id": "sign", "label": l10n.t("k.sign.title"), "icon": "assets/toolbox/每日签到.png"},
            {"id": "crisis", "label": l10n.t("k.crisis.title"), "icon": "assets/section/危机合约.png"},
            {"id": "monument", "label": l10n.t("k.mon.title"), "icon": "assets/section/影拓丰碑.png"},
            {"id": "echoes", "label": l10n.t("k.echo.title"), "icon": "assets/section/战争回响.png"},
            gamedata,
        ],
        "credential": {
            "label": l10n.t("p.cred.label"),
            # 宿主把 [文案](url) 渲染成可点超链接；content 字段在第二个链接的页面里
            "help": l10n.t("p.cred.help"),
            "required": True,
        },
        # 通用协议字段：宿主据此禁用社区页顶部账号切换器（上下箭头 + 头像入口）。
        # 不含任何游戏语义；旧包不给这个字段时宿主默认可交互。
        "accountSwitcher": {"enabled": not wip_server},
        "panels": {mid: {"placeholder": wip_text} for mid in unfinished},
        "error": None,
    }
    if wip_server:
        return model
    if not token:
        model["error"] = l10n.t("p.err.modelNoCred")
        return model
    try:
        # 只要签到数据：不请求 war-echoes 独立接口，也不构建三玩法面板
        ov = skland.overview(token, modules=("sign",))
    except skland.SklandError as e:
        model["error"] = str(e)
        return model

    acc = ov.get("account") or {}
    model["account"] = {
        "name": acc.get("name") or "",
        # 游戏 uid：账号栏与抽卡页的账号下拉都靠它认人（昵称可能为空）
        "uid": acc.get("uid") or "",
        "level": acc.get("level") or 0,
        "avatar": acc.get("avatar") or "",
    }
    panels: dict[str, Any] = dict(model["panels"])
    sign = (ov.get("modules") or {}).get("sign") or {}
    if sign:
        panel = dict(sign)
        h5 = str(sign.get("h5") or "").strip()
        if h5:
            panel["links"] = [{"label": l10n.t("p.panel.openH5"), "url": h5}]
        panels["sign"] = panel
    # 三玩法永远只留占位，避免以后 overview 重新带上数据时旧内容回流到页面
    for mid in unfinished:
        panels[mid] = {"placeholder": wip_text}
    model["panels"] = panels
    return model


METHODS = {
    "ping": method_ping,
    "skland-overview": method_skland_overview,
    "community-model": method_community_model,
    "community-action": method_community_action,
    "accounts": method_accounts,
    "fetch": method_fetch,
    "notice": method_notice,
    "background": method_background,
    "gacha-stats": method_gacha_stats,
    "gacha-url": method_gacha_url,
    "gacha-model": method_gacha_model,
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

    # 宿主注入的界面语言（GamePack.LanguageTagFor）：错误消息 / 模型文案按它翻译。
    # 请求为空 / 不是合法 JSON 发生在解析前，拿不到语言，维持简中兜底。
    l10n.set_lang(str((params or {}).get("ui_lang") or ""))

    handler = METHODS.get(method)
    if handler is None:
        print(json.dumps({"id": req_id, "ok": False,
                          "error": {"message": l10n.t("p.err.unknownMethod", method)}},
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
