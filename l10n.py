"""包内用户可见文案的多语表加载器（数据在 assets/l10n.json，全部包代码共用）。

语言来源（宿主 RunProviderAsync 给每个请求注入 params.ui_lang）：
  zh-Hans / zh-Hant / en / ja / ko / fr / de / es / th / pt-BR
查表顺序：指定语言 → zh-Hans（表由 10 语全覆盖，zh-Hans 是兜底）→ id 本身
（最后一步只在表损坏时发生，界面上直接暴露 id 方便定位）。
占位符 {0}{1}… 与 C# string.Format 同构（assets/l10n.json 一份数据两个消费端）。

用法：
  l10n.set_lang(params.get("ui_lang"))   # provider.py main() 里一次
  l10n.t("k.sign.success")               # 按全局语言取
  l10n.t("pool.special", lang="en")      # 显式覆盖语言（抽卡池列名跟内容语言走，不跟 ui_lang）
"""
import json
from pathlib import Path

LANG = "zh-Hans"
_TABLE: dict | None = None


def set_lang(lang: str) -> None:
    """设置全局界面语言；未知 / 空值回落 zh-Hans。"""
    global LANG
    tag = (lang or "").strip()
    LANG = tag if tag else "zh-Hans"


def _table() -> dict:
    global _TABLE
    if _TABLE is None:
        try:
            data = json.loads((Path(__file__).resolve().parent / "assets" / "l10n.json")
                              .read_text(encoding="utf-8"))
            _TABLE = data.get("strings") or {}
        except (OSError, ValueError):
            _TABLE = {}
    return _TABLE


def t(sid: str, *args, lang: str | None = None) -> str:
    """取文案：lang 参数优先（不传用全局语言）→ zh-Hans → id。args 填 {0}{1}… 占位符。"""
    entry = _table().get(sid) or {}
    key = (lang or "").strip() or LANG
    text = entry.get(key) or entry.get("zh-Hans") or sid
    return text.format(*args) if args else text
