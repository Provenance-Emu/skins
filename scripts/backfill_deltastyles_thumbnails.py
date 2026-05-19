#!/usr/bin/env python3
"""
backfill_deltastyles_thumbnails.py — Re-populate `thumbnailURL` on migrated
Delta Styles variant entries so the existing generate-thumbnails workflow
can mirror previews via its Path A (deltastyles.com/images/ rehost).

Why this exists:
    The migration cleared `thumbnailURL: null` on every variant so the
    thumbnail workflow could regenerate per-variant artwork. But the
    workflow's Path B (extract from skin ZIP) skips `deltastyles.com/files/`
    URLs because Cloudflare 403s GitHub Actions runners on those paths.
    The result was 717 variants stuck without thumbnails.

    Delta Styles still serves one shared preview image per skin detail page
    (the OG image at `deltastyles.com/images/skins/thumbnails/thumb_*.png`).
    That host is NOT 403-blocked, so the workflow's Path A — which mirrors
    `deltastyles.com/images/` URLs to GitHub Releases — works fine.

    This script:
      1. Groups migrated variants by Delta Styles landing id.
      2. Hits `https://deltastyles.com/skins/{id}` (301-redirects to the
         canonical detail path) once per bundle and extracts og:image.
      3. Writes that URL to every variant's `thumbnailURL` field.
      4. Caches detail-page HTML so reruns are cheap.

Idempotent. Safe to re-run.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SKINS_DIR = REPO_ROOT / "skins"
DEFAULT_CACHE = REPO_ROOT / ".migration-cache" / "deltastyles-details"

UA = "Provenance-SkinCatalog/1.0 (thumbnail-backfill)"
OG_IMAGE_RX = re.compile(
    r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)["\']',
    re.IGNORECASE,
)
DETAIL_LINK_RX = re.compile(
    r'href="/skins/(\d+)-[a-z0-9-]+"', re.IGNORECASE
)
LANDING_ID_RX = re.compile(
    r"deltastyles\.com/files/skins/(\d+)/", re.IGNORECASE
)
# Some older Delta Styles bundles serve variants directly under /files/skins/
# without a numeric id prefix (e.g. `…/files/skins/aa-leafgreen.deltaskin`).
# For those we can't recover the landing id from the URL — we resort to a
# reverse index built from the migration cache's landing-page HTML.
CDN_URL_RX = re.compile(
    r"https?://deltastyles\.com/files/skins/[^\"<>]+?\.(?:deltaskin|manicskin|zip)",
    re.IGNORECASE,
)
LANDING_CACHE_FILENAME_RX = re.compile(
    r"https_deltastyles_com_download_files_php_id_(\d+)\.html$"
)


def fetch_detail(landing_id: str, cache_dir: Path, throttle: float) -> str | None:
    cache_path = cache_dir / f"{landing_id}.html"
    if cache_path.exists():
        return cache_path.read_text(encoding="utf-8")
    url = f"https://deltastyles.com/skins/{landing_id}"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=30) as r:
            html = r.read().decode("utf-8", errors="replace")
    except Exception as ex:
        print(f"  id={landing_id}: fetch failed ({ex})", file=sys.stderr)
        return None
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(html, encoding="utf-8")
    if throttle > 0:
        time.sleep(throttle)
    return html


def extract_og_image(html: str) -> str | None:
    m = OG_IMAGE_RX.search(html)
    if not m:
        return None
    url = m.group(1).strip()
    if "deltastyles.com" not in url:
        return None
    return url


def discover_all_landing_ids(throttle: float) -> set[str]:
    """Walk /all-skins pagination to harvest every landing id on the site."""
    ids: set[str] = set()
    page = 1
    while True:
        url = f"https://deltastyles.com/all-skins?page={page}"
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=30) as r:
                html = r.read().decode("utf-8", errors="replace")
        except Exception as ex:
            print(f"  page {page}: fetch failed ({ex})", file=sys.stderr)
            break
        new_ids = {m.group(1) for m in DETAIL_LINK_RX.finditer(html)}
        new_ids -= ids
        if not new_ids:
            break
        ids |= new_ids
        print(f"  page {page}: +{len(new_ids)} new landing id(s), {len(ids)} total")
        page += 1
        if throttle > 0:
            time.sleep(throttle)
    return ids


def ensure_landings_cached(landing_ids: set[str], cache_dir: Path, throttle: float) -> int:
    """Fetch landing pages for any id not already cached. Returns count fetched."""
    cache_dir.mkdir(parents=True, exist_ok=True)
    fetched = 0
    for lid in sorted(landing_ids, key=int):
        url = f"https://deltastyles.com/download-files.php?id={lid}"
        key = re.sub(r"\W+", "_", url).strip("_")
        cache_path = cache_dir / f"{key}.html"
        if cache_path.exists():
            continue
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=30) as r:
                html = r.read().decode("utf-8", errors="replace")
        except Exception as ex:
            print(f"  landing id={lid}: fetch failed ({ex})", file=sys.stderr)
            continue
        cache_path.write_text(html, encoding="utf-8")
        fetched += 1
        if fetched % 10 == 0:
            print(f"  …cached {fetched} landing(s)")
        if throttle > 0:
            time.sleep(throttle)
    return fetched


def build_url_to_landing(landing_cache: Path) -> dict[str, str]:
    """Index variant URL → landing id using cached download-files landings.

    Catches bundles whose CDN URLs lack the `/files/skins/{id}/` prefix
    (older Delta Styles uploads use bare filenames under /files/skins/).
    """
    if not landing_cache.exists():
        return {}
    out: dict[str, str] = {}
    for html_path in landing_cache.glob("*.html"):
        m = LANDING_CACHE_FILENAME_RX.search(html_path.name)
        if not m:
            continue
        lid = m.group(1)
        try:
            html = html_path.read_text(encoding="utf-8")
        except Exception:
            continue
        for variant_url in CDN_URL_RX.findall(html):
            parsed = urllib.parse.urlsplit(variant_url)
            normalized = urllib.parse.urlunsplit((
                parsed.scheme, parsed.netloc,
                urllib.parse.quote(urllib.parse.unquote(parsed.path), safe="/"),
                "", "",
            ))
            out.setdefault(normalized, lid)
    return out


def backfill(dry_run: bool, cache_dir: Path, throttle: float) -> int:
    landing_cache = REPO_ROOT / ".migration-cache" / "deltastyles"
    url_to_landing = build_url_to_landing(landing_cache)
    print(f"Indexed {len(url_to_landing)} variant URL(s) from {landing_cache}")

    by_landing: dict[str, list[Path]] = {}
    for p in sorted(SKINS_DIR.rglob("*.json")):
        try:
            entry = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        url = entry.get("downloadURL") or ""
        if "deltastyles.com" not in url:
            continue
        if entry.get("thumbnailURL"):
            continue  # already has one
        m = LANDING_ID_RX.search(url)
        if m:
            lid = m.group(1)
        else:
            # Normalize the catalog URL the same way the reverse-index normalized
            # its keys, so URL-encoded brackets/spaces match landing-page literals.
            parsed = urllib.parse.urlsplit(url)
            norm = urllib.parse.urlunsplit((
                parsed.scheme, parsed.netloc,
                urllib.parse.quote(urllib.parse.unquote(parsed.path), safe="/"),
                "", "",
            ))
            lid = url_to_landing.get(norm) or url_to_landing.get(url)
        if not lid:
            continue
        by_landing.setdefault(lid, []).append(p)

    print(f"Found {sum(len(v) for v in by_landing.values())} variants "
          f"without thumbnails across {len(by_landing)} bundles")

    updated = 0
    missing_og = []
    for landing_id in sorted(by_landing, key=int):
        html = fetch_detail(landing_id, cache_dir, throttle)
        if not html:
            continue
        og = extract_og_image(html)
        if not og:
            missing_og.append(landing_id)
            continue
        for p in by_landing[landing_id]:
            entry = json.loads(p.read_text(encoding="utf-8"))
            entry["thumbnailURL"] = og
            if not dry_run:
                p.write_text(json.dumps(entry, indent=2) + "\n", encoding="utf-8")
            updated += 1

    print(f"Annotated {updated} entries with shared bundle thumbnail")
    if missing_og:
        print(f"  {len(missing_og)} landing(s) had no og:image — skipped: "
              f"{', '.join(missing_og[:10])}")
    if dry_run:
        print("Dry-run: no changes written")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--cache-dir", type=Path, default=DEFAULT_CACHE)
    ap.add_argument("--throttle", type=float, default=0.4)
    ap.add_argument(
        "--discover",
        action="store_true",
        help="Walk /all-skins to find every landing id and cache any missing landing pages before backfill.",
    )
    args = ap.parse_args()

    if args.discover:
        print("Discovering landing ids via /all-skins…")
        all_ids = discover_all_landing_ids(args.throttle)
        landing_cache = REPO_ROOT / ".migration-cache" / "deltastyles"
        print(f"Found {len(all_ids)} landing id(s) on site; ensuring all are cached…")
        fetched = ensure_landings_cached(all_ids, landing_cache, args.throttle)
        print(f"Fetched {fetched} new landing page(s)")

    return backfill(args.dry_run, args.cache_dir, args.throttle)


if __name__ == "__main__":
    sys.exit(main())
