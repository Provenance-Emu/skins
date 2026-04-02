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
import random
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

_UA = "Provenance-SkinCatalog/1.0"


# ---------------------------------------------------------------------------
# deltastyles.com scraper
# ---------------------------------------------------------------------------

def _deltastyles_parse_listing(html_content: str) -> list[dict]:
    """Parse deltastyles.com listing HTML to extract unique skins using regex."""
    import re

    # Split on file-list blocks
    blocks = re.split(r'<div class="file-list">', html_content)[1:]
    seen: dict[str, dict] = {}  # detail_path → skin dict (dedup)

    for block in blocks:
        # Detail path + thumbnail
        m_link = re.search(r'href="(/skins/\d+-[^"]+)"', block)
        m_thumb = re.search(r'<img src="([^"]*thumbnails/[^"]*)"', block)
        m_title = re.search(r'class="file-title">([^<]+)', block)
        m_author = re.search(r'href="/user/[^"]*">([^<]+)', block)

        if not m_link:
            continue

        detail_path = m_link.group(1)
        if detail_path in seen:
            continue  # already captured from another section

        skin: dict = {"_detail_path": detail_path}
        if m_title:
            skin["name"] = m_title.group(1).strip()
        if m_author:
            skin["author"] = m_author.group(1).strip()
        if m_thumb:
            src = m_thumb.group(1)
            if not src.startswith("http"):
                src = f"https://deltastyles.com{src}"
            skin["thumbnailURL"] = src

        seen[detail_path] = skin

    return list(seen.values())


def _deltastyles_resolve_download(detail_path: str) -> tuple[str | None, dict]:
    """Visit a deltastyles.com skin detail page, extract download URL and extra metadata."""
    url = f"https://deltastyles.com{detail_path}"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": _UA})
        with urllib.request.urlopen(req, timeout=15) as r:
            html_content = r.read().decode("utf-8", errors="replace")
    except Exception as ex:
        print(f"    Warning: failed to fetch {url}: {ex}", file=sys.stderr)
        return None, {}

    # Find download.php link
    import re
    m = re.search(r'href="(/download\.php\?id=(\d+))"', html_content)
    if not m:
        # Try alternate pattern: download-files.php
        m = re.search(r'href="(/download-files\.php\?id=(\d+))"', html_content)
    if not m:
        print(f"    Warning: no download link found on {url}", file=sys.stderr)
        return None, {}

    raw_path = m.group(1)
    if not raw_path.startswith("/"):
        raw_path = f"/{raw_path}"
    download_page_url = f"https://deltastyles.com{raw_path}"
    numeric_id = m.group(2)

    # Follow redirect to get actual file URL
    try:
        req = urllib.request.Request(download_page_url, headers={"User-Agent": _UA})
        req.method = "HEAD"
        # Use a custom opener that doesn't follow redirects
        class _NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, req, fp, code, msg, headers, newurl):
                return None
        opener = urllib.request.build_opener(_NoRedirect)
        try:
            opener.open(req, timeout=15)
        except urllib.error.HTTPError as e:
            if e.code in (301, 302, 303, 307, 308):
                location = e.headers.get("Location", "")
                if location:
                    if not location.startswith("http"):
                        if not location.startswith("/"):
                            location = f"/{location}"
                        location = f"https://deltastyles.com{location}"
                    return location, {}
        # If no redirect, use the download page URL directly
        return download_page_url, {}
    except Exception as ex:
        print(f"    Warning: failed to resolve download for id={numeric_id}: {ex}", file=sys.stderr)
        return download_page_url, {}


def scrape_deltastyles(system_pages: list[str],
                       existing_urls: set[str] | None = None) -> list[dict]:
    """Scrape skins from deltastyles.com for the given system page slugs.

    Skips detail-page requests for skins whose detail path already maps to a
    known download URL, and randomises request timing to be polite.
    """
    if existing_urls is None:
        existing_urls = set()

    entries = []
    pages = list(system_pages)
    random.shuffle(pages)

    for page in pages:
        url = f"https://deltastyles.com/systems/{page}"
        print(f"  deltastyles/{page}: fetching listing…")
        try:
            req = urllib.request.Request(url, headers={"User-Agent": _UA})
            with urllib.request.urlopen(req, timeout=15) as r:
                html_content = r.read().decode("utf-8", errors="replace")
            skins = _deltastyles_parse_listing(html_content)
            random.shuffle(skins)
            print(f"  deltastyles/{page}: found {len(skins)} skins")

            system_code = system_from_name(page) or "unofficial"

            for skin in skins:
                detail_path = skin.get("_detail_path", "")
                name = skin.get("name", "").strip()
                if not name or not detail_path:
                    continue

                # Build a provisional ID from the detail path so we can check
                # whether we already have this skin before hitting the server.
                provisional_source_key = f"deltastyles.com:{detail_path}"
                provisional_id = make_id("deltastyles.com", detail_path)
                # Also check if the detail-path slug is already in existing URLs
                if any(detail_path.split("/")[-1] in u for u in existing_urls):
                    print(f"    Skipping (already known): {name}")
                    continue

                print(f"    Resolving: {name}")
                dl_url, extra = _deltastyles_resolve_download(detail_path)
                if not dl_url:
                    continue

                # Skip if the resolved download URL is already in the catalog
                if dl_url in existing_urls:
                    print(f"    Skipping (already in catalog): {name}")
                    continue

                entry = {
                    "name": name,
                    "author": skin.get("author"),
                    "downloadURL": dl_url,
                    "thumbnailURL": skin.get("thumbnailURL"),
                    "systems": [system_code],
                    "source": "deltastyles.com",
                    "tags": [],
                }
                entry["id"] = make_id(entry["source"], entry["downloadURL"])
                entries.append(normalize_entry(entry))
                time.sleep(random.uniform(1.0, 3.0))

            time.sleep(random.uniform(1.0, 2.0))
        except Exception as ex:
            print(f"  Warning: failed to scrape deltastyles/{page}: {ex}", file=sys.stderr)
    return entries


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

        # Thumbnail is the img src — a relative path like "gba/darkmodegba pic.png"
        src = d.get("src", "")
        if src and not src.startswith("http"):
            import urllib.parse
            thumb_url = f"{DELTA_SKINS_BASE}/{urllib.parse.quote(src)}"
        elif src.startswith("http"):
            thumb_url = src
        else:
            thumb_url = None

        self.entries.append({
            "name": d.get("alt") or d.get("data-name") or Path(raw_dl).stem,
            "author": d.get("data-maker") or d.get("data-author"),
            "thumbnailURL": thumb_url,
            "downloadURL": dl_url,
            "tags": [t.strip() for t in d.get("data-tags", "").split(",") if t.strip()],
        })


def scrape_delta_skins() -> list[dict]:
    entries = []
    for page in DELTA_SKINS_PAGES:
        url = f"{DELTA_SKINS_SITE}/{page}.html"
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
# GitHub search auto-discovery
# ---------------------------------------------------------------------------

def discover_repos_via_github_search(search_config: dict,
                                      known_repos: set[str]) -> list[str]:
    """
    Use the GitHub code-search API to find repositories that contain
    .deltaskin or .manicskin files, then return repo full_names we haven't
    seen before.  Requires a GITHUB_TOKEN (unauthenticated requests get a
    very low rate limit and sometimes 401).
    """
    if not GITHUB_TOKEN:
        print("  Skipping GitHub search: no GITHUB_TOKEN", file=sys.stderr)
        return []

    exclude = set(search_config.get("exclude_repos", []))
    queries = search_config.get("queries", ["extension:deltaskin"])
    min_stars = search_config.get("min_stars", 0)

    headers = {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {GITHUB_TOKEN}",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "Provenance-SkinCatalog/1.0",
    }

    found: dict[str, int] = {}  # repo → skin file count

    for query in queries:
        # GitHub code search returns up to 100 results per page, max 10 pages
        for page in range(1, 4):
            url = (f"https://api.github.com/search/code"
                   f"?q={urllib.request.quote(query)}&per_page=100&page={page}")
            try:
                req = urllib.request.Request(url, headers=headers)
                with urllib.request.urlopen(req, timeout=20) as r:
                    data = json.loads(r.read())
            except urllib.error.HTTPError as e:
                if e.code in (403, 422):  # rate-limited or query error
                    print(f"  GitHub search rate-limited/error (HTTP {e.code}): {query}",
                          file=sys.stderr)
                break
            except Exception as e:
                print(f"  GitHub search failed: {e}", file=sys.stderr)
                break

            items = data.get("items", [])
            if not items:
                break

            for item in items:
                repo = item["repository"]["full_name"]
                found[repo] = found.get(repo, 0) + 1

            if len(items) < 100:
                break
            time.sleep(1.5)  # respect rate limits between pages
        time.sleep(2)  # between queries

    new_repos = []
    for repo, count in sorted(found.items(), key=lambda x: -x[1]):
        if repo in known_repos or repo in exclude:
            continue
        # Optionally filter by star count
        if min_stars > 0:
            try:
                req = urllib.request.Request(
                    f"https://api.github.com/repos/{repo}", headers=headers)
                with urllib.request.urlopen(req, timeout=10) as r:
                    info = json.loads(r.read())
                if info.get("stargazers_count", 0) < min_stars:
                    continue
            except Exception:
                pass
            time.sleep(0.5)
        print(f"  Discovered: {repo} ({count} skin file(s))")
        new_repos.append(repo)

    return new_repos


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

    # Build set of all known repos (explicit + already-sourced) for dedup
    known_repos = {s["repo"] for s in sources.get("repos", [])}

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

    # GitHub search auto-discovery
    search_config = sources.get("github_search", {})
    if search_config.get("enabled"):
        print("\nRunning GitHub search auto-discovery…")
        discovered = discover_repos_via_github_search(search_config, known_repos)
        for repo in discovered:
            print(f"\nScraping discovered repo: {repo}")
            try:
                entries = scrape_github_repo(repo)
                new = [e for e in entries if e.get("downloadURL") not in existing_urls]
                print(f"  {len(entries)} total, {len(new)} new")
                all_new.extend(new)
                existing_urls.update(e.get("downloadURL", "") for e in new)
                known_repos.add(repo)
            except Exception as ex:
                print(f"  Error: {ex}", file=sys.stderr)

    for source in sources.get("sites", []):
        stype = source.get("type")
        print(f"\nScraping site: {source.get('url', stype)}")
        try:
            if stype == "delta-skins-site":
                entries = scrape_delta_skins()
            elif stype == "deltastyles":
                pages = source.get("system_pages", [])
                entries = scrape_deltastyles(pages, existing_urls)
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
