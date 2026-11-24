"""
Family rendering shared by the system and author page generators.

A family is the set of catalog entries sharing a `groupId`, listed by each
entry's `variantLabel` (the full name when it has none). A single-file skin can
also carry `variants` ([{kind, key, label}], from the variants sidecar): the
file itself brings those variants, with one download.
"""

import json
from html import escape

ALT_LABEL = "Alternate layout"

# Click handler for every `[data-download-all]` button on a static page. Mirrors
# downloadAll() in docs/js/browse.js (which author pages load as well). Capture
# phase, so a click never reaches the card's open-the-modal handler.
DOWNLOAD_ALL_JS = (
    "<script>\n"
    "(function(){\n"
    "  var isIOS=/iPhone|iPad|iPod/.test(navigator.userAgent)&&!window.MSStream;\n"
    "  document.querySelectorAll('[data-download-all]').forEach(function(b){\n"
    "    if(isIOS){b.hidden=true;}\n"
    "  });\n"
    "  document.addEventListener('click',function(e){\n"
    "    var b=e.target.closest('[data-download-all]');\n"
    "    if(!b)return;\n"
    "    e.stopPropagation();\n"
    "    if(b.disabled)return;\n"
    "    var urls=JSON.parse(b.getAttribute('data-download-all'));\n"
    "    var label=b.textContent;\n"
    "    b.disabled=true;\n"
    "    var i=0;\n"
    "    (function next(){\n"
    "      if(i>=urls.length){\n"
    "        b.textContent='\\u2713 Started '+urls.length+' downloads';\n"
    "        setTimeout(function(){b.textContent=label;b.disabled=false;},3000);\n"
    "        return;\n"
    "      }\n"
    "      b.textContent='Downloading '+(i+1)+' of '+urls.length+'\\u2026';\n"
    "      var a=document.createElement('a');\n"
    "      a.href=urls[i++];a.download='';a.style.display='none';\n"
    "      document.body.appendChild(a);a.click();a.remove();\n"
    "      setTimeout(next,700);\n"
    "    })();\n"
    "  },true);\n"
    "})();\n"
    "</script>"
)

FAMILY_CSS = (
    ".variant-badge.variant-badge-includes{background:rgba(11,11,24,.82);color:var(--cyan)}"
    ".card-variants{margin-top:8px;font-size:12px;color:var(--text-muted)}"
    ".card-variants summary{cursor:pointer;font-weight:700}"
    ".card-variants ul{list-style:none;margin:6px 0 0;padding:0;display:flex;"
    "flex-direction:column;gap:4px}"
    ".card-variants a{color:var(--text);text-decoration:none}"
    ".card-variants a:hover{color:var(--accent)}"
    ".card-includes{margin-top:8px;font-size:12px;color:var(--text-muted)}"
    ".card-footer{flex-wrap:wrap;gap:6px}"
)


def line_badge(line):
    """'150 layouts · 22 colours' for a skin line (never the word "line")."""
    n = line.get("layoutCount") or 0
    text = f"{n} layout{'s' if n != 1 else ''}"
    colour = next((a for a in line.get("axes") or [] if a.get("role") == "colour"), None)
    c = len(colour.get("values") or []) if colour else 0
    return f"{text} \u00b7 {c} colour{'s' if c != 1 else ''}" if c else text


def line_ids(lines):
    return {line.get("id") for line in lines or [] if line.get("id")}


def in_line(skin, lines):
    """Whether `skin` is a member of one of `lines` (catalog line records)."""
    return bool(skin.get("lineId")) and skin.get("lineId") in line_ids(lines)


def split_lines(clusters, lines):
    """Replace every cluster of one line with a single `("line", line, members)` item
    where the line's first cluster stood. `clusters` is cluster_groups()'s
    `(primary, siblings)` list; other clusters pass through unchanged."""
    by_id = {line["id"]: line for line in lines or [] if line.get("id")}
    out, slots = [], {}
    for primary, siblings in clusters:
        line = by_id.get(primary.get("lineId"))
        if not line:
            out.append((primary, siblings))
            continue
        if line["id"] not in slots:
            slots[line["id"]] = len(out)
            out.append(("line", line, []))
        out[slots[line["id"]]][2].extend([primary, *siblings])
    return out


def is_line_item(item):
    return len(item) == 3 and item[0] == "line"


def line_default_member(line, members):
    """The member that fits the line's default on every axis, else the first listed."""
    default = line.get("default") or {}
    for m in members:
        options = m.get("options") or {}
        if options and all(default.get(a) in (v if isinstance(v, list) else [v]) for a, v in options.items()):
            return m
    return members[0] if members else {}


def line_card_html(line, members, href_prefix=""):
    """One card for a whole line: a link to its page, no variant list, no Download all."""
    shown = line_default_member(line, members)
    name = escape(line.get("name") or "Unnamed")
    href = f'{href_prefix}l/{escape(line.get("id") or "")}.html'
    badge = escape(line_badge(line))
    thumb_url = shown.get("thumbnailURL") or ""
    thumb = (f'<img src="{escape(thumb_url)}" alt="{name}" loading="lazy" '
             "onerror=\"this.style.display='none'\">" if thumb_url
             else '<span class="no-thumb">\U0001f3ae</span>')
    author = escape(shown.get("author") or "")
    return (
        f'<article class="skin-card line-card" data-line-id="{escape(line.get("id") or "")}">\n'
        f'  <a class="card-thumb" href="{href}" tabindex="-1" aria-hidden="true">{thumb}'
        f'<span class="variant-badge variant-badge-includes">{badge}</span></a>\n'
        '  <div class="card-body">\n'
        f'    <div class="card-name"><a href="{href}">{name}</a></div>\n'
        + (f'    <div class="card-author">{author}</div>\n' if author else "")
        + "  </div>\n"
        '  <div class="card-footer">\n'
        f'    <a href="{href}" class="btn btn-success btn-sm">Choose options</a>\n'
        "  </div>\n"
        "</article>"
    )


LINE_CARD_CSS = (
    ".line-card .card-name a{color:inherit;text-decoration:none}"
    ".line-card a.card-thumb{display:flex;color:inherit;text-decoration:none}"
)


def line_members_script(skins, lines):
    """`window.LINE_MEMBERS` (skin id -> line id) so a shared `?skin=` link for a line
    member can be sent to the line page without the page embedding every member."""
    table = {s["id"]: s["lineId"] for s in skins if s.get("id") and in_line(s, lines)}
    if not table:
        return ""
    data = json.dumps(table, separators=(",", ":")).replace("<", "\\u003c")
    return f"<script>\nwindow.LINE_MEMBERS={data};\n</script>\n"


def design_count(skins, lines):
    """Designs in `skins`: a line, a family outside any line, or a single skin."""
    seen = set()
    for s in skins:
        if in_line(s, lines):
            seen.add(("line", s["lineId"]))
        elif s.get("groupId"):
            seen.add(("group", s["groupId"]))
        else:
            seen.add(("skin", s.get("id")))
    return len(seen)


def is_sample(skin):
    """Sample skins keep their docs/s/ pages but stay out of listings."""
    return "sample" in (skin.get("tags") or [])


def listed(skins):
    return [s for s in skins if not is_sample(s)]


def variant_label(skin):
    """The variant's own name in its family; the full name when it has none."""
    return skin.get("variantLabel") or skin.get("name") or "Unnamed Skin"


def family_name(primary):
    """Card title for a family: the primary's name without its own label."""
    name = primary.get("name") or "Unnamed Skin"
    label = primary.get("variantLabel") or ""
    if label and len(name) > len(label) and name.lower().endswith(label.lower()):
        stripped = name[: -len(label)].rstrip(" -\u2014:")
        return stripped or name
    return name


def inner_variant_labels(skin):
    """Labels of the variants a single file brings with it (kind-aware)."""
    out = []
    for v in skin.get("variants") or []:
        if not isinstance(v, dict):
            continue
        label = ALT_LABEL if v.get("kind") == "alt" else v.get("label")
        if label:
            out.append(label)
    return out


def badge_html(skin, sibling_count):
    """Thumbnail badge: family size, or 'Includes N variants' for one file."""
    if sibling_count > 0:
        n = sibling_count + 1
        return (
            f'<span class="variant-badge" aria-label="{n} variants">'
            f"{n} variants</span>"
        )
    n = len(inner_variant_labels(skin))
    if n:
        return (
            f'<span class="variant-badge variant-badge-includes" '
            f'aria-label="Includes {n} variants">'
            f'Includes {n} variant{"s" if n != 1 else ""}</span>'
        )
    return ""


def body_html(skin, siblings):
    """Variant list under the card name: family members, or a file's own variants."""
    if siblings:
        members = [skin] + list(siblings)
        items = "".join(
            f'<li><a href="{escape(m.get("downloadURL") or "#")}" download '
            f'onclick="event.stopPropagation()">\u2b07 {escape(variant_label(m))}</a></li>'
            for m in members
        )
        return (
            f'    <details class="card-variants" onclick="event.stopPropagation()">'
            f"<summary>{len(members)} variants</summary><ul>{items}</ul></details>\n"
        )
    labels = inner_variant_labels(skin)
    if labels:
        return f'    <div class="card-includes">{escape(", ".join(labels))}</div>\n'
    return ""


def download_all_button(skin, siblings):
    """'Download all' for a family; empty for a single card."""
    if not siblings:
        return ""
    urls = [m.get("downloadURL") for m in [skin] + list(siblings) if m.get("downloadURL")]
    if len(urls) < 2:
        return ""
    data = escape(json.dumps(urls), quote=True)
    return (
        f'<button type="button" class="btn btn-outline btn-sm" '
        f'data-download-all="{data}">\u2b07 Download all ({len(urls)})</button>'
    )
