#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
终末地抽卡统计引擎（游戏包内部模块，纯标准库）

输入：UGF v1.3 文档（provider.py 的 fetch 产出的那一份），以及可选的
      「官方累计寻访次数」与「卡池 UP 信息」。
输出：与游戏无关的通用渲染模型（cards / bars / pools / history / notes），
      由 ui/gacha.html 渲染；宿主不认识任何终末地字段。

口径来源（本地参考库，2026-11-15 阅读）：
  D:/Work/Github/Endfield/endfield-gacha-master/app/utils/gachaCalc.ts
  D:/Work/Github/Endfield/endfield-gacha-master/app/composables/gacha/useGachaStatistics.ts
  D:/Work/Github/Endfield/nonebot-plugin-skland-master/nonebot_plugin_skland/schemas/endfield/gacha/*.py

要点：
  - 免费抽（isFree）计入总抽与稀有度，但既不推进也不重置保底；
  - 6★ 小保底 80（特许 / 重构跨池共享，基础 / 启程 / 辉光各自独立）；
  - 特许寻访每池 120 抽必出当期 UP；重构寻访 120 抽大保底跨版本继承，
    优先采用官方「累计寻访次数」（服务器权威，官方只保留 90 天明细）；
  - 武器申领 40 抽必出 6★（仅 25% 为 UP）/ 80 抽必得当期 UP，按池独立；
    100 抽是累计自选常驻 6★ 奖励（非保底，勿混淆）；重构申领按期次分段；
  - UP / 歪判定依赖 /api/content 的 up6 名单，缺失时标「未知」，不臆造；
  - 武库配额：角色池 4★=20 / 5★=200 / 6★=2000，武器池每十连消耗 1980。
"""

from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

import l10n  # 同包目录：池列名多语表（assets/l10n.json pool.*）

CHAR_POOLS = {
    "E_CharacterGachaPoolType_Special": ("特许寻访", "special"),
    "E_CharacterGachaPoolType_Rerun": ("重构寻访", "rerun"),
    "E_CharacterGachaPoolType_Joint": ("辉光庆典", "joint"),
    "E_CharacterGachaPoolType_Standard": ("基础寻访", "standard"),
    "E_CharacterGachaPoolType_Beginner": ("启程寻访", "beginner"),
}
CHAR_ORDER = ["special", "rerun", "joint", "standard", "beginner"]
CHAR_LABELS = {v[1]: v[0] for v in CHAR_POOLS.values()}

WEAPON_LABELS = {
    "special": "限定申领",
    "constant": "常驻申领",
    "rerun": "重构申领",
    "normal": "武器申领",
}

SMALL_PITY_CHAR = 80
# 武器申领：40 抽必出 6★（仅 25% 为 UP）/ 80 抽必得当期 UP，按池独立；
# 100 抽是累计自选常驻 6★ 奖励，不是保底。三方口径一致（endfield-gacha 工具、
# nonebot 参考库、公开资料，2026-11-16 核实，来源见 docs/endfield-gacha-抽卡工具逻辑分析-交接.md）。
SMALL_PITY_WEAPON = 40
BIG_PITY_CHAR = 120
BIG_PITY_WEAPON = 80

ARSENAL_EARN = {4: 20, 5: 200, 6: 2000}
ARSENAL_TEN_PULL_COST = 1980

# 稀有度三色（包口径）：6★ 红 / 5★ 金 / 4★ 紫；宿主页内标识用同一套
COLOR_6 = "#FF5C5C"
COLOR_5 = "#FFD751"
COLOR_4 = "#A97EE3"


def _as_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _seq_key(seq: str) -> int:
    n = _as_int(seq)
    return n if n is not None else 0


def char_kind(pool_type: str, pool_id: str) -> str:
    if pool_type in CHAR_POOLS:
        return CHAR_POOLS[pool_type][1]
    pid = (pool_id or "").lower()
    if pid.startswith("rerun_chr_") or "rerun_chr" in pid:
        return "rerun"
    if "joint" in pid:
        return "joint"
    if "special" in pid:
        return "special"
    if "beginner" in pid:
        return "beginner"
    return "standard"


def weapon_kind(pool_type: str, pool_id: str) -> str:
    pid = (pool_id or "").lower()
    pt = (pool_type or "").lower()
    if pt == "rerun" or pid.startswith("rerun") or "rerun_wpn" in pid:
        return "rerun"
    if pt == "constant" or "constant" in pid:
        return "constant"
    if pt in ("special", "normal", ""):
        return "special"
    return pt


def normalize(ugf: dict) -> tuple[dict, list[dict]]:
    """UGF → (账号信息, 归一化后的记录列表，按时间正序)。"""
    accounts = (ugf or {}).get("accounts") or []
    account = accounts[0] if isinstance(accounts, list) and accounts else {}
    raw = account.get("records") or []

    rows: list[dict] = []
    for r in raw:
        if not isinstance(r, dict):
            continue
        x = r.get("x_endfield") or {}
        if not isinstance(x, dict):
            x = {}
        pool = str(r.get("pool") or "").strip()
        pool_type = str(x.get("pool_type") or "").strip()
        is_weapon = r.get("item_type") == "武器" or str(x.get("item_type") or "") == "weapon"
        rows.append({
            "pool": pool,
            "pool_name": str(x.get("pool_name") or "").strip() or pool,
            "pool_type": pool_type,
            "kind": weapon_kind(pool_type, pool) if is_weapon else char_kind(pool_type, pool),
            "weapon": is_weapon,
            "item_id": str(r.get("item_id") or "").strip(),
            "name": str(r.get("name") or "").strip(),
            "rarity": _as_int(r.get("rarity")),
            "is_free": bool(x.get("is_free")),
            "is_new": bool(x.get("is_new")),
            "time": str(r.get("time") or ""),
            "seq": str(r.get("id") or "").strip(),
            "pool_version": x.get("pool_version"),
        })
    rows.sort(key=lambda p: (p["time"], _seq_key(p["seq"])))
    meta = {
        "uid": str(account.get("uid") or ""),
        "server": str(account.get("server") or ""),
        "lang": str(account.get("lang") or ""),
        "timezone": str(account.get("timezone") or ""),
        "records": len(rows),
    }
    return meta, rows


def _pool_changed(a: dict, b: dict) -> bool:
    """两条记录是否属于不同的申领段：poolId 变化，或重构申领的期次（poolVersion）变化。"""
    return a["pool"] != b["pool"] or a["pool_version"] != b["pool_version"]


def pity_from_end(pulls: list[dict], *, up_only: bool = False,
                  up_ids: set[str] | None = None, cap: int | None = None,
                  per_pool: bool = False) -> int:
    """从最新往回数「付费抽」，遇到重置项停止。免费抽跳过（不推进也不重置）。
    per_pool：回溯到更早的另一个申领就停——武器每个申领独立保底，不能跨池垫。"""
    count = 0
    latest = pulls[-1] if pulls else None
    for p in reversed(pulls):
        if per_pool and latest is not None and _pool_changed(p, latest):
            break
        if p["is_free"]:
            continue
        if p["rarity"] == 6:
            if not up_only or (up_ids and p["item_id"] in up_ids):
                break
        count += 1
        if cap is not None and count >= cap:
            return cap
    return count


def six_history(pulls: list[dict], up_ids: set[str] | None, *,
                per_pool: bool = False,
                up_map: dict[str, set[str]] | None = None) -> list[dict]:
    """6★ 历史：每条带「本抽是第几抽」、UP / 歪 / 未知 / 赠送标记。
    per_pool：付费垫抽按申领分段重置（poolId / poolVersion 变化即新一段）；
              UP 判定按每条记录所属池的名单（up_map），缺名单的池标「6★」不臆断。"""
    history: list[dict] = []
    paid_pity = 0
    prev: dict | None = None
    for p in pulls:
        if per_pool and prev is not None and _pool_changed(p, prev):
            paid_pity = 0
        prev = p
        if p["rarity"] != 6:
            if not p["is_free"]:
                paid_pity += 1
            continue
        if p["is_free"]:
            tag, tone = "赠送", "muted"
            pity = 0
        else:
            paid_pity += 1
            pity = paid_pity
            paid_pity = 0
            ids = up_map.get(p["pool"]) if per_pool else up_ids
            if not ids:
                tag, tone = "6★", "muted"
            elif p["item_id"] in ids:
                tag, tone = "UP", "good"
            else:
                tag, tone = "歪", "bad"
        history.append({
            "time": p["time"][:16].replace("T", " "),
            "name": p["name"] or p["item_id"] or "—",
            "pity": pity,
            "tag": tag,
            "tone": tone,
            "new": bool(p["is_new"]),
            "pool": p["pool_name"],
        })
    history.reverse()
    return history


def arsenal_earned(pulls: list[dict]) -> int:
    return sum(ARSENAL_EARN.get(p["rarity"] or 0, 0) for p in pulls)


def ten_pull_count(pulls: list[dict]) -> int:
    """同一时间戳内 seq 连续的付费抽算一次十连（武器池武库配额消耗用）。"""
    by_time: dict[str, list[dict]] = defaultdict(list)
    for p in pulls:
        if not p["is_free"]:
            by_time[p["time"]].append(p)
    total = 0
    for items in by_time.values():
        seqs = sorted(_seq_key(p["seq"]) for p in items)
        if not seqs:
            continue
        groups = 1
        for i in range(1, len(seqs)):
            if seqs[i] != seqs[i - 1] + 1:
                groups += 1
        total += groups
    return total


def count_rarity(pulls: list[dict]) -> dict[str, int]:
    out = {"6": 0, "5": 0, "4": 0}
    for p in pulls:
        key = str(p["rarity"] or "")
        if key in out:
            out[key] += 1
    return out


def _bars(pulls: list[dict]) -> list[dict]:
    c = count_rarity(pulls)
    return [
        {"label": "6★", "value": c["6"], "color": COLOR_6},
        {"label": "5★", "value": c["5"], "color": COLOR_5},
        {"label": "4★", "value": c["4"], "color": COLOR_4},
    ]


def _up_ids(pool_info: dict, pool_ids: list[str]) -> set[str] | None:
    """本组所有池的 UP 名单合集；任一池缺 UP 信息时整组视为未知，避免把缺数据算成歪。"""
    if not pool_info:
        return None
    found: set[str] = set()
    for pid in pool_ids:
        info = pool_info.get(pid) or {}
        ids = info.get("up6_ids") or ([info["up6_id"]] if info.get("up6_id") else [])
        ids = {str(x).strip() for x in ids if str(x).strip()}
        if not ids:
            return None
        found |= ids
    return found or None


def _official_count(rerun_counts: dict, kind: str, pool_ids: list[str]) -> int | None:
    table = (rerun_counts or {}).get(kind) or {}
    values = [_as_int(table.get(pid)) for pid in pool_ids]
    values = [v for v in values if v is not None and v >= 0]
    if not values:
        return None
    return max(values)


def _card(label: str, value: Any, hint: str = "", tone: str = "") -> dict:
    return {"label": label, "value": str(value), "hint": hint, "tone": tone}


def _group(pulls: list[dict], *, gid: str, label: str, badge: str,
           pool_info: dict, rerun_counts: dict, is_weapon: bool,
           official_kind: str | None = None,
           big_pity_max: int | None = None,
           pool_label_map: dict[str, str] | None = None) -> dict:
    """把一个统计单元（角色池类型 / 单个武器池）算成一组通用渲染模型。"""
    c = count_rarity(pulls)
    paid = sum(1 for p in pulls if not p["is_free"])
    free = len(pulls) - paid
    pool_ids = list(dict.fromkeys(p["pool"] for p in pulls if p["pool"]))
    up = _up_ids(pool_info, pool_ids)

    small_max = SMALL_PITY_WEAPON if is_weapon else SMALL_PITY_CHAR
    small = pity_from_end(pulls, cap=small_max)
    history = six_history(pulls, up)
    got_up = any(h["tag"] == "UP" for h in history)
    off = sum(1 for h in history if h["tag"] == "歪")

    cards = [
        _card("总抽数", len(pulls), f"付费 {paid} · 免费 {free}"),
        _card("6★", c["6"], f"平均 {_avg_six(pulls)} 抽" if c["6"] else "暂无 6★"),
        _card("当前垫抽", small, f"距 {small_max} 抽保底还差 {max(0, small_max - small)}"),
        _card("UP / 歪", f"{sum(1 for h in history if h['tag'] == 'UP')} / {off}",
              "缺少 UP 名单时不判歪" if up is None else "按卡池 UP 名单判定",
              "" if up is not None else "muted"),
    ]

    if big_pity_max:
        official = _official_count(rerun_counts, official_kind or "char", pool_ids) if official_kind else None
        since_up = pity_from_end(pulls, up_only=True, up_ids=up, cap=big_pity_max)
        if official is not None and not got_up:
            big = min(max(official, since_up), big_pity_max)
            hint = "官方累计次数为准（服务器保留 90 天明细）"
        else:
            big = since_up
            hint = "距上次 UP 的付费抽数"
        cards.append(_card("大保底", f"{big}/{big_pity_max}", hint,
                           "good" if got_up else ""))

    if is_weapon:
        ten = ten_pull_count(pulls)
        cards.append(_card("武库配额消耗", f"{ten * ARSENAL_TEN_PULL_COST:,}",
                           f"{ten} 次十连 × {ARSENAL_TEN_PULL_COST}"))
    else:
        cards.append(_card("武库配额产出", f"{arsenal_earned(pulls):,}",
                           "4★ 20 · 5★ 200 · 6★ 2000"))

    # 池列表：默认按 poolId；重构角色按池名聚合（跨版本 #1/#2 继承）
    # 重构角色池按池名聚合：同一系列 #1/#2 共用跨版本大保底
    merge_by_name = not is_weapon and gid == "rerun"
    by_pool: dict[str, list[dict]] = defaultdict(list)
    for p in pulls:
        key = p["pool_name"] if merge_by_name else p["pool"]
        by_pool[key].append(p)
    latest_key = pulls[-1]["pool_name"] if merge_by_name else pulls[-1]["pool"]
    pools = []
    for key, items in by_pool.items():
        p6 = sum(1 for x in items if x["rarity"] == 6)
        pools.append({
            "label": (pool_label_map or {}).get(key, key) or key,
            "value": f"{len(items)} 抽",
            "hint": f"6★ {p6} · 垫 {pity_from_end(items, cap=small_max)}",
            "current": key == latest_key,
        })
    pools.reverse()

    return {
        "id": gid,
        "label": label,
        "badge": badge,
        "cards": cards,
        "bars": _bars(pulls),
        "pools": pools,
        "history": history,
    }


def _avg_six(pulls: list[dict], tail: int | None = None) -> str:
    """付费 6★ 平均抽数：总付费抽减去尾部垫抽，除以付费 6★ 数。
    tail：可传入按申领分段后的垫抽（武器合并列）；缺省整列往回数。"""
    six = sum(1 for p in pulls if p["rarity"] == 6 and not p["is_free"])
    if not six:
        return "—"
    total_paid = sum(1 for p in pulls if not p["is_free"])
    tail = pity_from_end(pulls) if tail is None else tail
    # ponytail: 跨申领合并后，旧申领收尾没出的垫抽会略微抬高均值；
    # 真要精确就按 6★ 分段求均值，等有人在意再说。
    return f"{(total_paid - tail) / six:.1f}"


def analyze(ugf: dict, *, pool_info: dict | None = None,
            rerun_counts: dict | None = None, source: str = "live") -> dict:
    """UGF → 通用渲染模型。前端只按结构渲染，不含任何游戏知识。"""
    meta, rows = normalize(ugf)
    pool_info = pool_info or {}
    rerun_counts = rerun_counts or {}

    char_rows = [p for p in rows if not p["weapon"]]
    weapon_rows = [p for p in rows if p["weapon"]]

    char_groups: list[dict] = []
    for kind in CHAR_ORDER:
        pulls = [p for p in char_rows if p["kind"] == kind]
        if not pulls:
            continue
        big = BIG_PITY_CHAR if kind in ("special", "rerun") else None
        char_groups.append(_group(
            pulls, gid=kind, label=CHAR_LABELS[kind],
            badge="大保底 120" if big else "小保底 80",
            pool_info=pool_info, rerun_counts=rerun_counts,
            is_weapon=False,
            official_kind="char" if kind in ("special", "rerun") else None,
            big_pity_max=big,
            pool_label_map={},
        ))
    # 未知角色池类型兜底成一个组，别把记录吞掉
    known = set(CHAR_ORDER)
    other = [p for p in char_rows if p["kind"] not in known]
    if other:
        char_groups.append(_group(other, gid="other-char", label="其他角色池", badge="",
                                  pool_info=pool_info, rerun_counts=rerun_counts,
                                  is_weapon=False))

    weapon_groups: list[dict] = []
    by_pool: dict[str, list[dict]] = defaultdict(list)
    for p in weapon_rows:
        by_pool[p["pool"]].append(p)
    for pid, pulls in by_pool.items():
        kind = pulls[-1]["kind"]
        label = pulls[-1]["pool_name"] or pid or WEAPON_LABELS.get(kind, "武器申领")
        weapon_groups.append(_group(
            pulls, gid=pid or f"weapon-{len(weapon_groups)}",
            label=label, badge=WEAPON_LABELS.get(kind, "武器申领"),
            pool_info=pool_info, rerun_counts=rerun_counts,
            is_weapon=True,
            official_kind="weapon" if kind == "rerun" else None,
            big_pity_max=BIG_PITY_WEAPON,
        ))
    weapon_groups.reverse()

    c_all = count_rarity(rows)
    c_char = count_rarity(char_rows)
    c_weapon = count_rarity(weapon_rows)
    earned = arsenal_earned(char_rows)
    consumed = sum(ARSENAL_TEN_PULL_COST * ten_pull_count(v) for v in by_pool.values())
    six_avg = _avg_six(rows)

    cards = [
        _card("总寻访", len(rows), f"角色 {len(char_rows)} · 武器 {len(weapon_rows)}"),
        _card("6★", c_all["6"], f"角色 {c_char['6']} · 武器 {c_weapon['6']}", "good"),
        _card("平均出货", six_avg, "付费 6★ 平均抽数（去掉尾部垫抽）"),
        _card("5★ / 4★", f"{c_all['5']} / {c_all['4']}", "按稀有度计数"),
        _card("武库配额净值", f"{earned - consumed:,}", f"产出 {earned:,} · 消耗 {consumed:,}"),
        _card("已覆盖卡池", len(by_pool) + len({p["pool"] for p in char_rows if p["pool"]}),
              "官方仅保留近 90 天明细", "muted"),
    ]

    notes = [
        "免费抽计入总抽与稀有度，但不推进、也不重置保底。",
        "角色池 80 抽小保底；特许寻访每池 120 抽必出当期 UP；重构寻访大保底跨版本继承，"
        "可用时以官方累计寻访次数为准。",
        "武器申领 40 抽必出 6★（25% UP）/ 80 抽必得当期 UP，按池独立；重构申领按版本期次分段。",
        "UP / 歪需要卡池 UP 名单；接口未返回时标记「6★」而不臆断。",
    ]
    if source == "demo":
        notes.insert(0, "演示数据：用于离线预览界面，不代表任何真实账号。")

    return {
        "meta": {**meta, "source": source, "pool_count": len(by_pool)},
        "cards": cards,
        "tabs": [
            {"id": "char", "label": "角色寻访", "groups": char_groups},
            {"id": "weapon", "label": "武器申领", "groups": weapon_groups},
        ],
        "notes": notes,
    }


# ------------------------------------------------- WinUI3 原生页通用模型


def demo_ugf() -> dict:
    """无凭证时的演示 UGF：3 个角色池类型 + 1 个武器池 = 首页 4 个卡池列。"""
    special = "E_CharacterGachaPoolType_Special"
    rerun = "E_CharacterGachaPoolType_Rerun"
    beginner = "E_CharacterGachaPoolType_Beginner"
    records: list[dict] = []

    def add(pool: str, ptype: str, seq: int, rarity: int, name: str, item: str,
            *, free: bool = False, weapon: bool = False, pool_name: str = "",
            ts: str = "") -> None:
        records.append({
            "pool": pool,
            "time": ts or f"2026-11-0{min(seq // 30 + 1, 9)}T10:{seq % 60:02d}:00+08:00",
            "item_id": item, "name": name,
            "item_type": "武器" if weapon else "角色",
            "rarity": rarity, "count": 1, "pity_group": pool, "id": str(seq),
            "x_endfield": {"is_free": free, "is_new": False,
                           "pool_name": pool_name or pool, "pool_type": ptype},
        })

    for i in range(1, 21):
        add("special_pool_1", special, i, 6 if i in (1, 5, 18) else (5 if i % 7 == 0 else 4),
            "当期UP" if i == 5 else ("常驻六星" if i == 18 else f"干员{i}"),
            "chr_up" if i == 5 else ("chr_off" if i == 18 else f"chr_{i}"),
            free=(i == 1), pool_name="特许寻访 · 演示期")
    for i in range(21, 31):
        add("rerun_chr_1", rerun, i, 4, f"干员{i}", f"chr_{i}",
            free=(i == 25), pool_name="重构寻访 #1")
    for i in range(31, 36):
        add("beginner", beginner, i, 6 if i == 35 else 4, f"物品{i}", f"chr_{i}",
            pool_name="启程寻访")
    for i in range(41, 53):
        add("weaponbox_1_0_1", "special", i, 6 if i == 50 else 5,
            "幽寒" if i == 50 else f"武器{i}", "wpn_up" if i == 50 else f"wpn_{i}",
            weapon=True, pool_name="幽寒申领 · 演示期", ts="2026-11-05T12:00:00+08:00")
    return {
        "format": "UGF", "version": "1.3",
        "accounts": [{"game": "arknights-endfield", "uid": "10000001",
                      "server": "1", "timezone": "+08:00", "records": records}],
    }


def demo_pool_info() -> dict:
    return {
        "special_pool_1": {"up6_ids": ["chr_up"]},
        "weaponbox_1_0_1": {"up6_ids": ["wpn_up"]},
    }


def _rare_history(pulls: list[dict], guarantee: int, rarity: int, *,
                  per_pool: bool = False) -> list[dict]:
    """5★/4★ 明细（与 6★ 历史同规则，供原生页分栏）。per_pool：垫抽按申领分段。
    4★/5★ 没有保底语义，pity 列是「距上一发同稀有度的付费间隔抽数」。"""
    out: list[dict] = []
    pity = 0
    prev: dict | None = None
    for p in pulls:
        if per_pool and prev is not None and _pool_changed(p, prev):
            pity = 0
        prev = p
        if not p["is_free"]:
            pity += 1
        if p["rarity"] == rarity:
            out.append({"name": p["name"] or p["item_id"], "pity": pity,
                        "up": False, "time": p["time"][:16].replace("T", " "),
                        "current": False, "tag": ""})
            pity = 0
    out.reverse()
    return out[:6]


# ------------------------------------------------------------------ 物品名显示语言
# 设置面板「语言」的数据源：assets/gacha-names.json（gacha_names.py 烤制，国服 wiki
# 目录 × 国际服目录按 associate_id 连接）。走显示层翻译而不是接口 lang 参数——
# 实测国服记录接口只认 zh-cn，其它语言码返回空（交接 §8.12）。

NAMES_PATH = Path(__file__).resolve().parent / "assets" / "gacha-names.json"
# 表键 = gacha-names.json 的语言键（gacha_names.py 烤制）；值为空 = 不翻译。
# 除设置面板自己的码（zh-cn/zh-TW…）外，也认宿主全局语言的原始码（zh-Hans/zh-Hant，
# 单向耦合：全局语言 → 抽卡跟随）；全局里包侧没有的语言（fr/de/es/pt-BR）查不到 → 简中。
LANG_KEYS = {"zh-cn": "", "zh-Hans": "", "zh-TW": "zh_Hant", "zh-Hant": "zh_Hant",
             "en": "en", "ja": "ja", "ko": "ko", "ru": "ru", "th": "th"}
_NAME_TABLE: dict[str, dict[str, str]] | None = None


def _name_table() -> dict[str, dict[str, str]]:
    global _NAME_TABLE
    if _NAME_TABLE is None:
        try:
            _NAME_TABLE = json.loads(NAMES_PATH.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            _NAME_TABLE = {}
    return _NAME_TABLE


def available_languages() -> list[dict[str, str]]:
    """宿主「语言」下拉的内容；表不存在 / 为空 → 空列表（宿主隐藏该入口）。"""
    if not _name_table():
        return []
    return [{"code": "zh-cn", "label": "简体中文"},
            {"code": "zh-TW", "label": "繁體中文"},
            {"code": "en", "label": "English"},
            {"code": "ja", "label": "日本語"},
            {"code": "ko", "label": "한국어"},
            {"code": "ru", "label": "Русский"},
            {"code": "th", "label": "ไทย"}]


def _name_translator(lang: str):
    """zh 名 → 目标语言名；zh-cn / 未知码 → 原样。表里没有的名字回落简中。"""
    key = LANG_KEYS.get((lang or "").strip())
    if not key:
        return lambda name: name
    table = _name_table()

    def translate(name: str) -> str:
        return (table.get(name) or {}).get(key) or name

    return translate


def canonical_language(lang: str) -> str:
    """任意入参语言码 → 设置面板声明表里的规范码（未知一律 zh-cn），宿主恢复下拉选中用。"""
    key = LANG_KEYS.get((lang or "").strip())
    if key is None:
        key = ""
    return {"": "zh-cn", "zh_Hant": "zh-TW"}.get(key, key)


# ------------------------------------------------------------------ 模型内界面文案
# 统计行 / 已垫 / 计数 / 演示提示这类界面词，跟物品语言一起走（lang 参数）。
# 池列名（特许寻访 / 武器申领…）走 assets/l10n.json 的 pool.*（官方英文术语来源见其 _meta：
# Headhunting / Chartered / RE-Factor / Basic / New Horizons / Arsenal Exchange，endfield.wiki.gg）；
# 表内没有的语言（ru / th）由 l10n.t 回落简中。
_POOL_LABEL_IDS = {
    "char": {"special": "pool.special", "rerun": "pool.rerun", "joint": "pool.joint",
             "standard": "pool.standard", "beginner": "pool.beginner"},
    "weapon": {"special": "pool.arsenalLimited", "constant": "pool.arsenalConstant",
               "rerun": "pool.arsenalRerun", "normal": "pool.arsenal"},
}
# 抽卡内容语言码（available_languages 声明的那套）→ l10n.json 语言 tag
_POOL_LANG_TAGS = {"zh-cn": "zh-Hans", "zh-Hans": "zh-Hans", "zh-TW": "zh-Hant", "zh-Hant": "zh-Hant",
                   "en": "en", "ja": "ja", "ko": "ko", "ru": "ru", "th": "th"}


def pool_label(kind: str, weapon: bool, lang: str) -> str:
    """池列名按内容语言翻译；未知类型回落原表（CHAR_LABELS / 武器申领）。"""
    tag = _POOL_LANG_TAGS.get((lang or "").strip(), "zh-Hans")
    sid = _POOL_LABEL_IDS["weapon" if weapon else "char"].get(kind)
    if sid:
        return l10n.t(sid, lang=tag)
    if weapon:
        return l10n.t("pool.arsenal", lang=tag)
    return CHAR_LABELS.get(kind, "")


_CHROME: dict[str, dict[str, str]] = {
    "zh-cn": {"r_avg": "6★ 平均", "r6": "6★ 统计", "r5": "5★ 统计", "r4": "4★ 统计",
              "pity": "已垫", "count": "{n}次",
              "demo": "演示数据", "demo_sub": "点「更新记录」同步真实寻访记录"},
    "zh-TW": {"r_avg": "6★ 平均", "r6": "6★ 統計", "r5": "5★ 統計", "r4": "4★ 統計",
              "pity": "已墊", "count": "{n}次",
              "demo": "示範資料", "demo_sub": "點「更新記錄」同步真實尋訪記錄"},
    "en": {"r_avg": "6★ Avg", "r6": "6★ Count", "r5": "5★ Count", "r4": "4★ Count",
           "pity": "Pity", "count": "×{n}",
           "demo": "Demo data", "demo_sub": "Click Refresh to sync real records"},
    "ja": {"r_avg": "6★ 平均", "r6": "6★ 統計", "r5": "5★ 統計", "r4": "4★ 統計",
           "pity": "天井", "count": "{n}回",
           "demo": "デモデータ", "demo_sub": "「記録を更新」で実際の記録を同期"},
    "ko": {"r_avg": "6★ 평균", "r6": "6★ 통계", "r5": "5★ 통계", "r4": "4★ 통계",
           "pity": "천장", "count": "{n}회",
           "demo": "데모 데이터", "demo_sub": "「기록 업데이트」로 실제 기록을 동기화하세요"},
    "ru": {"r_avg": "6★ ср.", "r6": "6★ стат.", "r5": "5★ стат.", "r4": "4★ стат.",
           "pity": "Гарант", "count": "{n}×",
           "demo": "Демо-данные", "demo_sub": "Нажмите «Обновить» для синхронизации"},
    "th": {"r_avg": "6★ เฉลี่ย", "r6": "6★ สถิติ", "r5": "5★ สถิติ", "r4": "4★ สถิติ",
           "pity": "การันตี", "count": "{n}ครั้ง",
           "demo": "ข้อมูลตัวอย่าง", "demo_sub": 'กด "อัปเดต" เพื่อซิงก์ข้อมูลจริง'},
}


def _chrome(lang: str) -> dict[str, str]:
    return _CHROME.get(canonical_language(lang)) or _CHROME["zh-cn"]


def winui_model(ugf: dict, *, pool_info: dict | None = None,
                demo: bool = False, uid: str = "",
                icon_resolver=None, lang: str = "zh-cn") -> dict:
    """
    UGF → WinUI3 原生页的通用列模型。宿主只认下列通用键，不认识任何游戏字段：
      account{uid,display,subtitle} / pools[{id,name,range,total,rows,tabs,pityPoint,
      pityGuarantee,showUpColumn}] / items[{name,count,quality,icon}]

    icon_resolver: 可选回调 (name -> 本地图标路径 | None)，来自 wiki_catalog.IconResolver。
    只对出现过的名称调用（按需取图，抽到什么才下什么）；None / 未传 → 行内 icon=null，
    宿主走名称占位回落。
    """
    meta, rows = normalize(ugf)
    pool_info = pool_info or {}

    grouped: dict[str, dict] = {}
    for r in rows:
        # 武器全并成一列：终末地每把武器一个专属申领（幽寒申领、细枝申领……），
        # 按池开列的话每期武器都占一列，几期就溢出一屏。列内靠申领名（pool_name）
        # 区分，保底按申领分段——以后来任何新申领都自动落进这一列，不用改代码。
        key = "weapon" if r["weapon"] else ("char:" + r["kind"])
        label = pool_label(r["kind"], r["weapon"], lang) or (r["pool_name"] or r["pool"])
        grouped.setdefault(key, {"label": label, "weapon": r["weapon"], "rows": []})
        grouped[key]["rows"].append(r)

    pools: list[dict] = []
    c = _chrome(lang)
    # 卡池列不截断：宿主按「一屏固定 4 个、其余横向滚动」排版（口径见 Arietta
    # docs/窗口-三档尺寸设置-交接.md）。这里截断会把第 5 个及之后的卡池直接吞掉。
    for key, g in grouped.items():
        pulls = g["rows"]
        total = len(pulls)
        if total == 0:
            continue
        counts = count_rarity(pulls)
        guarantee = SMALL_PITY_WEAPON if g["weapon"] else SMALL_PITY_CHAR
        # 变红阈值取保底的 5/6（80→66 / 100→83），与原写死的两档一致
        pity_point = guarantee * 5 // 6
        pity = pity_from_end(pulls, cap=guarantee, per_pool=g["weapon"])

        # UP 名单：武器合并列按「每条记录所属池」各自判定，老申领缺名单不影响新申领；
        # 角色列维持整组一份名单（缺失时整组不判歪）。
        up_ids: set[str] | None = None
        up_map: dict[str, set[str]] | None = None
        if g["weapon"]:
            found: dict[str, set[str]] = {}
            for pid in dict.fromkeys(r["pool"] for r in pulls if r["pool"]):
                ids = _up_ids(pool_info, [pid])
                if ids:
                    found[pid] = ids
            up_map = found or None
        else:
            up_ids = _up_ids(pool_info, [r["pool"] for r in pulls if r["pool"]])
        hist6 = six_history(pulls, up_ids, per_pool=g["weapon"], up_map=up_map)

        # 武器各申领独立保底（池会过期），合并列没有可垫的进度 → 不显示「已垫」；
        # 角色列保底真实跨池共享，保留。申领名只用于分段计数，不在界面出现。
        items6 = ([] if g["weapon"] else
                  [{"name": c["pity"], "pity": pity, "up": False, "time": "",
                    "current": True, "tag": ""}])
        items6 += [
            {"name": h["name"], "pity": h["pity"], "up": h["tag"] == "UP",
             "time": h["time"], "current": False, "tag": h["tag"]}
            for h in hist6]

        def pct(n: int) -> str:
            return f"{n} [{n / total * 100:.2f}%]" if total else "0 [0.00%]"

        start = pulls[0]["time"][:16].replace("T", " ")
        end = pulls[-1]["time"][:16].replace("T", " ")
        pools.append({
            "id": key,
            "name": g["label"],
            "range": f"{start} - {end}",
            "total": str(total),
            "rows": [
                {"label": c["r_avg"], "value": _avg_six(
                    pulls, tail=pity_from_end(pulls, per_pool=g["weapon"])), "color": "avg"},
                {"label": c["r6"], "value": pct(counts["6"]), "color": "s6"},
                {"label": c["r5"], "value": pct(counts["5"]), "color": "s5"},
                {"label": c["r4"], "value": pct(counts["4"]), "color": "s4"},
            ],
            "tabs": [
                {"label": "6★", "items": items6},
                {"label": "5★", "items": _rare_history(pulls, guarantee, 5, per_pool=g["weapon"])},
            ],
            "pityPoint": pity_point,
            "pityGuarantee": guarantee,
            "showUpColumn": (bool(up_map) if g["weapon"] else up_ids is not None)
                            and any(x["up"] for x in items6),
        })

    items: dict[str, dict] = {}
    for r in rows:
        if r["rarity"] in (4, 5, 6) and r["name"]:
            entry = items.setdefault(r["name"], {"name": r["name"], "count": 0,
                                                 "quality": r["rarity"]})
            entry["count"] += 1
            entry["quality"] = max(entry["quality"], r["rarity"])
    item_cards = [
        {"name": v["name"], "count": c["count"].format(n=v["count"]), "quality": v["quality"]}
        for v in sorted(items.values(), key=lambda x: (-x["quality"], x["name"]))
    ]
    # 不设张数上限：4★ 卡排在 6★/5★ 之后，截 20 张的话真实账号里 4★ 永远挤不进总览

    # 图标按需解析（抽卡界面）：只解析出现过的名称，缺图 None → 宿主名称占位。
    # resolve_many 走批量并发下载（借鉴鸣潮 WutheringWavesTool），普通回调则逐个解析。
    if icon_resolver is not None:
        named_rows: list[dict] = []
        for pool in pools:
            for tab in pool.get("tabs") or []:
                for row in tab.get("items") or []:
                    if row.get("name") and not row.get("current"):
                        named_rows.append(row)
        all_names = [r["name"] for r in named_rows] + [c["name"] for c in item_cards]
        batch = getattr(icon_resolver, "resolve_many", None)
        resolved = batch(all_names) if batch else {n: icon_resolver(n) for n in all_names}
        for row in named_rows:
            row["icon"] = resolved.get(row["name"])
        for card in item_cards:
            card["icon"] = resolved.get(card["name"])

    # 物品名显示语言：图标仍按简中名解析（wiki 图鉴键是简中），所以翻译放在取图
    # 之后；「已垫」等状态行不翻——跟列名/统计口径一样属界面文案，不是物品名。
    translate = _name_translator(lang)
    for pool in pools:
        for tab in pool.get("tabs") or []:
            for row in tab.get("items") or []:
                if row.get("name") and not row.get("current"):
                    row["name"] = translate(row["name"])
    for card in item_cards:
        card["name"] = translate(card["name"])

    owner = uid or meta.get("uid") or "—"
    return {
        "demo": demo,
        "language": canonical_language(lang),
        "account": {
            "uid": owner,
            "display": c["demo"] if demo else owner,
            "subtitle": c["demo_sub"] if demo else "",
        },
        "pools": pools,
        "items": item_cards,
    }


def main() -> int:
    """调试入口：stdin 读 {\"ugf\": ..., \"pool_info\": ..., \"rerun_counts\": ...}，stdout 出模型。"""
    try:
        req = json.loads(sys.stdin.read() or "{}")
        model = analyze(
            req.get("ugf") or {},
            pool_info=req.get("pool_info") or {},
            rerun_counts=req.get("rerun_counts") or {},
            source=str(req.get("source") or "live"),
        )
        print(json.dumps(model, ensure_ascii=False))
        return 0
    except Exception as e:
        print(f"{type(e).__name__}: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
