#!/usr/bin/env python3
"""
migrate_deltastyles.py — Migrate deltastyles.com download(-files).php URLs
to direct CDN URLs and split bundles into per-variant skins.

Background:
    Delta Styles changed its download endpoint. `download-files.php?id=N` used
    to redirect straight to a .deltaskin/.manicskin file. It now serves an HTML
    landing page where each variant is exposed as a POST form whose
    `<button value="…">` holds the real CDN URL
    (e.g. `https://deltastyles.com/files/skins/648/jp-doom.manicskin`).

    For ids that publish a single variant Delta Styles still 30x-redirects;
    for ids with multiple variants the HTML page is returned. The Provenance
    app downloads HTML in the multi-variant case and chokes.

This script:
    1. Walks `skins/` for every JSON entry whose `downloadURL` matches a
       deltastyles.com download(-files).php endpoint.
    2. Groups them by numeric landing-page id and fetches each landing page
       once (HTML responses cached on disk so reruns are cheap and polite).
    3. Parses out every direct CDN variant URL from the landing page.
       Single-variant responses that 30x-redirect are also handled: we follow
       the redirect and treat the resolved URL as the single variant.
    4. Each variant becomes its own skin JSON file with a deterministic id
       (`make_id(source, downloadURL)`), inheriting author/systems from the
       original aggregated entries. `thumbnailURL` is cleared so the existing
       generate-thumbnails workflow can regenerate per-variant artwork on its
       next run.
    5. Original aggregated entries are deleted once their variants are written.

Run with `--dry-run` to preview changes. Without it, the working tree is
mutated in place — commit before running for a clean revert path.
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
from typing import Iterable

REPO_ROOT = Path(__file__).resolve().parent.parent
SKINS_DIR = REPO_ROOT / "skins"

sys.path.insert(0, str(Path(__file__).resolve().parent))
from skin_schema import make_id, normalize_entry, slugify, system_from_token  # noqa: E402

UA = "Provenance-SkinCatalog/1.0 (deltastyles-migration)"
SOURCE = "deltastyles.com"

LANDING_RX = re.compile(
    r"https?://(?:www\.)?deltastyles\.com/download(?:-files)?\.php\?id=(\d+)",
    re.IGNORECASE,
)
BUTTON_VALUE_RX = re.compile(
    r'<button[^>]+value="(https?://[^"]+\.(?:deltaskin|manicskin|zip))"',
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# Network
# ---------------------------------------------------------------------------

def _cache_key(url: str) -> str:
    return re.sub(r"\W+", "_", url).strip("_")


def fetch_landing(url: str, cache_dir: Path | None, throttle: float) -> tuple[str | None, str | None]:
    """Fetch a landing-page URL.

    Returns (html, redirect_target). One of the two is non-None on success.
    Single-variant ids 30x-redirect; we capture the Location header so the
    caller can use it as the sole variant without parsing HTML.
    """
    if cache_dir is not None:
        key = _cache_key(url)
        html_path = cache_dir / f"{key}.html"
        redir_path = cache_dir / f"{key}.redirect"
        if redir_path.exists():
            return None, redir_path.read_text(encoding="utf-8").strip()
        if html_path.exists():
            return html_path.read_text(encoding="utf-8"), None

    class _NoFollow(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: D401
            return None

    opener = urllib.request.build_opener(_NoFollow)
    req = urllib.request.Request(url, headers={"User-Agent": UA})

    redirect_target: str | None = None
    html: str | None = None
    try:
        with opener.open(req, timeout=30) as r:
            html = r.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        if e.code in (301, 302, 303, 307, 308):
            loc = e.headers.get("Location", "")
            if loc:
                redirect_target = urllib.parse.urljoin(url, loc)
        else:
            raise

    if cache_dir is not None:
        cache_dir.mkdir(parents=True, exist_ok=True)
        if redirect_target:
            (cache_dir / f"{_cache_key(url)}.redirect").write_text(redirect_target, encoding="utf-8")
        elif html is not None:
            (cache_dir / f"{_cache_key(url)}.html").write_text(html, encoding="utf-8")

    if throttle > 0:
        time.sleep(throttle)
    return html, redirect_target


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------

def _normalize_url(raw: str) -> str:
    parsed = urllib.parse.urlsplit(raw)
    path = urllib.parse.quote(urllib.parse.unquote(parsed.path), safe="/")
    return urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, path, "", ""))


def parse_variants(html: str) -> list[str]:
    """Return ordered, unique variant download URLs from a landing-page HTML body."""
    seen: set[str] = set()
    out: list[str] = []
    for m in BUTTON_VALUE_RX.finditer(html):
        url = _normalize_url(m.group(1))
        if url in seen:
            continue
        seen.add(url)
        out.append(url)
    return out


def variant_label(url: str) -> str:
    """Humanize the filename portion of a CDN URL into a short label."""
    leaf = urllib.parse.unquote(url.rsplit("/", 1)[-1])
    leaf = re.sub(r"\.(deltaskin|manicskin|zip)$", "", leaf, flags=re.IGNORECASE)
    leaf = re.sub(r"[_]+", " ", leaf)
    leaf = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", leaf)  # CamelCase → Camel Case
    leaf = re.sub(r"\s+", " ", leaf)
    return leaf.strip(" -")


def detect_variant_system(label: str, baseline_systems: list[str]) -> str:
    """Pick the best system folder for a variant. Falls back to the umbrella's
    declared system when no short code token is found in the label — the right
    behaviour for game-themed variants like `jp-doom` on a Jaguar skin."""
    code = system_from_token(label)
    if code:
        return code
    return baseline_systems[0] if baseline_systems else "unofficial"


# ---------------------------------------------------------------------------
# Catalog walk
# ---------------------------------------------------------------------------

def discover_targets(skins_dir: Path) -> list[tuple[Path, dict, str]]:
    out: list[tuple[Path, dict, str]] = []
    for path in sorted(skins_dir.rglob("*.json")):
        try:
            entry = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        url = entry.get("downloadURL") or ""
        m = LANDING_RX.search(url)
        if m:
            out.append((path, entry, m.group(1)))
    return out


def _strip_trailing_variant(name: str) -> str:
    """Remove a trailing ' — variant' / ' - variant' suffix added by a prior split."""
    return re.sub(r"\s*[—-]\s*[^—-]{1,40}$", "", name).strip() or name


# ---------------------------------------------------------------------------
# Migration
# ---------------------------------------------------------------------------

def plan_migration(
    targets: list[tuple[Path, dict, str]],
    cache_dir: Path | None,
    throttle: float,
) -> tuple[list[tuple[Path, dict]], set[Path], list[str]]:
    """Build the write/delete plan without touching disk."""
    by_id: dict[str, list[tuple[Path, dict]]] = {}
    for path, entry, lid in targets:
        by_id.setdefault(lid, []).append((path, entry))

    to_write: list[tuple[Path, dict]] = []
    to_delete: set[Path] = set()
    failed: list[str] = []
    used_paths: set[Path] = set()
    member_paths: set[Path] = {p for members in by_id.values() for p, _ in members}

    for lid in sorted(by_id, key=int):
        members = by_id[lid]
        landing = f"https://deltastyles.com/download-files.php?id={lid}"
        try:
            html, redirect = fetch_landing(landing, cache_dir, throttle)
        except Exception as ex:
            print(f"  id={lid}: fetch failed ({ex}) — skipping {len(members)} member(s)")
            failed.append(landing)
            continue

        if redirect:
            variants = [_normalize_url(redirect)]
        elif html:
            variants = parse_variants(html)
        else:
            variants = []

        if not variants:
            print(f"  id={lid}: no variants parsed — keeping {len(members)} original entry/entries")
            failed.append(landing)
            continue

        baseline_path, baseline_entry = members[0]
        base_name = _strip_trailing_variant(baseline_entry.get("name") or f"Delta Styles {lid}")
        baseline_systems = baseline_entry.get("systems") or ["unofficial"]

        print(f"  id={lid}: {len(variants)} variant(s) ← {len(members)} existing")

        for v_url in variants:
            label = variant_label(v_url)
            # Compose name: avoid duplicating base_name when label already contains it
            if (
                len(variants) == 1
                or label.lower() in base_name.lower()
                or base_name.lower() in label.lower()
            ):
                new_name = base_name if len(variants) == 1 else label or base_name
            else:
                new_name = f"{base_name} — {label}"
            new_id = make_id(SOURCE, v_url)
            # Prefer label-derived slug — bundle umbrella names often exceed slugify's
            # 64-char cap and would collapse every variant onto the same slug.
            slug = (
                slugify(label) if len(variants) > 1 and label else slugify(new_name)
            ) or new_id
            sys_folder = (
                detect_variant_system(label, baseline_systems)
                if len(variants) > 1
                else baseline_systems[0]
            )
            entry_systems = [sys_folder] if sys_folder != baseline_systems[0] else baseline_systems
            candidate = SKINS_DIR / sys_folder / f"{slug}.json"

            n = 2
            while candidate in used_paths or (
                candidate.exists() and candidate not in member_paths
            ):
                candidate = SKINS_DIR / sys_folder / f"{slug}-{n}.json"
                n += 1
            used_paths.add(candidate)

            new_entry = normalize_entry({
                **baseline_entry,
                "name": new_name,
                "systems": entry_systems,
                "downloadURL": v_url,
                "id": new_id,
                "thumbnailURL": None,
                "source": SOURCE,
            })

            print(f"    → {candidate.relative_to(REPO_ROOT)}  id={new_id}  ← {v_url}")
            to_write.append((candidate, new_entry))

        for path, _ in members:
            to_delete.add(path)

    to_delete -= used_paths
    return to_write, to_delete, failed


def apply_plan(to_write: list[tuple[Path, dict]], to_delete: set[Path]) -> None:
    for path, entry in to_write:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(entry, indent=2) + "\n", encoding="utf-8")
    for path in to_delete:
        if path.exists():
            path.unlink()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dry-run", action="store_true", help="Print the plan; do not modify files.")
    ap.add_argument(
        "--cache-dir",
        type=Path,
        default=REPO_ROOT / ".migration-cache" / "deltastyles",
        help="Directory for cached HTML/redirect responses (default: .migration-cache/deltastyles).",
    )
    ap.add_argument("--no-cache", action="store_true", help="Bypass the on-disk fetch cache.")
    ap.add_argument(
        "--throttle",
        type=float,
        default=0.4,
        help="Seconds to sleep between landing-page fetches (default: 0.4).",
    )
    args = ap.parse_args()

    cache_dir = None if args.no_cache else args.cache_dir

    targets = discover_targets(SKINS_DIR)
    print(f"Discovered {len(targets)} skin entries pointing at deltastyles.com download endpoints")
    if not targets:
        return 0

    to_write, to_delete, failed = plan_migration(targets, cache_dir, args.throttle)

    print()
    print(f"Plan: write {len(to_write)} file(s), delete {len(to_delete)} file(s), {len(failed)} failure(s).")
    if failed:
        print("Failed landings (left untouched):")
        for u in failed:
            print(f"  - {u}")

    if args.dry_run:
        print("\nDry-run: no changes written.")
        return 1 if failed else 0

    apply_plan(to_write, to_delete)
    print("Applied.")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
