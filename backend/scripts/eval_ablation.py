"""Ablations for the contest's "model contribution" criterion.

    python scripts/eval_ablation.py [--only titles,ids,feedback]

titles    Free generation vs catalog-grounded: ask each model for films that fit
          a request and check how many names resolve to a real catalog entry.
ids       Picking from a shortlist with vs without the JSON-schema enum:
          how often an unconstrained pick names an id that isn't on the list.
feedback  Feedback structuring on a hand-labelled set: 1.7B vs 4B on accuracy
          (status / rating within 1 / verbatim quote) and latency.

Writes data/eval_ablation.json.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from pianke.catalog import search as catalog  # noqa: E402
from pianke.flows import feedback as fb  # noqa: E402
from pianke.llm import client  # noqa: E402
from pianke.llm.runtime import runtime  # noqa: E402

REQUESTS = [
    "下班很累，想看点温暖治愈、节奏慢的日本电影",
    "想看一部烧脑的科幻片，最好有反转",
    "和家人一起看的轻松喜剧，不要有血腥镜头",
    "想哭一场，关于亲情的电影",
    "九十年代的香港电影，有江湖气的",
    "适合一个人深夜看的、安静的爱情片",
    "节奏快、动作戏好看的电影",
    "有关音乐或者乐队的电影",
]

FEEDBACK = [
    ("看完了，挺温柔的，就是中间有点慢，和女朋友一起看的。", "watched", 4),
    ("太闷了，看了半小时就关了。", "dropped", 1),
    ("神作，结尾我哭了好久，配乐绝了。", "watched", 5),
    ("还行吧，打发时间可以，没什么记忆点。", "watched", 3),
    ("今天心情不好，一个人看的，看完更难受了，拍得太压抑。", "watched", 2),
    ("和爸妈一起看的，他们笑得很开心，我觉得一般。", "watched", 3),
    ("剧情漏洞太多，演员也不行，硬撑着看完了。", "watched", 1),
    ("前半段特别好，后面烂尾了，可惜。", "watched", 3),
    ("看到一半睡着了，改天再看吧。", "dropped", 0),
    ("画面每一帧都能当壁纸，故事反而不重要了，很喜欢。", "watched", 5),
    ("太吵了，打斗一场接一场，看得我头疼，没看完。", "dropped", 1),
    ("意外地好看，本来没抱期待，演技很扎实。", "watched", 4),
]


def resolve_rate(names: list[dict]) -> tuple[int, int]:
    ok = 0
    for n in names:
        if catalog.resolve(n["title"], n.get("year") or None, n.get("original") or None):
            ok += 1
    return ok, len(names)


def eval_titles() -> dict:
    schema = {
        "type": "object",
        "properties": {
            "films": {
                "type": "array", "minItems": 6, "maxItems": 6,
                "items": {
                    "type": "object",
                    "properties": {"title": {"type": "string"}, "original": {"type": "string"}, "year": {"type": "integer"}},
                    "required": ["title", "original", "year"],
                },
            }
        },
        "required": ["films"],
    }
    out = {}
    for model in ("big", "small"):
        ok = total = 0
        examples = []
        for req in REQUESTS:
            data, _ = client.chat(
                model,
                [{"role": "user", "content": f"{req}。推荐 6 部真实存在的作品。title 填中文片名，original 填原始片名，year 填上映年份。"}],
                task="eval_titles", schema=schema, max_tokens=700,
                sampling={"temperature": 0.7, "top_p": 0.95},
            )
            k, n = resolve_rate(data["films"])
            ok += k
            total += n
            for f in data["films"]:
                if not catalog.resolve(f["title"], f.get("year") or None, f.get("original") or None):
                    examples.append(f"{f['title']} / {f['original']} / {f['year']}")
        out[runtime.servers[model].spec.name] = {
            "resolved": ok, "total": total, "rate": round(ok / total, 3),
            "unresolved_examples": examples[:8],
        }
        print(model, out[runtime.servers[model].spec.name], flush=True)
    return out


def eval_ids() -> dict:
    pool = catalog.candidates(kinds=["movie"], genres_any=["Drama"], limit=30)
    lines = "\n".join(catalog.brief(t) for t in pool)
    ids = [t["id"] for t in pool]
    free_schema = {
        "type": "object",
        "properties": {"picks": {"type": "array", "minItems": 3, "maxItems": 3,
                                 "items": {"type": "object", "properties": {"id": {"type": "string"}}, "required": ["id"]}}},
        "required": ["picks"],
    }
    enum_schema = json.loads(json.dumps(free_schema))
    enum_schema["properties"]["picks"]["items"]["properties"]["id"] = {"type": "string", "enum": ids}
    res = {}
    for name, schema in (("free", free_schema), ("enum", enum_schema)):
        bad = total = 0
        for req in REQUESTS:
            data, _ = client.chat(
                "big",
                [{"role": "user", "content": f"用户今晚想看：{req}\n从下面的候选里挑三部，只填 id。\n{lines}"}],
                task="eval_ids", schema=schema, max_tokens=200,
                sampling={"temperature": 0.7, "top_p": 0.95},
            )
            for p in data["picks"]:
                total += 1
                if p["id"] not in ids:
                    bad += 1
        res[name] = {"invalid": bad, "total": total, "invalid_rate": round(bad / total, 3)}
        print(name, res[name], flush=True)
    return res


def eval_feedback() -> dict:
    res = {}
    for model in ("small", "big"):
        status_ok = rating_ok = quote_ok = 0
        secs = []
        for text, status, rating in FEEDBACK:
            t0 = time.time()
            data, _ = client.chat(
                model,
                [{"role": "system", "content": fb.system_for("film")}, {"role": "user", "content": f"片子：某部电影\n用户说：{text}"}],
                task="eval_feedback", schema=fb.SCHEMA, max_tokens=400,
                sampling={"temperature": 0.2, "top_p": 0.9},
            )
            secs.append(time.time() - t0)
            status_ok += data["status"] == status
            rating_ok += (rating == 0 and data["rating"] in (0, 3)) or (rating and abs(data["rating"] - rating) <= 1)
            quote_ok += bool(data["quote"]) and data["quote"] in text
        n = len(FEEDBACK)
        name = runtime.servers[model].spec.name
        res[name] = {
            "status_acc": round(status_ok / n, 3),
            "rating_within_1": round(rating_ok / n, 3),
            "quote_verbatim": round(quote_ok / n, 3),
            "avg_seconds": round(sum(secs) / n, 2),
            "n": n,
        }
        print(name, res[name], flush=True)
    return res


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default="titles,ids,feedback")
    a = ap.parse_args()
    from pianke.memory import store

    store.init()
    runtime.start_all()  # reuses servers that are already up
    for k in ("big", "small"):
        runtime.wait(k)
    path = ROOT / "data" / "eval_ablation.json"
    out = json.loads(path.read_text()) if path.exists() else {}
    for part in a.only.split(","):
        out[part] = {"titles": eval_titles, "ids": eval_ids, "feedback": eval_feedback}[part]()
    out["measured_at"] = time.strftime("%Y-%m-%d %H:%M")
    path.write_text(json.dumps(out, ensure_ascii=False, indent=2))
    print(f"wrote {path}")


if __name__ == "__main__":
    main()
