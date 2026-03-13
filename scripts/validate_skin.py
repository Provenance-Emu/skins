#!/usr/bin/env python3
"""
validate_skin.py — Validate one or more skin JSON files. Used by CI on PRs.

Usage:
    python3 scripts/validate_skin.py skins/gba/my-skin.json
    python3 scripts/validate_skin.py skins/gba/*.json --check-url
"""

import argparse
import json
import sys
import urllib.request
import urllib.error
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from skin_schema import validate_entry


def check_url_reachable(url: str) -> bool:
    try:
        req = urllib.request.Request(
            url, method="HEAD",
            headers={"User-Agent": "Provenance-SkinCatalog/1.0"}
        )
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status < 400
    except Exception:
        return False


def main():
    parser = argparse.ArgumentParser(description="Validate skin JSON file(s)")
    parser.add_argument("files", nargs="+", help="Skin JSON file paths to validate")
    parser.add_argument("--check-url", action="store_true",
                        help="Verify downloadURL is reachable (makes HTTP HEAD request)")
    args = parser.parse_args()

    total_errors = 0

    for filepath in args.files:
        path = Path(filepath)
        if not path.exists():
            print(f"ERROR: File not found: {filepath}")
            total_errors += 1
            continue

        try:
            with open(path) as f:
                entry = json.load(f)
        except json.JSONDecodeError as e:
            print(f"ERROR: {filepath}: Invalid JSON: {e}")
            total_errors += 1
            continue

        errors = validate_entry(entry)

        if args.check_url and "downloadURL" in entry and entry["downloadURL"]:
            url = entry["downloadURL"]
            print(f"  Checking URL: {url}")
            if not check_url_reachable(url):
                errors.append(f"downloadURL is not reachable: {url}")

        if errors:
            print(f"INVALID: {filepath}")
            for e in errors:
                print(f"  - {e}")
            total_errors += len(errors)
        else:
            print(f"OK: {filepath}")

    if total_errors:
        print(f"\n{total_errors} error(s) found.")
        sys.exit(1)
    else:
        print(f"\nAll {len(args.files)} file(s) valid.")


if __name__ == "__main__":
    main()
