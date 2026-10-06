"""Compose the demo video from a real recording of the app.

    PIANKE_REC=<rec> ... npx electron .          # app/scripts/drive/demo.json
    python compose.py <rec> out.mp4 [--from 0 --to 30 --still 12.5]

<rec>/frames.mkv holds the app window as the driver saw it (2x, with alpha
where the window is translucent), <rec>/events.jsonl the time of every
frame, the pointer path, clicks, typing, marks and model waits.

The edit: a flowing warm gradient, the window right of centre, a short
caption on the left for each mark, a drawn pointer that follows the logged
path, and long model waits sped up with an honest badge showing the speed
and the real elapsed time. It opens with the pointer dragging the window
aside and ends on the team and product name. No audio."""

from __future__ import annotations

import argparse
import json
import math
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont

HERE = Path(__file__).resolve().parent
W, H, FPS = 2560, 1440, 30
APP_W, APP_H = 1280, 820  # window size in CSS px
SCALE = 1.25  # CSS px → video px
WIN_W, WIN_H = int(APP_W * SCALE), int(APP_H * SCALE)
WIN_X, WIN_Y = W - WIN_W - 150, (H - WIN_H) // 2
RADIUS = 18
TEXT_X, TEXT_W = 150, WIN_X - 150 - 90

FONT_DIR = Path.home() / "Library" / "Fonts"
SERIF = str(FONT_DIR / "NotoSerifCJKsc-SemiBold.otf")
SERIF_BOLD = str(FONT_DIR / "NotoSerifCJKsc-Bold.otf")
SANS = str(FONT_DIR / "NotoSansCJKsc-Regular.otf")
SANS_MED = str(FONT_DIR / "NotoSansCJKsc-Medium.otf")
LATIN_ITALIC = "/System/Library/Fonts/NewYorkItalic.ttf"

INK = (43, 31, 26)
INK_SOFT = (84, 66, 58)

CURSORS = "/System/Library/Frameworks/ApplicationServices.framework/Versions/A/Frameworks/HIServices.framework/Versions/A/Resources/cursors"

# ---------------------------------------------------------------- captions
# mark id → (step label, title, body, model chip). Only a summary: the
# window shows the rest.
B4 = "Spark-X2.5-4B · 本机推理"
S17 = "Spark-X2.5-1.7B · 本机推理"
CAPTIONS: dict[str, tuple[str, str, str, str | None]] = {
    "intro": ("片刻", "只推荐三部\n每一部都懂你", "管影视、书、音乐三个书架的 Mac 应用。两个 Spark-X2.5 模型都在这台电脑上运行。", None),
    "local": ("01  第一次打开", "模型跑在本机", "llama.cpp 在本机拉起 4B 和 1.7B。你的话、评分和口味画像都不离开这台 Mac。", "离线可用 · 数据不出设备"),
    "domains": ("01  第一次打开", "选你的书架", "影视、书、音乐可以多选，没选的以后点开时再认识。", None),
    "wall": ("02  封面墙", "认出看过的", "点一下是喜欢，点两下是不喜欢。认比回忆省力，每次点击都是核实过的作品。", None),
    "wall-book": ("02  封面墙", "书架也一样", "书库来自 Wikidata，含中文作品。墙上找不到的，可以按书名或作者搜。", None),
    "chat": ("03  四个问题", "从你点过的\n作品问起", "它哪里打动你，那部为什么不喜欢，平时什么时候看，有什么绝对不碰。", B4),
    "build": ("04  口味画像", "第一版画像", "4B 抽取对话里提到的作品，在片库和书库里逐一核实，再写下你的口味。", B4),
    "impression": ("04  口味画像", "先说说\n对你的印象", "每条结论都标出依据，来自你点过的封面和说过的话。", None),
    "compose": ("05  今晚看什么", "说一句\n今天的状态", "再选几个标签。推荐只读固定长度的画像和最近两周，记录再多也一样快。", None),
    "running": ("05  今晚看什么", "先定方向", "4B 把画像和今晚的要求变成片库筛选条件，再说出几部它想到的片。", B4),
    "seeds": ("05  今晚看什么", "每个片名\n都要核实", "先在本地 3 万多部的片库里查，查不到的直接丢掉，界面上如实显示。", B4),
    "result": ("06  只推荐三部", "今晚的三部", "4B 从候选清单里挑选，JSON 语法约束只允许清单里的 id。", B4),
    "reason": ("06  只推荐三部", "因为你说过", "推荐理由只能指向你自己的记录，原话从数据库逐字读出。", None),
    "log": ("07  看过了", "星级只由你给", "评语交给 1.7B 整理成喜欢和不喜欢的方面、状态和同伴，原话逐字保存。", S17),
    "pass": ("08  没看", "每个原因\n去不同的地方", "今晚不合适只进最近两周的近况，想看就存进片单，不感兴趣会写进画像。", None),
    "book": ("09  下一本读什么", "同一条管线", "口味会跨越书影音。在电影里喜欢克制叙述的人，读小说时多半也是。", B4),
    "book-result": ("09  下一本读什么", "跨书架的理由", "挑书的理由引用了你评《花样年华》时写下的原话。书名先查本地书库，再联网核实。", None),
    "records": ("10  记录", "每个书架\n一份日志", "看过的和想看的都在这里，点开是可编辑的记录页。", None),
    "profile": ("11  口味画像", "每条结论\n都有依据", "分偏爱、避开、书影音之间、习惯和最近的变化，标出依据的作品，你可以直接改。", None),
    "consolidate": ("11  口味画像", "重新整理", "4B 把全部记录完整读一遍再重写画像。长上下文只用在这种不赶时间的事上。", B4),
    "profile-v2": ("11  口味画像", "新的一版", "画像有版本，你改过的条目永远保留。", None),
    "settings": ("12  设置", "一切都在本机", "模型、片库、书库和曲库都在这台 Mac 上。联网只用来按作品名查封面。", None),
}

PRE = 3.6  # opening: the pointer drags the window aside
END = 7.0  # closing card
MIN_CAPTION = 4.2  # seconds a caption stays before the next one


# ---------------------------------------------------------------- timeline

@dataclass
class Piece:
    s0: float  # source seconds
    s1: float
    out: float  # output seconds
    fast: tuple[float, float] | None = None  # (wait start, speed) for the badge
    speed: float = 1.0


@dataclass
class Rec:
    frames: list[tuple[float, int]]
    cursor: list[tuple[float, float, float, str]]
    downs: list[tuple[float, float, float]]
    ups: list[float]
    typing: list[tuple[float, float]]
    marks: list[tuple[float, str]]
    waits: list[tuple[float, float]]
    end: float
    pieces: list[Piece] = field(default_factory=list)


def load(rec_dir: Path) -> Rec:
    ev = [json.loads(line) for line in open(rec_dir / "events.jsonl")]
    frames, cursor, downs, ups, typing, marks, waits = [], [], [], [], [], [], []
    t_on = None
    end = 0.0
    for e in ev:
        t = e["t"] / 1000
        end = max(end, t)
        k = e["type"]
        if k == "frame":
            frames.append((t, e["i"]))
        elif k == "cursor":
            cursor.append((t, e["x"], e["y"], e["cur"]))
        elif k == "down":
            downs.append((t, e["x"], e["y"]))
        elif k == "up":
            ups.append(t)
        elif k == "typing":
            if e["on"]:
                t_on = t
            elif t_on is not None:
                typing.append((t_on, t))
                t_on = None
        elif k == "mark":
            marks.append((t, e["id"]))
        elif k == "wait":
            waits.append((max(0.0, e["a"] / 1000), t))
    end_mark = next((t for t, m in marks if m == "end"), end)
    return Rec(frames, cursor, downs, ups, typing, marks, waits, end_mark)


def squeeze(m: float) -> float:
    """Output seconds for m seconds of waiting: short waits play as they
    are, long ones grow only logarithmically."""
    if m <= 3:
        return m
    return 3 + 1.7 * math.log2(1 + (m - 3) / 3)


def build_pieces(r: Rec) -> None:
    keep_a, keep_b = 1.2, 1.0  # real-speed head and tail of each long wait
    cuts: list[tuple[float, float, float]] = []  # (s0, s1, wait start)
    for a, b in sorted(r.waits):
        m = b - a - keep_a - keep_b
        if m > 3 and m / squeeze(m) >= 2:  # a ×1.3 badge would only distract
            cuts.append((a + keep_a, b - keep_b, a))
    pieces: list[Piece] = []
    s = 0.0
    for c0, c1, wa in cuts:
        if c0 < s:
            continue
        if c0 > s:
            pieces.append(Piece(s, c0, c0 - s))
        out = squeeze(c1 - c0)
        pieces.append(Piece(c0, c1, out, fast=(wa, (c1 - c0) / out), speed=(c1 - c0) / out))
        s = c1
    pieces.append(Piece(s, r.end, r.end - s))

    # a caption needs a few seconds on screen: hold the frame where a mark
    # would otherwise be replaced too soon
    caps = [(t, m) for t, m in r.marks if m in CAPTIONS]
    for (t, _), (t2, _) in zip(caps, caps[1:] + [(r.end, "")]):
        gap = to_out(pieces, t2) - to_out(pieces, t)
        if gap < MIN_CAPTION:
            pieces = insert_hold(pieces, t, MIN_CAPTION - gap)
    r.pieces = pieces


def insert_hold(pieces: list[Piece], s: float, dur: float) -> list[Piece]:
    out: list[Piece] = []
    for p in pieces:
        if p.s0 < s < p.s1 and p.speed == 1.0:
            out += [Piece(p.s0, s, s - p.s0), Piece(s, s, dur, speed=0.0), Piece(s, p.s1, p.s1 - s)]
        elif p.s0 == s and p.speed == 1.0 and p.s1 > p.s0:
            out += [Piece(s, s, dur, speed=0.0), p]
        else:
            out.append(p)
    return out


def to_out(pieces: list[Piece], s: float) -> float:
    t = 0.0
    for p in pieces:
        if s <= p.s1 and p.s1 > p.s0:
            return t + (s - p.s0) / max(p.speed, 1e-9) if p.speed else t
        t += p.out
    return t


def at_out(pieces: list[Piece], t: float) -> tuple[float, Piece]:
    for p in pieces:
        if t < p.out:
            return p.s0 + t * p.speed, p
        t -= p.out
    return pieces[-1].s1, pieces[-1]


def body_len(pieces: list[Piece]) -> float:
    return sum(p.out for p in pieces)


# ---------------------------------------------------------------- drawing

def ease(k: float) -> float:
    k = min(1.0, max(0.0, k))
    return 4 * k * k * k if k < 0.5 else 1 - (-2 * k + 2) ** 3 / 2


def ease_out(k: float) -> float:
    k = min(1.0, max(0.0, k))
    return 1 - (1 - k) ** 3


# warm palette, no blue or purple
BASE = np.array([253, 238, 222], np.float32)
BLOBS = [  # colour, centre, drift, speeds, radius
    ((255, 176, 140), (0.15, 0.20), (0.18, 0.14), (0.050, 0.037), 0.55),
    ((250, 132, 118), (0.85, 0.85), (0.16, 0.12), (0.041, 0.053), 0.50),
    ((255, 210, 128), (0.80, 0.15), (0.20, 0.16), (0.033, 0.046), 0.52),
    ((236, 150, 166), (0.25, 0.85), (0.15, 0.18), (0.057, 0.031), 0.45),
    ((168, 214, 186), (0.55, 0.50), (0.30, 0.22), (0.029, 0.043), 0.38),
    ((255, 226, 190), (0.45, 0.10), (0.25, 0.10), (0.047, 0.061), 0.40),
]
GW, GH = 160, 90
_gy, _gx = np.mgrid[0:GH, 0:GW].astype(np.float32)
_gx /= GW
_gy /= GH
_rng = np.random.default_rng(7)
GRAIN = [(_rng.random((H, W, 1), dtype=np.float32) - 0.5) * 3.0 for _ in range(3)]


def background(t: float, i: int) -> np.ndarray:
    x = _gx + 0.035 * np.sin(2.6 * _gy * math.tau / 2 + t * 0.21)
    y = _gy + 0.035 * np.cos(2.2 * _gx * math.tau / 2 + t * 0.17)
    acc = BASE[None, None, :] * 0.6
    wsum = np.full((GH, GW, 1), 0.6, np.float32)
    for k, (col, (cx, cy), (ax, ay), (wx, wy), rad) in enumerate(BLOBS):
        px = cx + ax * math.sin(t * wx * math.tau + k * 1.7)
        py = cy + ay * math.cos(t * wy * math.tau + k * 2.3)
        r = rad * (1 + 0.12 * math.sin(t * 0.07 * math.tau + k))
        d2 = ((x - px) * 16 / 9) ** 2 + (y - py) ** 2
        w = np.exp(-d2 / (r * r * 0.35))[..., None]
        acc = acc + w * np.array(col, np.float32)
        wsum = wsum + w
    small = np.clip(acc / wsum, 0, 255).astype(np.uint8)
    big = np.asarray(Image.fromarray(small).resize((W, H), Image.BICUBIC), np.float32)
    big += GRAIN[i % 3]
    return np.clip(big, 0, 255).astype(np.uint8)


def rounded_mask(w: int, h: int, r: int, ss: int = 4) -> Image.Image:
    m = Image.new("L", (w * ss, h * ss), 0)
    ImageDraw.Draw(m).rounded_rectangle((0, 0, w * ss - 1, h * ss - 1), r * ss, fill=255)
    return m.resize((w, h), Image.LANCZOS)


def make_shadow(w: int, h: int, pad: int) -> Image.Image:
    sh = Image.new("RGBA", (w + 2 * pad, h + 2 * pad), (0, 0, 0, 0))
    big = Image.new("L", sh.size, 0)
    ImageDraw.Draw(big).rounded_rectangle((pad, pad + 34, pad + w, pad + h + 34), RADIUS, fill=95)
    big = big.filter(ImageFilter.GaussianBlur(48))
    tight = Image.new("L", sh.size, 0)
    ImageDraw.Draw(tight).rounded_rectangle((pad, pad + 4, pad + w, pad + h + 4), RADIUS, fill=60)
    tight = tight.filter(ImageFilter.GaussianBlur(5))
    alpha = ImageChops.add(big, tight)
    sh.putalpha(alpha)
    shade = Image.new("RGBA", sh.size, (60, 30, 20, 0))
    shade.putalpha(alpha)
    return shade


def make_chrome(w: int, h: int) -> Image.Image:
    """Traffic lights and the hairline edge, drawn at 4x and reduced."""
    ss = 4
    im = Image.new("RGBA", (w * ss, h * ss), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    r = 6.2 * SCALE * ss
    for cx, fill, edge in ((27, (255, 95, 87), (226, 70, 63)), (50, (254, 188, 46), (222, 157, 28)),
                           (73, (40, 200, 64), (24, 166, 47))):
        x, y = cx * SCALE * ss, 27 * SCALE * ss
        d.ellipse((x - r, y - r, x + r, y + r), fill=edge)
        d.ellipse((x - r + ss * 0.8, y - r + ss * 0.8, x + r - ss * 0.8, y + r - ss * 0.8), fill=fill)
    d.rounded_rectangle((0, 0, w * ss - 1, h * ss - 1), RADIUS * ss, outline=(0, 0, 0, 40), width=int(1.2 * ss))
    return im.resize((w, h), Image.LANCZOS)


def arrow_cursor(px: int = 40) -> tuple[Image.Image, tuple[int, int]]:
    ss = 8
    u = px * ss / 22
    pts = [(0, 0), (0, 16.5), (3.9, 12.8), (6.6, 19.2), (9.2, 18.1), (6.6, 11.9), (11.8, 11.9)]
    im = Image.new("RGBA", (int(16 * u), int(23 * u)), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    off = 1.6 * u
    poly = [(x * u + off, y * u + off) for x, y in pts]
    d.polygon(poly, fill=(255, 255, 255, 255))
    d.line(poly + [poly[0]], fill=(255, 255, 255, 255), width=int(2.6 * u), joint="curve")
    d.polygon(poly, fill=(0, 0, 0, 255))
    im = im.resize((im.width // ss, im.height // ss), Image.LANCZOS)
    return with_shadow(im), (int(off / ss) + 4, int(off / ss) + 4)


def pdf_cursor(name: str, hot: tuple[float, float], px: int = 44) -> tuple[Image.Image, tuple[int, int]]:
    tmp = HERE / f".{name}.png"
    if not tmp.exists():
        subprocess.run(["sips", "-s", "format", "png", "-Z", "256", f"{CURSORS}/{name}/cursor.pdf",
                        "--out", str(tmp)], check=True, capture_output=True)
    im = Image.open(tmp).convert("RGBA")
    k = px / 32  # the PDFs are 32 pt boxes
    im = im.resize((round(32 * k), round(32 * k * im.height / im.width)), Image.LANCZOS)
    return with_shadow(im), (round(hot[0] * k) + 4, round(hot[1] * k) + 4)


def with_shadow(im: Image.Image) -> Image.Image:
    pad = 4
    out = Image.new("RGBA", (im.width + 2 * pad, im.height + 2 * pad + 2), (0, 0, 0, 0))
    a = Image.new("L", out.size, 0)
    a.paste(im.getchannel("A"), (pad, pad + 2))
    a = a.filter(ImageFilter.GaussianBlur(2)).point(lambda v: int(v * 0.45))
    sh = Image.new("RGBA", out.size, (0, 0, 0, 0))
    sh.putalpha(a)
    out = Image.alpha_composite(out, sh)
    out.alpha_composite(im, (pad, pad))
    return out


# ---------------------------------------------------------------- text

PUNCT_NO_START = set("，。、；：！？）》」』,.;:!?)")


def wrap(text: str, font: ImageFont.FreeTypeFont, width: int) -> list[str]:
    lines: list[str] = []
    for para in text.split("\n"):
        cur = ""
        tokens: list[str] = []
        buf = ""
        for ch in para:  # keep latin words and numbers together
            if ch.isascii() and ch not in " ":
                buf += ch
            else:
                if buf:
                    tokens.append(buf)
                    buf = ""
                tokens.append(ch)
        if buf:
            tokens.append(buf)
        for tok in tokens:
            if font.getlength(cur + tok) > width and cur.strip():
                if tok[0] in PUNCT_NO_START:  # pull the last char down with it
                    lines.append(cur[:-1])
                    cur = cur[-1] + tok
                else:
                    lines.append(cur.rstrip())
                    cur = tok.lstrip()
            else:
                cur += tok
        lines.append(cur)
    return lines


def text_block(lines: list[str], font: ImageFont.FreeTypeFont, color, lh: float, width: int) -> Image.Image:
    asc, desc = font.getmetrics()
    h = int(lh * (len(lines) - 1) + asc + desc + 8)
    im = Image.new("RGBA", (width, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    for i, ln in enumerate(lines):
        d.text((0, i * lh), ln, font=font, fill=color)
    return im


def chip(text: str) -> Image.Image:
    f = ImageFont.truetype(SANS_MED, 27)
    tw = int(f.getlength(text))
    w, h = tw + 84, 58
    ss = 3
    im = Image.new("RGBA", (w * ss, h * ss), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.rounded_rectangle((0, 0, w * ss - 1, h * ss - 1), h * ss // 2, fill=(255, 255, 255, 150),
                        outline=(255, 255, 255, 220), width=2 * ss)
    cx, cy, r = 32 * ss, h * ss // 2, 7 * ss
    d.ellipse((cx - r * 2, cy - r * 2, cx + r * 2, cy + r * 2), fill=(52, 199, 89, 60))
    d.ellipse((cx - r, cy - r, cx + r, cy + r), fill=(52, 199, 89, 255))
    im = im.resize((w, h), Image.LANCZOS)
    ImageDraw.Draw(im).text((56, 11), text, font=f, fill=INK)
    return im


@dataclass
class Caption:
    parts: list[tuple[Image.Image, int]]  # image, y offset within the block
    height: int


def make_caption(label: str, title: str, body: str, tag: str | None) -> Caption:
    f_label = ImageFont.truetype(SANS_MED, 28)
    f_title = ImageFont.truetype(SERIF, 84)
    f_body = ImageFont.truetype(SANS, 36)
    parts: list[tuple[Image.Image, int]] = []
    y = 0
    lab = Image.new("RGBA", (TEXT_W, 44), (0, 0, 0, 0))
    d = ImageDraw.Draw(lab)
    d.rounded_rectangle((0, 18, 34, 22), 2, fill=(*INK, 200))
    d.text((52, 0), label, font=f_label, fill=(*INK_SOFT, 255))
    parts.append((lab, y))
    y += 76
    t_img = text_block(wrap(title, f_title, TEXT_W), f_title, (*INK, 255), 112, TEXT_W)
    parts.append((t_img, y))
    y += t_img.height + 30
    b_img = text_block(wrap(body, f_body, TEXT_W - 20), f_body, (*INK_SOFT, 255), 60, TEXT_W)
    parts.append((b_img, y))
    y += b_img.height + 18
    if tag:
        c = chip(tag)
        parts.append((c, y + 14))
        y += c.height + 14
    return Caption(parts, y)


def fade(im: Image.Image, a: float) -> Image.Image:
    if a >= 0.999:
        return im
    arr = np.asarray(im).copy()
    arr[..., 3] = (arr[..., 3].astype(np.float32) * a).astype(np.uint8)
    return Image.fromarray(arr)


def badge(speed: float, elapsed: float) -> Image.Image:
    f = ImageFont.truetype(SANS_MED, 28)
    fm = ImageFont.truetype(SANS, 28)
    s1 = f"加速 ×{speed:.0f}"
    m, s = divmod(int(elapsed), 60)
    s2 = f"实际用时 {m}:{s:02d}"
    w = int(54 + f.getlength(s1) + 34 + fm.getlength(s2) + 32)
    h = 58
    ss = 3
    im = Image.new("RGBA", (w * ss, h * ss), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.rounded_rectangle((0, 0, w * ss - 1, h * ss - 1), h * ss // 2, fill=(43, 31, 26, 215))
    x0, cy = 22 * ss, h * ss // 2
    for dx in (0, 11 * ss):  # fast-forward glyph
        d.polygon([(x0 + dx, cy - 9 * ss), (x0 + dx + 12 * ss, cy), (x0 + dx, cy + 9 * ss)], fill=(255, 214, 160))
    im = im.resize((w, h), Image.LANCZOS)
    d = ImageDraw.Draw(im)
    d.text((54, 11), s1, font=f, fill=(255, 244, 232))
    x = 54 + f.getlength(s1) + 17
    d.line((x, 18, x, h - 18), fill=(255, 244, 232, 90), width=2)
    d.text((x + 17, 11), s2, font=fm, fill=(255, 230, 205))
    return im


# ---------------------------------------------------------------- frames

class Frames:
    """Sequential reader over frames.mkv, scaled to the window size."""

    def __init__(self, path: Path, start: int = 0):
        self.p = subprocess.Popen(
            # frames.mkv is 30 fps by index and ffv1 is intra-only, so -ss lands exactly
            ["ffmpeg", "-v", "error", "-threads", "8", "-ss", f"{start / 30:.4f}", "-i", str(path),
             "-vf", f"scale={WIN_W}:{WIN_H}:flags=lanczos", "-vsync", "0",
             "-f", "rawvideo", "-pix_fmt", "rgba", "-"],
            stdout=subprocess.PIPE, bufsize=WIN_W * WIN_H * 4 * 2)
        self.i = start - 1
        self.cur: Image.Image | None = None

    def get(self, i: int) -> Image.Image:
        n = WIN_W * WIN_H * 4
        while self.i < i:
            buf = self.p.stdout.read(n)
            if len(buf) < n:
                break
            self.i += 1
            if self.i >= i:
                # Chromium hands over premultiplied alpha (the translucent sidebar)
                self.cur = Image.frombuffer("RGBA", (WIN_W, WIN_H), buf, "raw", "RGBa", 0, 1).copy()
        return self.cur


def frame_at(r: Rec, s: float) -> int:
    lo, hi = 0, len(r.frames) - 1
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if r.frames[mid][0] <= s:
            lo = mid
        else:
            hi = mid - 1
    return r.frames[lo][1]


def cursor_at(r: Rec, s: float) -> tuple[float, float, str]:
    c = r.cursor
    lo, hi = 0, len(c) - 1
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if c[mid][0] <= s:
            lo = mid
        else:
            hi = mid - 1
    t0, x0, y0, k = c[lo]
    if lo + 1 < len(c) and c[lo + 1][0] - t0 < 0.1:
        t1, x1, y1, _ = c[lo + 1]
        f = (s - t0) / max(t1 - t0, 1e-6)
        f = min(1, max(0, f))
        return x0 + (x1 - x0) * f, y0 + (y1 - y0) * f, k
    return x0, y0, k


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("rec")
    ap.add_argument("out")
    ap.add_argument("--from", dest="t_from", type=float, default=0)
    ap.add_argument("--to", dest="t_to", type=float, default=None)
    ap.add_argument("--still", type=float, default=None, help="write one PNG at this output time")
    ap.add_argument("--crf", type=int, default=16)
    ap.add_argument("--team", default="天天开心")
    ap.add_argument("--jobs", type=int, default=1, help="render in parallel chunks, then join")
    a = ap.parse_args()
    if a.jobs > 1 and a.still is None:
        return render_parallel(a)

    rec_dir = Path(a.rec)
    r = load(rec_dir)
    build_pieces(r)
    body = body_len(r.pieces)
    total = PRE + body + END
    print(f"source {r.end:.1f}s → body {body:.1f}s, total {total:.1f}s")

    caps = {m: make_caption(*v) for m, v in CAPTIONS.items()}
    cap_times = [(PRE + to_out(r.pieces, t), m) for t, m in r.marks if m in caps]
    cap_times[0] = (PRE - 0.9, cap_times[0][1])  # intro caption arrives with the drag

    mask = rounded_mask(WIN_W, WIN_H, RADIUS)
    chrome = make_chrome(WIN_W, WIN_H)
    SH_PAD = 140
    shadow = make_shadow(WIN_W, WIN_H, SH_PAD)
    cur_img = {"arrow": arrow_cursor(), "pointer": pdf_cursor("pointinghand", (13, 8)),
               "text": pdf_cursor("ibeamhorizontal", (12, 11), 40)}
    end_card = make_end(a.team)

    def out_frames():
        if a.still is not None:
            yield a.still
            return
        n0 = round(a.t_from * FPS)
        n1 = round((a.t_to if a.t_to is not None else total) * FPS)
        for k in range(n0, n1):
            yield k / FPS

    start_frame = 0
    if a.still is None and a.t_from > PRE:
        start_frame = frame_at(r, at_out(r.pieces, a.t_from - PRE)[0])
    elif a.still is not None and a.still > PRE:
        start_frame = frame_at(r, at_out(r.pieces, min(a.still - PRE, body - 1e-3))[0])
    reader = Frames(rec_dir / "frames.mkv", start_frame)

    enc = None
    if a.still is None:
        enc = subprocess.Popen(
            ["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}",
             "-r", str(FPS), "-i", "-", "-c:v", "libx264", "-preset", "medium", "-crf", str(a.crf),
             "-x264-params", "aq-mode=3", "-pix_fmt", "yuv420p", "-movflags", "+faststart", a.out],
            stdin=subprocess.PIPE)

    first_cursor = cursor_at(r, 0)
    n = 0
    for t in out_frames():
        bg = background(t, n)
        canvas = Image.fromarray(bg).convert("RGBA")

        # where in the recording, and where the window sits
        if t < PRE:
            s, piece = 0.0, r.pieces[0]
            s = max(0.0, t - (PRE - 2.0))  # the app's own intro starts moving as the drag ends
        elif t < PRE + body:
            s, piece = at_out(r.pieces, t - PRE)
        else:
            s, piece = r.end, r.pieces[-1]
        drag_k = ease((t - 1.35) / 1.6)
        wx = round((W - WIN_W) / 2 + (WIN_X - (W - WIN_W) / 2) * drag_k)
        wy = WIN_Y
        t_end = t - (PRE + body)
        win_a = 1.0
        if t_end > 0:
            k = ease_out(t_end / 1.1)
            wx += round(90 * k)
            win_a = 1 - k

        if win_a > 0.01:
            app = reader.get(frame_at(r, s))
            under = Image.fromarray(bg[wy:wy + WIN_H, max(0, wx):wx + WIN_W]).convert("RGBA")
            if under.width < WIN_W:
                under = under.resize((WIN_W, WIN_H))
            # sidebar vibrancy: the gradient behind, washed towards light grey
            under = Image.blend(under, Image.new("RGBA", under.size, (238, 236, 234, 255)), 0.72)
            win = Image.alpha_composite(under, app)
            win = Image.alpha_composite(win, chrome)
            win.putalpha(mask if win_a >= 0.999 else mask.point(lambda v, a_=win_a: int(v * a_)))
            canvas.alpha_composite(fade(shadow, win_a), (wx - SH_PAD, wy - SH_PAD))
            canvas.alpha_composite(win, (wx, wy))

        # captions on the left
        if t_end < 1.2:
            draw_captions(canvas, caps, cap_times, t, fade_all=1 - ease_out(max(0, t_end) / 0.8))

        # speed badge during long waits
        if piece.fast and t_end < 0:
            wa, speed = piece.fast
            p0 = PRE + to_out(r.pieces, piece.s0)
            p1 = p0 + piece.out
            ka = min(ease_out((t - p0) / 0.35), ease_out((p1 - t) / 0.35))
            b = fade(badge(speed, s - wa), ka)
            canvas.alpha_composite(b, (TEXT_X, H - 170))

        # pointer
        cx, cy, ck = cursor_at(r, s)
        cur_alpha = 1.0
        if t < PRE:
            grab = (W / 2 + 120, WIN_Y + 22)
            if t < 1.2:
                k = ease(t / 1.2)
                px = W * 0.62 + (grab[0] - W * 0.62) * k
                py = H + 30 + (grab[1] - H - 30) * k
            elif t < 3.05:
                k = drag_k
                px = grab[0] + (WIN_X - (W - WIN_W) / 2) * k
                py = grab[1]
            else:
                k = ease((t - 3.05) / (PRE - 3.05))
                tx, ty = WIN_X + first_cursor[0] * SCALE, WIN_Y + first_cursor[1] * SCALE
                px = grab[0] + (WIN_X - (W - WIN_W) / 2) + (tx - grab[0] - (WIN_X - (W - WIN_W) / 2)) * k
                py = grab[1] + (ty - grab[1]) * k
            ck = "arrow"
            pressed = 1.25 < t < 3.0
        else:
            px, py = WIN_X + cx * SCALE + (wx - WIN_X), WIN_Y + cy * SCALE
            pressed = any(d <= s < u for (d, _, _), u in zip(r.downs, r.ups))
            for a0, a1 in r.typing:
                if a0 + 0.1 <= s <= a1 + 0.35:
                    cur_alpha = 0.0
            if t_end > 0:
                cur_alpha = min(cur_alpha, 1 - ease_out(t_end / 0.6))
        # click ripple
        for d, dx, dy in r.downs:
            if 0 <= s - d < 0.45 and t >= PRE:
                k = (s - d) / 0.45
                ring = Image.new("RGBA", (120, 120), (0, 0, 0, 0))
                rr = 14 + 40 * ease_out(k)
                ImageDraw.Draw(ring).ellipse((60 - rr, 60 - rr, 60 + rr, 60 + rr), outline=(255, 255, 255, int(200 * (1 - k))), width=4)
                canvas.alpha_composite(ring, (int(WIN_X + dx * SCALE - 60), int(WIN_Y + dy * SCALE - 60)))
        if cur_alpha > 0.01:
            im, (hx, hy) = cur_img.get(ck, cur_img["arrow"])
            if pressed:
                im = im.resize((int(im.width * 0.9), int(im.height * 0.9)), Image.LANCZOS)
                hx, hy = int(hx * 0.9), int(hy * 0.9)
            canvas.alpha_composite(fade(im, cur_alpha), (int(px - hx), int(py - hy)))

        # closing card
        if t_end > 0.6:
            k = ease_out((t_end - 0.6) / 1.4)
            for im, (x, y), delay in end_card:
                kk = ease_out((t_end - 0.6 - delay) / 1.2)
                if kk > 0:
                    canvas.alpha_composite(fade(im, kk), (x, int(y + 26 * (1 - kk))))

        rgb = np.asarray(canvas.convert("RGB"))
        if a.still is not None:
            Image.fromarray(rgb).save(a.out)
            print(f"still t={t:.2f}s (source {s:.2f}s) → {a.out}")
            return
        enc.stdin.write(rgb.tobytes())
        n += 1
        if n % 150 == 0:
            print(f"{t:.1f}/{total:.1f}s", flush=True)
    enc.stdin.close()
    enc.wait()
    print(f"done {a.out}")


def render_parallel(a) -> None:
    import sys
    import tempfile

    r = load(Path(a.rec))
    build_pieces(r)
    n_total = round((PRE + body_len(r.pieces) + END) * FPS)
    per = math.ceil(n_total / a.jobs)
    tmp = Path(tempfile.mkdtemp(prefix="compose-", dir=Path(a.out).resolve().parent))
    procs, parts = [], []
    for j in range(a.jobs):
        n0, n1 = j * per, min(n_total, (j + 1) * per)
        if n0 >= n1:
            break
        part = tmp / f"part{j:02d}.mp4"
        parts.append(part)
        procs.append(subprocess.Popen(
            [sys.executable, __file__, a.rec, str(part), "--from", repr(n0 / FPS), "--to", repr(n1 / FPS),
             "--crf", str(a.crf), "--team", a.team],
            stdout=subprocess.DEVNULL if j else None))
    if any(p.wait() for p in procs):
        raise SystemExit("a chunk failed")
    lst = tmp / "parts.txt"
    lst.write_text("".join(f"file '{p.name}'\n" for p in parts))
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "concat", "-safe", "0", "-i", str(lst),
                    "-c", "copy", "-movflags", "+faststart", a.out], check=True)
    for p in parts + [lst]:
        p.unlink()
    tmp.rmdir()
    print(f"done {a.out}")


def draw_captions(canvas: Image.Image, caps: dict[str, Caption], cap_times, t: float, fade_all: float) -> None:
    for idx, (t0, m) in enumerate(cap_times):
        t1 = cap_times[idx + 1][0] if idx + 1 < len(cap_times) else 1e9
        if not (t0 - 0.1 <= t < t1 + 0.45):
            continue
        cap = caps[m]
        top = (H - cap.height) // 2 - 20
        prev = cap_times[idx - 1][1] if idx else None
        same_label = prev is not None and CAPTIONS[prev][0] == CAPTIONS[m][0]
        for j, (im, dy) in enumerate(cap.parts):
            if t < t1:  # entering or shown
                if j == 0 and same_label:
                    k = 1.0  # the step label stays put within a step
                else:
                    k = ease_out((t - t0 - 0.07 * j) / 0.55)
                a_ = k
                off = 22 * (1 - k)
            else:  # leaving
                if j == 0 and idx + 1 < len(cap_times) and CAPTIONS[cap_times[idx + 1][1]][0] == CAPTIONS[m][0]:
                    continue
                k = ease_out((t - t1) / 0.35)
                a_ = 1 - k
                off = -14 * k
            a_ *= fade_all
            if a_ > 0.01:
                canvas.alpha_composite(fade(im, a_), (TEXT_X, int(top + dy + off)))


def make_end(team: str) -> list[tuple[Image.Image, tuple[int, int], float]]:
    out: list[tuple[Image.Image, tuple[int, int], float]] = []

    def centred(text: str, font: ImageFont.FreeTypeFont, color, y: int, delay: float, track: int = 0):
        w = int(font.getlength(text) + track * max(0, len(text) - 1)) + 20
        asc, desc = font.getmetrics()
        im = Image.new("RGBA", (w, asc + desc + 10), (0, 0, 0, 0))
        d = ImageDraw.Draw(im)
        x = 0.0
        if track:
            for ch in text:
                d.text((x, 0), ch, font=font, fill=color)
                x += font.getlength(ch) + track
        else:
            d.text((0, 0), text, font=font, fill=color)
        out.append((im, ((W - w + 20) // 2, y), delay))

    centred("片刻", ImageFont.truetype(SERIF_BOLD, 220), (*INK, 255), 360, 0.0, track=36)
    centred("只推荐三部，每一部都懂你", ImageFont.truetype(SERIF, 54), (*INK_SOFT, 255), 660, 0.25)
    centred("Fewer films, better nights.", ImageFont.truetype(LATIN_ITALIC, 40), (*INK_SOFT, 230), 752, 0.4)
    line = Image.new("RGBA", (120, 3), (*INK, 120))
    out.append((line, ((W - 120) // 2, 868), 0.55))
    centred(f"{team}  团队", ImageFont.truetype(SANS_MED, 46), (*INK, 255), 912, 0.7, track=4)
    centred("Spark-X2.5 端侧模型创新挑战赛", ImageFont.truetype(SANS, 32), (*INK_SOFT, 220), 990, 0.85, track=2)
    return out


if __name__ == "__main__":
    main()
