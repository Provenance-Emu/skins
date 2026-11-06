#!/usr/bin/env python3
"""
creator_profile_html.py — the profile parts of an author page: banner, bio,
social chips, links, claim and report links, JSON-LD, and the redirect stub for
an old alias slug.

Every value comes from a validated creators/<slug>.json (skin_schema.
validate_creator) and is escaped here regardless. Socials are handles turned
into URLs through skin_schema.social_url, never raw links; free `links` are
re-checked with creator_policy.url_problem before they are drawn.

Design: SkinKit docs/specs/2026-11-03-creator-profiles-design.md §4 and §5.
"""

import json
import re
import sys
from datetime import date
from html import escape
from pathlib import Path
from urllib.parse import urlencode

sys.path.insert(0, str(Path(__file__).parent))
from content_policy import REPORT_ISSUE_URL  # noqa: E402
from creator_policy import url_problem  # noqa: E402
from share_meta import SITE_URL  # noqa: E402
from skin_schema import SOCIAL_KEYS, social_url  # noqa: E402

# Issue forms. claim-profile.yml comes with the claim bot (a separate issue; the
# design's follow-up 2); its field id for the author names must be `names`.
CLAIM_TEMPLATE = "claim-profile.yml"
REPORT_CREATOR_TEMPLATE = "report-creator.yml"
MAX_CLAIM_NAMES = 10  # keeps the prefilled URL well under GitHub's length limit

SOCIAL_LABELS = {
    "github": "GitHub",
    "discord": "Discord",
    "x": "X",
    "bluesky": "Bluesky",
    "mastodon": "Mastodon",
    "instagram": "Instagram",
    "youtube": "YouTube",
    "twitch": "Twitch",
    "tiktok": "TikTok",
    "kofi": "Ko-fi",
    "patreon": "Patreon",
    "buymeacoffee": "Buy Me a Coffee",
    "deltastyles": "DeltaStyles",
    "reddit": "Reddit",
}

# User-supplied destinations: no referrer, no search-engine endorsement.
LINK_REL = "nofollow noopener noreferrer ugc"


def is_claimed(profile) -> bool:
    return bool(profile and profile.get("claimed"))


def image_url(profile, field: str) -> "str | None":
    """The avatar (`avatarURL`) or banner (`bannerURL`) to draw. One place to
    switch to the mirrored copy once the claim bot publishes the `creators`
    release (design §1); until then it is the URL the creator supplied."""
    if not profile:
        return None
    url = profile.get(field)
    return url if isinstance(url, str) and not url_problem(url, field) else None


def claim_url(profile: dict) -> str:
    """Prefilled claim form: the name(s) this page is listed under."""
    names = [profile["displayName"]]
    names += [a for a in profile.get("aliases") or [] if a not in names]
    names = names[:MAX_CLAIM_NAMES]
    params = {
        "template": CLAIM_TEMPLATE,
        "title": f"Claim profile: {profile['displayName']}",
        "names": "\n".join(names),
    }
    return f"{REPORT_ISSUE_URL}?{urlencode(params)}"


def report_creator_url(profile: dict) -> str:
    """Prefilled report form for one profile."""
    params = {
        "template": REPORT_CREATOR_TEMPLATE,
        "title": f"Report profile: {profile['displayName']}",
        "profile_name": profile["displayName"],
        "profile_url": f"{SITE_URL}authors/{profile['slug']}.html",
    }
    return f"{REPORT_ISSUE_URL}?{urlencode(params)}"


def social_items(socials) -> list[tuple[str, str, str, "str | None"]]:
    """(key, label, handle, url) in the schema's key order, unknown keys dropped.
    `url` is None for a service with no profile URL (Discord): show the handle."""
    items = []
    for key in SOCIAL_KEYS:
        handle = (socials or {}).get(key)
        if isinstance(handle, str) and handle:
            items.append((key, SOCIAL_LABELS[key], handle, social_url(key, handle)))
    return items


def socials_html(socials) -> str:
    chips = []
    for key, label, handle, url in social_items(socials):
        inner = f'<strong>{escape(label)}</strong><span>{escape(handle)}</span>'
        if url:
            chips.append(
                f'<a class="social-chip" href="{escape(url)}" target="_blank" rel="{LINK_REL}" '
                f'title="{escape(label)}: {escape(handle)}">{inner}</a>'
            )
        else:
            chips.append(f'<span class="social-chip social-chip-text" title="{escape(label)} username">{inner}</span>')
    return f'<div class="creator-socials">{"".join(chips)}</div>' if chips else ""


def safe_links(links) -> list[dict]:
    return [l for l in links or []
            if isinstance(l, dict) and isinstance(l.get("label"), str) and l["label"].strip()
            and not url_problem(l.get("url"), "url")]


def links_html(links) -> str:
    items = "".join(
        f'<a class="creator-link" href="{escape(l["url"])}" target="_blank" rel="{LINK_REL}">'
        f'{escape(l["label"])}<span aria-hidden="true"> &#8599;</span></a>'
        for l in safe_links(links)
    )
    return f'<div class="creator-links">{items}</div>' if items else ""


def banner_html(profile) -> str:
    """Banner above the hero. Fixed 3:1 box (the build resizes banners to 1200x400)
    so the page does not shift when the image arrives."""
    url = image_url(profile, "bannerURL") if is_claimed(profile) else None
    if not url:
        return ""
    return (
        '<div class="creator-banner">'
        f'<img src="{escape(url)}" alt="" width="1200" height="400" decoding="async" fetchpriority="high" '
        'onerror="this.parentNode.hidden=true"></div>\n'
    )


def bio_html(profile) -> str:
    bio = (profile or {}).get("bio") if is_claimed(profile) else None
    return f'<p class="creator-bio">{escape(bio)}</p>\n' if bio else ""


def claimed_mark_html(profile) -> str:
    if not is_claimed(profile):
        return ""
    return (' <span class="claimed-check" title="Claimed: this profile was verified by its creator" '
            'aria-label="Claimed profile">&#10003;</span>')


def profile_extras_html(profile: dict) -> str:
    """Socials and links under the bio (claimed profiles only)."""
    if not is_claimed(profile):
        return ""
    return socials_html(profile.get("socials")) + links_html(profile.get("links"))


def claim_button_html(profile: dict) -> str:
    """"Claim this page" on an unclaimed page; nothing on a claimed one or on one
    held for moderation (`held`; its aliases are taken, so a new claim would be refused)."""
    if is_claimed(profile) or profile.get("held"):
        return ""
    return (f'<a href="{escape(claim_url(profile))}" class="btn btn-outline" target="_blank" '
            'rel="noopener">&#9998; Claim this page</a>')


def report_link_html(profile: dict) -> str:
    """"Report this profile" under a claimed hero; an unclaimed page has no profile text to report."""
    if not is_claimed(profile):
        return ""
    return (f'<p class="hero-report"><a href="{escape(report_creator_url(profile))}" target="_blank" '
            'rel="noopener">Report this profile</a></p>\n')


# ---------------------------------------------------------------------------
# Stats and badges (gamification design §2, §5). Both come from the build's
# compute_creator_stats.py via creator_pages.attach_computed; a profile without
# them draws nothing here.
# ---------------------------------------------------------------------------

BADGE_ICON_DIR = Path(__file__).parent.parent / "docs" / "badges"
GENERIC_ICON = "generic"
CARD_BADGE_MAX = 3
# On an index card the "First release" badge says nothing a card does not already
# say; it is shown only when it is all the creator has.
CARD_QUIET_BADGES = frozenset({"creator.first-release"})
_ICON_ID = re.compile(r"^[a-z0-9]+(?:[.-][a-z0-9]+)*$")
_ICON_CACHE: dict[str, str] = {}


def badge_icon_html(badge_id) -> str:
    """The inline SVG for a badge id (docs/badges/<id>.svg), or the generic medal
    when the id has no icon, so a badge the build knows and the site does not still
    draws. Inline, so it takes the pill's colour."""
    name = badge_id if isinstance(badge_id, str) and _ICON_ID.fullmatch(badge_id) \
        and (BADGE_ICON_DIR / f"{badge_id}.svg").is_file() else GENERIC_ICON
    if name not in _ICON_CACHE:
        try:
            svg = (BADGE_ICON_DIR / f"{name}.svg").read_text(encoding="utf-8").strip()
        except OSError:
            svg = ""
        _ICON_CACHE[name] = svg.replace("<svg ", '<svg class="badge-icon" aria-hidden="true" focusable="false" ', 1) \
            if svg.startswith("<svg ") else ""
    return _ICON_CACHE[name]


def shown_badges(badges) -> list[dict]:
    """The badges to draw: only well-formed records, and one per tiered stem (the
    highest tier earned; `creator.systems.3/5/10` shows as the top one). Keeps the
    build's order."""
    clean = [b for b in badges or []
             if isinstance(b, dict) and isinstance(b.get("id"), str)
             and isinstance(b.get("title"), str) and b["title"].strip()]
    best: dict[str, int] = {}
    for b in clean:
        tier = b.get("tier")
        if isinstance(tier, int) and not isinstance(tier, bool):
            stem = b["id"].rsplit(".", 1)[0]
            best[stem] = max(best.get(stem, 0), tier)
    out = []
    for b in clean:
        tier = b.get("tier")
        if isinstance(tier, int) and not isinstance(tier, bool) \
                and tier < best[b["id"].rsplit(".", 1)[0]]:
            continue
        out.append(b)
    return out


def card_badges(badges) -> list[dict]:
    """Up to CARD_BADGE_MAX badges for an index card, in the build's order."""
    shown = shown_badges(badges)
    loud = [b for b in shown if b["id"] not in CARD_QUIET_BADGES]
    return (loud or shown)[:CARD_BADGE_MAX]


def _description(badge) -> str:
    d = badge.get("description")
    return d.strip() if isinstance(d, str) else ""


def _count(stats, key) -> "int | None":
    n = (stats or {}).get(key)
    return n if isinstance(n, int) and not isinstance(n, bool) and n >= 0 else None


def _month_year(value) -> "str | None":
    try:
        return date.fromisoformat(value).strftime("%b %Y")
    except (TypeError, ValueError):
        return None


def stats_html(profile, skins) -> str:
    """The hero's numbers: releases first (a family of variants is one), then the
    skins listed on this page, systems and how long the creator has been active.
    `skins` is what the page lists, so the second number matches the grid."""
    stats = (profile or {}).get("stats")
    if not isinstance(stats, dict):
        return ""
    tiles = []
    releases, systems = _count(stats, "releases"), _count(stats, "systems")
    if releases is not None:
        tiles.append((releases, "Release" if releases == 1 else "Releases",
                      "A family of variants counts once"))
    tiles.append((len(skins), "Skin" if len(skins) == 1 else "Skins", "Every skin file on this page"))
    if systems is not None:
        tiles.append((systems, "System" if systems == 1 else "Systems", "Different systems covered"))
    since = _month_year(stats.get("firstAddedAt"))
    if since:
        tiles.append((since, "Active since", "When the first skin was added to EmuSkins"))
    cells = "".join(
        f'<div class="creator-stat" title="{escape(hint)}"><strong>{escape(str(value))}</strong>'
        f'<span>{escape(label)}</span></div>'
        for value, label, hint in tiles)
    return f'<div class="creator-stats">{cells}</div>\n  '


def badges_html(profile, skins) -> str:
    """The badges row with hover descriptions, plus (on an unclaimed page that
    could be claimed) the one nudge: claiming unlocks the rest of the badges."""
    profile = profile or {}
    if not isinstance(profile.get("stats"), dict):
        return ""
    shown = shown_badges(profile.get("badges"))
    out = ""
    if shown:
        items = "".join(
            f'<li><button type="button" class="creator-badge" title="{escape(_description(b))}" '
            f'data-caption="{escape(b["title"] + (": " + _description(b) if _description(b) else ""))}">'
            f'{badge_icon_html(b["id"])}<span>{escape(b["title"])}</span></button></li>'
            for b in shown)
        out += (f'<ul class="creator-badges" aria-label="Badges">{items}</ul>\n  '
                '<p class="badge-caption" aria-live="polite"></p>\n  ')
    if not is_claimed(profile) and not profile.get("held"):
        out += (f'<p class="badges-nudge"><a href="{escape(claim_url(profile))}" target="_blank" '
                'rel="noopener">Claim your profile</a> to see all badges.</p>\n  ')
    return out


# Progressive enhancement for touch and keyboard: title text does not show there.
BADGE_JS = (
    "<script>\n"
    "(function(){\n"
    "  var cap=document.querySelector('.badge-caption');\n"
    "  if(!cap)return;\n"
    "  document.querySelectorAll('.creator-badge').forEach(function(b){\n"
    "    function show(){cap.textContent=b.getAttribute('data-caption')||'';}\n"
    "    b.addEventListener('click',show);\n"
    "    b.addEventListener('focus',show);\n"
    "    b.addEventListener('mouseenter',show);\n"
    "  });\n"
    "})();\n"
    "</script>"
)


def card_extras_html(item) -> str:
    """Index card extras: the release count and up to three badges. The card is a
    link, so these are plain spans (the description is the hover title)."""
    stats = (item or {}).get("stats")
    if not isinstance(stats, dict):
        return ""
    out = ""
    releases = _count(stats, "releases")
    if releases is not None:
        out += (f'    <div class="author-card-count"><span>{releases}</span> '
                f'release{"" if releases == 1 else "s"}</div>\n')
    chips = "".join(
        f'<span class="creator-badge creator-badge-sm" title="{escape(_description(b))}">'
        f'{badge_icon_html(b["id"])}<span>{escape(b["title"])}</span></span>'
        for b in card_badges(item.get("badges")))
    if chips:
        out += f'    <div class="author-card-badges">{chips}</div>\n'
    return out


def person_jsonld(profile: dict, page_url: str) -> dict:
    """schema.org ProfilePage for the creator. A claimed profile adds `image`,
    `description` and `sameAs` (social URLs and links); an unclaimed one is just the name."""
    person = {"@type": "Person", "name": profile["displayName"], "url": page_url}
    if is_claimed(profile):
        image = image_url(profile, "avatarURL")
        if image:
            person["image"] = image
        if profile.get("bio"):
            person["description"] = profile["bio"]
        same_as = [u for *_, u in social_items(profile.get("socials")) if u]
        same_as += [l["url"] for l in safe_links(profile.get("links"))]
        if same_as:
            person["sameAs"] = same_as
    return {"@context": "https://schema.org", "@type": "ProfilePage", "url": page_url, "mainEntity": person}


def jsonld_script(data: dict, indent: str = "  ") -> str:
    """A JSON-LD <script>; `<` is escaped so no value can close the tag."""
    body = json.dumps(data, ensure_ascii=False).replace("<", "\\u003c")
    return f'{indent}<script type="application/ld+json">{body}</script>\n'


def redirect_stub_html(slug: str) -> str:
    """A static page for an old alias slug that sends visitors to the creator's page."""
    target = f"{SITE_URL}authors/{slug}.html"
    return (
        "<!DOCTYPE html>\n"
        '<html lang="en">\n'
        "<head>\n"
        '  <meta charset="UTF-8">\n'
        '  <meta name="viewport" content="width=device-width, initial-scale=1.0">\n'
        "  <title>Moved | EmuSkins</title>\n"
        f'  <meta http-equiv="refresh" content="0; url={slug}.html">\n'
        f'  <link rel="canonical" href="{target}">\n'
        '  <meta name="robots" content="noindex">\n'
        "</head>\n"
        "<body>\n"
        f'<p>This page moved to <a href="{slug}.html">{escape(target)}</a>.</p>\n'
        "</body>\n"
        "</html>\n"
    )
