#!/usr/bin/env python3
"""
variants_sidecar.py — The generated `variants.json` sidecar: what a single-file
skin carries inside its archive.

Some skins pack several variants into one file:
  - `altRepresentations` (Ignited): a second full layout set, flipped in play
    by a `toggleAltRepresentations` button
  - `themes` (Provenance): artwork swaps the user picks per skin
  - `gameOverrides` (Provenance): a layout per game (title, filename or md5)

`variants` lists them so the site and stores can show them before download:

    [{"kind": "alt" | "theme" | "game", "key": str, "label": str}]

It is computed from `info.json`, so it lives in this sidecar (skin id ->
{url, variants}), never in the hand-edited skin JSON. Writers:
  - `link_health.py` records every skin it inspects, pass or fail
  - `process_submission.py` / `crawl_sources.py` record at import
Reader: `build_catalog.py` merges a record into an entry only when the
record's `url` equals the entry's `downloadURL`, and never downloads.

Never edit `variants.json` by hand.
"""

import json
import os
from typing import Optional

VARIANTS_FILE = "variants.json"
ALT_KEY = "alt"
ALT_LABEL = "Alternate layout"
KINDS = ("alt", "theme", "game")


# ---------------------------------------------------------------------------
# Computing variants from info.json
# ---------------------------------------------------------------------------

def compute_variants(info) -> list[dict]:
    """Variants an archive's `info.json` carries, in a stable order: the alt
    layout, then themes, then per-game overrides."""
    if not isinstance(info, dict):
        return []
    out: list[dict] = []
    seen: set[tuple[str, str]] = set()

    def add(kind: str, key, label=None):
        key = key.strip() if isinstance(key, str) else ""
        if not key or (kind, key) in seen:
            return
        seen.add((kind, key))
        label = label.strip() if isinstance(label, str) else ""
        out.append({"kind": kind, "key": key, "label": label or key})

    alt = info.get("altRepresentations")
    if isinstance(alt, dict) and alt:
        add("alt", ALT_KEY, ALT_LABEL)

    themes = info.get("themes")
    if isinstance(themes, list):
        for theme in themes:
            if isinstance(theme, dict):
                add("theme", theme.get("id"), theme.get("name"))

    games = info.get("gameOverrides")
    if isinstance(games, dict):
        for game in games:
            add("game", game, game)
    return out


# ---------------------------------------------------------------------------
# Sidecar file
# ---------------------------------------------------------------------------

def load_variants(path: str = VARIANTS_FILE) -> dict:
    """The sidecar as {skin id: {"url": str, "variants": [...]}}; {} if missing."""
    if not os.path.exists(path):
        return {}
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    return data if isinstance(data, dict) else {}


def save_variants(store: dict, path: str = VARIANTS_FILE) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(dict(sorted(store.items())), f, indent=2, ensure_ascii=False)
        f.write("\n")


def set_record(store: dict, skin_id: str, url: str, variants: list[dict]) -> bool:
    """Replace a skin's record. A skin with no variants has no record.
    Returns whether the store changed."""
    new = {"url": url, "variants": variants} if variants else None
    if store.get(skin_id) == new or (new is None and skin_id not in store):
        return False
    if new is None:
        del store[skin_id]
    else:
        store[skin_id] = new
    return True


def update_from_results(store: dict, skins: list[dict], results: dict[str, dict],
                        permanent: set[str], prune: bool = False,
                        live_ids: set[str] | None = None) -> dict[str, int]:
    """Fold one health-check run into the sidecar (in place).

    `results[id]` carries `variants` when the archive's info.json was read,
    whether the skin passed or failed. Those records are replaced. A skin whose
    archive is now unreadable for good (a `permanent` failure) loses its record,
    as does one whose URL changed; a network error or 5xx keeps it, since it
    says nothing about the archive. With `prune`, records for skins no longer
    in the catalog go too (pass it only for a run over every skin). "In the
    catalog" means `live_ids` when given, else the ids in `skins`: pass `live_ids`
    whenever `skins` can be narrower than the catalog (a host that refused us is
    left out of the run, and its records must survive that).
    """
    stats = {"recorded": 0, "dropped": 0}
    for skin in skins:
        sid, url = skin["id"], skin["downloadURL"]
        res = results.get(sid) or {}
        had = sid in store
        if "variants" in res:
            changed = set_record(store, sid, url, res["variants"])
        elif had and (store[sid].get("url") != url or res.get("result") in permanent):
            del store[sid]
            changed = True
        else:
            changed = False
        if changed:
            stats["recorded" if sid in store else "dropped"] += 1
    if prune:
        live = live_ids if live_ids is not None else {s["id"] for s in skins}
        for sid in [sid for sid in store if sid not in live]:
            del store[sid]
            stats["dropped"] += 1
    return stats


def merge_variants(entries: list[dict], store: dict) -> int:
    """Set `variants` on each entry whose record's url equals its downloadURL.
    A record for another URL is ignored. Returns how many entries got variants."""
    merged = 0
    for entry in entries:
        record = store.get(entry.get("id"))
        if record and record.get("url") == entry.get("downloadURL") and record.get("variants"):
            entry["variants"] = record["variants"]
            merged += 1
    return merged


# ---------------------------------------------------------------------------
# Import time (process_submission.py, crawl_sources.py)
# ---------------------------------------------------------------------------

# download URL -> variants, filled as importers read info.json. The id is not
# known yet at that point (it comes from the entry), so records are written by
# `flush_imports` once the entries exist.
_IMPORTED: dict[str, list[dict]] = {}


def note_import(url: str, info) -> None:
    """Remember the variants in the info.json just read for `url`."""
    _IMPORTED[url] = compute_variants(info)


def flush_imports(entries: list[dict], path: str = VARIANTS_FILE, dry_run: bool = False) -> int:
    """Write sidecar records for imported entries whose info.json was read.
    Returns how many records changed."""
    store = load_variants(path)
    changed = 0
    for entry in entries:
        url = entry.get("downloadURL")
        if url in _IMPORTED and entry.get("id"):
            changed += set_record(store, entry["id"], url, _IMPORTED[url])
    if changed and not dry_run:
        save_variants(store, path)
    return changed


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def validate_store(store) -> list[str]:
    """Problems in a loaded sidecar (shape of each record and its variants)."""
    from skin_schema import validate_variants
    if not isinstance(store, dict):
        return ["variants.json must be an object keyed by skin id"]
    errors = []
    for sid, record in store.items():
        if not isinstance(record, dict) or not isinstance(record.get("url"), str) or not record["url"]:
            errors.append(f"{sid}: record needs a url")
            continue
        if not record.get("variants"):
            errors.append(f"{sid}: record has no variants (a skin without variants has no record)")
        errors.extend(f"{sid}: {e}" for e in validate_variants(record.get("variants")))
    return errors
