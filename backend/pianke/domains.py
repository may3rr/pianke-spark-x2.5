"""The three shelves 片刻 keeps: films, books and albums. Everything that
differs between them in wording or rhythm lives here, so the flows can stay
one pipeline."""

from __future__ import annotations

DOMAINS = ("film", "book", "music")

WORDS = {
    "film": {
        "label": "影视", "unit": "部", "noun": "片", "work": "影视作品", "verb": "看",
        "done": "看过", "dropped": "没看完", "list": "片单", "ask": "今晚看什么",
        "when": "今晚", "pick3": "挑三部",
    },
    "book": {
        "label": "书", "unit": "本", "noun": "书", "work": "书", "verb": "读",
        "done": "读过", "dropped": "没读完", "list": "书单", "ask": "下一本读什么",
        "when": "接下来", "pick3": "挑三本",
    },
    "music": {
        "label": "音乐", "unit": "张", "noun": "专辑", "work": "专辑", "verb": "听",
        "done": "听过", "dropped": "没听完", "list": "歌单", "ask": "现在听什么",
        "when": "现在", "pick3": "挑三张",
    },
}

# how long after a pick we still ask "did you get to it?"
CHECKIN_DAYS = {"film": 3, "book": 14, "music": 2}

# why-not reasons: each one does something different to memory
#   want      → goes on the list
#   taste     → a negative record that consolidation reads (with the reason)
#   moment    → only the recent layer (L3); the long-term profile never sees it
PASS_REASONS = {
    "want": {"label": "想{verb}，先存着", "effect": "want"},
    "not_interested": {"label": "不感兴趣", "effect": "taste"},
    "not_my_taste": {"label": "知道它，不对胃口", "effect": "taste"},
    "not_now": {"label": "{when}不合适", "effect": "moment"},
}


def w(domain: str, key: str) -> str:
    return WORDS[domain][key]


def reason_label(domain: str, key: str) -> str:
    return PASS_REASONS[key]["label"].format(**WORDS[domain])


def tag(domain: str) -> str:
    return {"film": "影视", "book": "书", "music": "音乐"}[domain]
