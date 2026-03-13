#!/usr/bin/env python3
"""
Generate per-author SEO landing pages for the Provenance Skins catalog.

Creates:
  docs/authors/{slug}.html  — for each author with 2+ skins
  docs/authors/index.html   — author leaderboard sorted by skin count desc
"""

import json
import os
import re
import sys
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

# Inline CSS — the full retrowave design system needed for standalone pages
INLINE_CSS = """
:root {
  --retro-pink:    #FA3399;
  --retro-purple:  #8000CC;
  --retro-blue:    #00CCF2;
  --retro-cyan:    #00F2F2;
  --retro-black:   #0D0D1A;
  --retro-dark:    #0D0D33;
  --bg:            #0B0B18;
  --surface:       #131320;
  --surface2:      #1a1a2e;
  --border:        rgba(250, 51, 153, 0.18);
  --border-subtle: rgba(255,255,255,0.06);
  --text:          #f0eeff;
  --text-muted:    #9090b0;
  --accent:        #FA3399;
  --accent-hover:  #ff55aa;
  --accent-dim:    rgba(250, 51, 153, 0.12);
  --accent-glow:   rgba(250, 51, 153, 0.35);
  --cyan:          #00CCF2;
  --cyan-dim:      rgba(0, 204, 242, 0.12);
  --success:       #00F2CC;
  --danger:        #ff4060;
  --warning:       #FAD633;
  --radius:        10px;
  --radius-sm:     6px;
  --shadow:        0 4px 24px rgba(0,0,0,0.6);
  --font:          -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
  --font-mono:     "SF Mono", "Fira Code", monospace;
  --gradient-neon: linear-gradient(135deg, #FA3399 0%, #8000CC 100%);
  --gradient-cyber: linear-gradient(135deg, #00CCF2 0%, #8000CC 100%);
  --gradient-sunset: linear-gradient(180deg, #FAD633 0%, #FA3399 50%, #8000CC 100%);
}
* { box-sizing: border-box; margin: 0; padding: 0; }
body {
  background: var(--bg);
  color: var(--text);
  font-family: var(--font);
  font-size: 15px;
  line-height: 1.6;
  min-height: 100vh;
}
a { color: var(--accent); text-decoration: none; }
a:hover { color: var(--accent-hover); text-decoration: underline; }
nav {
  background: rgba(11,11,24,0.92);
  backdrop-filter: blur(16px);
  border-bottom: 1px solid var(--border);
  position: sticky;
  top: 0;
  z-index: 100;
  padding: 0 24px;
}
.nav-inner {
  max-width: 1200px;
  margin: 0 auto;
  display: flex;
  align-items: center;
  gap: 24px;
  height: 56px;
}
.nav-logo {
  font-weight: 800;
  font-size: 17px;
  color: var(--text);
  display: flex;
  align-items: center;
  gap: 8px;
  letter-spacing: -0.3px;
}
.nav-logo span {
  background: var(--gradient-neon);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  background-clip: text;
}
.nav-links { display: flex; gap: 4px; margin-left: auto; }
.nav-links a {
  color: var(--text-muted);
  padding: 6px 12px;
  border-radius: var(--radius-sm);
  font-size: 14px;
  transition: color 0.15s, background 0.15s;
}
.nav-links a:hover, .nav-links a.active {
  color: var(--text);
  background: var(--surface2);
  text-decoration: none;
}
.nav-cta {
  background: var(--gradient-neon) !important;
  color: #fff !important;
  font-weight: 700;
  padding: 6px 16px !important;
  border-radius: var(--radius-sm);
  box-shadow: 0 0 16px var(--accent-glow);
}
.nav-cta:hover { filter: brightness(1.15); text-decoration: none !important; }
.hero {
  text-align: center;
  padding: 64px 24px 48px;
  position: relative;
  overflow: hidden;
  background:
    linear-gradient(rgba(250,51,153,0.03) 1px, transparent 1px),
    linear-gradient(90deg, rgba(250,51,153,0.03) 1px, transparent 1px),
    radial-gradient(ellipse at 50% 0%, rgba(128,0,204,0.18) 0%, transparent 65%),
    radial-gradient(ellipse at 50% 100%, rgba(0,204,242,0.1) 0%, transparent 60%),
    var(--bg);
  background-size: 40px 40px, 40px 40px, 100% 100%, 100% 100%, 100% 100%;
}
.hero::before {
  content: '';
  position: absolute;
  inset: 0;
  background: repeating-linear-gradient(
    0deg,
    transparent,
    transparent 2px,
    rgba(0,0,0,0.08) 2px,
    rgba(0,0,0,0.08) 4px
  );
  pointer-events: none;
}
.hero h1 {
  font-size: clamp(28px, 5vw, 52px);
  font-weight: 900;
  letter-spacing: -1px;
  margin-bottom: 12px;
  background: var(--gradient-neon);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  background-clip: text;
}
.hero p {
  color: var(--text-muted);
  font-size: 17px;
  max-width: 560px;
  margin: 0 auto 28px;
}
.hero-systems {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
  justify-content: center;
  margin-bottom: 20px;
}
.hero-actions { display: flex; gap: 12px; justify-content: center; flex-wrap: wrap; }
.btn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 10px 20px;
  border-radius: var(--radius-sm);
  font-size: 14px;
  font-weight: 700;
  cursor: pointer;
  border: none;
  transition: all 0.15s;
  text-decoration: none !important;
}
.btn-primary {
  background: var(--gradient-neon);
  color: #fff;
  box-shadow: 0 0 20px var(--accent-glow);
}
.btn-primary:hover { filter: brightness(1.15); box-shadow: 0 0 28px var(--accent-glow); color: #fff; }
.btn-outline {
  background: transparent;
  color: var(--cyan);
  border: 1px solid var(--cyan);
}
.btn-outline:hover { background: var(--cyan-dim); border-color: var(--cyan); color: var(--cyan); }
.btn-sm { padding: 6px 12px; font-size: 13px; }
.btn-success { background: var(--success); color: #0D0D1A; font-weight: 800; }
.btn-success:hover { filter: brightness(1.1); color: #0D0D1A; }
.back-link {
  max-width: 1200px;
  margin: 20px auto 0;
  padding: 0 24px;
  display: block;
  font-size: 14px;
  color: var(--text-muted);
}
.back-link:hover { color: var(--accent); text-decoration: none; }
.grid-wrap { max-width: 1200px; margin: 20px auto; padding: 0 24px 48px; }
.skin-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(240px, 1fr));
  gap: 16px;
}
.skin-card {
  background: var(--surface);
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius);
  overflow: hidden;
  transition: transform 0.15s, border-color 0.15s, box-shadow 0.15s;
  display: flex;
  flex-direction: column;
}
.skin-card:hover {
  transform: translateY(-3px);
  border-color: var(--accent);
  box-shadow: 0 8px 32px var(--accent-glow), 0 0 0 1px var(--accent);
}
.card-thumb {
  aspect-ratio: 16/10;
  background: var(--surface2);
  background-image:
    linear-gradient(rgba(250,51,153,0.04) 1px, transparent 1px),
    linear-gradient(90deg, rgba(250,51,153,0.04) 1px, transparent 1px);
  background-size: 20px 20px;
  display: flex;
  align-items: center;
  justify-content: center;
  overflow: hidden;
  position: relative;
}
.card-thumb img { width: 100%; height: 100%; object-fit: cover; }
.card-thumb .no-thumb { font-size: 40px; opacity: 0.15; }
.card-body { padding: 12px; flex: 1; display: flex; flex-direction: column; gap: 6px; }
.card-name { font-weight: 700; font-size: 14px; line-height: 1.3; }
.card-author { font-size: 12px; color: var(--text-muted); }
.card-tags { display: flex; gap: 4px; flex-wrap: wrap; margin-top: 2px; }
.tag {
  font-size: 11px;
  padding: 2px 7px;
  border-radius: 4px;
  background: var(--surface2);
  color: var(--text-muted);
  border: 1px solid var(--border-subtle);
}
.system-badge {
  font-size: 11px;
  font-weight: 800;
  padding: 2px 7px;
  border-radius: 4px;
  background: var(--accent-dim);
  color: var(--accent);
  text-transform: uppercase;
  letter-spacing: 0.3px;
  border: 1px solid rgba(250,51,153,0.25);
}
.card-footer { padding: 0 12px 12px; }
.card-footer .btn { width: 100%; justify-content: center; }
.loading {
  text-align: center;
  padding: 64px;
  color: var(--text-muted);
  grid-column: 1 / -1;
}
.spinner {
  width: 36px; height: 36px;
  border: 3px solid var(--border-subtle);
  border-top-color: var(--accent);
  border-radius: 50%;
  animation: spin 0.7s linear infinite;
  margin: 0 auto 16px;
  box-shadow: 0 0 12px var(--accent-glow);
}
@keyframes spin { to { transform: rotate(360deg); } }
.empty-state {
  text-align: center;
  padding: 64px 24px;
  color: var(--text-muted);
  grid-column: 1 / -1;
}
.empty-state .icon { font-size: 48px; margin-bottom: 12px; }
.empty-state h3 { color: var(--text); margin-bottom: 8px; }
footer {
  border-top: 1px solid var(--border-subtle);
  padding: 32px 24px;
  text-align: center;
  color: var(--text-muted);
  font-size: 13px;
}
footer a { color: var(--text-muted); }
footer a:hover { color: var(--accent); }
::-webkit-scrollbar { width: 6px; }
::-webkit-scrollbar-track { background: var(--bg); }
::-webkit-scrollbar-thumb { background: var(--border); border-radius: 3px; }
::-webkit-scrollbar-thumb:hover { background: var(--accent); }
@media (max-width: 600px) {
  .stats-bar { gap: 24px; }
  .nav-logo { font-size: 15px; }
}
/* Author index grid */
.authors-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(260px, 1fr));
  gap: 16px;
}
.author-card {
  background: var(--surface);
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius);
  padding: 20px;
  transition: transform 0.15s, border-color 0.15s, box-shadow 0.15s;
  text-decoration: none !important;
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.author-card:hover {
  transform: translateY(-3px);
  border-color: var(--accent);
  box-shadow: 0 8px 32px var(--accent-glow), 0 0 0 1px var(--accent);
}
.author-card-name {
  font-weight: 800;
  font-size: 17px;
  color: var(--text);
  background: var(--gradient-neon);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  background-clip: text;
}
.author-card-count {
  font-size: 13px;
  color: var(--text-muted);
}
.author-card-count span {
  background: var(--gradient-neon);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  background-clip: text;
  font-weight: 800;
}
.author-card-systems {
  display: flex;
  gap: 4px;
  flex-wrap: wrap;
}
"""


def slugify(name):
    """Convert author name to URL-safe slug (max 50 chars)."""
    slug = name.lower()
    slug = re.sub(r"[^a-z0-9]+", "-", slug)
    slug = slug.strip("-")
    return slug[:50]


def system_label(code):
    return SYSTEM_LABELS.get(code, code)


def build_nav(active=""):
    active_browse = ' class="active"' if active == "browse" else ""
    active_systems = ' class="active"' if active == "systems" else ""
    active_authors = ' class="active"' if active == "authors" else ""
    return f"""<nav>
  <div class="nav-inner">
    <div class="nav-logo">&#127918; <span>Provenance</span> Skins</div>
    <div class="nav-links">
      <a href="../index.html"{active_browse}>Browse</a>
      <a href="../systems/index.html"{active_systems}>Systems</a>
      <a href="index.html"{active_authors}>Authors</a>
      <a href="../submit.html">Submit</a>
      <a href="https://wiki.provenance-emu.com/info/skins-guide" target="_blank">Docs</a>
      <a href="https://github.com/Provenance-Emu/skins" target="_blank" class="nav-cta">GitHub</a>
    </div>
  </div>
</nav>"""


def build_footer():
    return """<footer>
  <p>
    <a href="https://provenance-emu.com" target="_blank">Provenance Emulator</a> ·
    <a href="../submit.html">Submit a Skin</a> ·
    <a href="https://github.com/Provenance-Emu/skins" target="_blank">GitHub</a> ·
    <a href="https://discord.gg/provenance" target="_blank">Discord</a> ·
    <a href="https://wiki.provenance-emu.com" target="_blank">Wiki</a>
  </p>
  <p style="margin-top:8px;font-size:12px">Skins are community-created. Provenance is not affiliated with Delta or DeltaStyles.</p>
</footer>"""


def generate_author_page(author_name, skin_count, system_count, systems_list):
    """Generate a per-author landing page that loads catalog.json at runtime."""
    systems_badges = ""
    for sys_code in sorted(systems_list):
        label = system_label(sys_code)
        systems_badges += f'<span class="system-badge">{label}</span>\n      '

    page = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{author_name} Skins for Provenance</title>
  <meta name="description" content="Browse {skin_count} free skins by {author_name} for Provenance emulator on iPhone, iPad and Apple TV.">
  <meta property="og:title" content="{author_name} Skins for Provenance">
  <meta property="og:description" content="{skin_count} community-created skins by {author_name} for Provenance emulator on iPhone, iPad and Apple TV.">
  <meta property="og:image" content="https://provenance-emu.com/img/sharing-default.png">
  <meta name="twitter:card" content="summary_large_image">
  <link rel="icon" href="data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'><text y='.9em' font-size='90'>&#127918;</text></svg>">
  <style>{INLINE_CSS}</style>
</head>
<body>

{build_nav(active="authors")}

<div class="hero">
  <h1>{author_name}&#39;s Skins for Provenance</h1>
  <p id="hero-sub">{skin_count} skin{"s" if skin_count != 1 else ""} across {system_count} system{"s" if system_count != 1 else ""}</p>
  <div class="hero-systems" id="hero-systems">
    {systems_badges}
  </div>
  <div class="hero-actions">
    <a href="../submit.html" class="btn btn-primary">&#10133; Submit Your Skin</a>
    <a href="index.html" class="btn btn-outline">&#8592; All Authors</a>
  </div>
</div>

<a href="index.html" class="back-link">&#8592; All Authors</a>

<div class="grid-wrap">
  <div class="skin-grid" id="skin-grid">
    <div class="loading">
      <div class="spinner"></div>
      Loading skins&hellip;
    </div>
  </div>
</div>

{build_footer()}

<script>
(function() {{
  var AUTHOR_NAME = {json.dumps(author_name)};

  function escHtml(str) {{
    if (!str) return '';
    return String(str)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }}

  function buildCard(skin) {{
    var thumb = skin.thumbnailURL
      ? '<img src="' + escHtml(skin.thumbnailURL) + '" alt="' + escHtml(skin.name) + '" loading="lazy" onerror="this.parentNode.innerHTML=\'<span class=no-thumb>&#127918;</span>\'">'
      : '<span class="no-thumb">&#127918;</span>';

    var tags = (skin.tags || []).slice(0, 3).map(function(t) {{
      return '<span class="tag">' + escHtml(t) + '</span>';
    }}).join('');

    var systems = (skin.systems || []).map(function(s) {{
      return '<span class="system-badge">' + escHtml(s) + '</span>';
    }}).join('');

    return '<div class="skin-card">'
      + '<div class="card-thumb">' + thumb + '</div>'
      + '<div class="card-body">'
      +   '<div class="card-name">' + escHtml(skin.name) + '</div>'
      +   '<div class="card-author">by ' + escHtml(skin.author || 'Unknown') + '</div>'
      +   (systems || tags ? '<div class="card-tags">' + systems + tags + '</div>' : '')
      + '</div>'
      + '<div class="card-footer">'
      +   '<a href="' + escHtml(skin.downloadURL) + '" class="btn btn-success btn-sm" target="_blank" rel="noopener">&#8595; Download</a>'
      + '</div>'
      + '</div>';
  }}

  fetch('../catalog.json')
    .then(function(r) {{ return r.json(); }})
    .then(function(catalog) {{
      var skins = (catalog.skins || []).filter(function(s) {{
        return s.author === AUTHOR_NAME;
      }});

      // Update hero sub-headline with live count
      var systemSet = {{}};
      skins.forEach(function(s) {{
        (s.systems || []).forEach(function(sys) {{ systemSet[sys] = true; }});
      }});
      var sysCount = Object.keys(systemSet).length;
      document.getElementById('hero-sub').textContent =
        skins.length + ' skin' + (skins.length !== 1 ? 's' : '') +
        ' across ' + sysCount + ' system' + (sysCount !== 1 ? 's' : '');

      var grid = document.getElementById('skin-grid');
      if (skins.length === 0) {{
        grid.innerHTML = '<div class="empty-state">'
          + '<div class="icon">&#127918;</div>'
          + '<h3>No skins found</h3>'
          + '<p>No skins by ' + escHtml(AUTHOR_NAME) + ' found.</p>'
          + '</div>';
        return;
      }}

      grid.innerHTML = skins.map(buildCard).join('');
    }})
    .catch(function(err) {{
      document.getElementById('skin-grid').innerHTML =
        '<div class="empty-state"><div class="icon">&#9888;&#65039;</div><h3>Failed to load</h3><p>' + escHtml(String(err)) + '</p></div>';
    }});
}})();
</script>
</body>
</html>"""
    return page


def generate_authors_index(authors_data):
    """Generate the authors leaderboard index page."""
    # Build author card HTML (sorted by skin count desc — already sorted when passed in)
    cards_html = ""
    for item in authors_data:
        author = item["author"]
        slug = item["slug"]
        count = item["count"]
        systems = item["systems"]

        badges = ""
        for sys_code in sorted(systems):
            label = system_label(sys_code)
            badges += f'<span class="system-badge">{label}</span>\n        '

        cards_html += f"""  <a href="{slug}.html" class="author-card">
    <div class="author-card-name">{author}</div>
    <div class="author-card-count"><span>{count}</span> skin{"s" if count != 1 else ""}</div>
    <div class="author-card-systems">
      {badges}
    </div>
  </a>
"""

    total_skins = sum(item["count"] for item in authors_data)
    total_authors = len(authors_data)

    page = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Skin Contributors — Provenance Skins Catalog</title>
  <meta name="description" content="Browse Provenance emulator skin contributors. {total_authors} community artists have created {total_skins} total skins for iPhone, iPad and Apple TV.">
  <meta property="og:title" content="Skin Contributors — Provenance Skins">
  <meta property="og:description" content="{total_authors} contributors · {total_skins} community skins for Provenance emulator.">
  <meta property="og:image" content="https://provenance-emu.com/img/sharing-default.png">
  <meta name="twitter:card" content="summary_large_image">
  <link rel="icon" href="data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'><text y='.9em' font-size='90'>&#127918;</text></svg>">
  <style>{INLINE_CSS}</style>
</head>
<body>

{build_nav(active="authors")}

<div class="hero">
  <h1>Skin <span style="background:var(--gradient-cyber);-webkit-background-clip:text;-webkit-text-fill-color:transparent;background-clip:text;">Contributors</span></h1>
  <p>{total_authors} contributors &middot; {total_skins} community skins for Provenance emulator</p>
  <div class="hero-actions">
    <a href="../index.html" class="btn btn-outline">&#8592; Browse All Skins</a>
    <a href="../submit.html" class="btn btn-primary">&#10133; Submit a Skin</a>
  </div>
</div>

<div class="grid-wrap">
  <div class="authors-grid">
{cards_html}  </div>
</div>

{build_footer()}

</body>
</html>"""
    return page


def main():
    print(f"Reading catalog from {CATALOG_PATH}…")
    with open(CATALOG_PATH) as f:
        catalog = json.load(f)

    skins = catalog.get("skins", [])
    print(f"Total skins in catalog: {len(skins)}")

    # Build per-author data
    author_skins = {}  # author -> list of skins
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
        # Collect systems this author covers
        systems = set()
        for skin in sk_list:
            for sys_code in (skin.get("systems") or []):
                systems.add(sys_code)

        out_path = AUTHORS_DIR / f"{slug}.html"
        html = generate_author_page(author, count, len(systems), systems)
        out_path.write_text(html, encoding="utf-8")
        generated.append({
            "author": author,
            "slug": slug,
            "count": count,
            "systems": sorted(systems),
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
