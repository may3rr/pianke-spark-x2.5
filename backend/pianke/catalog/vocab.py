"""Shared genre / language / region vocabularies for books and albums.
Used by the library build script, online lookups and the recommender's
JSON schemas, so the model can only ask for buckets that exist."""

from __future__ import annotations

# genre vocab: (Chinese label, English keywords matched against Wikidata
# genre labels). First match wins, so specific before general.
BOOK_GENRES = [
    ("武侠", ["wuxia", "martial arts"]),
    ("科幻", ["science fiction", "sci-fi", "cyberpunk", "dystopi", "space opera"]),
    ("奇幻", ["fantasy", "magic realism", "magical realism", "fairy tale"]),
    ("推理悬疑", ["detective", "mystery", "crime", "thriller", "suspense", "whodunit"]),
    ("恐怖", ["horror", "gothic"]),
    ("爱情", ["romance", "romantic", "love"]),
    ("历史", ["historical", "history"]),
    ("战争", ["war ", "war novel", "military"]),
    ("成长", ["bildungsroman", "coming-of-age", "young adult", "school"]),
    ("儿童", ["children", "picture book", "juvenile"]),
    ("冒险", ["adventure", "picaresque"]),
    ("讽刺", ["satire", "satirical", "humor", "comic novel", "humour"]),
    ("诗歌", ["poetry", "poem", "verse"]),
    ("戏剧", ["play", "drama", "tragedy", "comedy"]),
    ("传记", ["biograph", "memoir", "autobiograph"]),
    ("哲学", ["philosoph"]),
    ("社会", ["social", "sociolog", "politic", "economic"]),
    ("科普", ["popular science", "science"]),
    ("散文随笔", ["essay", "non-fiction", "nonfiction", "travel"]),
    ("漫画", ["manga", "comic", "graphic novel"]),
    ("文学小说", ["novel", "fiction", "literary", "short story", "modernis", "realism", "existential"]),
]
ALBUM_GENRES = [
    ("原声配乐", ["soundtrack", "film score", "musical theatre", "video game music"]),
    ("古典", ["classical", "opera", "baroque", "symphon", "contemporary classical"]),
    ("爵士", ["jazz", "bebop", "swing"]),
    ("金属", ["metal"]),
    ("朋克", ["punk", "hardcore"]),
    ("后摇实验", ["post-rock", "experimental", "avant-garde", "noise", "ambient", "math rock"]),
    ("电子", ["electronic", "techno", "house", "trance", "edm", "synth", "electro", "dubstep", "drum and bass", "idm", "trip hop"]),
    ("嘻哈说唱", ["hip hop", "hip-hop", "rap", "trap"]),
    ("R&B 灵魂", ["r&b", "rhythm and blues", "soul", "funk", "neo soul", "disco", "motown"]),
    ("民谣", ["folk", "singer-songwriter", "acoustic", "americana"]),
    ("乡村", ["country", "bluegrass"]),
    ("蓝调", ["blues"]),
    ("独立另类", ["indie", "alternative", "shoegaze", "dream pop", "grunge", "britpop", "new wave", "post-punk", "emo"]),
    ("摇滚", ["rock"]),
    ("世界音乐", ["world", "latin", "reggae", "bossa", "afro", "flamenco", "k-pop", "j-pop", "city pop"]),
    ("流行", ["pop", "dance", "ballad", "mandopop", "cantopop"]),
]

BOOK_GENRE_NAMES = [g for g, _ in BOOK_GENRES]
ALBUM_GENRE_NAMES = [g for g, _ in ALBUM_GENRES]
BOOK_LANGS = ["中文", "日文", "英文", "法文", "俄文", "西班牙文", "德文", "意大利文", "葡萄牙文", "韩文"]
ALBUM_REGIONS = ["华语", "日本", "韩国", "欧美", "拉美", "其他"]


def map_genres(names: list[str], vocab: list[tuple[str, list[str]]]) -> list[str]:
    out: list[str] = []
    for n in names:
        n = f" {n.lower()} "
        for zh, kws in vocab:
            if any(k in n for k in kws):
                if zh not in out:
                    out.append(zh)
                break
    return out
