#!/usr/bin/env python3
"""
crawl_sources.py — Crawl external skin repositories listed in sources.json
and generate new skin JSON files for any skins not already in the catalog.

Usage:
    python3 scripts/crawl_sources.py
    python3 scripts/crawl_sources.py --sources sources.json --existing-catalog docs/catalog.json
    python3 scripts/crawl_sources.py --dry-run
"""

import argparse
import json
import os
import sys
import time
import urllib.request
import urllib.error
import html.parser
from pathlib import Path
from datetime import datetime, timezone

sys.path.insert(0, str(Path(__file__).parent))
from extract_metadata import stream_extract_info_json
from skin_schema import make_id, slugify, normalize_entry, system_from_gti, system_from_name
from process_submission import process_github_repo, save_entries

GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")


# ---------------------------------------------------------------------------
# delta-skins.github.io scraper
# ---------------------------------------------------------------------------

DELTA_SKINS_PAGES = ["gba", "gbc", "nes", "snes", "n64", "nds", "unofficial"]
DELTA_SKINS_BASE = "https://raw.githubusercontent.com/delta-skins/delta-skins.github.io/master"
DELTA_SKINS_SITE = "https://delta-skins.github.io"


class _DeltaSkinsParser(html.parser.HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.entries = []

    def handle_starttag(self, tag, attrs):
        if tag != "img":
            return
        d = dict(attrs)
        if "data-download" not in d:
            return
        raw_dl = d["data-download"]
        if raw_dl.startswith("/"):
            dl_url = f"{DELTA_SKINS_BASE}{raw_dl}"
        elif raw_dl.startswith("http"):
            dl_url = raw_dl
        else:
            dl_url = f"{DELTA_SKINS_BASE}/{raw_dl}"

        self.entries.append({
            "name": d.get("alt") or d.get("data-name") or Path(raw_dl).stem,
            "author": d.get("data-author"),
            "thumbnailURL": (f"{DELTA_SKINS_SITE}{d['data-thumbnail']}"
                             if d.get("data-thumbnail", "").startswith("/")
                             else d.get("data-thumbnail")),
            "downloadURL": dl_url,
            "tags": [t.strip() for t in d.get("data-tags", "").split(",") if t.strip()],
        })


def scrape_delta_skins() -> list[dict]:
    entries = []
    for page in DELTA_SKINS_PAGES:
        url = f"{DELTA_SKINS_SITE}/{page}/"
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Provenance-SkinCatalog/1.0"})
            with urllib.request.urlopen(req, timeout=15) as r:
                html_content = r.read().decode("utf-8", errors="replace")
            parser = _DeltaSkinsParser()
            parser.feed(html_content)
            for e in parser.entries:
                system_code = system_from_name(page) or "unofficial"
                e["systems"] = [system_code]
                e["source"] = "delta-skins.github.io"
                e["id"] = make_id(e["source"], e["downloadURL"])
                entries.append(normalize_entry(e))
            print(f"  delta-skins/{page}: {len(parser.entries)} skins")
            time.sleep(0.5)
        except Exception as ex:
            print(f"  Warning: failed to scrape delta-skins/{page}: {ex}", file=sys.stderr)
    return entries


# ---------------------------------------------------------------------------
# GitHub repo scrapers
# ---------------------------------------------------------------------------

def scrape_github_repo(repo: str, attribution: str = None) -> list[dict]:
    """Scrape all skin files from a GitHub repo."""
    entries = process_github_repo(repo, GITHUB_TOKEN)
    for e in entries:
        e["source"] = repo
        if attribution and not e.get("author"):
            e["author"] = attribution
    return entries


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def load_existing_ids(catalog_path: str) -> set:
    if not os.path.exists(catalog_path):
        return set()
    with open(catalog_path) as f:
        catalog = json.load(f)
    return {s["id"] for s in catalog.get("skins", [])}


def load_existing_urls(catalog_path: str) -> set:
    if not os.path.exists(catalog_path):
        return set()
    with open(catalog_path) as f:
        catalog = json.load(f)
    return {s.get("downloadURL", "") for s in catalog.get("skins", [])}


def main():
    parser = argparse.ArgumentParser(description="Crawl external skin sources")
    parser.add_argument("--sources", default="sources.json")
    parser.add_argument("--existing-catalog", default="docs/catalog.json")
    parser.add_argument("--output-dir", default="skins")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    with open(args.sources) as f:
        sources = json.load(f)

    existing_urls = load_existing_urls(args.existing_catalog)
    print(f"Existing catalog has {len(existing_urls)} skins")

    all_new = []

    for source in sources.get("repos", []):
        print(f"\nScraping GitHub repo: {source['repo']}")
        try:
            entries = scrape_github_repo(source["repo"], source.get("attribution"))
            new = [e for e in entries if e.get("downloadURL") not in existing_urls]
            print(f"  {len(entries)} total, {len(new)} new")
            all_new.extend(new)
            existing_urls.update(e.get("downloadURL", "") for e in new)
        except Exception as ex:
            print(f"  Error: {ex}", file=sys.stderr)

    for source in sources.get("sites", []):
        stype = source.get("type")
        print(f"\nScraping site: {source.get('url', stype)}")
        try:
            if stype == "delta-skins-site":
                entries = scrape_delta_skins()
            else:
                print(f"  Unknown source type: {stype}", file=sys.stderr)
                continue
            new = [e for e in entries if e.get("downloadURL") not in existing_urls]
            print(f"  {len(entries)} total, {len(new)} new")
            all_new.extend(new)
            existing_urls.update(e.get("downloadURL", "") for e in new)
        except Exception as ex:
            print(f"  Error: {ex}", file=sys.stderr)

    print(f"\nTotal new skins found: {len(all_new)}")

    if all_new:
        save_entries(all_new, args.output_dir, args.dry_run)

    # Write count to GITHUB_OUTPUT
    github_output = os.environ.get("GITHUB_OUTPUT")
    if github_output:
        with open(github_output, "a") as f:
            f.write(f"new_skin_count={len(all_new)}\n")


if __name__ == "__main__":
    main()
