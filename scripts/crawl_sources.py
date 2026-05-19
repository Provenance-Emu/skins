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
from skin_schema import make_id, slugify, normalize_entry, system_from_gti, system_from_name, system_from_token
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


import re as _re

# Direct CDN URL in `<button … value="…">` form elements on the download-files
# landing page. Older skins still serve .zip; current ones serve .deltaskin /
# .manicskin. Single-variant ids 30x-redirect; multi-variant ids return HTML.
_DS_VARIANT_BUTTON_RX = _re.compile(
    r'<button[^>]+value="(https?://[^"]+\.(?:deltaskin|manicskin|zip))"',
    _re.IGNORECASE,
)


def _deltastyles_humanize_variant(url: str) -> str:
    """Turn a CDN URL into a short human label suitable for a name suffix."""
    import re
    leaf = urllib.parse.unquote(url.rsplit("/", 1)[-1])
    leaf = re.sub(r"\.(deltaskin|manicskin|zip)$", "", leaf, flags=re.IGNORECASE)
    leaf = re.sub(r"[_]+", " ", leaf)
    leaf = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", leaf)
    leaf = re.sub(r"\s+", " ", leaf)
    return leaf.strip(" -")


def _deltastyles_normalize_cdn_url(raw: str) -> str:
    parsed = urllib.parse.urlsplit(raw)
    path = urllib.parse.quote(urllib.parse.unquote(parsed.path), safe="/")
    return urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, path, "", ""))


def _deltastyles_resolve_variants(detail_path: str) -> list[dict]:
    """Resolve a Delta Styles skin detail page into one or more variant dicts.

    Each variant is `{"downloadURL": str, "label": str}`. Returns [] when the
    page cannot be reached or no variants are exposed.
    """
    import re
    detail_url = f"https://deltastyles.com{detail_path}"
    try:
        req = urllib.request.Request(detail_url, headers={"User-Agent": _UA})
        with urllib.request.urlopen(req, timeout=15) as r:
            detail_html = r.read().decode("utf-8", errors="replace")
    except Exception as ex:
        print(f"    Warning: failed to fetch {detail_url}: {ex}", file=sys.stderr)
        return []

    m = re.search(r'href="/download(?:-files)?\.php\?id=(\d+)"', detail_html)
    if not m:
        print(f"    Warning: no download link on {detail_url}", file=sys.stderr)
        return []
    # Always probe the canonical landing path. `/download.php?id=N` is just an
    # alias that 302-redirects to `/download-files.php?id=N`; following that
    # redirect blindly would mistake the alias hop for a single-variant resolve.
    landing_url = f"https://deltastyles.com/download-files.php?id={m.group(1)}"

    # Fetch the landing without following redirects. Single-variant ids 30x to
    # the direct CDN file; multi-variant ids return HTML with form-value URLs.
    class _NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: D401
            return None

    opener = urllib.request.build_opener(_NoRedirect)
    landing_req = urllib.request.Request(landing_url, headers={"User-Agent": _UA})
    landing_html = None
    redirect_target = None
    try:
        with opener.open(landing_req, timeout=30) as r:
            landing_html = r.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        if e.code in (301, 302, 303, 307, 308):
            loc = e.headers.get("Location", "")
            if loc:
                redirect_target = urllib.parse.urljoin(landing_url, loc)
        else:
            print(f"    Warning: landing {landing_url} → HTTP {e.code}", file=sys.stderr)
            return []
    except Exception as ex:
        print(f"    Warning: landing fetch failed for {landing_url}: {ex}", file=sys.stderr)
        return []

    if redirect_target:
        url = _deltastyles_normalize_cdn_url(redirect_target)
        return [{"downloadURL": url, "label": _deltastyles_humanize_variant(url)}]

    seen: set[str] = set()
    out: list[dict] = []
    for m in _DS_VARIANT_BUTTON_RX.finditer(landing_html or ""):
        url = _deltastyles_normalize_cdn_url(m.group(1))
        if url in seen:
            continue
        seen.add(url)
        out.append({"downloadURL": url, "label": _deltastyles_humanize_variant(url)})
    return out


def _deltastyles_detect_system(detail_path: str, html: str) -> str:
    """Detect system code from a deltastyles.com detail page HTML."""
    import re
    m = re.search(r'href="/category/\d+-([^"]+)"', html)
    if m:
        cat = m.group(1).lower()
        code = system_from_name(cat)
        if code:
            return code
    return "unofficial"


def _deltastyles_resolve_skin(detail_path: str,
                               existing_urls: set[str]) -> list[dict]:
    """Resolve a Delta Styles skin detail page into per-variant entries.

    Returns a list of {downloadURL, label, system_code} dicts (possibly empty).
    Each variant gets its own deterministic id downstream — Delta Styles bundles
    that ship multiple .deltaskin/.manicskin files under one detail page now
    expose them as separate variants, and we treat each as its own skin entry.

    Variants whose downloadURL is already in `existing_urls` are filtered out.
    """
    import re
    detail_url = f"https://deltastyles.com{detail_path}"
    try:
        req = urllib.request.Request(detail_url, headers={"User-Agent": _UA})
        with urllib.request.urlopen(req, timeout=15) as r:
            detail_html = r.read().decode("utf-8", errors="replace")
    except Exception as ex:
        print(f"    Warning: failed to fetch {detail_url}: {ex}", file=sys.stderr)
        return []

    baseline_system = _deltastyles_detect_system(detail_path, detail_html)

    variants = _deltastyles_resolve_variants(detail_path)
    out: list[dict] = []
    for v in variants:
        if v["downloadURL"] in existing_urls:
            continue
        sys_code = system_from_token(v["label"]) if len(variants) > 1 else None
        out.append({
            "downloadURL": v["downloadURL"],
            "label": v["label"],
            "system_code": sys_code or baseline_system,
        })
    return out


def scrape_deltastyles(system_pages: list[str],
                       existing_urls: set[str] | None = None,
                       scrape_all: bool = False) -> list[dict]:
    """Scrape skins from deltastyles.com.

    When scrape_all is True, also paginates through /all-skins to catch skins
    not listed on any system landing page.

    Skips detail-page requests for skins whose detail path already maps to a
    known download URL, and randomises request timing to be polite.
    """
    if existing_urls is None:
        existing_urls = set()
    else:
        existing_urls = existing_urls.copy()

    entries = []

    def _emit_variants(detail_path: str,
                       name: str,
                       skin_meta: dict,
                       baseline_system: str) -> int:
        """Resolve `detail_path` into one or more variant entries and append
        them to `entries`. Returns number of new entries emitted."""
        import re as _re_inner
        variants = _deltastyles_resolve_variants(detail_path)
        # Detail paths are `/skins/{id}-{slug}`; the leading int is the
        # landing-page id we use as the group key for sibling variants.
        m_lid = _re_inner.search(r"/skins/(\d+)-", detail_path)
        landing_id = m_lid.group(1) if m_lid else None
        is_group = len(variants) > 1 and landing_id is not None
        emitted = 0
        for idx, v in enumerate(variants, start=1):
            dl_url = v["downloadURL"]
            if dl_url in existing_urls:
                continue
            label = v["label"]
            sys_code = (
                system_from_token(label) if len(variants) > 1 else None
            ) or baseline_system
            if len(variants) > 1 and label and label.lower() not in name.lower():
                variant_name = f"{name} — {label}"
            else:
                variant_name = name
            entry = {
                "name": variant_name,
                "author": skin_meta.get("author"),
                "downloadURL": dl_url,
                "thumbnailURL": None,  # let thumbnail workflow regenerate per variant
                "systems": [sys_code],
                "source": "deltastyles.com",
                "tags": [],
            }
            if is_group:
                entry["groupId"] = f"deltastyles:{landing_id}"
                entry["groupOrder"] = idx
            entry["id"] = make_id(entry["source"], entry["downloadURL"])
            entries.append(normalize_entry(entry))
            existing_urls.add(dl_url)
            emitted += 1
            time.sleep(random.uniform(0.5, 1.5))
        return emitted

    # --- Phase 1: system landing pages ---
    pages = list(system_pages)
    random.shuffle(pages)

    all_seen_paths: set[str] = set()

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

                all_seen_paths.add(detail_path)

                # Also check if the detail-path slug is already in existing URLs
                if any(detail_path.split("/")[-1] in u for u in existing_urls):
                    print(f"    Skipping (already known): {name}")
                    continue

                print(f"    Resolving: {name}")
                emitted = _emit_variants(detail_path, name, skin, system_code)
                if emitted == 0:
                    print(f"    Skipping (no new variants): {name}")
                    continue
                print(f"      → +{emitted} variant entry/entries")
                time.sleep(random.uniform(1.0, 3.0))

            time.sleep(random.uniform(1.0, 2.0))
        except Exception as ex:
            print(f"  Warning: failed to scrape deltastyles/{page}: {ex}", file=sys.stderr)

    # --- Phase 2: paginate /all-skins to catch the rest ---
    if scrape_all:
        import re
        print("\n  deltastyles/all-skins: paginating…")
        page_num = 1
        while True:
            url = f"https://deltastyles.com/all-skins?page={page_num}&sort=&order="
            try:
                req = urllib.request.Request(url, headers={"User-Agent": _UA})
                with urllib.request.urlopen(req, timeout=15) as r:
                    html_content = r.read().decode("utf-8", errors="replace")
            except Exception as ex:
                print(f"    Warning: failed page {page_num}: {ex}", file=sys.stderr)
                break

            skins = _deltastyles_parse_listing(html_content)
            if not skins:
                break

            new_on_page = [s for s in skins if s.get("_detail_path") not in all_seen_paths]
            print(f"    Page {page_num}: {len(skins)} skins, {len(new_on_page)} unseen")

            for skin in new_on_page:
                detail_path = skin.get("_detail_path", "")
                name = skin.get("name", "").strip()
                if not name or not detail_path:
                    continue
                all_seen_paths.add(detail_path)

                if any(detail_path.split("/")[-1] in u for u in existing_urls):
                    continue

                print(f"      Resolving: {name}")
                # For /all-skins entries we don't know the system upfront — let
                # _emit_variants's baseline come from the detail page's category.
                # Pre-fetch the detail page once for that detection so
                # _emit_variants does not re-fetch it.
                try:
                    req2 = urllib.request.Request(
                        f"https://deltastyles.com{detail_path}",
                        headers={"User-Agent": _UA},
                    )
                    with urllib.request.urlopen(req2, timeout=15) as r:
                        detail_html = r.read().decode("utf-8", errors="replace")
                    baseline_system = _deltastyles_detect_system(detail_path, detail_html)
                except Exception:
                    baseline_system = "unofficial"

                emitted = _emit_variants(detail_path, name, skin, baseline_system)
                if emitted == 0:
                    continue
                print(f"        → +{emitted} variant entry/entries")
                time.sleep(random.uniform(1.0, 3.0))

            page_num += 1
            time.sleep(random.uniform(1.0, 2.0))

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
                scrape_all = source.get("scrape_all", False)
                entries = scrape_deltastyles(pages, existing_urls, scrape_all=scrape_all)
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
