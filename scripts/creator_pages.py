#!/usr/bin/env python3
"""
creator_pages.py — which creators get an author page, and what the page knows
about them. Shared by the author-page, skin-page, sitemap and share-card
generators so they agree on every slug.

A page exists for every creator slug that has at least one listed (visible,
non-sample) skin. Skins are grouped by the `creator` slug the catalog build
resolves (see creator_directory.py); this module resolves it again in memory so
a catalog written before `creator` existed still renders.

Design: SkinKit docs/specs/2026-11-03-creator-profiles-design.md §4.
"""

import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import creator_directory
from creator_policy import author_slug

REPO_ROOT = Path(__file__).parent.parent
CREATORS_DIR = REPO_ROOT / "creators"

# Slugs that name a page the generator writes itself: a creator called "Index"
# would otherwise be overwritten by (or overwrite) authors/index.html.
RESERVED_SLUGS = frozenset({"index"})


def load_profiles(creators_dir=None) -> list[dict]:
    """The hand-edited creators/*.json that pass validation. A file that fails is
    skipped with a warning, so a bad profile never reaches a page; CI's
    `build_catalog.py --check-only` is what fails the build over it."""
    creators, errors = creator_directory.load_creators(str(creators_dir or CREATORS_DIR))
    for e in errors:
        print(f"  ! {e}")
    valid = []
    for c in creators:
        problems = creator_directory.validate_creators(valid + [c])
        if problems:
            for p in problems:
                print(f"  ! skipping creator profile: {p}")
            continue
        valid.append(c)
    return valid


def group_by_creator(skins: list[dict], creators: list[dict]) -> dict[str, list[dict]]:
    """Creator slug -> skins, in input order. Sets `creator` on each skin that
    resolves to one: a hand-set override first, then an alias, then the slug of
    the `author` string. Skins with no author and no override are left out."""
    creator_directory.assign_creators(skins, creators)
    groups: dict[str, list[dict]] = {}
    for s in skins:
        if s.get("creator") and s["creator"] not in RESERVED_SLUGS:
            groups.setdefault(s["creator"], []).append(s)
    return groups


def page_slugs(skins: list[dict], creators: list[dict]) -> set[str]:
    """Slugs that get an author page, from the listed, non-mature skins."""
    return set(group_by_creator(skins, creators))


def build_profiles(groups: dict[str, list[dict]], creators: list[dict],
                   updated: "str | None" = None) -> dict[str, dict]:
    """Slug -> public profile record (the shape of one `creators.json` entry) for
    every slug in `groups`. Claimed creators carry their bio, links and socials;
    everyone else, and a creator held with `hidden`, gets the minimal record. A
    held creator's record also has `held: True` (not part of the published
    directory) so the page does not invite a claim the bot would refuse."""
    entries = [s for skins in groups.values() for s in skins]
    directory = creator_directory.build_directory(entries, creators, updated or date.today().isoformat())
    held = {c["slug"] for c in creators if c.get("hidden")}
    return {r["slug"]: ({**r, "held": True} if r["slug"] in held else r)
            for r in directory["creators"] if r["slug"] in groups}


def count_by_creator(skins: list[dict], creators: list[dict]) -> dict[str, int]:
    """Creator slug -> number of skins (used for the hidden mature ones)."""
    return {slug: len(group) for slug, group in group_by_creator(skins, creators).items()}


def redirect_slugs(creators: list[dict], page_slugs_: "set[str] | dict") -> dict[str, str]:
    """Old author-page slug -> the creator's slug, for every alias whose own slug
    differs from the creator's, so bookmarked `authors/<alias>.html` links keep
    working. Never shadows a real page, and a slug claimed by two creators goes
    to the first (file order)."""
    out: dict[str, str] = {}
    for c in creators:
        slug = c["slug"]
        if slug not in page_slugs_:
            continue
        for alias in c.get("aliases") or []:
            old = author_slug(alias)
            if old and old != slug and old not in page_slugs_ and old not in RESERVED_SLUGS:
                out.setdefault(old, slug)
    return out


def last_added(skins: list[dict]) -> "str | None":
    """Most recent `addedAt` among `skins` (ISO dates compare as strings)."""
    dates = [s["addedAt"] for s in skins if isinstance(s.get("addedAt"), str) and s["addedAt"]]
    return max(dates) if dates else None
