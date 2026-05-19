#!/usr/bin/env python3
"""
backfill_group_ids.py — Assign groupId + groupOrder to skin entries that came
out of the Delta Styles migration so the website generators can cluster
variants into a single card per umbrella.

Strategy:
    1. Walk every cached landing page in `.migration-cache/deltastyles/`
       (also re-fetches if cache is missing).
    2. Parse the form-button variant URLs in order.
    3. For each variant URL, find the matching skin JSON by downloadURL and
       set `groupId = "deltastyles:{landingId}"` + `groupOrder = index+1`.
    4. Landings with only one variant get no group annotation — they don't
       need clustering.

Idempotent. Safe to re-run.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SKINS_DIR = REPO_ROOT / "skins"
DEFAULT_CACHE = REPO_ROOT / ".migration-cache" / "deltastyles"

sys.path.insert(0, str(Path(__file__).resolve().parent))
from skin_schema import normalize_entry  # noqa: E402

UA = "Provenance-SkinCatalog/1.0 (deltastyles-grouping)"
BUTTON_VALUE_RX = re.compile(
    r'<button[^>]+value="(https?://[^"]+\.(?:deltaskin|manicskin|zip))"',
    re.IGNORECASE,
)


def _normalize_url(raw: str) -> str:
    parsed = urllib.parse.urlsplit(raw)
    path = urllib.parse.quote(urllib.parse.unquote(parsed.path), safe="/")
    return urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, path, "", ""))


def parse_landing(html: str) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for m in BUTTON_VALUE_RX.finditer(html):
        url = _normalize_url(m.group(1))
        if url in seen:
            continue
        seen.add(url)
        out.append(url)
    return out


def fetch_landing(landing_id: str, cache_dir: Path, throttle: float) -> str | None:
    url = f"https://deltastyles.com/download-files.php?id={landing_id}"
    key = re.sub(r"\W+", "_", url).strip("_")
    cache_path = cache_dir / f"{key}.html"
    if cache_path.exists():
        return cache_path.read_text(encoding="utf-8")
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    try:
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


def discover_landing_ids(cache_dir: Path) -> list[str]:
    ids: set[str] = set()
    if cache_dir.exists():
        for p in cache_dir.glob("*.html"):
            m = re.search(r"id_(\d+)\.html$", p.name)
            if m:
                ids.add(m.group(1))
    # Also scan catalog for landing ids embedded in CDN paths like /files/skins/{id}/
    for p in SKINS_DIR.rglob("*.json"):
        try:
            entry = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        url = entry.get("downloadURL") or ""
        m = re.search(r"deltastyles\.com/files/skins/(\d+)/", url)
        if m:
            ids.add(m.group(1))
    return sorted(ids, key=int)


def build_url_to_path(skins_dir: Path) -> dict[str, Path]:
    """Index every catalog entry by its downloadURL."""
    out: dict[str, Path] = {}
    for p in sorted(skins_dir.rglob("*.json")):
        try:
            entry = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        url = entry.get("downloadURL")
        if url:
            out[url] = p
    return out


def backfill(dry_run: bool, cache_dir: Path, throttle: float) -> int:
    landing_ids = discover_landing_ids(cache_dir)
    print(f"Found {len(landing_ids)} Delta Styles landing id(s) to backfill")

    url_to_path = build_url_to_path(SKINS_DIR)

    updated = 0
    skipped_single = 0
    unmatched = 0
    annotated_paths: set[Path] = set()

    for lid in landing_ids:
        html = fetch_landing(lid, cache_dir, throttle)
        if not html:
            continue
        variants = parse_landing(html)
        if len(variants) <= 1:
            skipped_single += 1
            continue

        group_id = f"deltastyles:{lid}"
        for i, v_url in enumerate(variants, start=1):
            path = url_to_path.get(v_url)
            if path is None:
                # URL may have been re-encoded — try unquoted form
                alt = urllib.parse.unquote(v_url)
                path = url_to_path.get(alt)
            if path is None:
                unmatched += 1
                continue
            try:
                entry = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                unmatched += 1
                continue

            if (
                entry.get("groupId") == group_id
                and entry.get("groupOrder") == i
            ):
                continue  # already annotated

            entry["groupId"] = group_id
            entry["groupOrder"] = i
            entry = normalize_entry(entry)
            if not dry_run:
                path.write_text(json.dumps(entry, indent=2) + "\n", encoding="utf-8")
            annotated_paths.add(path)
            updated += 1

    print(f"Annotated {updated} entries across {len(annotated_paths)} files")
    print(f"  {skipped_single} landing(s) had only 1 variant — left ungrouped")
    if unmatched:
        print(f"  {unmatched} variant URL(s) had no matching catalog entry")
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
