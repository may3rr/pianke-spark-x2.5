#!/usr/bin/env python3
"""把 deck.html 导出成 16:9 矢量 PDF（1280 × 720），并截每页 PNG 预览。

界面图全部来自真实应用：
  颜色     直接引用 app/src/renderer/src/styles/tokens.css
  图标     每次构建时从 app/src/renderer/src/components/Icons.tsx 抽出 SVG
  截图     shots/ 下是驱动脚本 app/scripts/drive/*.json 在真机上拍的原图，只裁切不修改
  代码     data-src 标注的代码块在构建时从源码文件按行号读出

用法：
    conda activate claude
    python presentation/build_deck.py
"""

from __future__ import annotations

import html
import textwrap
import json
import re
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parent
DECK = ROOT / "deck.html"
ICONS_TSX = REPO / "app/src/renderer/src/components/Icons.tsx"
OUT = ROOT / "out" / "片刻_初赛.pdf"
PREVIEW = ROOT / "out" / "deck_png"


def build_icons() -> None:
    """Icons.tsx 里每个 <Fill> 图标 → window.ICONS[name] = svg 内部标记。"""
    src = ICONS_TSX.read_text()
    icons = {}
    for m in re.finditer(r"export function (\w+)Icon\(p: IconProps\) \{\s*return \(\s*<Fill[^>]*>(.*?)</Fill>", src, re.S):
        body = m.group(2)
        body = body.replace("fillRule=", "fill-rule=")
        body = re.sub(r"\s+", " ", body).strip()
        icons[m.group(1)] = body
    (ROOT / "icons.gen.js").write_text(
        "// 构建时从 app/src/renderer/src/components/Icons.tsx 生成，不要手改\n"
        f"window.ICONS = {json.dumps(icons, ensure_ascii=False, indent=1)};\n"
    )
    print(f"[icons] {len(icons)} 个")


def build_code() -> None:
    """data-src="path#L10-L20" 的代码块：从源码按行号读出，写进 code.gen.js。"""
    deck = DECK.read_text()
    blocks = {}
    for ref in sorted(set(re.findall(r'data-src="([^"]+)"', deck))):
        path, rng = ref.split("#L")
        a, b = (int(x) for x in rng.split("-L"))
        lines = (REPO / path).read_text().splitlines()[a - 1 : b]
        blocks[ref] = html.escape(textwrap.dedent("\n".join(lines)))
    (ROOT / "code.gen.js").write_text(
        "// 构建时从源码按行号读出，不要手改\n"
        f"window.CODE = {json.dumps(blocks, ensure_ascii=False, indent=1)};\n"
    )
    print(f"[code] {len(blocks)} 段")


def main() -> None:
    build_icons()
    build_code()
    PREVIEW.mkdir(parents=True, exist_ok=True)
    for old in PREVIEW.glob("*.png"):
        old.unlink()
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome")
        page = browser.new_page(viewport={"width": 1280, "height": 720}, device_scale_factor=2,
                                color_scheme="light")
        page.goto(DECK.as_uri())
        page.wait_for_function("window.deckReady === true", timeout=30000)
        page.evaluate("document.fonts.ready")
        page.wait_for_timeout(400)
        bad = page.evaluate("window.deckOverflow()")
        page.emulate_media(media="print", color_scheme="light")
        slides = page.locator(".slide")
        n = slides.count()
        for i in range(n):
            slides.nth(i).screenshot(path=str(PREVIEW / f"{i + 1:02d}.png"))
        page.pdf(path=str(OUT), width="1280px", height="720px", print_background=True,
                 margin={"top": "0", "right": "0", "bottom": "0", "left": "0"}, prefer_css_page_size=True)
        browser.close()
    for b in bad:
        print(f"[overflow] 第 {b['page']} 页 {b['what']}")
    print(f"[ok] {n} 页 -> {OUT}")


if __name__ == "__main__":
    main()
