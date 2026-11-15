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
  - 武器申领小保底 40 / 大保底 80；重构申领按期次分段；
  - UP / 歪判定依赖 /api/content 的 up6 名单，缺失时标「未知」，不臆造；
  - 武库配额：角色池 4★=20 / 5★=200 / 6★=2000，武器池每十连消耗 1980。
"""

from __future__ import annotations

import json
import sys
from collections import defaultdict
from typing import Any

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
SMALL_PITY_WEAPON = 40
BIG_PITY_CHAR = 120
BIG_PITY_WEAPON = 80

ARSENAL_EARN = {4: 20, 5: 200, 6: 2000}
ARSENAL_TEN_PULL_COST = 1980

COLOR_6 = "#E6D800"
COLOR_5 = "#C864E0"
COLOR_4 = "#5EAAED"


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


def pity_from_end(pulls: list[dict], *, up_only: bool = False,
                  up_ids: set[str] | None = None, cap: int | None = None) -> int:
    """从最新往回数「付费抽」，遇到重置项停止。免费抽跳过（不推进也不重置）。"""
    count = 0
    for p in reversed(pulls):
        if p["is_free"]:
            continue
        if p["rarity"] == 6:
            if not up_only or (up_ids and p["item_id"] in up_ids):
                break
        count += 1
        if cap is not None and count >= cap:
            return cap
    return count


def six_history(pulls: list[dict], up_ids: set[str] | None) -> list[dict]:
    """6★ 历史：每条带「本抽是第几抽」、UP / 歪 / 未知 / 赠送标记。"""
    history: list[dict] = []
    paid_pity = 0
    for p in pulls:
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
            if up_ids is None or not up_ids:
                tag, tone = "6★", "muted"
            elif p["item_id"] in up_ids:
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


def _avg_six(pulls: list[dict]) -> str:
    """付费 6★ 平均抽数：总付费抽减去尾部垫抽，除以付费 6★ 数。"""
    six = sum(1 for p in pulls if p["rarity"] == 6 and not p["is_free"])
    if not six:
        return "—"
    total_paid = sum(1 for p in pulls if not p["is_free"])
    tail = pity_from_end(pulls)
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
        "武器申领 40 / 80 保底按池独立；重构申领按版本期次分段。",
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
