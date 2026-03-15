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

# Author-page-specific styles only — everything else comes from ../style.css.
AUTHOR_CSS = (
    # Page layout helpers not in style.css
    ".hero-systems{display:flex;gap:6px;flex-wrap:wrap;justify-content:center;margin-bottom:20px}"
    ".back-link{max-width:1200px;margin:20px auto 0;padding:0 24px;"
    "display:block;font-size:14px;color:var(--text-muted)}"
    ".back-link:hover{color:var(--accent);text-decoration:none}"
    # Skin card — cursor tweak so cards feel clickable
    ".skin-card{cursor:pointer}"
    # Author leaderboard grid + cards (not in style.css)
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
    ".author-card-header{display:flex;align-items:center;gap:12px}"
    # Hero avatar override (style.css sets 48px; hero needs 80px with glow)
    ".hero .author-avatar-lg{width:80px!important;height:80px!important;margin-bottom:12px;"
    "border:3px solid var(--accent)!important;box-shadow:0 0 20px var(--accent-glow)}"
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

MODAL_JS = (  # kept for reference — author pages now use browse.js directly
    "<script>\n"
    "(function(){\n"
    "  var cards=Array.from(document.querySelectorAll('.skin-card[data-skin]'));\n"
    "  var overlay=document.getElementById('skin-modal');\n"
    "  var content=document.getElementById('modal-content');\n"
    "  var currentIdx=-1;\n"
    "  var isIOS=/iPhone|iPad|iPod/.test(navigator.userAgent)&&!window.MSStream;\n"
    "  var isInApp=isIOS&&!/Safari\\//.test(navigator.userAgent);\n"
    "\n"
    "  function esc(s){\n"
    "    return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/\"/g,'&quot;');\n"
    "  }\n"
    "\n"
    "  function openAt(idx){\n"
    "    currentIdx=idx;\n"
    "    var s=JSON.parse(cards[idx].dataset.skin);\n"
    "    content.innerHTML=buildModal(s,idx);\n"
    "    overlay.classList.add('open');\n"
    "  }\n"
    "\n"
    "  function close(){\n"
    "    overlay.classList.remove('open');\n"
    "  }\n"
    "\n"
    "  function navigate(dir){\n"
    "    var next=currentIdx+dir;\n"
    "    if(next>=0&&next<cards.length)openAt(next);\n"
    "  }\n"
    "\n"
    "  function buildModal(s,idx){\n"
    "    var name=esc(s.name||'Unnamed Skin');\n"
    "    var dlUrl=s.downloadURL||'#';\n"
    "    var ext=dlUrl.split('.').pop().toLowerCase();\n"
    "    var thumb=s.thumbnailURL\n"
    "      ?'<img src=\"'+esc(s.thumbnailURL)+'\" alt=\"'+name+'\">'\n"
    "      :'<div class=\"modal-no-thumb\">\U0001f3ae</div>';\n"
    "    var systemLabels=s.systemLabels||s.systems||[];\n"
    "    var systems=systemLabels.map(function(x){return'<span class=\"system-badge\">'+esc(x)+'</span>';}).join(' ');\n"
    "    var tags=(s.tags||[]).map(function(x){return'<span class=\"tag\">'+esc(x)+'</span>';}).join(' ');\n"
    "    var meta='';\n"
    "    if(s.version)meta+='<div class=\"modal-meta-row\"><span>Version</span><strong>'+esc(s.version)+'</strong></div>';\n"
    "    if(s.lastUpdated){var d=new Date(s.lastUpdated).toLocaleDateString('en-US',{year:'numeric',month:'short',day:'numeric'});meta+='<div class=\"modal-meta-row\"><span>Updated</span><strong>'+d+'</strong></div>';}\n"
    "    if(s.fileSize){var kb=Math.round(s.fileSize/1024);meta+='<div class=\"modal-meta-row\"><span>Size</span><strong>'+(kb>1024?(kb/1024).toFixed(1)+'MB':kb+'KB')+'</strong></div>';}\n"
    "    if(s.downloadCount)meta+='<div class=\"modal-meta-row\"><span>Downloads</span><strong>'+s.downloadCount.toLocaleString()+'</strong></div>';\n"
    "    var dlBtn=isInApp\n"
    "      ?'<a href=\"'+esc(dlUrl)+'\" class=\"btn btn-primary\">\U0001f4f2 Install Skin</a>'\n"
    "      :isIOS\n"
    "        ?'<a href=\"'+esc(dlUrl)+'\" class=\"btn btn-primary ios-install\">\U0001f4f2 Open in Provenance</a>'\n"
    "        :'<a href=\"'+esc(dlUrl)+'\" class=\"btn btn-primary\" download>\u2b07 Download .'+esc(ext)+'</a>';\n"
    "    var hintText=isInApp\n"
    "      ?'Tap <strong>Install Skin</strong> to add it to your Provenance library.'\n"
    "      :isIOS\n"
    "        ?'Tap <strong>Open in Provenance</strong> \u2014 iOS will open the skin directly in the app.'\n"
    "        :'On iPhone/iPad: open this page in Safari, then tap the download link to install in Provenance.';\n"
    "    var prevBtn=idx>0?'<button class=\"modal-nav modal-prev\" onclick=\"window._pvNav(-1)\" aria-label=\"Previous skin\">\u2039</button>':'';\n"
    "    var nextBtn=idx<cards.length-1?'<button class=\"modal-nav modal-next\" onclick=\"window._pvNav(1)\" aria-label=\"Next skin\">\u203a</button>':'';\n"
    "    return prevBtn+nextBtn\n"
    "      +'<button class=\"modal-close\" onclick=\"window._pvClose()\" aria-label=\"Close\">\u2715</button>'\n"
    "      +'<div class=\"modal-body\">'\n"
    "      +'<div class=\"modal-thumb\">'+thumb+'</div>'\n"
    "      +'<div class=\"modal-info\">'\n"
    "      +'<h2 class=\"modal-title\">'+name+'</h2>'\n"
    "      +(s.author?'<div class=\"modal-author\">by '+esc(s.author)+'</div>':'')\n"
    "      +(systems?'<div class=\"modal-systems\">'+systems+'</div>':'')\n"
    "      +(tags?'<div class=\"modal-tags\">'+tags+'</div>':'')\n"
    "      +(meta?'<div class=\"modal-meta\">'+meta+'</div>':'')\n"
    "      +'<div class=\"modal-actions\">'+dlBtn+'</div>'\n"
    "      +'<div class=\"modal-hint\">'+hintText+'</div>'\n"
    "      +'</div></div>';\n"
    "  }\n"
    "\n"
    "  window._pvClose=close;\n"
    "  window._pvNav=navigate;\n"
    "\n"
    "  document.addEventListener('click',function(e){\n"
    "    var card=e.target.closest('.skin-card[data-skin]');\n"
    "    if(card){\n"
    "      if(e.target.closest('.btn-download'))return;\n"
    "      e.preventDefault();\n"
    "      var idx=cards.indexOf(card);\n"
    "      if(idx>=0)openAt(idx);\n"
    "      return;\n"
    "    }\n"
    "    if(e.target===overlay)close();\n"
    "  });\n"
    "\n"
    "  document.addEventListener('keydown',function(e){\n"
    "    if(!overlay.classList.contains('open'))return;\n"
    "    if(e.key==='Escape')close();\n"
    "    if(e.key==='ArrowLeft')navigate(-1);\n"
    "    if(e.key==='ArrowRight')navigate(1);\n"
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


def github_username_from_skins(skins: list[dict]) -> str | None:
    """Try to derive the GitHub username from the source field of any skin.

    Source field is typically "owner/repo" for GitHub-hosted skins.
    Returns the repo owner if it looks like a GitHub username, else None.
    """
    for s in skins:
        src = s.get("source") or ""
        m = re.match(r"^([A-Za-z0-9_-]+)/[A-Za-z0-9_.-]+$", src)
        if m:
            return m.group(1)
    return None


def author_avatar_html(author_name: str, github_user: str | None, size: int = 48) -> str:
    """Return an <img> tag for an author avatar, with colored-initial fallback."""
    initial = escape(author_name[0].upper()) if author_name else "?"
    # Simple deterministic hue from name
    hue = sum(ord(c) for c in author_name) % 360
    fs = int(size * 0.44)
    r = size // 2
    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{size}" height="{size}">'
        f'<circle cx="{r}" cy="{r}" r="{r}" fill="hsl({hue},62%,40%)"/>'
        f'<text x="{r}" y="{r}" dy=".36em" text-anchor="middle" '
        f'font-family="system-ui,sans-serif" font-size="{fs}" font-weight="700" fill="white">{initial}</text>'
        f'</svg>'
    )
    from urllib.parse import quote
    fallback_url = "data:image/svg+xml;charset=utf-8," + quote(svg)

    if github_user:
        gh_url = f"https://github.com/{github_user}.png?size={size * 2}"
        return (
            f'<img class="author-avatar-lg" src="{escape(gh_url)}" '
            f'alt="{escape(author_name)}" width="{size}" height="{size}" '
            f"onerror=\"this.onerror=null;this.src='{fallback_url}'\">"
        )
    return (
        f'<img class="author-avatar-lg" src="{fallback_url}" '
        f'alt="{escape(author_name)}" width="{size}" height="{size}">'
    )


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

def generate_author_page(author_name, slug, sk_list, github_user=None):
    """Generate a static per-author landing page with all skin cards baked in."""
    count = len(sk_list)
    systems = sorted({sys for s in sk_list for sys in (s.get("systems") or [])})
    system_count = len(systems)

    systems_badges = "".join(
        f'<span class="system-badge">{escape(system_label(c))}</span>\n      '
        for c in systems
    )

    avatar = author_avatar_html(author_name, github_user, size=80)
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
        '  <link rel="stylesheet" href="../style.css">\n'
        f'  <style>{AUTHOR_CSS}</style>\n'
        "</head>\n"
        "<body>\n\n"
        f"{build_nav(active='authors')}\n\n"
        '<div class="hero">\n'
        f'  {avatar}\n'
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
        '<div id="skin-modal" class="modal-overlay" role="dialog" aria-modal="true" aria-label="Skin detail">\n'
        '  <div id="modal-content" class="modal-card"></div>\n'
        '</div>\n\n'
        f"<script>\nwindow.CATALOG_OVERRIDE={json.dumps(sk_list, ensure_ascii=True)};\n</script>\n"
        '<script src="../js/browse.js"></script>\n'
        "<script>\n"
        "(function(){\n"
        "  document.querySelectorAll('.skin-card').forEach(function(card,idx){\n"
        "    card.addEventListener('click',function(e){\n"
        "      if(e.target.closest('a'))return;\n"
        "      openModal(idx);\n"
        "    });\n"
        "  });\n"
        "})();\n"
        "</script>\n"
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
        github_user = item.get("github_user")

        avatar = author_avatar_html(author, github_user, size=48)
        badges = "".join(
            f'<span class="system-badge">{escape(system_label(c))}</span>\n        '
            for c in sorted(systems)
        )
        suffix = "s" if count != 1 else ""
        cards_html += (
            f'  <a href="{slug}.html" class="author-card" '
            f'itemscope itemtype="https://schema.org/Person">\n'
            f'    <div class="author-card-header">\n'
            f'      {avatar}\n'
            f'      <div>\n'
            f'        <div class="author-card-name" itemprop="name">{escape(author)}</div>\n'
            f'        <div class="author-card-count"><span>{count}</span> skin{suffix}</div>\n'
            f'      </div>\n'
            f'    </div>\n'
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
        '  <link rel="stylesheet" href="../style.css">\n'
        f'  <style>{AUTHOR_CSS}</style>\n'
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
        github_user = github_username_from_skins(sk_list)

        out_path = AUTHORS_DIR / f"{slug}.html"
        html = generate_author_page(author, slug, sk_list, github_user=github_user)
        out_path.write_text(html, encoding="utf-8")
        generated.append({
            "author": author,
            "slug": slug,
            "count": count,
            "systems": systems,
            "github_user": github_user,
        })
        print(f"  Generated: authors/{slug}.html  ({count} skins, {len(systems)} systems, gh={github_user})")

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
