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
LANDING_ID_RX = re.compile(
    r"deltastyles\.com/files/skins/(\d+)/", re.IGNORECASE
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


def backfill(dry_run: bool, cache_dir: Path, throttle: float) -> int:
    by_landing: dict[str, list[Path]] = {}
    for p in sorted(SKINS_DIR.rglob("*.json")):
        try:
            entry = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        url = entry.get("downloadURL") or ""
        m = LANDING_ID_RX.search(url)
        if not m:
            continue
        if entry.get("thumbnailURL"):
            continue  # already has one
        by_landing.setdefault(m.group(1), []).append(p)

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
    args = ap.parse_args()
    return backfill(args.dry_run, args.cache_dir, args.throttle)


if __name__ == "__main__":
    sys.exit(main())
