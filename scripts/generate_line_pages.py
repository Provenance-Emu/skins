#!/usr/bin/env python3
"""
Generate one page per skin line (design: specs/2026-11-23-skin-lines-design.md §7).

  docs/l/{line-id}.html

A line is one design in many configurations. Its page shows a picker per option
and resolves the selection to one file (docs/js/line-page.js, docs/js/lines.js),
reading the members from docs/lines/{line-id}.json, which build_catalog.py
writes. Without JavaScript the page still shows the line and a download of its
default file.

Usage:
    python3 scripts/generate_line_pages.py
"""

import json
import sys
from html import escape
from pathlib import Path

SCRIPTS_DIR = Path(__file__).parent
sys.path.insert(0, str(SCRIPTS_DIR))

import creator_pages  # noqa: E402
import family_cards  # noqa: E402
from content_policy import split_mature  # noqa: E402
from generate_author_pages import build_nav, slugify as author_slug  # noqa: E402
from generate_skin_pages import (  # noqa: E402
    PAGE_CSS, file_ext, install_hint, own_thumbnail, system_label,
)
from generate_system_pages import FOOTER, INSTALL_JS, apps_phrase  # noqa: E402
from share_meta import SITE_URL, breadcrumb_jsonld, head_meta, system_card  # noqa: E402

REPO_ROOT = SCRIPTS_DIR.parent
CATALOG_PATH = REPO_ROOT / "docs" / "catalog.json"
LINE_DIR = REPO_ROOT / "docs" / "l"

LINE_CSS = (
    ".line-count{color:var(--cyan);font-weight:700;margin:0 0 12px}"
    ".line-options{display:grid;gap:12px;margin:18px 0}"
    ".line-axis{border:0;padding:0;margin:0;min-width:0}"
    ".line-axis legend{font-size:12px;font-weight:700;color:var(--text-muted);padding:0;margin-bottom:6px}"
    ".line-axis .auto{font-weight:400;color:var(--cyan);margin-left:6px}"
    ".line-values{display:flex;flex-wrap:wrap;gap:6px}"
    ".line-value{border:1px solid var(--border-subtle);background:var(--surface2);color:var(--text);"
    "border-radius:999px;padding:6px 12px;font:inherit;font-size:13px;cursor:pointer}"
    ".line-value[aria-pressed=true]{border-color:var(--accent);box-shadow:0 0 0 1px var(--accent)}"
    ".line-value.is-unavailable{opacity:.45;border-style:dashed}"
    ".line-value.swatch{width:30px;height:30px;padding:0;border-radius:50%}"
    ".line-axis select{font:inherit;background:var(--surface2);color:var(--text);"
    "border:1px solid var(--border-subtle);border-radius:8px;padding:6px 10px;max-width:100%}"
    ".line-selected{font-weight:700;margin:14px 0 0}"
    ".line-selected-meta{font-size:12px;color:var(--text-muted);margin:2px 0 0}"
)


def line_description(line: dict, system_name: str, apps: str) -> str:
    own = " ".join((line.get("description") or "").split())
    if own:
        return own
    return (f"{family_cards.line_badge(line)} of one {system_name} controller skin for {apps}. "
            "Pick the options that fit your device and hand.")


def generate_line_page(line: dict, default_member: dict, author_pages=frozenset()) -> str:
    """`default_member` is the file the page offers before (or without) JavaScript."""
    line_id = line["id"]
    name = line.get("name") or "Unnamed"
    codes = line.get("systems") or default_member.get("systems") or []
    primary = codes[0] if codes else ""
    system_name = system_label(primary) if primary else "Emulator"
    author = default_member.get("author") or ""
    path = f"l/{line_id}.html"
    badge = family_cards.line_badge(line)
    description = line_description(line, system_name, apps_phrase(primary))
    title = f"{name} — {system_name} Skins" + (f" by {author}" if author else "") + " | EmuSkins"
    alt = f"{name}, {system_name} controller skins" + (f" by {author}" if author else "")

    thumb = own_thumbnail(default_member.get("thumbnailURL"))
    if thumb:
        meta = head_meta(title=title, description=description, path=path, image_alt=alt,
                         external_image=thumb, card="summary")
    else:
        meta = head_meta(title=title, description=description, path=path, image=system_card(primary),
                         image_alt=f"EmuSkins card: {system_name} Skins, with previews of popular {system_name} skins")

    creator = line.get("creator") or default_member.get("creator") or (author_slug(author) if author else "")
    if author and creator in author_pages:
        by = f'by <a href="../authors/{escape(creator)}.html">{escape(author)}</a>'
    else:
        by = f"by {escape(author)}" if author else ""

    shown = default_member.get("thumbnailURL") or ""
    thumb_html = (f'<img id="line-img" src="{escape(shown)}" alt="{escape(alt)}">' if shown
                  else '<span class="no-thumb">\U0001f3ae</span>')
    url = default_member.get("downloadURL") or ""
    ext = file_ext(url)
    chips = "".join(f'<span class="tag">{escape(system_label(c))}</span>' for c in codes)

    return (
        "<!DOCTYPE html>\n"
        '<html lang="en">\n'
        "<head>\n"
        '  <meta charset="UTF-8">\n'
        '  <meta name="viewport" content="width=device-width, initial-scale=1.0">\n'
        + meta
        + breadcrumb_jsonld([("EmuSkins", ""), (name, path)])
        + '  <meta name="apple-itunes-app" content="app-id=1596862805">\n'
        '  <link rel="icon" href="../logo.svg" type="image/svg+xml">\n'
        '  <link rel="apple-touch-icon" href="../apple-touch-icon.png">\n'
        '  <link rel="stylesheet" href="../style.css">\n'
        f"  <style>{PAGE_CSS}{LINE_CSS}</style>\n"
        "</head>\n"
        "<body>\n\n"
        f"{build_nav(active='browse')}\n\n"
        f'<main class="skin-page line-page" data-line-id="{escape(line_id)}" '
        f'data-default-skin="{escape(default_member.get("id") or "")}">\n'
        f'  <div><div class="skin-page-thumb" id="line-thumb">{thumb_html}</div>'
        '<section class="skin-page-previews" id="line-previews" aria-label="All previews"></section></div>\n'
        "  <div>\n"
        f"    <h1>{escape(name)}</h1>\n"
        f'    <div class="by">{by}</div>\n'
        f'    <p class="line-count">{escape(badge)}</p>\n'
        f'    <div class="chips">{chips}</div>\n'
        f'    <p class="desc">{escape(description)}</p>\n'
        '    <form class="line-options" id="line-options" aria-label="Options" hidden></form>\n'
        f'    <p class="line-selected" id="line-selected">{escape(default_member.get("name") or name)}</p>\n'
        '    <p class="line-selected-meta" id="line-selected-meta"></p>\n'
        '    <div class="actions">\n'
        f'      <a href="{escape(url)}" class="btn btn-primary btn-download" id="line-download" download>'
        f"⬇ Download .{escape(ext)}</a>\n"
        f'      <a href="../s/{escape(default_member.get("id") or "")}.html" class="btn btn-outline" '
        'id="line-skin-page">This skin\'s page</a>\n'
        '      <button type="button" class="btn btn-outline" id="line-download-all" data-download-all="[]" hidden>'
        "</button>\n"
        "    </div>\n"
        f'    <p class="hint">{install_hint(ext)}</p>\n'
        "  </div>\n"
        "</main>\n\n"
        + FOOTER + "\n"
        + INSTALL_JS + "\n"
        + family_cards.DOWNLOAD_ALL_JS + "\n"
        + '<script src="../js/lines.js"></script>\n'
        + '<script src="../js/line-page.js"></script>\n'
        + "</body>\n</html>\n"
    )


def default_member_of(line: dict, members: list[dict]) -> "dict | None":
    """The member that fits the line's default on every axis, else the first in line order."""
    ordered = sorted(members, key=lambda m: (m.get("groupOrder") is None, m.get("groupOrder") or 0, m.get("id") or ""))
    default = line.get("default") or {}
    for m in ordered:
        options = m.get("options") or {}
        if all(default.get(a) in (v if isinstance(v, list) else [v]) for a, v in options.items()):
            return m
    return ordered[0] if ordered else None


def write_pages(catalog: dict, out_dir: Path, author_pages=frozenset()) -> list[Path]:
    """Write a page per line into `out_dir` and remove pages of lines that are gone."""
    skins = [s for s in catalog.get("skins", []) if s.get("id")]
    lines = catalog.get("lines") or []
    written = []
    if lines:
        out_dir.mkdir(parents=True, exist_ok=True)
    for line in lines:
        members = [s for s in skins if s.get("lineId") == line.get("id")]
        default = default_member_of(line, members)
        if not default:
            continue
        out = out_dir / f"{line['id']}.html"
        html = generate_line_page(line, default, author_pages)
        if not out.exists() or out.read_text(encoding="utf-8") != html:
            out.write_text(html, encoding="utf-8")
        written.append(out)
    if out_dir.is_dir():
        keep = {p.name for p in written}
        for stale in out_dir.glob("*.html"):
            if stale.name not in keep:
                stale.unlink()
    return written


def main():
    with open(CATALOG_PATH, encoding="utf-8") as f:
        catalog = json.load(f)
    visible, _mature = split_mature(family_cards.listed([s for s in catalog.get("skins", []) if s.get("id")]))
    creators = creator_pages.load_profiles()
    author_pages = creator_pages.page_slugs(visible, creators)
    creator_pages.group_by_creator(catalog.get("skins", []), creators)
    written = write_pages(catalog, LINE_DIR, author_pages)
    print(f"Done. Generated {len(written)} line page(s) in {LINE_DIR}")


if __name__ == "__main__":
    main()
