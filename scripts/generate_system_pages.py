#!/usr/bin/env python3
"""
Generate per-system SEO landing pages for the Provenance Skins catalog.

Creates static HTML — no runtime JavaScript fetch required:
  docs/systems/{systemCode}.html  — for each system with 3+ skins
  docs/systems/index.html         — directory overview of all systems

All skin cards are baked into the HTML at build time so pages work for
search engines, AI agents, and users with JavaScript disabled.
"""

import json
import os
import sys
from html import escape
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
CATALOG_PATH = REPO_ROOT / "docs" / "catalog.json"
SYSTEMS_DIR = REPO_ROOT / "docs" / "systems"

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
    "pcfx": "PC-FX",
    "lynx": "Atari Lynx",
    "jaguar": "Atari Jaguar",
    "atari2600": "Atari 2600",
    "atari5200": "Atari 5200",
    "atari7800": "Atari 7800",
    "mame": "MAME",
    "neogeo": "Neo Geo",
    "ngp": "Neo Geo Pocket",
    "ngpc": "Neo Geo Pocket Color",
    "wonderswan": "WonderSwan",
    "wonderswancolor": "WonderSwan Color",
}

DUAL_SCREEN_SYSTEMS = {"nds", "threeDS"}
DUAL_SCREEN_ISSUE = "https://github.com/Provenance-Emu/Provenance/issues/2540"

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
    ".card-footer{padding:0 12px 12px}"
    ".card-footer .btn{width:100%;justify-content:center}"
    ".dl-count{font-size:11px;color:var(--text-muted);margin-top:4px;text-align:center}"
    ".dual-screen-warning{padding:10px 16px;background:rgba(250,214,51,.07);"
    "border:1px solid rgba(250,214,51,.3);border-radius:var(--radius-sm);"
    "font-size:13px;color:var(--warning);line-height:1.5;"
    "max-width:1200px;margin:16px auto 0;padding-left:24px;padding-right:24px}"
    ".dual-screen-warning a{color:var(--warning);text-decoration:underline}"
    "footer{border-top:1px solid var(--border-subtle);padding:32px 24px;"
    "text-align:center;color:var(--text-muted);font-size:13px}"
    "footer a{color:var(--text-muted)}"
    "footer a:hover{color:var(--accent)}"
    "::-webkit-scrollbar{width:6px}::-webkit-scrollbar-track{background:var(--bg)}"
    "::-webkit-scrollbar-thumb{background:var(--border);border-radius:3px}"
    "::-webkit-scrollbar-thumb:hover{background:var(--accent)}"
    "@media(max-width:600px){.nav-logo{font-size:15px}}"
    ".systems-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(220px,1fr));gap:16px}"
    ".system-card{background:var(--surface);border:1px solid var(--border-subtle);"
    "border-radius:var(--radius);overflow:hidden;transition:transform .15s,border-color .15s,"
    "box-shadow .15s;text-decoration:none!important;display:flex;flex-direction:column}"
    ".system-card:hover{transform:translateY(-3px);border-color:var(--accent);"
    "box-shadow:0 8px 32px var(--accent-glow),0 0 0 1px var(--accent)}"
    ".system-card-thumb{aspect-ratio:16/9;background:var(--surface2);"
    "background-image:linear-gradient(rgba(250,51,153,.04) 1px,transparent 1px),"
    "linear-gradient(90deg,rgba(250,51,153,.04) 1px,transparent 1px);"
    "background-size:20px 20px;overflow:hidden;display:flex;align-items:center;justify-content:center}"
    ".system-card-thumb img{width:100%;height:100%;object-fit:cover}"
    ".system-card-thumb .no-thumb{font-size:36px;opacity:.15}"
    ".system-card-body{padding:14px;flex:1}"
    ".system-card-name{font-weight:800;font-size:15px;margin-bottom:4px;color:var(--text)}"
    ".system-card-count{font-size:12px;color:var(--text-muted)}"
    ".system-card-count span{background:var(--gradient-neon);-webkit-background-clip:text;"
    "-webkit-text-fill-color:transparent;background-clip:text;font-weight:800}"
)

# Small JS snippet — purely progressive enhancement for iOS install button.
# Pages are fully usable (all links work) without JS.
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

NAV = """\
<nav>
  <div class="nav-inner">
    <div class="nav-logo">\U0001f3ae <span>Provenance</span> Skins</div>
    <div class="nav-links">
      <a href="../index.html">Browse</a>
      <a href="index.html" class="active">Systems</a>
      <a href="../authors/index.html">Authors</a>
      <a href="../submit.html">Submit</a>
      <a href="https://wiki.provenance-emu.com/info/skins-guide" target="_blank">Docs</a>
      <a href="https://github.com/Provenance-Emu/skins" target="_blank" class="nav-cta">GitHub</a>
    </div>
  </div>
</nav>"""

INDEX_NAV = NAV.replace('href="index.html" class="active"', 'href="index.html" class="active"')

FOOTER = """\
<footer>
  <p>
    <a href="https://provenance-emu.com" target="_blank">Provenance Emulator</a> \xb7
    <a href="../submit.html">Submit a Skin</a> \xb7
    <a href="https://github.com/Provenance-Emu/skins" target="_blank">GitHub</a> \xb7
    <a href="https://discord.gg/provenance" target="_blank">Discord</a> \xb7
    <a href="https://wiki.provenance-emu.com" target="_blank">Wiki</a>
  </p>
  <p style="margin-top:8px;font-size:12px">Skins are community-created. Provenance is not affiliated with Delta or DeltaStyles.</p>
</footer>"""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def prefer_own_thumbnail(skins):
    """Return a thumbnail URL, preferring skins-repo thumbnails (most reliable)."""
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
    dl_count = skin.get("downloadCount") or 0

    # Use onerror to hide broken images (hide, not replace inline HTML — no quoting issues)
    if thumb_url:
        thumb_html = (
            f'<img src="{escape(thumb_url)}" alt="{name}" loading="lazy" '
            'onerror="this.style.display=\'none\'">'
        )
    else:
        thumb_html = '<span class="no-thumb">\U0001f3ae</span>'

    tags_html = "".join(f'<span class="tag">{escape(t)}</span>' for t in tags)
    dl_html = f'<div class="dl-count">\u2b07 {dl_count:,}</div>' if dl_count else ""

    return (
        f'<article class="skin-card" itemscope itemtype="https://schema.org/SoftwareApplication">\n'
        f'  <div class="card-thumb">{thumb_html}</div>\n'
        f'  <div class="card-body">\n'
        f'    <div class="card-name" itemprop="name">{name}</div>\n'
        + (f'    <div class="card-author" itemprop="author">{author}</div>\n' if author else "")
        + (f'    <div class="card-tags">{tags_html}</div>\n' if tags_html else "")
        + f'  </div>\n'
        f'  <div class="card-footer">\n'
        f'    <a href="{download_url}" class="btn btn-success btn-sm btn-download" '
        f'download itemprop="downloadUrl">\u2b07 Download</a>\n'
        + (f'    {dl_html}\n' if dl_html else "")
        + f'  </div>\n'
        f'</article>'
    )


def build_jsonld_system(system_code, system_name, skins):
    items = []
    for i, skin in enumerate(skins[:20]):
        items.append({
            "@type": "ListItem",
            "position": i + 1,
            "item": {
                "@type": "SoftwareApplication",
                "name": skin.get("name") or "Unnamed",
                "author": {"@type": "Person", "name": skin.get("author") or "Unknown"},
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
        "name": f"{system_name} Skins for Provenance Emulator",
        "description": (
            f"Browse {len(skins)} free community-created {system_name} controller skins "
            f"for Provenance emulator on iPhone, iPad and Apple TV."
        ),
        "url": f"https://provenance-emu.com/skins/systems/{system_code}.html",
        "numberOfItems": len(skins),
        "itemListElement": items,
    }


# ---------------------------------------------------------------------------
# Page generators
# ---------------------------------------------------------------------------

def generate_system_page(system_code, system_name, skins):
    count = len(skins)
    is_dual = system_code in DUAL_SCREEN_SYSTEMS
    thumb_url = prefer_own_thumbnail(skins)
    og_image = thumb_url or "https://provenance-emu.com/img/sharing-default.png"

    cards_html = "\n".join(build_card(s) for s in skins)

    dual_warning = ""
    if is_dual:
        dual_warning = (
            '<div class="dual-screen-warning">'
            f'<strong>\u26a0\ufe0f Dual-screen layout not yet active in Provenance.</strong> '
            f'{system_name} dual-screen skin support is in development. '
            f'<a href="{DUAL_SCREEN_ISSUE}" target="_blank" rel="noopener">Track progress \u2192</a>'
            '</div>'
        )

    jsonld = json.dumps(
        build_jsonld_system(system_code, system_name, skins),
        ensure_ascii=False,
    )

    suffix = "s" if count != 1 else ""
    return (
        "<!DOCTYPE html>\n"
        '<html lang="en">\n'
        "<head>\n"
        '  <meta charset="UTF-8">\n'
        '  <meta name="viewport" content="width=device-width, initial-scale=1.0">\n'
        f'  <title>{system_name} Skins for Provenance — {count} Free Download{suffix}</title>\n'
        f'  <meta name="description" content="Browse {count} free community-created '
        f'{system_name} controller skins for Provenance emulator on iPhone, iPad and Apple TV.">\n'
        f'  <meta property="og:title" content="{system_name} Skins for Provenance ({count})">\n'
        f'  <meta property="og:description" content="{count} free {system_name} skins '
        f'for Provenance emulator \u2014 iPhone, iPad &amp; Apple TV.">\n'
        f'  <meta property="og:image" content="{escape(og_image)}">\n'
        '  <meta property="og:type" content="website">\n'
        '  <meta name="twitter:card" content="summary_large_image">\n'
        '  <meta name="apple-itunes-app" content="app-id=1596862805">\n'
        f'  <link rel="canonical" href="https://provenance-emu.com/skins/systems/{system_code}.html">\n'
        "  <link rel=\"icon\" href=\"data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'><text y='.9em' font-size='90'>\U0001f3ae</text></svg>\">\n"
        f'  <script type="application/ld+json">{jsonld}</script>\n'
        f'  <style>{INLINE_CSS}</style>\n'
        "</head>\n"
        "<body>\n\n"
        f"{NAV}\n\n"
        '<div class="hero">\n'
        f'  <h1>{system_name} Skins for Provenance</h1>\n'
        f'  <p>{count} community-created skin{suffix} for iPhone, iPad and Apple TV</p>\n'
        '  <div class="hero-actions">\n'
        '    <a href="../submit.html" class="btn btn-primary">\u2795 Submit Your Skin</a>\n'
        '    <a href="index.html" class="btn btn-outline">\u2190 All Systems</a>\n'
        '  </div>\n'
        '</div>\n\n'
        + (dual_warning + "\n\n" if dual_warning else "")
        + '<div class="grid-wrap">\n'
        '  <div class="skin-grid" itemscope itemtype="https://schema.org/ItemList">\n'
        + cards_html + "\n"
        + '  </div>\n'
        '</div>\n\n'
        + FOOTER + "\n"
        + INSTALL_JS + "\n"
        "</body>\n</html>\n"
    )


def generate_systems_index(systems_data):
    total_skins = sum(item["count"] for item in systems_data)
    total_systems = len(systems_data)

    cards_html = ""
    for item in sorted(systems_data, key=lambda x: x["label"]):
        code = item["code"]
        label = escape(item["label"])
        count = item["count"]
        thumb = item.get("thumbnail", "")
        is_dual = code in DUAL_SCREEN_SYSTEMS

        if thumb:
            thumb_html = (
                f'<img src="{escape(thumb)}" alt="{label}" loading="lazy" '
                'onerror="this.style.display=\'none\'">'
            )
        else:
            thumb_html = '<span class="no-thumb">\U0001f3ae</span>'

        dual_badge = (
            ' <span style="font-size:10px;color:var(--warning);font-weight:800">COMING SOON</span>'
            if is_dual else ""
        )
        suffix = "s" if count != 1 else ""

        cards_html += (
            f'  <a href="{code}.html" class="system-card">\n'
            f'    <div class="system-card-thumb">{thumb_html}</div>\n'
            f'    <div class="system-card-body">\n'
            f'      <div class="system-card-name">{label}{dual_badge}</div>\n'
            f'      <div class="system-card-count"><span>{count}</span> skin{suffix}</div>\n'
            f'    </div>\n'
            f'  </a>\n'
        )

    jsonld = json.dumps({
        "@context": "https://schema.org",
        "@type": "CollectionPage",
        "name": "Provenance Skins \u2014 Browse by System",
        "description": (
            f"Browse {total_systems} emulated systems with {total_skins} "
            f"community-created controller skins for Provenance emulator."
        ),
        "url": "https://provenance-emu.com/skins/systems/",
        "numberOfItems": total_systems,
    }, ensure_ascii=False)

    return (
        "<!DOCTYPE html>\n"
        '<html lang="en">\n'
        "<head>\n"
        '  <meta charset="UTF-8">\n'
        '  <meta name="viewport" content="width=device-width, initial-scale=1.0">\n'
        '  <title>All Systems \u2014 Provenance Skins Catalog</title>\n'
        f'  <meta name="description" content="Browse {total_systems} emulated systems with '
        f'{total_skins} community-created controller skins for Provenance emulator on iPhone, '
        f'iPad and Apple TV.">\n'
        '  <meta property="og:title" content="All Systems \u2014 Provenance Skins">\n'
        f'  <meta property="og:description" content="Browse {total_systems} emulated systems '
        f'with {total_skins} community skins for Provenance.">\n'
        '  <meta property="og:image" content="https://provenance-emu.com/img/sharing-default.png">\n'
        '  <meta property="og:type" content="website">\n'
        '  <meta name="twitter:card" content="summary_large_image">\n'
        '  <meta name="apple-itunes-app" content="app-id=1596862805">\n'
        '  <link rel="canonical" href="https://provenance-emu.com/skins/systems/">\n'
        "  <link rel=\"icon\" href=\"data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'><text y='.9em' font-size='90'>\U0001f3ae</text></svg>\">\n"
        f'  <script type="application/ld+json">{jsonld}</script>\n'
        f'  <style>{INLINE_CSS}</style>\n'
        "</head>\n"
        "<body>\n\n"
        f"{NAV}\n\n"
        '<div class="hero">\n'
        '  <h1>Browse by <span style="background:var(--gradient-cyber);'
        '-webkit-background-clip:text;-webkit-text-fill-color:transparent;'
        'background-clip:text;">System</span></h1>\n'
        f'  <p>{total_systems} systems \xb7 {total_skins} community skins for Provenance emulator</p>\n'
        '  <div class="hero-actions">\n'
        '    <a href="../index.html" class="btn btn-outline">\u2190 Browse All Skins</a>\n'
        '    <a href="../submit.html" class="btn btn-primary">\u2795 Submit a Skin</a>\n'
        '  </div>\n'
        '</div>\n\n'
        '<div class="grid-wrap">\n'
        '  <div class="systems-grid">\n'
        + cards_html
        + '  </div>\n'
        '</div>\n\n'
        + FOOTER + "\n"
        "</body>\n</html>\n"
    )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    print(f"Reading catalog from {CATALOG_PATH}...")
    with open(CATALOG_PATH, encoding="utf-8") as f:
        catalog = json.load(f)

    skins = catalog.get("skins", [])
    print(f"Total skins in catalog: {len(skins)}")

    system_skins: dict = {}
    for skin in skins:
        for sys_code in (skin.get("systems") or []):
            system_skins.setdefault(sys_code, []).append(skin)

    SYSTEMS_DIR.mkdir(parents=True, exist_ok=True)

    generated = []
    skipped = []

    for code, sk_list in sorted(system_skins.items()):
        count = len(sk_list)
        label = SYSTEM_LABELS.get(code, code)
        if count < 3:
            skipped.append(f"{label} ({code}): {count} skin(s) -- skipped")
            continue

        sk_sorted = sorted(sk_list, key=lambda s: (s.get("name") or "").lower())
        thumb = prefer_own_thumbnail(sk_sorted)

        out_path = SYSTEMS_DIR / f"{code}.html"
        out_path.write_text(generate_system_page(code, label, sk_sorted), encoding="utf-8")

        thumb_src = "own" if thumb and "Provenance-Emu/skins" in thumb else ("external" if thumb else "none")
        print(f"  v {out_path.name}  ({count} skins, thumb: {thumb_src})")
        generated.append({"code": code, "label": label, "count": count, "thumbnail": thumb})

    for msg in skipped:
        print(f"  - {msg}")

    index_path = SYSTEMS_DIR / "index.html"
    index_path.write_text(generate_systems_index(generated), encoding="utf-8")
    print(f"  v systems/index.html  ({len(generated)} systems)")
    print(f"\nDone. Generated {len(generated)} system pages + index.")


if __name__ == "__main__":
    main()
