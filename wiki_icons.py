# -*- coding: utf-8 -*-
"""森空岛 Wiki 图鉴图标抓取（国服 zonai.skland.com / 国际服 zonai.skport.com）

接口（均为匿名可访问，platform=3 Web 端签名）：
  GET {host}/web/v1/auth/refresh                                  -> {token}（空 token 签名调用）
  GET {host}/web/v1/wiki/item/catalog?typeMainId=1&onlyOnline=true -> 图鉴目录（typeSubId 1=干员 2=武器）

签名（从前端 vendor_src_libs 逆向还原）：
  msg   = path + query(GET) + timestamp + JSON({"platform","timestamp","dId","vName"}, 紧凑)
  sign  = md5( hex( hmac_sha256(token, msg) ) )     # 先 HMAC-SHA256 转 hex，再对 hex 串 MD5
  token 来自 /web/v1/auth/refresh；首次调用该接口时 token 用空串
  必带头: platform=3 / timestamp / dId / vName=1.0.0 / sign / Referer
  国际服额外带 sk-language 选择内容语言（有效: en ja ko zh_Hant ru_RU th_TH；
  2026-11-17 实测：id_ID / vi_VN 只回落英文内容，站方菜单有但内容没翻，不收）

用法:
  python wiki_icons.py            # 全部：国服 zh_Hans + 国际服 4 语言
  python wiki_icons.py --langs en ja zh_Hant   # 只拉国际服指定语言
  python wiki_icons.py --dry      # 只生成清单不下载图片
"""
import json, time, hashlib, hmac, sys, subprocess, os, re, argparse
from concurrent.futures import ThreadPoolExecutor

PACK_DIR = os.path.dirname(os.path.abspath(__file__))
OUT_DIR = os.path.join(PACK_DIR, "icons", "wiki")
MANIFEST_DIR = os.path.join(PACK_DIR, "assets", "wiki-catalog")

CN_HOST = "https://zonai.skland.com"
CN_REFERER = "https://wiki.skland.com/"
PORT_HOST = "https://zonai.skport.com"
PORT_REFERER = "https://wiki.skport.com/"
PORT_PROXY = os.environ.get("WIKI_PROXY", "http://127.0.0.1:7897")  # 国际服国内网络需代理；置空则直连
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126 Safari/537.36")
D_ID = "5f3a9c7e2b1d4f6a8c0e2d4b6a8f1c3e"  # 32 位 hex，等价前端 crypto.randomUUID() 去连字符


def _hex(b):
    return "".join(f"{x:02x}" for x in b)


def make_sign(path, query, ts, token):
    payload = json.dumps({"platform": "3", "timestamp": str(ts), "dId": D_ID, "vName": "1.0.0"},
                         separators=(",", ":"))
    msg = path + (query or "") + str(ts) + payload
    hmac_hex = _hex(hmac.new((token or "").encode(), msg.encode(), hashlib.sha256).digest())
    return _hex(hashlib.md5(hmac_hex.encode()).digest())


def api_get(host, path_query, token, referer, lang=None, proxy=None):
    p, _, q = path_query.partition("?")
    ts = int(time.time())
    headers = {
        "platform": "3",
        "timestamp": str(ts),
        "dId": D_ID,
        "vName": "1.0.0",
        "sign": make_sign(p, q, ts, token),
        "Content-Type": "application/json",
        "Referer": referer,
        "User-Agent": UA,
    }
    if lang:
        headers["sk-language"] = lang
    cmd = ["curl", "-s", "--max-time", "30", host + path_query]
    for k, v in headers.items():
        cmd += ["-H", f"{k}: {v}"]
    if proxy:
        cmd += ["-x", proxy]
    out = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace").stdout
    try:
        return json.loads(out)
    except ValueError:
        return {"code": -1, "message": f"non-json response: {out[:80]!r}"}


def refresh_token(host, referer, proxy=None):
    r = api_get(host, "/web/v1/auth/refresh", "", referer, proxy=proxy)
    assert r.get("code") == 0, f"refresh failed: {r}"
    return r["data"]["token"]


def fetch_catalog(host, referer, token, lang=None, proxy=None):
    """带重试：偶发软限流会返回 code=0 但 items 为空"""
    for _ in range(3):
        q = f"/web/v1/wiki/item/catalog?typeMainId=1&onlyOnline=true&_={int(time.time()*1000)}"
        r = api_get(host, q, token, referer, lang=lang, proxy=proxy)
        subs = ((r.get("data") or {}).get("catalog") or [{}])[0].get("typeSub", [])
        ops = next((s for s in subs if s["id"] == "1"), None)
        wep = next((s for s in subs if s["id"] == "2"), None)
        if ops and ops.get("items"):
            return {"operators": ops["items"], "weapons": (wep or {}).get("items", [])}
        time.sleep(2)
    raise RuntimeError(f"catalog empty for lang={lang}")


def safe_name(name):
    return re.sub(r'[\\/:*?"<>|\s]+', "_", name).strip("_")[:60]


def download(url, dest, proxy=None, retries=3):
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    # 跳过已存在的有效 PNG（\x89PNG 魔数）
    if os.path.exists(dest) and open(dest, "rb").read(4) == b"\x89PNG":
        return True
    # 防盗链：hycdn 拒绝 skport Referer，按 CDN 选 Referer
    referer = "https://wiki.skland.com/" if "hycdn.cn" in url else "https://wiki.skport.com/"
    cmd = ["curl", "-s", "--max-time", "60", "-o", dest, "-H", f"User-Agent: {UA}",
           "-H", f"Referer: {referer}", url]
    if proxy and "skport.com" in url or "static.skport" in url:
        cmd += ["-x", proxy] if proxy else []
    for i in range(retries):
        if subprocess.run(cmd, capture_output=True).returncode == 0 and open(dest, "rb").read(4) == b"\x89PNG":
            return True
        time.sleep(1 + i)
    print("  download failed:", os.path.basename(dest), url[:80])
    return False


def collect(server, host, referer, langs, proxy, dry):
    token = refresh_token(host, referer, proxy)
    manifest = {}
    for lang in langs:
        cat = fetch_catalog(host, referer, token, lang=lang, proxy=proxy)
        lang_tag = lang or "zh_Hans"
        for kind in ("operators", "weapons"):
            sub = "operators" if kind == "operators" else "weapons"
            for it in cat[kind]:
                key = it["brief"]["associate"]["id"] if it["brief"].get("associate") else it["itemId"]
                fname = f"{it['itemId']}_{safe_name(it['name'])}.png"
                url = it["brief"]["cover"]
                dest = os.path.join(OUT_DIR, server, sub, lang_tag, fname)
                manifest.setdefault(key, {})[f"{server}:{sub}:{lang_tag}"] = {
                    "itemId": it["itemId"], "name": it["name"], "file": dest,
                    "url": url,
                }
                if not dry and url:
                    download(url, dest, proxy)
        print(f"[{server}] {lang}: operators={len(cat['operators'])} weapons={len(cat['weapons'])} done")
    return manifest


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--langs", nargs="*", default=["en", "ja", "ko", "zh_Hant", "ru_RU", "th_TH"],
                    help="国际服内容语言（有效: en ja ko zh_Hant ru_RU th_TH）")
    ap.add_argument("--dry", action="store_true")
    args = ap.parse_args()

    manifests: dict[str, dict] = {}

    def merge(part: dict):
        # 逐条目合并，不能用 update() —— 国服/国际服共用 associate_id，
        # 整体覆盖会把先收的一方冲掉（真实翻车：cn:operators 全丢）
        for k, v in part.items():
            manifests.setdefault(k, {}).update(v)

    merge(collect("cn", CN_HOST, CN_REFERER, [None], None, args.dry))
    merge(collect("port", PORT_HOST, PORT_REFERER, args.langs, PORT_PROXY, args.dry))

    os.makedirs(MANIFEST_DIR, exist_ok=True)
    out = os.path.join(MANIFEST_DIR, "catalog-manifest.json")
    json.dump(manifests, open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("manifest ->", out, f"({len(manifests)} entries)")


if __name__ == "__main__":
    main()
