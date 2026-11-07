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

A record also carries `"dualScreen": true` when any representation of the skin
lays out two screens (a `screens` list with two `inputFrame`s that
do not overlap: the DS and 3DS top and bottom). That is the
real screen data behind the creator `dualScreen` stat; a skin with neither
variants nor two screens has no record.

It is computed from `info.json`, so it lives in this sidecar (skin id ->
{url, variants, dualScreen?}), never in the hand-edited skin JSON. Writers:
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


def _rect(frame):
    """(x, y, w, h) of a frame dict, or None unless all four are numbers and the size is positive."""
    if not isinstance(frame, dict):
        return None
    vals = [frame.get(k) for k in ("x", "y", "width", "height")]
    if not all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in vals):
        return None
    return tuple(vals) if vals[2] > 0 and vals[3] > 0 else None


def _disjoint(a, b) -> bool:
    return a[0] >= b[0] + b[2] or b[0] >= a[0] + a[2] or a[1] >= b[1] + b[3] or b[1] >= a[1] + a[3]


def _two_screens(screens) -> bool:
    """Whether a `screens` list shows two different parts of the game output: two
    `inputFrame`s that do not overlap (the DS and 3DS top and bottom screens).

    An entry with no `inputFrame` draws the whole output, and a backdrop copy of the
    game (GBA, SNES and NES skins blur one behind the real screen) crops a region
    that overlaps the real one, so neither is a second screen."""
    rects = [r for r in (_rect(sc.get("inputFrame")) for sc in screens if isinstance(sc, dict)) if r]
    return any(_disjoint(a, b) for n, a in enumerate(rects) for b in rects[n + 1:])


def _has_two_screens(node) -> bool:
    if isinstance(node, dict):
        if isinstance(node.get("screens"), list) and _two_screens(node["screens"]):
            return True
        return any(_has_two_screens(v) for k, v in node.items() if k != "screens")
    if isinstance(node, list):
        return any(_has_two_screens(v) for v in node)
    return False


def has_dual_screen(info) -> bool:
    """True when some representation of `info.json` lays out two different screens:
    the base layouts, the alternate layouts or a per-game override. A theme only
    swaps artwork, so it never adds a screen."""
    if not isinstance(info, dict):
        return False
    for key in ("representations", "altRepresentations", "gameOverrides"):
        if _has_two_screens(info.get(key)):
            return True
    return False


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


def set_record(store: dict, skin_id: str, url: str, variants: list[dict],
               dual_screen: bool = False) -> bool:
    """Replace a skin's record. A skin with no variants and a single screen has
    no record. Returns whether the store changed."""
    new = None
    if variants or dual_screen:
        new = {"url": url, "variants": variants}
        if dual_screen:
            new["dualScreen"] = True
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
            changed = set_record(store, sid, url, res["variants"], bool(res.get("dualScreen")))
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
    """Set `variants` (and `dualScreen`) on each entry whose record's url equals
    its downloadURL. A record for another URL is ignored. Returns how many
    entries got variants."""
    merged = 0
    for entry in entries:
        record = store.get(entry.get("id"))
        if not record or record.get("url") != entry.get("downloadURL"):
            continue
        if record.get("variants"):
            entry["variants"] = record["variants"]
            merged += 1
        if record.get("dualScreen") is True:
            entry["dualScreen"] = True
    return merged


# ---------------------------------------------------------------------------
# Import time (process_submission.py, crawl_sources.py)
# ---------------------------------------------------------------------------

# download URL -> variants, filled as importers read info.json. The id is not
# known yet at that point (it comes from the entry), so records are written by
# `flush_imports` once the entries exist.
_IMPORTED: dict[str, tuple[list[dict], bool]] = {}


def note_import(url: str, info) -> None:
    """Remember the variants and screen layout in the info.json just read for `url`."""
    _IMPORTED[url] = (compute_variants(info), has_dual_screen(info))


def flush_imports(entries: list[dict], path: str = VARIANTS_FILE, dry_run: bool = False) -> int:
    """Write sidecar records for imported entries whose info.json was read.
    Returns how many records changed."""
    store = load_variants(path)
    changed = 0
    for entry in entries:
        url = entry.get("downloadURL")
        if url in _IMPORTED and entry.get("id"):
            variants, dual = _IMPORTED[url]
            changed += set_record(store, entry["id"], url, variants, dual)
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
        dual = record.get("dualScreen")
        if dual is not None and dual is not True:
            errors.append(f"{sid}: dualScreen must be true when present")
        if not record.get("variants") and dual is not True:
            errors.append(f"{sid}: record has no variants (a skin without variants has no record)")
        if record.get("variants") or "variants" not in record:
            errors.extend(f"{sid}: {e}" for e in validate_variants(record.get("variants")))
    return errors
