#!/usr/bin/env python3
"""
Generate sitemap.xml for the Provenance Skins catalog site.

Outputs docs/sitemap.xml covering:
  - Main pages (index.html, submit.html, systems/index.html, authors/index.html, feed.xml)
  - All system pages (systems/{code}.html)
  - All author pages (authors/{slug}.html)
"""

import json
import re
import sys
from datetime import date
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
CATALOG_PATH = REPO_ROOT / "docs" / "catalog.json"
SITEMAP_PATH = REPO_ROOT / "docs" / "sitemap.xml"
BASE_URL = "https://provenance-emu.github.io/skins/"

SYSTEM_LABELS = {
    "gb": "Game Boy",
    "gbc": "Game Boy Color",
    "gba": "Game Boy Advance",
    "nes": "NES",
    "snes": "SNES",
    "n64": "Nintendo 64",
    "nds": "Nintendo DS",
    "virtualBoy": "Virtual Boy",
    "threeDS": "Nintendo 3DS",
    "gamecube": "GameCube",
    "wii": "Wii",
    "pokemonMini": "Pokemon Mini",
    "genesis": "Sega Genesis",
    "gamegear": "Game Gear",
    "masterSystem": "Master System",
    "sg1000": "SG-1000",
    "segaCD": "Sega CD",
    "sega32X": "Sega 32X",
    "saturn": "Sega Saturn",
    "dreamcast": "Dreamcast",
    "psx": "PlayStation",
    "psp": "PSP",
    "pce": "PC Engine",
    "pcecd": "PC Engine CD",
    "pcfx": "PC-FX",
    "sgfx": "SuperGrafx",
    "lynx": "Atari Lynx",
    "jaguar": "Atari Jaguar",
    "jaguarcd": "Jaguar CD",
    "atari2600": "Atari 2600",
    "atari5200": "Atari 5200",
    "atari7800": "Atari 7800",
    "atari8bit": "Atari 8-bit",
    "atarist": "Atari ST",
    "neogeo": "Neo Geo",
    "ngp": "Neo Geo Pocket",
    "ngpc": "NGP Color",
    "wonderswan": "WonderSwan",
    "wonderswancolor": "WonderSwan Color",
    "vectrex": "Vectrex",
    "_3do": "3DO",
    "appleII": "Apple II",
    "c64": "C64",
    "cdi": "CD-i",
    "colecovision": "ColecoVision",
    "cps1": "CPS1",
    "cps2": "CPS2",
    "cps3": "CPS3",
    "doom": "DOOM",
    "dos": "DOS",
    "intellivision": "Intellivision",
    "macintosh": "Mac Classic",
    "mame": "MAME",
    "megaduck": "Mega Duck",
    "msx": "MSX",
    "msx2": "MSX2",
    "odyssey2": "Odyssey 2",
    "supervision": "Supervision",
    "tic80": "TIC-80",
    "zxspectrum": "ZX Spectrum",
    "retroarch": "RetroArch",
    "unofficial": "Other",
}


def slugify(name):
    """Convert author name to URL-safe slug (max 50 chars)."""
    slug = name.lower()
    slug = re.sub(r"[^a-z0-9]+", "-", slug)
    slug = slug.strip("-")
    return slug[:50]


def url_entry(loc, lastmod, changefreq, priority):
    return (
        f"  <url>\n"
        f"    <loc>{loc}</loc>\n"
        f"    <lastmod>{lastmod}</lastmod>\n"
        f"    <changefreq>{changefreq}</changefreq>\n"
        f"    <priority>{priority:.1f}</priority>\n"
        f"  </url>"
    )


def main():
    print(f"Reading catalog from {CATALOG_PATH}…")
    with open(CATALOG_PATH) as f:
        catalog = json.load(f)

    skins = catalog.get("skins", [])
    today = date.today().isoformat()
    print(f"Total skins in catalog: {len(skins)}")

    entries = []

    # Main pages — priority 1.0
    main_pages = [
        "index.html",
        "submit.html",
        "systems/index.html",
        "authors/index.html",
        "feed.xml",
    ]
    for page in main_pages:
        entries.append(url_entry(
            loc=BASE_URL + page,
            lastmod=today,
            changefreq="daily",
            priority=1.0,
        ))

    # System pages — priority 0.8
    system_skins = {}
    for skin in skins:
        for sys_code in (skin.get("systems") or []):
            system_skins.setdefault(sys_code, []).append(skin)

    for code, sk_list in sorted(system_skins.items()):
        if len(sk_list) < 3:
            continue
        entries.append(url_entry(
            loc=BASE_URL + f"systems/{code}.html",
            lastmod=today,
            changefreq="weekly",
            priority=0.8,
        ))

    # Author pages — priority 0.8
    author_skins = {}
    for skin in skins:
        author = skin.get("author")
        if not author:
            continue
        author_skins.setdefault(author, []).append(skin)

    for author, sk_list in sorted(author_skins.items()):
        if len(sk_list) < 2:
            continue
        slug = slugify(author)
        entries.append(url_entry(
            loc=BASE_URL + f"authors/{slug}.html",
            lastmod=today,
            changefreq="weekly",
            priority=0.8,
        ))

    # Individual skin permalinks via index.html?skin=ID — priority 0.6
    for skin in skins:
        skin_id = skin.get("id")
        if not skin_id:
            continue
        entries.append(url_entry(
            loc=BASE_URL + f"index.html?skin={skin_id}",
            lastmod=today,
            changefreq="monthly",
            priority=0.6,
        ))

    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        + "\n".join(entries)
        + "\n</urlset>\n"
    )

    SITEMAP_PATH.write_text(xml, encoding="utf-8")
    print(f"  Generated: docs/sitemap.xml  ({len(entries)} URLs)")
    print(f"\nDone.")


if __name__ == "__main__":
    main()
