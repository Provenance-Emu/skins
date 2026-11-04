#!/usr/bin/env python3
"""
creator_policy.py — limits and content rules for `creators/<slug>.json`.

The schema lives in skin_schema.py (`validate_creator`); this module holds the
numbers and lists it enforces, so a maintainer can tighten a rule without
touching the schema, plus the slug function the build uses to name creators.
Design: SkinKit docs/specs/2026-11-03-creator-profiles-design.md §1 and §5.
"""

import ipaddress
import re
import sys
from pathlib import Path
from urllib.parse import urlsplit

sys.path.insert(0, str(Path(__file__).parent))

SLUG_MAX = 50
SLUG_RE = re.compile(r"^[a-z0-9-]{1,%d}$" % SLUG_MAX)

BIO_MAX = 500
DISPLAY_NAME_MAX = 100
MAX_LINKS = 6
LINK_LABEL_MAX = 30

# URL shorteners hide the destination, so a profile cannot link through one.
SHORTENER_HOSTS = frozenset({
    "bit.ly", "bitly.com", "tinyurl.com", "t.co", "goo.gl", "ow.ly", "is.gd",
    "v.gd", "buff.ly", "rebrand.ly", "rb.gy", "cutt.ly", "shorturl.at",
    "tiny.cc", "lnkd.in", "t.ly", "s.id", "shorte.st", "adf.ly", "bl.ink",
})

# IP-logging redirectors. Seed list: extend it in a PR when a report names a host.
MALICIOUS_HOSTS = frozenset({
    "grabify.link", "iplogger.org", "iplogger.com", "iplogger.ru", "2no.co",
    "yip.su", "blasze.com", "leancoding.co", "stopify.co",
})

DENIED_HOSTS = SHORTENER_HOSTS | MALICIOUS_HOSTS


def author_slug(name: str) -> str:
    """URL-safe slug for an `author` string (max 50 chars).

    Identical to `generate_author_pages.slugify`; tests pin the two together.
    """
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return slug[:SLUG_MAX]


def host_denied(host: str) -> bool:
    """True when `host` or any parent domain is on the deny list."""
    host = host.lower().rstrip(".")
    parts = host.split(".")
    return any(".".join(parts[i:]) in DENIED_HOSTS for i in range(len(parts)))


def url_problem(url, what: str = "url") -> "str | None":
    """Why `url` cannot appear on a profile, or None. https only, no credentials,
    no IP literals, no denied hosts."""
    if not isinstance(url, str) or not url.strip():
        return f"{what} must be a non-empty string"
    if url != url.strip() or any(ord(c) < 33 for c in url):
        return f"{what} must not contain whitespace or control characters"
    try:
        parts = urlsplit(url)
        host = parts.hostname
        parts.port  # raises ValueError on a bad port
    except ValueError:
        return f"{what} is not a valid URL: {url!r}"
    if parts.scheme != "https":
        return f"{what} must be https: {url!r}"
    if not host or "." not in host:
        return f"{what} needs a public host name: {url!r}"
    if parts.username or parts.password:
        return f"{what} must not embed credentials: {url!r}"
    try:
        ipaddress.ip_address(host)
        return f"{what} must use a host name, not an IP address: {url!r}"
    except ValueError:
        pass
    if host_denied(host):
        return f"{what} host is not allowed ({host})"
    return None


_URL_IN_TEXT = re.compile(r"(?i)\b(?:https?://|www\.)\S+")
_HTML_TAG = re.compile(r"</?[A-Za-z!]")


def bio_problem(bio) -> "str | None":
    """Hard failures for a bio: wrong type, too long, control characters, HTML."""
    if not isinstance(bio, str):
        return "bio must be a string or null"
    if len(bio) > BIO_MAX:
        return f"bio is {len(bio)} characters; the limit is {BIO_MAX}"
    if any(ord(c) < 32 and c not in "\n\t" for c in bio) or "\x7f" in bio:
        return "bio must not contain control characters"
    if _HTML_TAG.search(bio):
        return "bio is plain text; remove the HTML"
    return None


def review_reasons(profile: dict) -> list[str]:
    """Soft flags: the claim bot routes these to `needs-maintainer` instead of
    rejecting. Today a URL in the bio, or a mature keyword in bio or display name."""
    from content_policy import default_keywords  # lazy: content_policy imports skin_schema

    reasons = []
    bio = profile.get("bio") or ""
    if _URL_IN_TEXT.search(bio):
        reasons.append("bio contains a URL")
    keywords = default_keywords()
    for field in ("bio", "displayName"):
        hits = keywords.find(profile.get(field) or "")
        if hits:
            reasons.append(f"{field} matches mature keyword(s): {', '.join(sorted(set(hits)))}")
    return reasons
