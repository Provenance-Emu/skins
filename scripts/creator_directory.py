#!/usr/bin/env python3
"""
creator_directory.py — load creators/*.json, resolve each catalog entry to a
creator slug, and build the published directory (docs/creators.json and
docs/creators/<slug>.json).

Resolution order for an entry (design §2 and §6):
  1. a hand-set `creator` on the skin's own JSON (uploader-vs-artist cases),
  2. the creator whose `aliases` contain the entry's exact `author`,
  3. `author_slug(author)`, so every credited author has a profile.
The override must win: the uploader's own `author` string is often itself a
claimed alias, and alias-first would hand the artist's skin to the uploader.
"""

import json
import os
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from creator_policy import author_slug
from skin_schema import validate_creator

CREATORS_DIR = "creators"
DIRECTORY_VERSION = 1

_GITHUB_SOURCE = re.compile(r"^([A-Za-z0-9_-]+)/[A-Za-z0-9_.-]+$")


def load_creators(creators_dir: str = CREATORS_DIR) -> tuple[list[dict], list[str]]:
    """Read every creators/*.json. Returns (creators, errors); each creator dict
    carries `_source_file`. A missing directory is not an error (no claims yet)."""
    creators, errors = [], []
    if not os.path.isdir(creators_dir):
        return creators, errors
    for fname in sorted(os.listdir(creators_dir)):
        if not fname.endswith(".json"):
            continue
        path = os.path.join(creators_dir, fname)
        try:
            with open(path, encoding="utf-8") as f:
                obj = json.load(f)
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            errors.append(f"{path}: invalid JSON: {e}")
            continue
        if isinstance(obj, dict):
            obj["_source_file"] = path
        creators.append(obj)
    return creators, errors


def _label(creator) -> str:
    return creator.get("_source_file", "?") if isinstance(creator, dict) else "?"


def validate_creators(creators: list[dict]) -> list[str]:
    """Per-file schema plus the cross-file rules: an alias belongs to one
    creator, and slugs must not collide even on a case-insensitive file system."""
    errors = []
    alias_owner: dict[str, str] = {}
    slug_owner: dict[str, str] = {}
    for c in creators:
        path = _label(c)
        stem = Path(path).stem if path != "?" else None
        public = {k: v for k, v in c.items() if not k.startswith("_")} if isinstance(c, dict) else c
        for e in validate_creator(public, filename_slug=stem):
            errors.append(f"{path}: {e}")
        if not isinstance(c, dict):
            continue

        slug = c.get("slug")
        if isinstance(slug, str) and slug:
            other = slug_owner.get(slug.lower())
            if other is not None and other != path:
                errors.append(f"{path}: slug {slug!r} collides with {other} (slugs are compared case-insensitively)")
            else:
                slug_owner[slug.lower()] = path

        if isinstance(c.get("aliases"), list):
            for alias in c["aliases"]:
                if not isinstance(alias, str):
                    continue
                other = alias_owner.get(alias)
                if other is not None and other != path:
                    errors.append(f"{path}: alias {alias!r} is already claimed by {other}")
                else:
                    alias_owner[alias] = path
    return errors


def alias_map(creators: list[dict]) -> dict[str, str]:
    """Exact `author` string -> creator slug. Assumes `validate_creators` passed."""
    mapping = {}
    for c in creators:
        for alias in c.get("aliases") or []:
            mapping.setdefault(alias, c["slug"])
    return mapping


def derived_slug(entry: dict, aliases: dict[str, str]) -> "str | None":
    """Creator slug from author alone (steps 2 and 3), ignoring any override."""
    author = entry.get("author")
    if not isinstance(author, str) or not author.strip():
        return None
    return aliases.get(author) or author_slug(author) or None


def resolve_creator(entry: dict, aliases: dict[str, str]) -> "str | None":
    """Creator slug for one entry, or None when there is no author to credit."""
    override = entry.get("creator")
    if isinstance(override, str) and override:
        return override
    return derived_slug(entry, aliases)


def assign_creators(entries: list[dict], creators: list[dict]) -> None:
    """Set `creator` on every entry that resolves to one (in place)."""
    aliases = alias_map(creators)
    for e in entries:
        slug = resolve_creator(e, aliases)
        if slug:
            e["creator"] = slug


def check_resolution(entries: list[dict], creators: list[dict]) -> tuple[list[str], list[str]]:
    """Build-time collision rules over the whole catalog. Returns (errors, warnings).

    Errors:
      - two different unclaimed `author` strings that slugify to the same slug
      - an unclaimed `author` whose slug equals a claimed creator's slug (merging
        it silently would be a guess; add it to the aliases, or give the entry a
        `creator` override)
    Warnings:
      - a claimed creator none of whose aliases appear in the catalog (stale claim)
      - a `creator` override naming a slug no creator file or author produces. It
        is allowed, because the artist an uploader's skin credits may have no
        other skins, but it creates a bare profile, so a typo deserves a look.
    """
    errors, warnings = [], []
    aliases = alias_map(creators)
    claimed = {c["slug"] for c in creators}

    unclaimed_authors: dict[str, set[str]] = defaultdict(set)
    seen_authors = set()
    for e in entries:
        author = e.get("author")
        if not isinstance(author, str) or not author.strip():
            continue
        seen_authors.add(author)
        if author not in aliases:
            slug = author_slug(author)
            if slug:
                unclaimed_authors[slug].add(author)

    for slug, authors in sorted(unclaimed_authors.items()):
        if len(authors) > 1:
            errors.append(
                f"authors {sorted(authors)} all become creator slug {slug!r}; "
                "claim them as aliases of one creator, or set `creator` on the entries that differ")
        if slug in claimed:
            errors.append(
                f"author(s) {sorted(authors)} become creator slug {slug!r}, which belongs to a claimed "
                "creator without being one of its aliases; add the alias or set `creator` on the entry")

    known = claimed | set(unclaimed_authors)
    for e in entries:
        override = e.get("creator")
        if isinstance(override, str) and override and override not in known:
            warnings.append(
                f"{e.get('_source_file', e.get('id', '?'))}: creator override {override!r} matches "
                "no creators/ file and no author; it will get a bare profile")

    for c in creators:
        if not any(a in seen_authors for a in c.get("aliases") or []):
            warnings.append(f"{_label(c)}: no catalog entry uses any alias of {c['slug']!r} (stale claim)")
    return errors, warnings


def _github_owner(skins: list[dict]) -> "str | None":
    """Repo owner from a GitHub-style `source` ("owner/repo"), else None.
    Same rule as generate_author_pages.github_username_from_skins."""
    for s in skins:
        m = _GITHUB_SOURCE.match(s.get("source") or "")
        if m:
            return m.group(1)
    return None


def _claimed_record(c: dict, skin_ids: list[str]) -> dict:
    """Public profile: the creator file without `claim`/`hidden`, plus skinIds."""
    return {
        "slug": c["slug"],
        "displayName": c["displayName"],
        "aliases": list(c["aliases"]),
        "claimed": True,
        "githubLogin": c["githubLogin"],
        "bio": c.get("bio"),
        "avatarURL": c.get("avatarURL"),
        "bannerURL": c.get("bannerURL"),
        "links": list(c.get("links") or []),
        "socials": dict(c.get("socials") or {}),
        "skinIds": skin_ids,
    }


def build_directory(entries: list[dict], creators: list[dict], updated: str) -> dict:
    """The `creators.json` document. `entries` are the catalog entries that will
    be published (hidden-download skins already removed) and must already carry
    `creator` (see `assign_creators`). Unclaimed authors appear as minimal
    records. A `hidden` creator publishes nothing of its own: it is emitted as a
    minimal record under the same slug and aliases, so its skins still resolve."""
    by_creator: dict[str, list[dict]] = defaultdict(list)
    for e in entries:
        if e.get("creator"):
            by_creator[e["creator"]].append(e)

    aliases = alias_map(creators)
    claimed = {c["slug"]: c for c in creators}
    records = {}

    for slug, c in claimed.items():
        skins = by_creator.get(slug, [])
        ids = sorted(s["id"] for s in skins if s.get("id"))
        if c.get("hidden"):
            records[slug] = {
                "slug": slug,
                "displayName": c["aliases"][0],
                "aliases": list(c["aliases"]),
                "claimed": False,
                "avatarURL": _unclaimed_avatar(skins),
                "skinIds": ids,
            }
        else:
            records[slug] = _claimed_record(c, ids)

    for slug, skins in by_creator.items():
        if slug in records:
            continue
        # Authors credited on these entries who are not aliases of a claimed creator.
        names = Counter(
            s["author"] for s in skins
            if isinstance(s.get("author"), str) and s["author"] not in aliases and author_slug(s["author"]) == slug
        )
        ordered = [n for n, _ in sorted(names.items(), key=lambda kv: (-kv[1], kv[0]))]
        records[slug] = {
            "slug": slug,
            "displayName": ordered[0] if ordered else slug,
            "aliases": sorted(names),
            "claimed": False,
            "avatarURL": _unclaimed_avatar(skins),
            "skinIds": sorted(s["id"] for s in skins if s.get("id")),
        }

    return {
        "version": DIRECTORY_VERSION,
        "updated": updated,
        "creators": [records[k] for k in sorted(records)],
    }


def _unclaimed_avatar(skins: list[dict]) -> "str | None":
    # Stand-in until the claim bot mirrors avatars to the `creators` release (design §1).
    owner = _github_owner(skins)
    return f"https://github.com/{owner}.png" if owner else None


def write_directory(directory: dict, out_dir: str) -> list[str]:
    """Write creators.json and creators/<slug>.json under `out_dir`
    (normally docs/). Per-creator files no longer in the directory are removed;
    this directory is generated and owned by the build. Returns paths written."""
    os.makedirs(out_dir, exist_ok=True)
    per_dir = os.path.join(out_dir, "creators")
    os.makedirs(per_dir, exist_ok=True)

    written = []
    path = os.path.join(out_dir, "creators.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(directory, f, separators=(",", ":"), ensure_ascii=False)
        f.write("\n")
    written.append(path)

    keep = set()
    for record in directory["creators"]:
        name = f"{record['slug']}.json"
        keep.add(name)
        path = os.path.join(per_dir, name)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(record, f, indent=2, ensure_ascii=False)
            f.write("\n")
        written.append(path)

    for name in os.listdir(per_dir):
        if name.endswith(".json") and name not in keep:
            os.remove(os.path.join(per_dir, name))
    return written
