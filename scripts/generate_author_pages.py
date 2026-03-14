#!/usr/bin/env python3
"""
Generate per-author SEO landing pages for the Provenance Skins catalog.

Creates static HTML — no runtime JavaScript fetch required:
  docs/authors/{slug}.html  — for each author with 2+ skins
  docs/authors/index.html   — author leaderboard sorted by skin count desc

All skin cards are baked into the HTML at build time so pages work for
search engines, AI agents, and users with JavaScript disabled.
"""

import json
import re
import sys
from html import escape
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
CATALOG_PATH = REPO_ROOT / "docs" / "catalog.json"
AUTHORS_DIR = REPO_ROOT / "docs" / "authors"

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
    "pokemonMini": "Pokémon Mini",
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

# ---------------------------------------------------------------------------
# Shared HTML fragments
# ---------------------------------------------------------------------------

INLINE_CSS = (
    ":root{--retro-pink:#FA3399;--retro-purple:#8000CC;--retro-blue:#00CCF2;"
    "--retro-cyan:#00F2F2;--retro-black:#0D0D1A;--retro-dark:#0D0D33;"
    "--bg:#0B0B18;--surface:#131320;--surface2:#1a1a2e;"
    "--border:rgba(250,51,153,0.18);--border-subtle:rgba(255,255,255,0.06);"
    "--text:#f0eeff;--text-muted:#9090b0;--accent:#FA3399;--accent-hover:#ff55aa;"
    "--accent-dim:rgba(250,51,153,0.12);--accent-glow:rgba(250,51,153,0.35);"
    "--cyan:#00CCF2;--cyan-dim:rgba(0,204,242,0.12);--success:#00F2CC;"
    "--danger:#ff4060;--warning:#FAD633;--radius:10px;--radius-sm:6px;"
    "--font:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;"
    "--gradient-neon:linear-gradient(135deg,#FA3399 0%,#8000CC 100%);"
    "--gradient-cyber:linear-gradient(135deg,#00CCF2 0%,#8000CC 100%)}"
    "*{box-sizing:border-box;margin:0;padding:0}"
    "body{background:var(--bg);color:var(--text);font-family:var(--font);"
    "font-size:15px;line-height:1.6;min-height:100vh}"
    "a{color:var(--accent);text-decoration:none}"
    "a:hover{color:var(--accent-hover);text-decoration:underline}"
    "nav{background:rgba(11,11,24,.92);backdrop-filter:blur(16px);"
    "border-bottom:1px solid var(--border);position:sticky;top:0;z-index:100;padding:0 24px}"
    ".nav-inner{max-width:1200px;margin:0 auto;display:flex;align-items:center;gap:24px;height:56px}"
    ".nav-logo{font-weight:800;font-size:17px;color:var(--text);display:flex;align-items:center;gap:8px}"
    ".nav-logo span{background:var(--gradient-neon);-webkit-background-clip:text;"
    "-webkit-text-fill-color:transparent;background-clip:text}"
    ".nav-links{display:flex;gap:4px;margin-left:auto}"
    ".nav-links a{color:var(--text-muted);padding:6px 12px;border-radius:var(--radius-sm);"
    "font-size:14px;transition:color .15s,background .15s}"
    ".nav-links a:hover,.nav-links a.active{color:var(--text);background:var(--surface2);text-decoration:none}"
    ".nav-cta{background:var(--gradient-neon)!important;color:#fff!important;font-weight:700;"
    "padding:6px 16px!important;border-radius:var(--radius-sm);box-shadow:0 0 16px var(--accent-glow)}"
    ".nav-cta:hover{filter:brightness(1.15);text-decoration:none!important}"
    ".hero{text-align:center;padding:64px 24px 48px;position:relative;overflow:hidden;"
    "background:linear-gradient(rgba(250,51,153,.03) 1px,transparent 1px),"
    "linear-gradient(90deg,rgba(250,51,153,.03) 1px,transparent 1px),"
    "radial-gradient(ellipse at 50% 0%,rgba(128,0,204,.18) 0%,transparent 65%),"
    "radial-gradient(ellipse at 50% 100%,rgba(0,204,242,.1) 0%,transparent 60%),"
    "var(--bg);background-size:40px 40px,40px 40px,100% 100%,100% 100%,100% 100%}"
    ".hero::before{content:'';position:absolute;inset:0;"
    "background:repeating-linear-gradient(0deg,transparent,transparent 2px,"
    "rgba(0,0,0,.08) 2px,rgba(0,0,0,.08) 4px);pointer-events:none}"
    ".hero h1{font-size:clamp(28px,5vw,52px);font-weight:900;letter-spacing:-1px;"
    "margin-bottom:12px;background:var(--gradient-neon);-webkit-background-clip:text;"
    "-webkit-text-fill-color:transparent;background-clip:text}"
    ".hero p{color:var(--text-muted);font-size:17px;max-width:560px;margin:0 auto 28px}"
    ".hero-systems{display:flex;gap:6px;flex-wrap:wrap;justify-content:center;margin-bottom:20px}"
    ".hero-actions{display:flex;gap:12px;justify-content:center;flex-wrap:wrap}"
    ".btn{display:inline-flex;align-items:center;gap:6px;padding:10px 20px;"
    "border-radius:var(--radius-sm);font-size:14px;font-weight:700;cursor:pointer;"
    "border:none;transition:all .15s;text-decoration:none!important}"
    ".btn-primary{background:var(--gradient-neon);color:#fff;box-shadow:0 0 20px var(--accent-glow)}"
    ".btn-primary:hover{filter:brightness(1.15);box-shadow:0 0 28px var(--accent-glow);color:#fff}"
    ".btn-outline{background:transparent;color:var(--cyan);border:1px solid var(--cyan)}"
    ".btn-outline:hover{background:var(--cyan-dim);border-color:var(--cyan);color:var(--cyan)}"
    ".btn-sm{padding:6px 12px;font-size:13px}"
    ".btn-success{background:var(--success);color:#0D0D1A;font-weight:800}"
    ".btn-success:hover{filter:brightness(1.1);color:#0D0D1A}"
    ".back-link{max-width:1200px;margin:20px auto 0;padding:0 24px;"
    "display:block;font-size:14px;color:var(--text-muted)}"
    ".back-link:hover{color:var(--accent);text-decoration:none}"
    ".grid-wrap{max-width:1200px;margin:20px auto;padding:0 24px 48px}"
    ".skin-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(240px,1fr));gap:16px}"
    ".skin-card{background:var(--surface);border:1px solid var(--border-subtle);"
    "border-radius:var(--radius);overflow:hidden;transition:transform .15s,border-color .15s,"
    "box-shadow .15s;display:flex;flex-direction:column}"
    ".skin-card:hover{transform:translateY(-3px);border-color:var(--accent);"
    "box-shadow:0 8px 32px var(--accent-glow),0 0 0 1px var(--accent)}"
    ".card-thumb{aspect-ratio:16/10;background:var(--surface2);"
    "background-image:linear-gradient(rgba(250,51,153,.04) 1px,transparent 1px),"
    "linear-gradient(90deg,rgba(250,51,153,.04) 1px,transparent 1px);"
    "background-size:20px 20px;display:flex;align-items:center;justify-content:center;"
    "overflow:hidden;position:relative}"
    ".card-thumb img{width:100%;height:100%;object-fit:cover}"
    ".card-thumb .no-thumb{font-size:40px;opacity:.15}"
    ".card-body{padding:12px;flex:1;display:flex;flex-direction:column;gap:6px}"
    ".card-name{font-weight:700;font-size:14px;line-height:1.3}"
    ".card-author{font-size:12px;color:var(--text-muted)}"
    ".card-tags{display:flex;gap:4px;flex-wrap:wrap;margin-top:2px}"
    ".tag{font-size:11px;padding:2px 7px;border-radius:4px;background:var(--surface2);"
    "color:var(--text-muted);border:1px solid var(--border-subtle)}"
    ".system-badge{font-size:11px;font-weight:800;padding:2px 7px;border-radius:4px;"
    "background:var(--accent-dim);color:var(--accent);text-transform:uppercase;"
    "letter-spacing:.3px;border:1px solid rgba(250,51,153,.25)}"
    ".card-footer{padding:0 12px 12px}"
    ".card-footer .btn{width:100%;justify-content:center}"
    ".dl-count{font-size:11px;color:var(--text-muted);margin-top:4px;text-align:center}"
    "footer{border-top:1px solid var(--border-subtle);padding:32px 24px;"
    "text-align:center;color:var(--text-muted);font-size:13px}"
    "footer a{color:var(--text-muted)}"
    "footer a:hover{color:var(--accent)}"
    "::-webkit-scrollbar{width:6px}::-webkit-scrollbar-track{background:var(--bg)}"
    "::-webkit-scrollbar-thumb{background:var(--border);border-radius:3px}"
    "::-webkit-scrollbar-thumb:hover{background:var(--accent)}"
    "@media(max-width:600px){.nav-logo{font-size:15px}}"
    # Author index
    ".authors-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(260px,1fr));gap:16px}"
    ".author-card{background:var(--surface);border:1px solid var(--border-subtle);"
    "border-radius:var(--radius);padding:20px;transition:transform .15s,border-color .15s,"
    "box-shadow .15s;text-decoration:none!important;display:flex;flex-direction:column;gap:10px}"
    ".author-card:hover{transform:translateY(-3px);border-color:var(--accent);"
    "box-shadow:0 8px 32px var(--accent-glow),0 0 0 1px var(--accent)}"
    ".author-card-name{font-weight:800;font-size:17px;color:var(--text);"
    "background:var(--gradient-neon);-webkit-background-clip:text;"
    "-webkit-text-fill-color:transparent;background-clip:text}"
    ".author-card-count{font-size:13px;color:var(--text-muted)}"
    ".author-card-count span{background:var(--gradient-neon);-webkit-background-clip:text;"
    "-webkit-text-fill-color:transparent;background-clip:text;font-weight:800}"
    ".author-card-systems{display:flex;gap:4px;flex-wrap:wrap}"
)

# Progressive-enhancement only — pages are fully usable without JS.
INSTALL_JS = (
    "<script>\n"
    "(function(){\n"
    "  var isIOS=/iPhone|iPad|iPod/.test(navigator.userAgent)&&!window.MSStream;\n"
    "  var isInApp=isIOS&&!/Safari\\//.test(navigator.userAgent);\n"
    "  if(!isIOS)return;\n"
    "  document.querySelectorAll('.btn-download').forEach(function(a){\n"
    "    a.textContent=isInApp?'\\u{1F4F2} Install Skin':'\\u{1F4F2} Open in Provenance';\n"
    "    a.removeAttribute('download');\n"
    "  });\n"
    "})();\n"
    "</script>"
)


def slugify(name):
    """Convert author name to URL-safe slug (max 50 chars)."""
    slug = name.lower()
    slug = re.sub(r"[^a-z0-9]+", "-", slug)
    slug = slug.strip("-")
    return slug[:50]


def system_label(code):
    return SYSTEM_LABELS.get(code, code)


def build_nav(active="authors"):
    active_browse = ' class="active"' if active == "browse" else ""
    active_systems = ' class="active"' if active == "systems" else ""
    active_authors = ' class="active"' if active == "authors" else ""
    return (
        "<nav>\n"
        "  <div class=\"nav-inner\">\n"
        "    <div class=\"nav-logo\">\U0001f3ae <span>Provenance</span> Skins</div>\n"
        "    <div class=\"nav-links\">\n"
        f"      <a href=\"../index.html\"{active_browse}>Browse</a>\n"
        f"      <a href=\"../systems/index.html\"{active_systems}>Systems</a>\n"
        f"      <a href=\"index.html\"{active_authors}>Authors</a>\n"
        "      <a href=\"../submit.html\">Submit</a>\n"
        "      <a href=\"https://wiki.provenance-emu.com/info/skins-guide\" target=\"_blank\">Docs</a>\n"
        "      <a href=\"https://github.com/Provenance-Emu/skins\" target=\"_blank\" class=\"nav-cta\">GitHub</a>\n"
        "    </div>\n"
        "  </div>\n"
        "</nav>"
    )


FOOTER = (
    "<footer>\n"
    "  <p>\n"
    "    <a href=\"https://provenance-emu.com\" target=\"_blank\">Provenance Emulator</a> \xb7\n"
    "    <a href=\"../submit.html\">Submit a Skin</a> \xb7\n"
    "    <a href=\"https://github.com/Provenance-Emu/skins\" target=\"_blank\">GitHub</a> \xb7\n"
    "    <a href=\"https://discord.gg/provenance\" target=\"_blank\">Discord</a> \xb7\n"
    "    <a href=\"https://wiki.provenance-emu.com\" target=\"_blank\">Wiki</a>\n"
    "  </p>\n"
    "  <p style=\"margin-top:8px;font-size:12px\">Skins are community-created. "
    "Provenance is not affiliated with Delta or DeltaStyles.</p>\n"
    "</footer>"
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def prefer_own_thumbnail(skins):
    """Prefer thumbnails hosted in the skins repo (most reliable, no hotlink protection)."""
    own = next(
        (s["thumbnailURL"] for s in skins
         if s.get("thumbnailURL") and "Provenance-Emu/skins" in s["thumbnailURL"]),
        None,
    )
    if own:
        return own
    return next((s["thumbnailURL"] for s in skins if s.get("thumbnailURL")), "")


def build_card(skin):
    name = escape(skin.get("name") or "Unnamed Skin")
    author = escape(skin.get("author") or "")
    thumb_url = skin.get("thumbnailURL") or ""
    download_url = escape(skin.get("downloadURL") or "#")
    tags = (skin.get("tags") or [])[:3]
    systems = (skin.get("systems") or [])
    dl_count = skin.get("downloadCount") or 0

    # Safe onerror — hides broken image without innerHTML manipulation (no quoting issues)
    if thumb_url:
        thumb_html = (
            f'<img src="{escape(thumb_url)}" alt="{name}" loading="lazy" '
            'onerror="this.style.display=\'none\'">'
        )
    else:
        thumb_html = '<span class="no-thumb">\U0001f3ae</span>'

    sys_html = "".join(
        f'<span class="system-badge">{escape(system_label(s))}</span>' for s in systems
    )
    tags_html = "".join(f'<span class="tag">{escape(t)}</span>' for t in tags)
    dl_html = f'<div class="dl-count">\u2b07 {dl_count:,}</div>' if dl_count else ""

    return (
        f'<article class="skin-card" itemscope itemtype="https://schema.org/SoftwareApplication">\n'
        f'  <div class="card-thumb">{thumb_html}</div>\n'
        f'  <div class="card-body">\n'
        f'    <div class="card-name" itemprop="name">{name}</div>\n'
        + (f'    <div class="card-author" itemprop="author">{author}</div>\n' if author else "")
        + (f'    <div class="card-tags">{sys_html}{tags_html}</div>\n' if sys_html or tags_html else "")
        + "  </div>\n"
        "  <div class=\"card-footer\">\n"
        f'    <a href="{download_url}" class="btn btn-success btn-sm btn-download" '
        f'download itemprop="downloadUrl">\u2b07 Download</a>\n'
        + (f"    {dl_html}\n" if dl_html else "")
        + "  </div>\n"
        "</article>"
    )


def build_jsonld_author(author_name, slug, skins):
    items = []
    for i, skin in enumerate(skins[:20]):
        items.append({
            "@type": "ListItem",
            "position": i + 1,
            "item": {
                "@type": "SoftwareApplication",
                "name": skin.get("name") or "Unnamed",
                "author": {"@type": "Person", "name": author_name},
                "applicationCategory": "GameApplication",
                "operatingSystem": "iOS, iPadOS, macOS, tvOS",
                "downloadUrl": skin.get("downloadURL") or "",
                "image": skin.get("thumbnailURL") or "",
                "isAccessibleForFree": True,
            },
        })
    return {
        "@context": "https://schema.org",
        "@type": "ItemList",
        "name": f"{author_name} Skins for Provenance Emulator",
        "description": (
            f"Browse {len(skins)} free community-created skins by {author_name} "
            f"for Provenance emulator on iPhone, iPad and Apple TV."
        ),
        "url": f"https://provenance-emu.com/skins/authors/{slug}.html",
        "numberOfItems": len(skins),
        "itemListElement": items,
    }


# ---------------------------------------------------------------------------
# Page generators
# ---------------------------------------------------------------------------

def generate_author_page(author_name, slug, sk_list):
    """Generate a static per-author landing page with all skin cards baked in."""
    count = len(sk_list)
    systems = sorted({sys for s in sk_list for sys in (s.get("systems") or [])})
    system_count = len(systems)

    systems_badges = "".join(
        f'<span class="system-badge">{escape(system_label(c))}</span>\n      '
        for c in systems
    )

    og_image = prefer_own_thumbnail(sk_list) or "https://provenance-emu.com/img/sharing-default.png"
    cards_html = "\n".join(build_card(s) for s in sk_list)
    jsonld = json.dumps(build_jsonld_author(author_name, slug, sk_list), ensure_ascii=False)

    suffix_s = "s" if count != 1 else ""
    suffix_sys = "s" if system_count != 1 else ""

    return (
        "<!DOCTYPE html>\n"
        '<html lang="en">\n'
        "<head>\n"
        '  <meta charset="UTF-8">\n'
        '  <meta name="viewport" content="width=device-width, initial-scale=1.0">\n'
        f'  <title>{escape(author_name)} Skins for Provenance — {count} Free Download{suffix_s}</title>\n'
        f'  <meta name="description" content="Browse {count} free skin{suffix_s} by '
        f'{escape(author_name)} for Provenance emulator on iPhone, iPad and Apple TV.">\n'
        f'  <meta property="og:title" content="{escape(author_name)} Skins for Provenance ({count})">\n'
        f'  <meta property="og:description" content="{count} community-created skin{suffix_s} '
        f'by {escape(author_name)} for Provenance emulator.">\n'
        f'  <meta property="og:image" content="{escape(og_image)}">\n'
        '  <meta property="og:type" content="website">\n'
        '  <meta name="twitter:card" content="summary_large_image">\n'
        '  <meta name="apple-itunes-app" content="app-id=1596862805">\n'
        f'  <link rel="canonical" href="https://provenance-emu.com/skins/authors/{slug}.html">\n'
        '  <link rel="icon" href="data:image/svg+xml,<svg xmlns=\'http://www.w3.org/2000/svg\' '
        'viewBox=\'0 0 100 100\'><text y=\'.9em\' font-size=\'90\'>&#127918;</text></svg>">\n'
        f'  <script type="application/ld+json">\n{jsonld}\n  </script>\n'
        f'  <style>{INLINE_CSS}</style>\n'
        "</head>\n"
        "<body>\n\n"
        f"{build_nav(active='authors')}\n\n"
        '<div class="hero">\n'
        f'  <h1>{escape(author_name)}&#39;s Skins</h1>\n'
        f'  <p>{count} skin{suffix_s} across {system_count} system{suffix_sys}</p>\n'
        '  <div class="hero-systems">\n'
        f'    {systems_badges}\n'
        '  </div>\n'
        '  <div class="hero-actions">\n'
        '    <a href="../submit.html" class="btn btn-primary">&#10133; Submit Your Skin</a>\n'
        '    <a href="index.html" class="btn btn-outline">&#8592; All Authors</a>\n'
        '  </div>\n'
        '</div>\n\n'
        '<a href="index.html" class="back-link">&#8592; All Authors</a>\n\n'
        '<div class="grid-wrap">\n'
        '  <div class="skin-grid">\n'
        f'{cards_html}\n'
        '  </div>\n'
        '</div>\n\n'
        f"{FOOTER}\n\n"
        f"{INSTALL_JS}\n"
        "</body>\n"
        "</html>"
    )


def generate_authors_index(authors_data):
    """Generate the authors leaderboard index page (fully static)."""
    cards_html = ""
    for item in authors_data:
        author = item["author"]
        slug = item["slug"]
        count = item["count"]
        systems = item["systems"]

        badges = "".join(
            f'<span class="system-badge">{escape(system_label(c))}</span>\n        '
            for c in sorted(systems)
        )
        suffix = "s" if count != 1 else ""
        cards_html += (
            f'  <a href="{slug}.html" class="author-card" '
            f'itemscope itemtype="https://schema.org/Person">\n'
            f'    <div class="author-card-name" itemprop="name">{escape(author)}</div>\n'
            f'    <div class="author-card-count"><span>{count}</span> skin{suffix}</div>\n'
            f'    <div class="author-card-systems">\n      {badges}\n    </div>\n'
            f'  </a>\n'
        )

    total_skins = sum(item["count"] for item in authors_data)
    total_authors = len(authors_data)

    # Nav for index uses ../index.html paths — rebuild without the .. prefix
    nav_index = (
        "<nav>\n"
        "  <div class=\"nav-inner\">\n"
        "    <div class=\"nav-logo\">\U0001f3ae <span>Provenance</span> Skins</div>\n"
        "    <div class=\"nav-links\">\n"
        "      <a href=\"../index.html\">Browse</a>\n"
        "      <a href=\"../systems/index.html\">Systems</a>\n"
        "      <a href=\"index.html\" class=\"active\">Authors</a>\n"
        "      <a href=\"../submit.html\">Submit</a>\n"
        "      <a href=\"https://wiki.provenance-emu.com/info/skins-guide\" target=\"_blank\">Docs</a>\n"
        "      <a href=\"https://github.com/Provenance-Emu/skins\" target=\"_blank\" class=\"nav-cta\">GitHub</a>\n"
        "    </div>\n"
        "  </div>\n"
        "</nav>"
    )

    return (
        "<!DOCTYPE html>\n"
        '<html lang="en">\n'
        "<head>\n"
        '  <meta charset="UTF-8">\n'
        '  <meta name="viewport" content="width=device-width, initial-scale=1.0">\n'
        '  <title>Skin Contributors — Provenance Skins Catalog</title>\n'
        f'  <meta name="description" content="Browse Provenance emulator skin contributors. '
        f'{total_authors} community artists have created {total_skins} total skins for iPhone, iPad and Apple TV.">\n'
        f'  <meta property="og:title" content="Skin Contributors — Provenance Skins">\n'
        f'  <meta property="og:description" content="{total_authors} contributors · {total_skins} community skins.">\n'
        '  <meta property="og:image" content="https://provenance-emu.com/img/sharing-default.png">\n'
        '  <meta property="og:type" content="website">\n'
        '  <meta name="twitter:card" content="summary_large_image">\n'
        '  <link rel="canonical" href="https://provenance-emu.com/skins/authors/">\n'
        '  <link rel="icon" href="data:image/svg+xml,<svg xmlns=\'http://www.w3.org/2000/svg\' '
        'viewBox=\'0 0 100 100\'><text y=\'.9em\' font-size=\'90\'>&#127918;</text></svg>">\n'
        f'  <style>{INLINE_CSS}</style>\n'
        "</head>\n"
        "<body>\n\n"
        f"{nav_index}\n\n"
        '<div class="hero">\n'
        '  <h1>Skin <span style="background:var(--gradient-cyber);-webkit-background-clip:text;'
        '-webkit-text-fill-color:transparent;background-clip:text;">Contributors</span></h1>\n'
        f'  <p>{total_authors} contributors &middot; {total_skins} community skins for Provenance emulator</p>\n'
        '  <div class="hero-actions">\n'
        '    <a href="../index.html" class="btn btn-outline">&#8592; Browse All Skins</a>\n'
        '    <a href="../submit.html" class="btn btn-primary">&#10133; Submit a Skin</a>\n'
        '  </div>\n'
        '</div>\n\n'
        '<div class="grid-wrap">\n'
        '  <div class="authors-grid">\n'
        f'{cards_html}'
        '  </div>\n'
        '</div>\n\n'
        f"{FOOTER}\n\n"
        "</body>\n"
        "</html>"
    )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    print(f"Reading catalog from {CATALOG_PATH}…")
    with open(CATALOG_PATH) as f:
        catalog = json.load(f)

    skins = catalog.get("skins", [])
    print(f"Total skins in catalog: {len(skins)}")

    # Group by author
    author_skins: dict[str, list] = {}
    for skin in skins:
        author = skin.get("author")
        if not author:
            continue
        author_skins.setdefault(author, []).append(skin)

    AUTHORS_DIR.mkdir(parents=True, exist_ok=True)

    generated = []
    skipped = []

    for author, sk_list in sorted(author_skins.items()):
        count = len(sk_list)
        if count < 2:
            skipped.append(f"{author}: {count} skin(s) — skipped")
            continue

        slug = slugify(author)
        systems = sorted({sys for s in sk_list for sys in (s.get("systems") or [])})

        out_path = AUTHORS_DIR / f"{slug}.html"
        html = generate_author_page(author, slug, sk_list)
        out_path.write_text(html, encoding="utf-8")
        generated.append({
            "author": author,
            "slug": slug,
            "count": count,
            "systems": systems,
        })
        print(f"  Generated: authors/{slug}.html  ({count} skins, {len(systems)} systems)")

    for msg in skipped:
        print(f"  Skipped: {msg}")

    # Sort by skin count descending for the index
    generated.sort(key=lambda x: x["count"], reverse=True)

    # Generate authors index
    index_path = AUTHORS_DIR / "index.html"
    index_html = generate_authors_index(generated)
    index_path.write_text(index_html, encoding="utf-8")
    print(f"  Generated: authors/index.html  ({len(generated)} authors)")

    print(f"\nDone. Generated {len(generated)} author pages + index.")


if __name__ == "__main__":
    main()
