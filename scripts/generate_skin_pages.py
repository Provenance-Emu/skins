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
import re
import sys
from html import escape
from pathlib import Path
from urllib.parse import urlsplit

SCRIPTS_DIR = Path(__file__).parent
sys.path.insert(0, str(SCRIPTS_DIR))

from PIL import Image  # noqa: E402

from family_cards import line_badge, listed, variant_label  # noqa: E402
from content_policy import is_mature, report_link_html, split_mature  # noqa: E402
import creator_pages  # noqa: E402
import thumbnail_shards  # noqa: E402
from generate_author_pages import build_nav, slugify as author_slug  # noqa: E402
from generate_system_pages import (  # noqa: E402
    DUAL_SCREEN_ISSUE, DUAL_SCREEN_SYSTEMS, FOOTER, INSTALL_JS, SYSTEM_LABELS, apps_phrase,
)
from share_meta import SITE_URL, breadcrumb_jsonld, head_meta, system_card  # noqa: E402

REPO_ROOT = SCRIPTS_DIR.parent
CATALOG_PATH = REPO_ROOT / "docs" / "catalog.json"
SKIN_DIR = REPO_ROOT / "docs" / "s"
THUMBS_DIR = REPO_ROOT / "thumbnails"

MIN_SYSTEM_SKINS = 3  # generate_system_pages.py threshold
MAX_DESCRIPTION = 200

PAGE_CSS = (
    ".skin-page-previews{display:grid;grid-template-columns:repeat(auto-fill,minmax(80px,1fr));gap:8px;margin-top:12px}"
    ".skin-page-previews a{border:2px solid transparent;border-radius:8px;padding:6px;background:var(--surface2);color:var(--text);text-decoration:none;text-align:center;font-size:12px;overflow-wrap:anywhere}"
    ".skin-page-previews img{width:100%;height:90px;object-fit:contain}"
    ".skin-page-previews a[aria-current=page]{border-color:var(--accent)}"
    ".skin-page-family{margin-top:20px}.skin-page-family summary{cursor:pointer;padding:8px 0}"

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
)  # the .mature-gate and [hidden] rules for mature skins live in style.css (content_policy.MATURE_CSS)

# In the apps' web views the converter page can't save a zip. The button would hand the skin to Provenance
# (provenance://skins/retroarch), but the app has no such route yet and iFly and iCube don't register the
# scheme, so for now the script removes the button there (as before SkinKit#82). Turn PROVENANCE_HANDOFF on
# with SkinKit#83. Same rule as retroArchButton() in docs/js/browse.js.
PROVENANCE_HANDOFF = False
_IN_APP = "/iPhone|iPad|iPod/.test(navigator.userAgent)&&!/Safari\\//.test(navigator.userAgent)"
_RA_IN_APP = (
    "    var id=(a.getAttribute('href').match(/[?&]skin=([^&]+)/)||[])[1];\n"
    "    if(!id)return;\n"
    "    a.href='provenance://skins/retroarch?skin='+id;\n"
    "    a.textContent='Send to RetroArch';\n"
) if PROVENANCE_HANDOFF else "    a.remove();\n"
RETROARCH_JS = (
    "<script>\n"
    "(function(){\n"
    f"  if(!({_IN_APP}))return;\n"
    "  document.querySelectorAll('.btn-retroarch').forEach(function(a){\n"
    + _RA_IN_APP +
    "  });\n"
    "})();\n"
    "</script>"
)


def own_thumbnail(url):
    """(url, (w, h)) for a thumbnail we host and have locally, else None."""
    if not thumbnail_shards.is_own_thumbnail_url(url):
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


MATURE_GATE_HTML = (
    '<section class="mature-gate" id="mature-gate" hidden>\n'
    '  <h1>Mature skin</h1>\n'
    '  <p>This skin is marked mature and may contain adult content. Hidden by default so families can browse EmuSkins safely.</p>\n'
    '  <div class="actions">\n'
    '    <button type="button" class="btn btn-primary" id="mature-gate-continue">Show this skin</button>\n'
    '    <a href="../index.html" class="btn btn-outline">Back to EmuSkins</a>\n'
    '  </div>\n'
    '</section>\n'
    '<noscript><section class="mature-gate"><h1>Mature skin</h1>'
    '<p>This skin is marked mature. Turn on JavaScript to view it.</p>'
    '<a href="../index.html" class="btn btn-outline">Back to EmuSkins</a></section></noscript>\n'
)


def generate_skin_page(skin, system_pages, author_pages, siblings=(), line=None):
    """`author_pages` is the set of creator slugs that have an author page. `line` is
    the catalog line this skin belongs to, if any: the page links to it."""
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
    mature = is_mature(skin)

    thumb = own_thumbnail(skin.get("thumbnailURL"))
    alt = f"{name}, a {system_name} controller skin" + (f" by {author}" if author else "")
    if mature:
        # Nothing about the skin in the head: search results and link previews show
        # the generic card. The page is noindex, and the name only appears after the gate.
        meta = head_meta(title="Mature skin | EmuSkins",
                         description="This skin is marked mature. Confirm on the page to view it.",
                         path=path, noindex=True)
        thumb = None
    elif thumb:
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
    # A mature skin's image waits in data-src until the gate is passed (docs/js/mature.js).
    img_src = "data-src" if mature else "src"
    thumb_html = (f'<img {img_src}="{escape(shown_thumb)}" alt="{escape(alt)}">' if shown_thumb
                  else '<span class="no-thumb">\U0001f3ae</span>')

    previews = list(dict.fromkeys(u for u in [shown_thumb, *(skin.get("screenshotURLs") or [])]
                                   if isinstance(u, str) and urlsplit(u).scheme in ("http", "https")
                                   and urlsplit(u).netloc))
    screenshots_html = ""
    if len(previews) > 1:
        images = "".join(
            f'<a href="{escape(url)}" target="_blank" rel="noopener"><img {img_src}="{escape(url)}" loading="lazy" alt="{escape(name)} — preview {i}"></a>'
            for i, url in enumerate(previews, 1))
        screenshots_html = f'<section class="skin-page-previews" aria-label="All previews">{images}</section>'
    siblings_html = ""
    siblings = [member for member in siblings if mature or not is_mature(member)]
    if len(siblings) > 1:
        links = "".join(
            f'<a href="{escape(member["id"])}.html"' + (' aria-current="page"' if member["id"] == skin_id else '') + '>'
            + (f'<img {img_src}="{escape(member["thumbnailURL"])}" alt="" loading="lazy">' if member.get("thumbnailURL") else '')
            + f'<span>{escape(variant_label(member))}</span></a>' for member in siblings)
        siblings_html = (f'<details class="skin-page-family"><summary>Browse {len(siblings)} variants</summary>'
                         f'<nav class="skin-page-previews" aria-label="Skin variants">{links}</nav></details>')

    # The credit stays the catalog's `author`; the link goes to the creator it resolves to.
    creator = skin.get("creator") or (author_slug(author) if author else "")
    if author and creator in author_pages:
        by = f'by <a href="../authors/{creator}.html">{escape(author)}</a>'
    else:
        by = f"by {escape(author)}" if author else ""

    chips = "".join(
        f'<a class="tag" href="../systems/{c}.html">{escape(system_label(c))}</a>' if c in system_pages
        else f'<span class="tag">{escape(system_label(c))}</span>'
        for c in codes
    ) + "".join(f'<span class="tag">{escape(t)}</span>' for t in (skin.get("tags") or [])[:8])

    line_html = ""
    if line and not mature:
        line_html = (f'<p class="hint skin-page-line">Part of <a href="../l/{escape(line["id"])}.html?skin={skin_id}">'
                     f'{escape(line.get("name") or "a set")}</a>: {escape(line_badge(line))}.</p>')

    url = skin.get("downloadURL") or ""
    desc_html = f'<p class="desc">{escape(description)}</p>' if skin.get("description") else ""
    dual = ""
    touch = any(c in DUAL_SCREEN_SYSTEMS for c in codes)
    if touch:
        dual = (f'<p class="hint">Dual-screen layouts aren\'t active in Provenance yet. '
                f'<a href="{DUAL_SCREEN_ISSUE}" target="_blank" rel="noopener">Track progress →</a></p>')
    retroarch_hint = ('<p class="hint">For RetroArch the converter maps the buttons; RetroArch takes '
                      'touch-screen input from the screen itself.</p>') if touch else ""
    return (
        "<!DOCTYPE html>\n"
        '<html lang="en">\n'
        "<head>\n"
        '  <meta charset="UTF-8">\n'
        '  <meta name="viewport" content="width=device-width, initial-scale=1.0">\n'
        + meta
        + ("" if mature else breadcrumb_jsonld(crumbs) + skin_jsonld(skin, SITE_URL + path, thumb[0] if thumb else None))
        + '  <meta name="apple-itunes-app" content="app-id=1596862805">\n'
        '  <link rel="icon" href="../logo.svg" type="image/svg+xml">\n'
        '  <link rel="apple-touch-icon" href="../apple-touch-icon.png">\n'
        '  <link rel="stylesheet" href="../style.css">\n'
        f"  <style>{PAGE_CSS}</style>\n"
        "</head>\n"
        "<body>\n\n"
        f"{build_nav(active='browse')}\n\n"
        + (MATURE_GATE_HTML if mature else "") +
        f'<main class="skin-page"{" data-mature hidden" if mature else ""}>\n'
        f'  <div><div class="skin-page-thumb">{thumb_html}</div>{screenshots_html}{siblings_html}</div>\n'
        "  <div>\n"
        f"    <h1>{escape(name)}</h1>\n"
        f'    <div class="by">{by}</div>\n'
        f'    <div class="chips">{chips}</div>\n'
        f"    {line_html}\n"
        f"    {desc_html}\n"
        '    <div class="actions">\n'
        f'      <a href="{escape(url)}" class="btn btn-primary btn-download" download>⬇ Download .{escape(file_ext(url))}</a>\n'
        f'      <a href="../index.html?skin={skin_id}" class="btn btn-outline">Open in catalog</a>\n'
        f'      <a href="../retroarch.html?skin={skin_id}" class="btn btn-outline btn-retroarch">Get for RetroArch</a>\n'
        f'      <a href="../edit.html?skin={skin_id}" class="btn btn-outline btn-edit">Edit a copy</a>\n'
        "    </div>\n"
        f'    <p class="hint">{report_link_html(skin, "report-page-link", "Report this skin")}</p>\n'
        f'    <p class="hint">{install_hint(file_ext(url))}</p>\n'
        f"    {dual}\n"
        f"    {retroarch_hint}\n"
        "  </div>\n"
        "</main>\n\n"
        + FOOTER + "\n"
        + INSTALL_JS + "\n"
        + RETROARCH_JS + "\n"
        + ('<script src="../js/mature.js" defer></script>\n' if mature else "")
        + "</body>\n</html>\n"
    )



REDIRECT_PATH = REPO_ROOT / "skin-redirects.json"


def migration_redirects(path):
    if not path.exists():
        return {}
    redirects = json.loads(path.read_text())
    if not isinstance(redirects, dict):
        raise ValueError("Skin redirects must be an object")
    for sid, target in redirects.items():
        if not re.fullmatch(r"[0-9a-f]{16}", sid) or not isinstance(target, str) or not re.fullmatch(
            r"(authors/[a-z0-9-]+|s/[0-9a-f]{16})\.html", target
        ):
            raise ValueError(f"Invalid skin redirect: {sid}")
    return redirects


def live_redirects(redirects, skin_ids, author_slugs):
    """Split the migration map into (live, dropped) by whether the destination
    still gets a page. An opt-out or takedown removes the skins a redirect points
    at, and with a creator's last skin their author page: those redirects are
    dropped, so the retired permalink is a plain 404 and not a hop to one."""
    live, dropped = {}, {}
    for sid, target in redirects.items():
        folder, _, name = target.partition("/")
        exists = Path(name).stem in (skin_ids if folder == "s" else author_slugs)
        (live if exists else dropped)[sid] = target
    return live, dropped


def migration_redirect_page(target):
    url = "../" + target
    canonical = SITE_URL.rstrip("/") + "/" + target
    return (
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        '<title>Skin listing moved · EmuSkins</title>'
        f'<link rel="canonical" href="{escape(canonical)}">'
        f'<meta http-equiv="refresh" content="0;url={escape(url)}">'
        '</head><body>'
        f'<p>This listing has moved. <a href="{escape(url)}">Continue to the updated skins</a>.</p>'
        '</body></html>\n'
    )

def main():
    with open(CATALOG_PATH, encoding="utf-8") as f:
        catalog = json.load(f)
    skins = [s for s in catalog.get("skins", []) if s.get("id")]
    lines_by_id = {line["id"]: line for line in catalog.get("lines") or [] if line.get("id")}

    # System and author pages list visible skins only, so only those count toward
    # whether a page exists to link to. Mature skins still get their own gated page.
    visible, _mature = split_mature(listed(skins))
    system_counts = {}
    for s in visible:
        for c in s.get("systems") or []:
            system_counts[c] = system_counts.get(c, 0) + 1
    system_pages = {c for c, n in system_counts.items() if n >= MIN_SYSTEM_SKINS}
    # Every creator with a listed skin has an author page (generate_author_pages.py).
    # Resolve `creator` on all skins, mature ones included: their pages link there too.
    creators = creator_pages.load_profiles()
    author_pages = creator_pages.page_slugs(visible, creators)
    creator_pages.group_by_creator(skins, creators)

    families = {}
    for member in listed(skins):
        if member.get("groupId"):
            families.setdefault(member["groupId"], []).append(member)
    for members in families.values():
        members.sort(key=lambda m: m.get("groupOrder", float("inf")))

    SKIN_DIR.mkdir(parents=True, exist_ok=True)
    keep, small = set(), 0
    for s in skins:
        out = SKIN_DIR / f"{s['id']}.html"
        html = generate_skin_page(s, system_pages, author_pages, families.get(s.get("groupId"), ()),
                                  line=lines_by_id.get(s.get("lineId")))
        if not out.exists() or out.read_text(encoding="utf-8") != html:
            out.write_text(html, encoding="utf-8")
        keep.add(out.name)
        small += own_thumbnail(s.get("thumbnailURL")) is not None

    active_ids = {skin["id"] for skin in skins}
    author_slugs = author_pages | set(creator_pages.redirect_slugs(creators, author_pages))
    redirects, dropped = live_redirects(migration_redirects(REDIRECT_PATH), active_ids, author_slugs)
    if dropped:
        print(f"  ! {len(dropped)} redirect(s) dropped: the destination is no longer listed")
    for sid, target in redirects.items():
        if sid in active_ids:
            continue
        out = SKIN_DIR / f"{sid}.html"
        out.write_text(migration_redirect_page(target), encoding="utf-8")
        keep.add(out.name)
    (SKIN_DIR.parent / "skin-redirects.json").write_text(
        json.dumps(redirects, sort_keys=True) + "\n", encoding="utf-8"
    )

    removed = [p for p in SKIN_DIR.glob("*.html") if p.name not in keep]
    for p in removed:
        p.unlink()
    print(f"Done. {len(keep)} skin pages ({small} with the skin's own thumbnail), {len(removed)} removed.")


if __name__ == "__main__":
    main()
