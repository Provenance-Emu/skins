#!/usr/bin/env python3
"""
build_catalog.py — Scan skins/**/*.json and build docs/catalog.json.

Usage:
    python3 scripts/build_catalog.py
    python3 scripts/build_catalog.py --output docs/catalog.json
    python3 scripts/build_catalog.py --check-only   # validate only, no output
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
from skin_schema import CATALOG_VERSION, validate_entry


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


def check_for_issues(entries: list[dict]) -> int:
    """Validate all entries. Returns number of errors found."""
    seen_ids = set()
    seen_urls = set()
    total_errors = 0

    for entry in entries:
        path = entry.get("_source_file", "?")
        errors = validate_entry(entry, catalog_ids=seen_ids)

        dl = entry.get("downloadURL", "")
        if dl and dl in seen_urls:
            errors.append(f"Duplicate downloadURL: {dl}")
        elif dl:
            seen_urls.add(dl)

        if entry.get("id"):
            seen_ids.add(entry["id"])

        if errors:
            print(f"INVALID: {path}")
            for e in errors:
                print(f"  - {e}")
            total_errors += len(errors)

    return total_errors


def main():
    parser = argparse.ArgumentParser(description="Build skin catalog from JSON files")
    parser.add_argument("--skins-dir", default="skins", help="Directory containing skin JSON files")
    parser.add_argument("--output", default="docs/catalog.json", help="Output catalog path")
    parser.add_argument("--check-only", action="store_true", help="Validate only, no output")
    parser.add_argument("--pretty", action="store_true", default=True)
    args = parser.parse_args()

    entries = load_all_skins(args.skins_dir)
    print(f"Loaded {len(entries)} skin entries from {args.skins_dir}/")

    error_count = check_for_issues(entries)
    if error_count:
        print(f"\n{error_count} validation error(s) found.", file=sys.stderr)
        if args.check_only:
            sys.exit(1)

    if args.check_only:
        print("All entries valid.")
        sys.exit(0)

    # Fetch download counts from GitHub Releases API and merge into entries
    download_counts = fetch_release_download_counts()
    if download_counts:
        print(f"Fetched download counts for {len(download_counts)} thumbnails from GitHub.")
        for entry in entries:
            skin_id = entry.get("id", "")
            if skin_id in download_counts:
                entry["downloadCount"] = download_counts[skin_id]

    catalog = build_catalog(entries)
    os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
    with open(args.output, "w") as f:
        json.dump(catalog, f, indent=2, ensure_ascii=False)
        f.write("\n")

    print(f"Wrote {args.output} ({catalog['totalSkins']} skins)")

    # Write GitHub Actions step summary
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_path:
        with open(summary_path, "a") as f:
            f.write(f"## Catalog Build\n\n")
            f.write(f"- **Total skins:** {catalog['totalSkins']}\n")
            f.write(f"- **Last updated:** {catalog['lastUpdated']}\n")
            if error_count:
                f.write(f"- **Validation errors:** {error_count}\n")


if __name__ == "__main__":
    main()
