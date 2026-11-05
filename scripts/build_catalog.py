#!/usr/bin/env python3
"""
build_catalog.py — Scan skins/**/*.json and build docs/catalog.json.

Usage:
    python3 scripts/build_catalog.py
    python3 scripts/build_catalog.py --output docs/catalog.json
    python3 scripts/build_catalog.py --check-only   # validate only, no output

Also reads creators/*.json: every entry gets a `creator` slug, and the build
writes creators.json plus creators/<slug>.json next to the catalog
(docs/creators.json, docs/creators/). See scripts/creator_directory.py.
"""

import argparse
import json
import os
import sys
import urllib.request
import urllib.error
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import added_dates
import blocklist
from skin_schema import CATALOG_VERSION, validate_entry, validate_merged_refs
import creator_directory
from link_health import HEALTH_FILE, is_hidden, load_health
from variants_sidecar import VARIANTS_FILE, load_variants, merge_variants, validate_store


# Fields only the detail view or other tools read. `docs/catalog.min.json`
# (what the home page loads on first paint) leaves them out; browse.js fetches
# the full `catalog.json` when someone opens a skin. A denylist, so a new field
# the grid needs reaches the browse index without touching this script.
BROWSE_INDEX_DETAIL_FIELDS = frozenset({
    "description",
    "fileSize",
    "gameTypeIdentifier",
    "mergedHash",
    "originalURL",
    "rating",
    "screenshotURLs",
    "submittedAt",
    "submittedBy",
    "version",
})

# Keys written first, most compressible runs together; the rest follow sorted.
BROWSE_INDEX_KEY_ORDER = (
    "id", "name", "author", "systems", "source", "tags",
    "groupId", "groupOrder", "thumbnailURL", "downloadURL",
    "downloadCount", "lastUpdated", "addedAt", "deviceSupport",
)


GITHUB_THUMBNAILS_API = (
    "https://api.github.com/repos/Provenance-Emu/skins/releases/tags/thumbnails"
)


def fetch_release_download_counts() -> dict[str, int]:
    """
    Fetch asset download counts from the public GitHub Releases API.
    Returns a dict mapping skin_id -> download_count.
    On any error, returns {} so the build is not broken.
    """
    try:
        req = urllib.request.Request(
            GITHUB_THUMBNAILS_API,
            headers={"Accept": "application/vnd.github+json", "User-Agent": "build-catalog/1.0"},
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())
        counts = {}
        for asset in data.get("assets", []):
            name = asset.get("name", "")
            count = asset.get("download_count", 0)
            if name.endswith(".png"):
                skin_id = name[:-4]  # strip .png
                counts[skin_id] = count
        return counts
    except Exception as exc:
        print(f"Warning: could not fetch download counts: {exc}", file=sys.stderr)
        return {}


def load_all_skins(skins_dir: str) -> list[dict]:
    entries = []
    for root, dirs, files in os.walk(skins_dir):
        dirs.sort()
        for fname in sorted(files):
            if not fname.endswith(".json"):
                continue
            path = os.path.join(root, fname)
            try:
                with open(path) as f:
                    entry = json.load(f)
                entry["_source_file"] = path
                entries.append(entry)
            except json.JSONDecodeError as e:
                print(f"ERROR: Invalid JSON in {path}: {e}", file=sys.stderr)
    return entries


def build_catalog(entries: list[dict]) -> dict:
    # Strip internal metadata, sort by system then name
    clean = []
    for e in entries:
        c = {k: v for k, v in e.items() if not k.startswith("_")}
        clean.append(c)

    clean.sort(key=lambda e: (
        (e.get("systems") or ["z"])[0],
        (e.get("name") or "").lower(),
    ))

    return {
        "version": CATALOG_VERSION,
        "lastUpdated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "totalSkins": len(clean),
        "skins": clean,
    }


def browse_index_entry(skin: dict) -> dict:
    """One skin trimmed for the home-page grid: detail-only fields and empty values dropped."""
    slim = {
        k: v for k, v in skin.items()
        if k not in BROWSE_INDEX_DETAIL_FIELDS
        and not k.startswith("_")
        and v not in (None, "", [])
    }
    ordered = {k: slim.pop(k) for k in BROWSE_INDEX_KEY_ORDER if k in slim}
    ordered.update(sorted(slim.items()))
    return ordered


def build_browse_index(catalog: dict) -> dict:
    """Slim copy of `catalog` for first paint. `catalog.json` itself is unchanged
    (the apps read it); this file is only for the website."""
    return {
        "version": catalog.get("version"),
        "lastUpdated": catalog.get("lastUpdated"),
        "totalSkins": catalog.get("totalSkins"),
        "skins": [browse_index_entry(s) for s in catalog.get("skins", [])],
    }


def browse_index_path(catalog_path: str) -> str:
    """`docs/catalog.json` -> `docs/catalog.min.json`."""
    base, ext = os.path.splitext(catalog_path)
    return f"{base}.min{ext}"


def write_browse_index(catalog: dict, catalog_path: str) -> str:
    path = browse_index_path(catalog_path)
    with open(path, "w") as f:
        # Compact separators: this file is fetched on every first visit.
        json.dump(build_browse_index(catalog), f, separators=(",", ":"), ensure_ascii=False)
        f.write("\n")
    return path


def split_hidden(entries: list[dict], health: dict,
                 opted_out=None) -> tuple[list[dict], list[dict]]:
    """Separate entries whose downloads are known broken (see link_health.py),
    plus any that match the opt-out blocklist (safety net; `opted_out` overrides
    blocklist.json for tests)."""
    records = health.get("skins", {})
    shown, hidden = [], []
    for e in entries:
        if blocklist.is_blocked(e, opted_out) or is_hidden(records.get(e.get("id")), e.get("downloadURL")):
            hidden.append(e)
        else:
            shown.append(e)
    return shown, hidden


def check_for_issues(entries: list[dict]) -> int:
    """Validate all entries. Returns number of errors found."""
    seen_ids = set()
    seen_urls = set()
    seen_paths: dict[str, str] = {}
    total_errors = 0
    merged_problems = validate_merged_refs(entries)

    for entry in entries:
        path = entry.get("_source_file", "?")
        errors = validate_entry(entry, catalog_ids=seen_ids)
        errors.extend(merged_problems.get(entry.get("id"), []))

        dl = entry.get("downloadURL", "")
        if dl and dl in seen_urls:
            errors.append(f"Duplicate downloadURL: {dl}")
        elif dl:
            seen_urls.add(dl)

        if entry.get("id"):
            seen_ids.add(entry["id"])

        # Paths that differ only by case collide on macOS/Windows checkouts:
        # one file silently overwrites the other and shows as modified.
        folded = path.lower()
        if folded in seen_paths and seen_paths[folded] != path:
            errors.append(f"Path differs only by case from {seen_paths[folded]}")
        else:
            seen_paths[folded] = path

        if errors:
            print(f"INVALID: {path}")
            for e in errors:
                print(f"  - {e}")
            total_errors += len(errors)

    return total_errors


def check_creators(entries: list[dict], creators_dir: str) -> tuple[list[dict], int]:
    """Validate creators/ and how the catalog resolves onto it.
    Returns (creators, error count); errors and warnings are printed."""
    creators, errors = creator_directory.load_creators(creators_dir)
    errors += creator_directory.validate_creators(creators)
    # Resolution rules assume well-formed creator files.
    if not errors:
        more, warnings = creator_directory.check_resolution(entries, creators)
        errors += more
        for w in warnings:
            print(f"WARNING: {w}", file=sys.stderr)
    for e in errors:
        print(f"INVALID: {e}")
    return creators, len(errors)


def main():
    parser = argparse.ArgumentParser(description="Build skin catalog from JSON files")
    parser.add_argument("--skins-dir", default="skins", help="Directory containing skin JSON files")
    parser.add_argument("--output", default="docs/catalog.json", help="Output catalog path")
    parser.add_argument("--check-only", action="store_true", help="Validate only, no output")
    parser.add_argument("--pretty", action="store_true", default=True)
    parser.add_argument("--index-only", action="store_true",
                        help="Rewrite the browse index (catalog.min.json) from the existing "
                             "--output catalog; does not rescan skins/")
    parser.add_argument("--added-dates-file", default=added_dates.ADDED_DATES_FILE,
                        help="Generated cache of when each skin file was first committed (addedAt)")
    parser.add_argument("--creators-dir", default=creator_directory.CREATORS_DIR,
                        help="Hand-edited creator profiles (creators/<slug>.json)")
    parser.add_argument("--health-file", default=HEALTH_FILE,
                        help="link_health.py state; entries it marks broken are left out")
    parser.add_argument("--variants-file", default=VARIANTS_FILE,
                        help="Generated sidecar of single-file variants (never downloads anything)")
    args = parser.parse_args()

    if args.index_only:
        with open(args.output) as f:
            existing = json.load(f)
        path = write_browse_index(existing, args.output)
        print(f"Wrote {path} ({len(existing.get('skins', []))} skins)")
        return

    entries = load_all_skins(args.skins_dir)
    print(f"Loaded {len(entries)} skin entries from {args.skins_dir}/")

    error_count = check_for_issues(entries)
    creators, creator_errors = check_creators(entries, args.creators_dir)
    error_count += creator_errors
    variants = load_variants(args.variants_file)
    for problem in validate_store(variants):
        print(f"INVALID: {args.variants_file}: {problem}", file=sys.stderr)
        error_count += 1
    if error_count:
        print(f"\n{error_count} validation error(s) found.", file=sys.stderr)
        if args.check_only:
            sys.exit(1)

    if args.check_only:
        print("All entries valid.")
        sys.exit(0)

    # addedAt needs complete git history; see added_dates.py. Hidden entries too,
    # so their dates are cached before they come back.
    dated = added_dates.apply_added_dates(entries, args.skins_dir, args.added_dates_file)
    print(f"addedAt: {dated['dated']} entries dated ({dated['looked_up']} looked up in git, "
          f"{dated['dated'] - dated['looked_up']} from {args.added_dates_file} or the skin file), "
          f"{dated['missing']} without.")
    if dated["unavailable"]:
        print("Warning: git history is shallow or unavailable; entries not in "
              f"{args.added_dates_file} have no addedAt (use fetch-depth: 0).", file=sys.stderr)

    # Fetch download counts from GitHub Releases API and merge into entries
    download_counts = fetch_release_download_counts()
    if download_counts:
        print(f"Fetched download counts for {len(download_counts)} thumbnails from GitHub.")
        for entry in entries:
            skin_id = entry.get("id", "")
            if skin_id in download_counts:
                entry["downloadCount"] = download_counts[skin_id]

    entries, hidden = split_hidden(entries, load_health(args.health_file))
    if hidden:
        print(f"Hiding {len(hidden)} skin(s) with broken downloads (see {args.health_file}).")

    with_variants = merge_variants(entries, variants)
    print(f"Merged variants into {with_variants} skin(s) (records for a different URL are ignored).")

    if creator_errors:
        # A broken claim must not take the build down or half-apply: publish
        # without creator profiles until it is fixed (CI's --check-only fails first).
        print("Ignoring creators/ because of the errors above.", file=sys.stderr)
        creators = []
    creator_directory.assign_creators(entries, creators)
    catalog = build_catalog(entries)
    os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
    with open(args.output, "w") as f:
        json.dump(catalog, f, indent=2, ensure_ascii=False)
        f.write("\n")

    print(f"Wrote {args.output} ({catalog['totalSkins']} skins)")
    print(f"Wrote {write_browse_index(catalog, args.output)} (browse index)")

    directory = creator_directory.build_directory(
        entries, creators, datetime.now(timezone.utc).strftime("%Y-%m-%d"))
    out_dir = os.path.dirname(args.output) or "."
    creator_directory.write_directory(directory, out_dir)
    print(f"Wrote {os.path.join(out_dir, 'creators.json')} and {len(directory['creators'])} "
          f"profile files under {os.path.join(out_dir, 'creators')}/ "
          f"({len(creators)} claimed)")

    # Write GitHub Actions step summary
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_path:
        with open(summary_path, "a") as f:
            f.write(f"## Catalog Build\n\n")
            f.write(f"- **Total skins:** {catalog['totalSkins']}\n")
            f.write(f"- **Last updated:** {catalog['lastUpdated']}\n")
            if error_count:
                f.write(f"- **Validation errors:** {error_count}\n")
            if hidden:
                f.write(f"- **Hidden (broken download):** {len(hidden)}\n")
            f.write(f"- **Single-file skins with variants:** {with_variants}\n")
            f.write(f"- **Entries without addedAt:** {dated['missing']}\n")


if __name__ == "__main__":
    main()
