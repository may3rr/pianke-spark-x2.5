"""L2 consolidation: the 4B model reads the whole memory (every record, in
full, plus the previous profile) and rewrites the taste profile. This is the
one place that uses the long context; recommendation then reads only the
compact result. Every claim must cite records — citations are validated
against the store and invented ones are dropped."""

from __future__ import annotations

import time
from typing import Iterator

from ..llm import client
from ..llm.runtime import runtime
from ..memory import store
from . import memory_view

SECTIONS = [
    ("love", "你偏爱的"),
    ("avoid", "你会避开的"),
    ("bridge", "书影音之间"),
    ("habit", "你的习惯"),
    ("shift", "最近的变化"),
]


def _schema(ids: list[str]) -> dict:
    ev = {"type": "array", "maxItems": 4, "items": {"type": "string", "enum": ids}} if ids else {
        "type": "array", "maxItems": 0, "items": {"type": "string"}}
    claim = {
        "type": "object",
        # a cap lets the grammar end a runaway repetition instead of running
        # to max_tokens (and then a retry at twice that)
        "properties": {"text": {"type": "string", "maxLength": 120}, "evidence": ev},
        "required": ["text", "evidence"],
    }
    return {
        "type": "object",
        "properties": {
            "summary": {"type": "string", "maxLength": 60},
            **{k: {"type": "array", "items": claim, "maxItems": 5} for k, _ in SECTIONS},
        },
        "required": ["summary", *[k for k, _ in SECTIONS]],
    }


SYSTEM = """你在为一位用户整理他的「口味画像」。画像只存在用户自己的电脑上，用户会读，也会改。
记录里有影视、书和音乐三类（每条开头的〔〕标明是哪一类）。根据下面的全部记录、访谈和上一版画像，重写画像：
- summary：一句话概括他的口味，不超过 30 个字，用“你”称呼。
- love（你偏爱的）：他会被什么打动。写具体的感觉、节奏、题材、气质，不要只写类型名；某条只适用于一类时，在开头点明，比如“读书时……”“听歌时……”。
- avoid（你会避开的）：他不喜欢或明确不想碰的东西。“不想看/读/听”后面括号里的原因，是他看到推荐时亲口选的。
- bridge（书影音之间）：跨越不同类别、反复出现的同一种偏好，比如他在电影和小说里都喜欢克制的叙述。必须有至少两类记录作依据；记录只有一类时留空数组。
- habit（你的习惯）：什么时候看、读、听，和谁一起，状态如何影响选择。
- shift（最近的变化）：和更早的记录相比，最近口味有没有移动；没有明显变化就留空数组。
每条 text 不超过 40 个字，用“你”称呼，平实，不用感叹号。
evidence 填支撑这条结论的记录编号（方括号里的 tt 开头编号），只能用记录里真实出现的编号；来自访谈的结论可以不填。
上一版里标注了〔用户改过〕的条目，用户亲自改过，要原样保留。
不要编造记录里没有的片子或感受。"""


def consolidate(reason: str = "manual", think: bool = False) -> Iterator[dict]:
    yield {"type": "step", "key": "read", "status": "running"}
    records, n = memory_view.all_records_text()
    prev = store.profile()
    prev_txt = _prev_text(prev)
    avoid = store.get_pref("avoid", [])
    habits = store.get_pref("habits", {})
    interview = memory_view.interview_text()
    prompt = (
        f"## 全部记录（{n} 条，从早到晚）\n{records or '（暂无）'}\n\n"
        f"## 访谈\n{interview or '（无）'}\n"
        f"明确不想碰：{'、'.join(avoid) or '（未说明）'}\n"
        f"习惯：{habits.get('when') or '未说明'}；{habits.get('with') or ''}\n\n"
        f"## 上一版画像\n{prev_txt}"
    )
    tokens = client.tokenize_count("big", SYSTEM + prompt)
    yield {"type": "step", "key": "read", "status": "done",
           "detail": f"读入 {n} 条记录，约 {tokens:,} 个 token", "tokens": tokens, "records": n}

    yield {"type": "step", "key": "write", "status": "running"}
    ids = [i["id"] for i in store.items()]
    t0 = time.time()
    data, stats = client.chat(
        "big",
        [{"role": "system", "content": SYSTEM}, {"role": "user", "content": prompt}],
        task="profile_consolidate",
        think=think,
        schema=_schema(ids),
        max_tokens=2500,
    )
    valid = set(ids)
    doc = {"summary": data["summary"].strip().replace("您", "你"), "sections": []}
    kept_user = _user_claims(prev)
    for key, title in SECTIONS:
        claims = []
        for c in data.get(key, []):
            text = c["text"].strip().replace("您", "你")
            if not text:
                continue
            ev = [e for e in dict.fromkeys(c.get("evidence") or []) if e in valid]
            claims.append({"text": text, "evidence": ev})
        # user edits survive regardless of what the model did with them
        for uc in kept_user.get(key, []):
            if all(uc["text"] != c["text"] for c in claims):
                claims.insert(0, uc)
            else:
                for c in claims:
                    if c["text"] == uc["text"]:
                        c["user"] = True
        doc["sections"].append({"key": key, "title": title, "claims": claims})
    pstats = {
        "reason": reason,
        "records": n,
        "prompt_tokens": stats.get("prompt_tokens") or tokens,
        "seconds": round(time.time() - t0, 1),
        "prompt_tps": stats.get("prompt_tps"),
        "gen_tps": stats.get("gen_tps"),
        "model": runtime.servers["big"].name,
        "diff": _diff(prev, doc),
    }
    version = store.save_profile(doc, pstats)
    store.event("profile", {"version": version, "reason": reason})
    yield {"type": "step", "key": "write", "status": "done",
           "detail": f"第 {version} 版画像，用时 {pstats['seconds']} 秒"}
    yield {"type": "profile", "profile": store.profile()}


def _prev_text(p: dict | None) -> str:
    if not p:
        return "（这是第一版）"
    lines = [f"一句话：{p['doc'].get('summary', '')}"]
    for sec in p["doc"]["sections"]:
        lines.append(f"【{sec['title']}】")
        for c in sec["claims"]:
            tag = "〔用户改过〕" if c.get("user") else ""
            lines.append(f"- {tag}{c['text']}")
    return "\n".join(lines)


def _user_claims(p: dict | None) -> dict[str, list[dict]]:
    if not p:
        return {}
    return {
        sec["key"]: [c for c in sec["claims"] if c.get("user")] for sec in p["doc"]["sections"]
    }


def _diff(prev: dict | None, doc: dict) -> dict:
    old = {c["text"] for s in (prev["doc"]["sections"] if prev else []) for c in s["claims"]}
    new = {c["text"] for s in doc["sections"] for c in s["claims"]}
    return {"added": len(new - old), "removed": len(old - new), "kept": len(new & old)}


def edit(doc: dict) -> dict:
    """User edits from the profile page. Any claim the user touched or wrote
    is marked user=True so consolidation keeps it."""
    prev = store.profile()
    prev_texts = {c["text"] for s in (prev["doc"]["sections"] if prev else []) for c in s["claims"]}
    for sec in doc.get("sections", []):
        for c in sec.get("claims", []):
            c["text"] = c["text"].strip()
            if c["text"] not in prev_texts:
                c["user"] = True
            c.setdefault("evidence", [])
        sec["claims"] = [c for c in sec.get("claims", []) if c["text"]]
    stats = {"reason": "edit", "diff": _diff(prev, doc)}
    v = store.save_profile(doc, stats)
    store.event("profile_edit", {"version": v})
    return store.profile()
