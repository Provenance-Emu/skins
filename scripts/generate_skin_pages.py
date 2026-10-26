#!/usr/bin/env python3
"""
Generate a static page per skin, so a shared link shows that skin.

  docs/s/{id}.html — one per catalog skin

The catalog's own links (`index.html?skin=ID`) only open the skin with
JavaScript, and link-preview crawlers don't run it, so every shared skin used
to preview as the home page. These pages carry the skin's own title,
description and thumbnail. The thumbnail is square and small, so they use
twitter:card=summary (small square preview); a skin whose thumbnail isn't one
of ours (size unknown, third-party host) uses its system's large card instead.

Pages for skins no longer in the catalog are deleted.
"""

import json
import sys
from html import escape
from pathlib import Path

SCRIPTS_DIR = Path(__file__).parent
sys.path.insert(0, str(SCRIPTS_DIR))

from PIL import Image  # noqa: E402

from generate_author_pages import build_nav, slugify as author_slug  # noqa: E402
from generate_system_pages import (  # noqa: E402
    DUAL_SCREEN_ISSUE, DUAL_SCREEN_SYSTEMS, FOOTER, INSTALL_JS, SYSTEM_LABELS, apps_phrase,
)
from share_meta import SITE_URL, breadcrumb_jsonld, head_meta, system_card  # noqa: E402

REPO_ROOT = SCRIPTS_DIR.parent
CATALOG_PATH = REPO_ROOT / "docs" / "catalog.json"
SKIN_DIR = REPO_ROOT / "docs" / "s"
THUMBS_DIR = REPO_ROOT / "thumbnails"

# Thumbnails we host: the `thumbnails` release and the repo's thumbnails/ folder.
OWN_THUMB_PREFIXES = (
    "https://github.com/Provenance-Emu/skins/releases/download/thumbnails/",
    "https://raw.githubusercontent.com/Provenance-Emu/skins/main/thumbnails/",
)
MIN_SYSTEM_SKINS = 3  # generate_system_pages.py threshold
MIN_AUTHOR_SKINS = 2  # generate_author_pages.py threshold
MAX_DESCRIPTION = 200

PAGE_CSS = (
    ".skin-page{max-width:880px;margin:32px auto 48px;padding:0 24px;display:grid;"
    "grid-template-columns:minmax(0,320px) 1fr;gap:32px;align-items:start}"
    ".skin-page-thumb{background:var(--surface2);border:1px solid var(--border-subtle);"
    "border-radius:var(--radius);aspect-ratio:1;display:flex;align-items:center;justify-content:center;overflow:hidden}"
    ".skin-page-thumb img{width:100%;height:100%;object-fit:contain}"
    ".skin-page-thumb .no-thumb{font-size:64px;opacity:.15}"
    ".skin-page h1{font-size:28px;line-height:1.2;margin:0 0 6px}"
    ".skin-page .by{color:var(--text-muted);margin-bottom:14px}"
    ".skin-page .by a{color:var(--text-muted);text-decoration:underline dotted}"
    ".skin-page .chips{display:flex;gap:6px;flex-wrap:wrap;margin-bottom:14px}"
    ".skin-page .desc{color:var(--text-muted);margin-bottom:16px}"
    ".skin-page .actions{display:flex;gap:10px;flex-wrap:wrap;margin:18px 0 10px}"
    ".skin-page .hint{font-size:12px;color:var(--text-muted)}"
    "@media(max-width:640px){.skin-page{grid-template-columns:1fr}}"
)


def own_thumbnail(url):
    """(url, (w, h)) for a thumbnail we host and have locally, else None."""
    if not url or not url.startswith(OWN_THUMB_PREFIXES):
        return None
    local = THUMBS_DIR / url.rsplit("/", 1)[-1]
    if not local.exists():
        return None
    with Image.open(local) as im:
        return url, im.size


def system_label(code):
    return SYSTEM_LABELS.get(code, code)


def description_for(skin, system_name, apps):
    own = " ".join((skin.get("description") or "").split())
    if own:
        return own if len(own) <= MAX_DESCRIPTION else own[: MAX_DESCRIPTION - 1].rsplit(" ", 1)[0] + "…"
    author = skin.get("author") or "the community"
    return f"Free {system_name} controller skin by {author} for {apps}."


def file_ext(url):
    name = url.split("?", 1)[0].rsplit("/", 1)[-1].lower()
    return name.rsplit(".", 1)[-1] if "." in name else "deltaskin"


def install_hint(ext):
    """Which apps iOS can hand this file to. Delta reads .deltaskin only; iCube and
    iFly don't register the skin types and install from their in-app catalog."""
    apps = "Provenance or Manic EMU" if ext == "manicskin" else "Provenance, Delta or Manic EMU"
    return f"Installs in {apps}. iCube and iFly install skins from their in-app catalog."


def skin_jsonld(skin, page_url, image_url):
    data = {
        "@context": "https://schema.org",
        "@type": "SoftwareApplication",
        "name": skin.get("name") or "Unnamed",
        "url": page_url,
        "author": {"@type": "Person", "name": skin.get("author") or "Unknown"},
        "applicationCategory": "GameApplication",
        "operatingSystem": "iOS, iPadOS",
        "downloadUrl": skin.get("downloadURL") or "",
        "isAccessibleForFree": True,
    }
    if image_url:
        data["image"] = image_url
    body = json.dumps(data, ensure_ascii=False).replace("<", "\\u003c")
    return f'  <script type="application/ld+json">{body}</script>\n'


def generate_skin_page(skin, system_pages, author_pages):
    skin_id = skin["id"]
    name = skin.get("name") or "Unnamed skin"
    author = skin.get("author") or ""
    codes = skin.get("systems") or []
    primary = codes[0] if codes else ""
    system_name = system_label(primary) if primary else "Emulator"
    apps = apps_phrase(primary)
    path = f"s/{skin_id}.html"
    description = description_for(skin, system_name, apps)
    title = f"{name} — {system_name} Skin" + (f" by {author}" if author else "") + " | EmuSkins"

    thumb = own_thumbnail(skin.get("thumbnailURL"))
    alt = f"{name}, a {system_name} controller skin" + (f" by {author}" if author else "")
    if thumb:
        meta = head_meta(title=title, description=description, path=path, image_alt=alt,
                         external_image=thumb, card="summary")
    else:
        meta = head_meta(title=title, description=description, path=path,
                         image=system_card(primary),
                         image_alt=f"EmuSkins card: {system_name} Skins, with previews of popular {system_name} skins")

    crumbs = [("EmuSkins", "")]
    if primary in system_pages:
        crumbs.append((system_name, f"systems/{primary}.html"))
    crumbs.append((name, path))

    shown_thumb = skin.get("thumbnailURL") or ""
    thumb_html = (f'<img src="{escape(shown_thumb)}" alt="{escape(alt)}">' if shown_thumb
                  else '<span class="no-thumb">\U0001f3ae</span>')

    if author and author in author_pages:
        by = f'by <a href="../authors/{author_slug(author)}.html">{escape(author)}</a>'
    else:
        by = f"by {escape(author)}" if author else ""

    chips = "".join(
        f'<a class="tag" href="../systems/{c}.html">{escape(system_label(c))}</a>' if c in system_pages
        else f'<span class="tag">{escape(system_label(c))}</span>'
        for c in codes
    ) + "".join(f'<span class="tag">{escape(t)}</span>' for t in (skin.get("tags") or [])[:8])

    url = skin.get("downloadURL") or ""
    desc_html = f'<p class="desc">{escape(description)}</p>' if skin.get("description") else ""
    dual = ""
    if any(c in DUAL_SCREEN_SYSTEMS for c in codes):
        dual = (f'<p class="hint">Dual-screen layouts aren\'t active in Provenance yet. '
                f'<a href="{DUAL_SCREEN_ISSUE}" target="_blank" rel="noopener">Track progress →</a></p>')

    return (
        "<!DOCTYPE html>\n"
        '<html lang="en">\n'
        "<head>\n"
        '  <meta charset="UTF-8">\n'
        '  <meta name="viewport" content="width=device-width, initial-scale=1.0">\n'
        + meta
        + breadcrumb_jsonld(crumbs)
        + skin_jsonld(skin, SITE_URL + path, thumb[0] if thumb else None)
        + '  <meta name="apple-itunes-app" content="app-id=1596862805">\n'
        '  <link rel="icon" href="../logo.svg" type="image/svg+xml">\n'
        '  <link rel="apple-touch-icon" href="../apple-touch-icon.png">\n'
        '  <link rel="stylesheet" href="../style.css">\n'
        f"  <style>{PAGE_CSS}</style>\n"
        "</head>\n"
        "<body>\n\n"
        f"{build_nav(active='browse')}\n\n"
        '<main class="skin-page">\n'
        f'  <div class="skin-page-thumb">{thumb_html}</div>\n'
        "  <div>\n"
        f"    <h1>{escape(name)}</h1>\n"
        f'    <div class="by">{by}</div>\n'
        f'    <div class="chips">{chips}</div>\n'
        f"    {desc_html}\n"
        '    <div class="actions">\n'
        f'      <a href="{escape(url)}" class="btn btn-primary btn-download" download>⬇ Download .{escape(file_ext(url))}</a>\n'
        f'      <a href="../index.html?skin={skin_id}" class="btn btn-outline">Open in catalog</a>\n'
        "    </div>\n"
        f'    <p class="hint">{install_hint(file_ext(url))}</p>\n'
        f"    {dual}\n"
        "  </div>\n"
        "</main>\n\n"
        + FOOTER + "\n"
        + INSTALL_JS + "\n"
        "</body>\n</html>\n"
    )


def main():
    with open(CATALOG_PATH, encoding="utf-8") as f:
        skins = [s for s in json.load(f).get("skins", []) if s.get("id")]

    system_counts, author_counts = {}, {}
    for s in skins:
        for c in s.get("systems") or []:
            system_counts[c] = system_counts.get(c, 0) + 1
        if s.get("author"):
            author_counts[s["author"]] = author_counts.get(s["author"], 0) + 1
    system_pages = {c for c, n in system_counts.items() if n >= MIN_SYSTEM_SKINS}
    author_pages = {a for a, n in author_counts.items() if n >= MIN_AUTHOR_SKINS}

    SKIN_DIR.mkdir(parents=True, exist_ok=True)
    keep, small = set(), 0
    for s in skins:
        out = SKIN_DIR / f"{s['id']}.html"
        html = generate_skin_page(s, system_pages, author_pages)
        if not out.exists() or out.read_text(encoding="utf-8") != html:
            out.write_text(html, encoding="utf-8")
        keep.add(out.name)
        small += own_thumbnail(s.get("thumbnailURL")) is not None

    removed = [p for p in SKIN_DIR.glob("*.html") if p.name not in keep]
    for p in removed:
        p.unlink()
    print(f"Done. {len(keep)} skin pages ({small} with the skin's own thumbnail), {len(removed)} removed.")


if __name__ == "__main__":
    main()
