# -*- coding: utf-8 -*-
"""森空岛 Wiki 图鉴图标 · 运行时按需解析（抽卡界面专用）

思路（Alpha 2026-11-16 钦定）：抽卡界面只显示抽到过的东西，图标**按需获取**，
不往包里塞图库。三层取图，逐层回落：

  ① 宿主数据目录缓存 `<data_dir>/gacha-icons/<名称>.png`（已下载过 → 直接用）
  ② 包内离线索引 `assets/wiki-catalog/catalog-manifest.json`
     （name → CDN URL，国服 zh_Hans，由 wiki_icons.py 生成）
  ③ 在线刷新：直连 `zonai.skland.com/web/v1/wiki/item/catalog`（匿名 + Web 签名，
     见 docs/森空岛Wiki-图鉴图标抓取-交接.md），补 ①② 都没有的新条目

匹配键是抽卡记录里的 `name`（简体中文，与图鉴目录同名；注意部分官方名带前导空格，
匹配前统一 strip）。取不到图返回 None，宿主已有名称占位回落（NameVisibility）。

签名（与 skland.py 的 App 端同源、Web 端参数不同）：
  msg  = path + query + str(ts) + JSON({"platform","timestamp","dId","vName"}, 紧凑)
  sign = md5(hex(hmac_sha256(token, msg)))
  token 由 /web/v1/auth/refresh 匿名获取；首次调用该接口时 token 用空串。
"""
from __future__ import annotations

import hashlib
import hmac
import json
import re
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

PACK_DIR = Path(__file__).resolve().parent
MANIFEST_PATH = PACK_DIR / "assets" / "wiki-catalog" / "catalog-manifest.json"

CN_HOST = "https://zonai.skland.com"
CN_REFERER = "https://wiki.skland.com/"
ICON_REFERER = "https://wiki.skland.com/"   # hycdn 拒绝其它来源的 Referer
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")
D_ID = "5f3a9c7e2b1d4f6a8c0e2d4b6a8f1c3e"  # 32 位 hex（等价前端 randomUUID 去连字符）

# manifest 里参与图标解析的服务端:分类:语言键（国服简中一套就够；国际服语言见交接文档第 5 节）
MANIFEST_KEYS = ("cn:operators:zh_Hans", "cn:weapons:zh_Hans")
CATALOG_TTL = 24 * 3600  # 在线刷新条目的内存缓存时效


def _safe_name(name: str) -> str:
    return re.sub(r'[\\/:*?"<>|\s]+', "_", name).strip("_")[:60] or "unnamed"


def _is_png(path: Path) -> bool:
    try:
        return path.is_file() and path.read_bytes()[:4] == b"\x89PNG"
    except OSError:
        return False


def _load_manifest() -> dict[str, str]:
    """name(strip 后) → cover URL。manifest 结构：{associate_id: {"cn:operators:zh_Hans": {...}}}"""
    try:
        raw = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    out: dict[str, str] = {}
    for entry in raw.values():
        if not isinstance(entry, dict):
            continue
        for key in MANIFEST_KEYS:
            info = entry.get(key)
            if isinstance(info, dict) and info.get("name") and info.get("url"):
                out[str(info["name"]).strip()] = str(info["url"])
    return out


def _curl_json(url: str, headers: dict[str, str], timeout: int = 20) -> dict[str, Any]:
    cmd = ["curl", "-s", "--max-time", str(timeout), url]
    for k, v in headers.items():
        cmd += ["-H", f"{k}: {v}"]
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                             errors="replace").stdout
        return json.loads(out)
    except (OSError, ValueError):
        return {}


def _hex(b: bytes) -> str:
    return "".join(f"{x:02x}" for x in b)


def _sign(path: str, query: str, ts: int, token: str) -> str:
    payload = json.dumps({"platform": "3", "timestamp": str(ts), "dId": D_ID, "vName": "1.0.0"},
                         separators=(",", ":"))
    msg = path + (query or "") + str(ts) + payload
    hmac_hex = _hex(hmac.new((token or "").encode(), msg.encode(), hashlib.sha256).digest())
    return _hex(hashlib.md5(hmac_hex.encode()).digest())


def _api_get(path_query: str, token: str) -> dict[str, Any]:
    p, _, q = path_query.partition("?")
    ts = int(time.time())
    r = _curl_json(CN_HOST + path_query, {
        "platform": "3",
        "timestamp": str(ts),
        "dId": D_ID,
        "vName": "1.0.0",
        "sign": _sign(p, q, ts, token),
        "Content-Type": "application/json",
        "Referer": CN_REFERER,
        "User-Agent": UA,
    })
    return r if isinstance(r, dict) else {}


def _live_catalog_names() -> dict[str, str]:
    """在线拉图鉴目录，返回 name(strip) → cover URL。失败返回空表（回落离线索引）。"""
    try:
        refresh = _api_get("/web/v1/auth/refresh", "")
        token = str((refresh.get("data") or {}).get("token") or "")
        if not token:
            return {}
        q = f"/web/v1/wiki/item/catalog?typeMainId=1&onlyOnline=true&_={int(time.time() * 1000)}"
        for _ in range(2):  # 偶发软限流：code=0 但 items 空，重试一次
            r = _api_get(q, token)
            subs = ((r.get("data") or {}).get("catalog") or [{}])[0].get("typeSub", [])
            names: dict[str, str] = {}
            for sub in subs:
                if sub.get("id") in ("1", "2"):  # 干员 / 武器
                    for it in sub.get("items") or []:
                        url = (it.get("brief") or {}).get("cover")
                        nm = str(it.get("name") or "").strip()
                        if nm and url:
                            names[nm] = str(url)
            if names:
                return names
            time.sleep(2)
    except Exception:
        pass
    return {}


class IconResolver:
    """抽卡记录名称 → 本地图标路径。所有失败最终返回 None，绝不抛异常打断统计页。"""

    def __init__(self, data_dir: str | Path):
        self.cache_dir = Path(data_dir) / "gacha-icons" if data_dir else None
        self.manifest: dict[str, str] = _load_manifest()
        self.live: dict[str, str] = {}
        self.live_ts = 0.0

    def _url_for(self, name: str) -> str:
        url = self.manifest.get(name, "")
        if url:
            return url
        # 离线索引没有（图鉴新条目 / manifest 过期）→ 在线刷新一次
        if time.time() - self.live_ts > CATALOG_TTL:
            self.live = _live_catalog_names()
            self.live_ts = time.time()
        return self.live.get(name, "")

    def _download(self, url: str, dest: Path) -> bool:
        try:
            dest.parent.mkdir(parents=True, exist_ok=True)
            cmd = ["curl", "-s", "--max-time", "30", "-o", str(dest),
                   "-H", f"User-Agent: {UA}", "-H", f"Referer: {ICON_REFERER}", url]
            subprocess.run(cmd, capture_output=True)
            if _is_png(dest):
                return True
            dest.unlink(missing_ok=True)
        except OSError:
            pass
        return False

    def resolve_cached(self, name: str) -> str | None:
        """只查本地缓存，绝不联网（mode=cache 打开页面用，缺图回落名称占位）。"""
        nm = str(name or "").strip()
        if not nm or self.cache_dir is None:
            return None
        dest = self.cache_dir / f"{_safe_name(nm)}.png"
        return str(dest) if _is_png(dest) else None

    def resolve(self, name: str) -> str | None:
        nm = str(name or "").strip()
        if not nm or self.cache_dir is None:
            return None
        dest = self.cache_dir / f"{_safe_name(nm)}.png"
        if _is_png(dest):
            return str(dest)
        url = self._url_for(nm)
        if url and self._download(url, dest):
            return str(dest)
        return None

    def resolve_many(self, names, *, max_workers: int = 6) -> dict[str, str | None]:
        """批量解析（借鉴鸣潮 WutheringWavesTool 的并发头像下载）：缓存命中直接回，
        未命中并发下载，避免几十张图标串行 curl 拖慢「更新记录」。"""
        todo = list(dict.fromkeys(
            str(n or "").strip() for n in names if str(n or "").strip()))
        out: dict[str, str | None] = {}
        hits = [n for n in todo if (p := self._cached_path(n))]
        for n in hits:
            out[n] = self._cached_path(n)
        missing = [n for n in todo if n not in out]
        if missing:
            with ThreadPoolExecutor(max_workers=max_workers) as pool:
                for n, path in zip(missing, pool.map(self.resolve, missing)):
                    out[n] = path
        return out

    def _cached_path(self, name: str) -> str | None:
        nm = str(name or "").strip()
        if not nm or self.cache_dir is None:
            return None
        dest = self.cache_dir / f"{_safe_name(nm)}.png"
        return str(dest) if _is_png(dest) else None
