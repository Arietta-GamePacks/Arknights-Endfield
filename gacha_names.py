# -*- coding: utf-8 -*-
"""抽卡物品名多语表生成器（设置面板「语言」的数据源）

把国服 wiki 图鉴目录（zh_Hans）和国际服目录（sk-language 六语）按条目连成
「简中名 → 各语言名」的表，烤成 assets/gacha-names.json 给 gacha.py 在模型
构建时做显示层翻译（不走接口 lang 参数——实测国服只认 zh-cn，见
docs/抽卡-社区账号耦合与四列自适应-交接.md §8.12/§8.13）。

国际服内容语言（2026-11-17 实测，站方菜单 8 语里 id/vi 只回落英文，不收）：
  sk-language 头: en ja ko zh_Hant ru_RU th_TH
  表内键:         en ja ko zh_Hant ru  th

连接键（按优先级）：
  1. associate_id（国服/国际服 wiki 条目共用，覆盖绝大多数条目）
  2. 归一化 zh_Hant 名 == 归一化 zh_Hans 名（简繁字形一致的剩余条目）
  3. _HAND_JOINS：国际服改了名、前两步都配不上的，按英文名手工连接
配不上的条目保持简中（宿主端所有语言回落显示简中名）。

用法：
  python wiki_icons.py --dry --langs en ja ko zh_Hant ru_RU th_TH   # 先刷 manifest
  python gacha_names.py                                             # 再烤出表
"""
from __future__ import annotations

import json
import re
import unicodedata
from pathlib import Path

PACK_DIR = Path(__file__).resolve().parent
MANIFEST_PATH = PACK_DIR / "assets" / "wiki-catalog" / "catalog-manifest.json"
OUT_PATH = PACK_DIR / "assets" / "gacha-names.json"

# sk-language 头的取值 → 表内键（表键 = gacha.py LANG_KEYS 的语言码）
PORT_LANGS = {"en": "en", "ja": "ja", "ko": "ko", "zh_Hant": "zh_Hant",
              "ru_RU": "ru", "th_TH": "th"}
SUBS = ("operators", "weapons")

# associate 与 zh_Hant 归一化都连不上的剩余条目：国际服改了名，按英文名手工连接。
# 新物品上线若出现新的配不上条目，优先补跑 wiki_icons.py 刷新 manifest，实在不行在这里加一行。
_HAND_JOINS = {
    "聚合工业": "Complexed Industry",   # GL itemId 1282
    "悼亡诗": "Stanza of Memorials",    # GL itemId 94
}


def norm(name: str) -> str:
    """全半角折叠 + 去空白/标点：简繁对照匹配用的键。"""
    s = unicodedata.normalize("NFKC", name)
    return re.sub(r"[\s·・\-—_:：()（）]+", "", s).lower()


def main() -> int:
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))

    # 国际服自连接：GL itemId 在各语言里稳定（实测 119 项 0 冲突），
    # associate 键跨语言偶有分裂，先按 itemId 把各语拼成完整条目。
    gl: dict[tuple[str, str], dict[str, str]] = {}
    for entry in manifest.values():
        if not isinstance(entry, dict):
            continue
        for sub in SUBS:
            for header, key in PORT_LANGS.items():
                info = entry.get(f"port:{sub}:{header}")
                if isinstance(info, dict) and info.get("name"):
                    item = (sub, str(info.get("itemId") or ""))
                    gl.setdefault(item, {}).setdefault(key, str(info["name"]).strip())

    table: dict[str, dict[str, str]] = {}
    consumed: set[tuple[str, str]] = set()
    leftovers: list[tuple[str, str]] = []  # (sub, zh_name) 没配上associate的
    for aid, entry in manifest.items():
        if not isinstance(entry, dict):
            continue
        for sub in SUBS:
            cn = entry.get(f"cn:{sub}:zh_Hans")
            if not (isinstance(cn, dict) and cn.get("name")):
                continue
            zh = str(cn["name"]).strip()
            # 国服和国际服共用 associate_id，但国际服各语言的 associate 键会分裂，
            # 所以先从本条目任意语言拿到 GL itemId，再用自连接的完整条目回填。
            gl_key = next(((sub, str(info.get("itemId") or "")) for header in PORT_LANGS
                           for info in [entry.get(f"port:{sub}:{header}")]
                           if isinstance(info, dict) and info.get("name")), None)
            if gl_key and gl_key in gl:
                table[zh] = dict(gl[gl_key])
                consumed.add(gl_key)
            else:
                leftovers.append((sub, zh))

    # associate 配不上的：拿没被占用的国际服条目，按归一化 zh_Hant == zh_Hans 补配
    free = {k: v for k, v in gl.items() if k not in consumed and v.get("zh_Hant")}
    patched = 0
    for sub, zh in leftovers:
        hit = next((v for k, v in free.items() if k[0] == sub and norm(v["zh_Hant"]) == norm(zh)), None)
        if hit is None and zh in _HAND_JOINS:
            hit = next((v for k, v in free.items()
                        if k[0] == sub and v.get("en") == _HAND_JOINS[zh]), None)
        if hit:
            table[zh] = {key: hit[key] for key in PORT_LANGS.values() if key in hit}
            del free[next(k for k, v in free.items() if k[0] == sub and v is hit)]
            patched += 1

    OUT_PATH.write_text(json.dumps(table, ensure_ascii=False, indent=1), encoding="utf-8")
    langs = list(PORT_LANGS.values())
    full = sum(1 for v in table.values() if all(v.get(k) for k in langs))
    by_lang = {k: sum(1 for v in table.values() if v.get(k)) for k in langs}
    print(f"gacha-names.json: {len(table)} 条（{len(langs)}语齐全 {full}），补配 {patched}")
    print("各语言覆盖:", by_lang, "（缺的运行时回落简中）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
