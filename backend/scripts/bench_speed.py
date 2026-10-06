"""How fast can Spark-X2.5-4B read a long memory on this Mac?

    python scripts/bench_speed.py [--url http://127.0.0.1:18741] [--sizes 4096,16384,...]

For each size, builds a memory of realistic record lines (catalog titles +
user-style remarks) of about that many tokens, then
  1) asks once with a fresh prefix  -> cold prefill speed and wall time
  2) asks again with the same prefix -> time when the KV cache is reused
Writes data/bench_speed.json, which the Settings page charts.
"""

from __future__ import annotations

import argparse
import json
import platform
import random
import subprocess
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[2]

REMARKS = [
    "节奏很慢，但最后那场戏后劲很大", "配乐太满了，有点吵", "和女朋友一起看的，她哭了",
    "加班回来看的，刚好不用动脑", "前半段很好，结尾烂了", "看了二十分钟弃了，太闷",
    "颜色和构图都特别好看", "台词很密，要很专注", "笑得停不下来", "有点压抑，但拍得真诚",
]


def machine() -> str:
    try:
        chip = subprocess.check_output(["sysctl", "-n", "machdep.cpu.brand_string"], text=True).strip()
        mem = int(subprocess.check_output(["sysctl", "-n", "hw.memsize"], text=True)) / 2**30
        return f"{chip}，{mem:.0f}GB 内存"
    except Exception:
        return platform.platform()


def corpus(n_lines: int, seed: int) -> list[str]:
    import sqlite3

    db = sqlite3.connect(ROOT / "data" / "catalog.sqlite")
    rows = db.execute(
        "select id, coalesce(zh, title), year, genres from titles order by votes desc limit 20000"
    ).fetchall()
    rnd = random.Random(seed)
    out = []
    for i in range(n_lines):
        tid, name, year, genres = rows[rnd.randrange(len(rows))]
        out.append(
            f"[{tid}] {name}（{year}） ｜ 看过 ｜ {rnd.randint(1, 5)}/5 ｜ {genres} ｜ "
            f"原话：“{rnd.choice(REMARKS)}，{rnd.choice(REMARKS)}” ｜ 2026-0{rnd.randint(1, 9)}-{rnd.randint(10, 28)}"
        )
    return out


def count(url: str, text: str) -> int:
    return len(httpx.post(f"{url}/tokenize", json={"content": text}, timeout=120).json()["tokens"])


def ask(url: str, memory: str, question: str) -> dict:
    t0 = time.time()
    r = httpx.post(
        f"{url}/v1/chat/completions",
        json={
            "messages": [
                {"role": "system", "content": "下面是一位用户的全部观影记录。"},
                {"role": "user", "content": memory + "\n\n" + question},
            ],
            "max_tokens": 24,
            "temperature": 0,
            "cache_prompt": True,
            "chat_template_kwargs": {"enable_thinking": False},
        },
        timeout=3600,
    ).json()
    t = r.get("timings", {})
    return {
        "seconds": round(time.time() - t0, 2),
        "prompt_n": t.get("prompt_n"),
        "cache_n": t.get("cache_n"),
        "prompt_tps": t.get("prompt_per_second"),
        "gen_tps": t.get("predicted_per_second"),
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://127.0.0.1:18741")
    ap.add_argument("--sizes", default="4096,16384,32768,65536,122880")
    a = ap.parse_args()
    probe = "\n".join(corpus(200, 0))
    per_line = count(a.url, probe) / 200
    rows = []
    for size in [int(s) for s in a.sizes.split(",")]:
        n = max(10, int(size / per_line))
        mem = f"（第 {size} 组，{time.time()}）\n" + "\n".join(corpus(n, size))
        toks = count(a.url, mem)
        first = ask(a.url, mem, "用一句话概括这位用户的口味。")
        cached = ask(a.url, mem, "他最近最喜欢哪一部？只说片名。")
        row = {
            "ctx": toks,
            "records": n,
            "prompt_tps": round(first["prompt_tps"] or 0, 1),
            "first_seconds": first["seconds"],
            "cached_seconds": cached["seconds"],
            "cached_tokens": cached["cache_n"],
            "gen_tps": round(first["gen_tps"] or 0, 1),
        }
        rows.append(row)
        print(json.dumps(row, ensure_ascii=False), flush=True)
    out = {
        "model": "Spark-X2.5-4B Q4_K_M",
        "machine": machine(),
        "runtime": "llama.cpp (Metal), flash attention",
        "measured_at": time.strftime("%Y-%m-%d %H:%M"),
        "rows": rows,
    }
    p = ROOT / "data" / "bench_speed.json"
    p.write_text(json.dumps(out, ensure_ascii=False, indent=2))
    print(f"wrote {p}")


if __name__ == "__main__":
    main()
