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
import sys
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
        f'<img src="{escape(url)}" alt="" width="1200" height="400" decoding="async" '
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
    """"Claim this page" on an unclaimed page; nothing on a claimed one."""
    if is_claimed(profile):
        return ""
    return (f'<a href="{escape(claim_url(profile))}" class="btn btn-outline" target="_blank" '
            'rel="noopener">&#9998; Claim this page</a>')


def report_link_html(profile: dict) -> str:
    """"Report this profile" under a claimed hero; an unclaimed page has no profile text to report."""
    if not is_claimed(profile):
        return ""
    return (f'<p class="hero-report"><a href="{escape(report_creator_url(profile))}" target="_blank" '
            'rel="noopener">Report this profile</a></p>\n')


# Hooks for the badges and stats work (SkinKit#68). They draw nothing yet.
def stats_html(profile, skins) -> str:
    return ""


def badges_html(profile, skins) -> str:
    return ""


def card_extras_html(item) -> str:
    return ""


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
