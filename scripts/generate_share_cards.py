#!/usr/bin/env python3
"""
Generate 1200x630 social share cards for the EmuSkins site.

  docs/cards/home.jpg            — home, submit, 404, the index pages, author pages
  docs/cards/systems/{code}.jpg  — one per system page (systems with 3+ skins)

Every card is one image that has to survive every platform's crop: Facebook,
X, LinkedIn and Discord show it at 1.91:1, WhatsApp and some iMessage layouts
crop it square. So the logo and title sit inside the centre 630x630, and the
thumbnail row underneath can lose its edges. Text is wrapped to SAFE_WIDTH.

No counts are drawn into the images. They change on every catalog rebuild and
would rewrite every card; they go in og:description instead. A card is only
rewritten when its bytes change, so an unchanged catalog commits nothing.

Exits non-zero if a font is missing or a card isn't 1200x630 and under
MAX_BYTES (WhatsApp is known to drop large previews).
"""

import io
import json
import sys
import urllib.request
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

SCRIPTS_DIR = Path(__file__).parent
REPO_ROOT = SCRIPTS_DIR.parent
sys.path.insert(0, str(SCRIPTS_DIR))

from generate_system_pages import FAMILY_APPS_BY_SYSTEM, SYSTEM_LABELS  # noqa: E402

CATALOG_PATH = REPO_ROOT / "docs" / "catalog.json"
FEATURED_PATH = REPO_ROOT / "docs" / "featured.json"
CARDS_DIR = REPO_ROOT / "docs" / "cards"
ASSETS_DIR = SCRIPTS_DIR / "assets"
CACHE_DIR = SCRIPTS_DIR / ".cache" / "thumbs"

WIDTH, HEIGHT = 1200, 630
MAX_BYTES = 300 * 1024
MIN_SYSTEM_SKINS = 3  # same threshold as generate_system_pages.py
THUMBS_PER_CARD = 5
THUMB_SIZE = 180
# Text stays inside this width, centred, so a 630x630 centre crop keeps it.
SAFE_WIDTH = 590
IPHONE_IPAD = "iPhone\u00a0&\u00a0iPad"  # never split across lines
USER_AGENT = "EmuSkins-ShareCards/1.0 (+https://emuskins.com)"

BG = (11, 11, 24)
SURFACE = (19, 19, 32)
TEXT = (240, 238, 255)
MUTED = (144, 144, 176)
PINK = (250, 51, 153)
PURPLE = (128, 0, 204)
CYAN = (0, 204, 242)


def font(name, size):
    path = ASSETS_DIR / "fonts" / name
    if not path.exists():
        sys.exit(f"error: missing font {path}")
    return ImageFont.truetype(str(path), size)


def horizontal_gradient(width, height, stops):
    """A left-to-right gradient through `stops` (list of RGB tuples)."""
    grad = Image.new("RGB", (width, height))
    px = grad.load()
    segments = len(stops) - 1
    for x in range(width):
        t = x / max(1, width - 1) * segments
        i = min(int(t), segments - 1)
        f = t - i
        a, b = stops[i], stops[i + 1]
        col = tuple(round(a[k] + (b[k] - a[k]) * f) for k in range(3))
        for y in range(height):
            px[x, y] = col
    return grad


def background():
    img = Image.new("RGB", (WIDTH, HEIGHT), BG)
    # Purple glow from the top centre, cyan from the bottom (same as the site hero).
    for colour, centre_y, strength in ((PURPLE, 0, 0.30), (CYAN, HEIGHT, 0.12)):
        glow = Image.radial_gradient("L").resize((WIDTH * 2, HEIGHT * 2))
        glow = glow.point(lambda v: int((255 - v) * strength))
        layer = Image.new("RGB", (WIDTH, HEIGHT), colour)
        mask = glow.crop((WIDTH // 2, HEIGHT - centre_y, WIDTH // 2 + WIDTH, 2 * HEIGHT - centre_y))
        img.paste(layer, (0, 0), mask)
    # Faint retro grid.
    grid = Image.new("L", (WIDTH, HEIGHT), 0)
    gd = ImageDraw.Draw(grid)
    for x in range(0, WIDTH, 40):
        gd.line([(x, 0), (x, HEIGHT)], fill=14)
    for y in range(0, HEIGHT, 40):
        gd.line([(0, y), (WIDTH, y)], fill=14)
    img.paste(Image.new("RGB", (WIDTH, HEIGHT), PINK), (0, 0), grid)
    # Accent bar along the bottom edge.
    img.paste(horizontal_gradient(WIDTH, 6, [PINK, PURPLE, CYAN]), (0, HEIGHT - 6))
    return img


def wrap(text, f, max_width):
    """Greedy word wrap on plain spaces (NBSP keeps a phrase together); a single
    word wider than max_width gets a line of its own."""
    lines, line = [], ""
    for word in text.split(" "):
        trial = f"{line} {word}".strip()
        if line and f.getlength(trial) > max_width:
            lines.append(line)
            line = word
        else:
            line = trial
    return lines + ([line] if line else [])


def fit_lines(text, name, size, min_size, max_lines=2, max_width=None):
    """The largest size (stepping down by 2) at which `text` wraps into at most
    `max_lines` lines that all fit `max_width`; returns (font, lines)."""
    max_width = max_width or SAFE_WIDTH
    while True:
        f = font(name, size)
        lines = wrap(text, f, max_width)
        if size <= min_size or (len(lines) <= max_lines and all(f.getlength(l) <= max_width for l in lines)):
            return f, lines
        size -= 2


def draw_centered(img, text, f, y, fill):
    d = ImageDraw.Draw(img)
    w = f.getlength(text)
    d.text(((WIDTH - w) / 2, y), text, font=f, fill=fill)


def draw_wordmark(img, y):
    """Logo tile + "Emu" in white + "Skins" in the pink-purple gradient, centred."""
    logo = Image.open(ASSETS_DIR / "logo-160.png").convert("RGBA").resize((64, 64), Image.LANCZOS)
    f = font("Outfit-Bold.ttf", 44)
    emu_w, skins_w = f.getlength("Emu"), f.getlength("Skins")
    total = 64 + 14 + emu_w + skins_w
    x = (WIDTH - total) / 2
    img.paste(logo, (round(x), y), logo)
    tx = x + 64 + 14
    ty = y + 32 - 44 * 0.62  # optical vertical centre against the logo
    d = ImageDraw.Draw(img)
    d.text((tx, ty), "Emu", font=f, fill=TEXT)
    mask = Image.new("L", (round(skins_w) + 4, 70), 0)
    ImageDraw.Draw(mask).text((0, 0), "Skins", font=f, fill=255)
    grad = horizontal_gradient(mask.width, mask.height, [PINK, PURPLE])
    img.paste(grad, (round(tx + emu_w), round(ty)), mask)


def thumb_tile(thumb, size):
    tile = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(tile)
    d.rounded_rectangle([0, 0, size - 1, size - 1], radius=18, fill=SURFACE + (255,),
                        outline=(250, 51, 153, 60), width=2)
    inner = size - 20
    t = thumb.convert("RGBA")
    t.thumbnail((inner, inner), Image.LANCZOS)
    tile.paste(t, ((size - t.width) // 2, (size - t.height) // 2), t)
    return tile


def draw_thumb_row(img, thumbs, y, size=THUMB_SIZE, gap=22):
    if not thumbs:
        return
    total = len(thumbs) * size + (len(thumbs) - 1) * gap
    x = (WIDTH - total) // 2
    for t in thumbs:
        tile = thumb_tile(t, size)
        img.paste(tile, (x, y), tile)
        x += size + gap


def fetch_thumb(skin):
    """The skin's catalog thumbnail, from the local cache or the network; None on failure."""
    url = skin.get("thumbnailURL")
    if not url:
        return None
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cached = CACHE_DIR / f"{skin['id']}.png"
    if not cached.exists():
        try:
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=20) as resp:
                cached.write_bytes(resp.read())
        except Exception as exc:  # network errors, 404s: skip this thumbnail
            print(f"  ! thumbnail {skin['id']}: {exc}")
            return None
    try:
        return Image.open(cached)
    except Exception:
        cached.unlink(missing_ok=True)
        return None


def pick_thumbs(skins, limit, one_per_system=False, prefer_ids=()):
    """Up to `limit` thumbnails: preferred ids first, then most downloaded.
    Variants of one skin share a groupId and look alike, so only one per group."""
    by_id = {s["id"]: s for s in skins if s.get("id")}
    ordered = [by_id[i] for i in prefer_ids if i in by_id]
    ordered += sorted(skins, key=lambda s: (-(s.get("downloadCount") or 0), (s.get("name") or "").lower(), s.get("id", "")))
    picked, seen_groups, seen_systems = [], set(), set()
    for s in ordered:
        group = s.get("groupId") or s.get("id")
        system = (s.get("systems") or [""])[0]
        if group in seen_groups or (one_per_system and system in seen_systems):
            continue
        thumb = fetch_thumb(s)
        if thumb is None:
            continue
        picked.append(thumb)
        seen_groups.add(group)
        seen_systems.add(system)
        if len(picked) == limit:
            break
    return picked


def render_card(title, subtitle, thumbs, footnote=None):
    """Wordmark, title, subtitle and footnote all fit SAFE_WIDTH, so a centre
    square crop keeps them whole; the thumbnail row below may lose its edges."""
    img = background()
    draw_wordmark(img, 36)
    y = 118
    title_font, title_lines = fit_lines(title, "Outfit-Bold.ttf", 76, 52)
    for line in title_lines:
        draw_centered(img, line, title_font, y, TEXT)
        y += round(title_font.size * 1.08)
    y += 10
    sub_font, sub_lines = fit_lines(subtitle, "Outfit-Regular.ttf", 32, 22)
    for line in sub_lines:
        draw_centered(img, line, sub_font, y, MUTED)
        y += round(sub_font.size * 1.25)
    if footnote:
        note_font, note_lines = fit_lines(footnote, "Outfit-Regular.ttf", 24, 18, max_lines=1)
        draw_centered(img, note_lines[0], note_font, y + 4, MUTED)
    draw_thumb_row(img, thumbs, HEIGHT - 6 - 22 - THUMB_SIZE)
    return img


def save_card(img, path):
    assert img.size == (WIDTH, HEIGHT), img.size
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=86, optimize=True, progressive=True)
    data = buf.getvalue()
    if len(data) > MAX_BYTES:
        sys.exit(f"error: {path.name} is {len(data) // 1024} KB, over {MAX_BYTES // 1024} KB")
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and path.read_bytes() == data:
        return "unchanged"
    path.write_bytes(data)
    return f"{len(data) // 1024} KB"


def system_subtitle(code):
    apps = FAMILY_APPS_BY_SYSTEM.get(code, ["Provenance"])
    return "for " + ", ".join(apps) + " and other " + IPHONE_IPAD + " emulators"


def main():
    with open(CATALOG_PATH, encoding="utf-8") as f:
        skins = json.load(f).get("skins", [])
    featured = []
    if FEATURED_PATH.exists():
        featured = [p["id"] for p in json.loads(FEATURED_PATH.read_text()).get("picks", [])]

    home = render_card(
        "Free Controller Skins",
        "for " + IPHONE_IPAD + " emulators",
        pick_thumbs(skins, THUMBS_PER_CARD, one_per_system=True, prefer_ids=featured),
        footnote="Provenance · iCube · iFly · Delta · Manic EMU",
    )
    print(f"  v cards/home.jpg ({save_card(home, CARDS_DIR / 'home.jpg')})")

    by_system = {}
    for s in skins:
        for code in s.get("systems") or []:
            by_system.setdefault(code, []).append(s)
    for code, sk in sorted(by_system.items()):
        if len(sk) < MIN_SYSTEM_SKINS:
            continue
        label = SYSTEM_LABELS.get(code, code)
        card = render_card(f"{label} Skins", system_subtitle(code), pick_thumbs(sk, THUMBS_PER_CARD))
        print(f"  v cards/systems/{code}.jpg ({save_card(card, CARDS_DIR / 'systems' / f'{code}.jpg')})")


if __name__ == "__main__":
    main()
