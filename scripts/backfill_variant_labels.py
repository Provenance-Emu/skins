#!/usr/bin/env python3
"""
backfill_variant_labels.py — Set `variantLabel` on grouped skin entries.

`variantLabel` is a variant's own name inside its `groupId` family ("Doom" for
"Atari Jaguar Paw — Doom"). This mirrors what the website derives at render
time (`stripVariantSuffix()` / `variantLabel()` in docs/js/browse.js), so
storing it changes nothing on the site:

    1. Group entries by `groupId`, ordered by `groupOrder` (then file path).
    2. The group's base name is the first member's name up to its " — " / " - ".
    3. A member's label is the text after its own " — " / " - ", else its name
       with the base name stripped from the front.
    4. If nothing can be derived the field stays unset and the UI shows the
       full name.

Idempotent. An existing `variantLabel` is kept unless --overwrite is given
(hand-set labels win). Reads and rewrites `skins/**/*.json` in place, keeping
each file's own formatting (indent 2, ASCII-escaped or not).

Usage:
    python3 scripts/backfill_variant_labels.py --dry-run
    python3 scripts/backfill_variant_labels.py
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SKINS_DIR = REPO_ROOT / "skins"

sys.path.insert(0, str(Path(__file__).resolve().parent))
from skin_schema import derive_variant_label, strip_variant_suffix  # noqa: E402


def load_entries(skins_dir: Path) -> list[tuple[Path, str, dict]]:
    out = []
    for path in sorted(skins_dir.rglob("*.json")):
        try:
            raw = path.read_text(encoding="utf-8")
            entry = json.loads(raw)
        except (OSError, ValueError):
            continue
        if isinstance(entry, dict):
            out.append((path, raw, entry))
    return out


def plan_labels(entries: list[tuple[Path, str, dict]], overwrite: bool = False) -> dict[Path, str]:
    """{path: label} for every grouped entry whose label should change."""
    groups: dict[str, list[tuple[Path, dict]]] = {}
    for path, _raw, entry in entries:
        gid = entry.get("groupId")
        if gid:
            groups.setdefault(gid, []).append((path, entry))

    plan: dict[Path, str] = {}
    for members in groups.values():
        members.sort(key=lambda m: (
            m[1].get("groupOrder") if m[1].get("groupOrder") is not None else float("inf"),
            str(m[0]),
        ))
        base_name = strip_variant_suffix(members[0][1].get("name") or "")
        for path, entry in members:
            if entry.get("variantLabel") and not overwrite:
                continue
            label = derive_variant_label(entry.get("name") or "", base_name)
            if label and label != entry.get("variantLabel"):
                plan[path] = label
    return plan


def with_label(entry: dict, label: str) -> dict:
    """`entry` with variantLabel placed right after groupOrder (or groupId)."""
    out: dict = {}
    placed = False
    for k, v in entry.items():
        if k == "variantLabel":
            continue
        out[k] = v
        if k == "groupOrder" or (k == "groupId" and "groupOrder" not in entry):
            out["variantLabel"] = label
            placed = True
    if not placed:
        out["variantLabel"] = label
    return out


def dump_like(raw: str, data: dict) -> str:
    """Serialize `data` the way `raw` was (ensure_ascii on or off)."""
    plain = json.dumps(data, indent=2, ensure_ascii=False) + "\n"
    ascii_ = json.dumps(data, indent=2) + "\n"
    if any(ord(c) > 127 for c in raw):
        return plain
    return ascii_


def backfill(skins_dir: Path, dry_run: bool = False, overwrite: bool = False) -> dict[str, int]:
    entries = load_entries(skins_dir)
    plan = plan_labels(entries, overwrite)
    by_path = {p: (raw, e) for p, raw, e in entries}
    grouped = sum(1 for _p, _r, e in entries if e.get("groupId"))
    if not dry_run:
        for path, label in plan.items():
            raw, entry = by_path[path]
            path.write_text(dump_like(raw, with_label(entry, label)), encoding="utf-8")
    kept = {p for p, _r, e in entries if e.get("groupId") and e.get("variantLabel")}
    return {
        "entries": len(entries),
        "grouped": grouped,
        "already_labeled": len(kept),
        "written": len(plan),
        "unlabeled": grouped - len(kept | set(plan)),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--skins-dir", type=Path, default=SKINS_DIR)
    ap.add_argument("--dry-run", action="store_true", help="Count what would change; write nothing")
    ap.add_argument("--overwrite", action="store_true", help="Replace labels that are already set")
    args = ap.parse_args()
    stats = backfill(args.skins_dir, args.dry_run, args.overwrite)
    verb = "Would label" if args.dry_run else "Labeled"
    print(f"{stats['entries']} entries, {stats['grouped']} grouped, {stats['already_labeled']} already labeled")
    print(f"{verb} {stats['written']}; {stats['unlabeled']} grouped entries have no derivable label (UI shows the full name)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
