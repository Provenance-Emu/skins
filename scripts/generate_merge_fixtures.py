#!/usr/bin/env python3
"""
generate_merge_fixtures.py — Write the merge test families in fixtures/merge/.

Each case is a tiny family of skins as folders (`members/<n>-<label>/info.json`
plus 2×2 PNGs), its catalog entries (`family.json`) and the outcome the merge
rules must give (`expected.json`, written by hand here, not computed by
merge_variants.py). tests/test_merge_variants.py zips each member and checks the
job against it; a JavaScript merge tool can read the same files.

Rules: SkinKit docs/specs/2026-11-03-skin-editing-tools-design.md §3.

`expected.json` holds the outcome with the default rules. A case whose outcome changes
under `--item-art-themes` (per-item art becomes theme art, SkinKit#78) also has an
`itemArtThemes` object: the same fields, for that flag. A case without one has the same
outcome either way.

Output is deterministic, so re-running changes nothing unless this script does.

Usage:
    python3 scripts/generate_merge_fixtures.py
"""

from __future__ import annotations

import copy
import hashlib
import json
import shutil
import struct
import zlib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
FIXTURES_DIR = REPO_ROOT / "fixtures" / "merge"
GBA = "com.rileytestut.delta.game.gba"
GBC = "com.rileytestut.delta.game.gbc"
MANIC_GBA = "public.aoshuang.game.gba"
IDENTIFIER = "com.provenance-emu.mergefixture"


def png(rgb: tuple[int, int, int]) -> bytes:
    """A 2×2 solid PNG."""
    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))
    rows = b"".join(b"\x00" + bytes(rgb) * 2 for _ in range(2))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 2, 2, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(rows, 9)) + chunk(b"IEND", b""))


def layout(background: str, a_x: int = 70, item_art: str | None = None) -> dict:
    items = [
        {"inputs": {"up": "up", "down": "down", "left": "left", "right": "right"},
         "frame": {"x": 10, "y": 120, "width": 40, "height": 40}},
        {"inputs": ["a"], "frame": {"x": a_x, "y": 130, "width": 20, "height": 20}},
        {"inputs": ["b"], "frame": {"x": 60, "y": 150, "width": 20, "height": 20}},
        {"inputs": ["menu"], "frame": {"x": 40, "y": 185, "width": 20, "height": 10}},
    ]
    if item_art:
        items[1]["asset"] = {"normal": item_art}
    return {
        "assets": {"resizable": background},
        "mappingSize": {"width": 100, "height": 200},
        "screens": [{"outputFrame": {"x": 0, "y": 0, "width": 100, "height": 100}}],
        "items": items,
    }


def skin(name: str, slug: str, gti: str, reps: dict) -> dict:
    return {"name": name, "identifier": f"{IDENTIFIER}.{slug}",
            "gameTypeIdentifier": gti, "representations": reps}


def iphone(edge: dict, standard: dict | None = None) -> dict:
    out = {"iphone": {"edgeToEdge": {"portrait": edge}}}
    if standard:
        out["iphone"]["standard"] = {"portrait": standard}
    return out


def member(label: str, info: dict, files: dict[str, bytes]) -> dict:
    return {"label": label, "info": info, "files": files}


RED, GREEN, BLUE, GREY = (200, 40, 40), (40, 160, 70), (40, 70, 200), (90, 90, 90)


def cases() -> dict[str, dict]:
    def colour(label, rgb, a_x=70, gti=GBA, extra=None):
        reps = iphone(layout("bg-edge.png", a_x), layout("bg-standard.png", a_x))
        info = skin(f"Merge Test — {label}", label.lower(), gti, reps)
        if extra:
            info.update(extra)
        return member(label, info, {"bg-edge.png": png(rgb), "bg-standard.png": png(tuple(c // 2 for c in rgb))})

    def manic(label, button_rgb, a_x=70, art="btn-a.png"):
        """A Manic skin whose A button has its own art; `art=None` leaves the button bare."""
        reps = iphone(layout("bg.png", a_x, item_art=art))
        files = {"bg.png": png(GREY)}
        if art:
            files[art] = png(button_rgb)
        return member(label, skin(f"Manic Merge — {label}", f"manic.{label.lower()}", MANIC_GBA, reps), files)

    with_ipad = colour("Green", GREEN)
    with_ipad["info"]["representations"]["ipad"] = {"standard": {"portrait": layout("bg-standard.png")}}

    return {
        "themes-three-colours": {
            "members": [colour("Blue", BLUE), colour("Red", RED), colour("Green", GREEN)],
            "expected": {
                "outcome": "themes",
                "name": "Merge Test (All variants)",
                "identifier": f"{IDENTIFIER}.blue.allinone",
                "themes": ["red", "green"],
                "files": ["bg-edge.png", "bg-standard.png",
                          "green__bg-edge.png", "green__bg-standard.png",
                          "red__bg-edge.png", "red__bg-standard.png"],
            },
        },
        "alt-two-layouts": {
            "members": [colour("Blue", BLUE), colour("Red", RED, a_x=50)],
            "expected": {
                "outcome": "alt",
                "reason": "`items` differs",
                "name": "Merge Test (All variants)",
                "files": ["alt__bg-edge.png", "alt__bg-standard.png", "bg-edge.png", "bg-standard.png"],
            },
        },
        "per-item-art-two": {
            "members": [manic("Blue", BLUE), manic("Red", RED)],
            "expected": {
                "outcome": "alt",
                "reason": "per-item art differs",
                "name": "Manic Merge (All variants)",
                "files": ["alt__bg.png", "alt__btn-a.png", "bg.png", "btn-a.png"],
            },
            "itemArtThemes": {
                "outcome": "themes",
                "name": "Manic Merge (All variants)",
                "themes": ["red"],
                "files": ["bg.png", "btn-a.png", "red__bg.png", "red__btn-a.png"],
                "items": {"red": {"iphone/edgeToEdge/portrait": {"1": "red__btn-a.png"}}},
            },
        },
        "per-item-art-three": {
            "members": [manic("Blue", BLUE), manic("Red", RED), manic("Green", GREEN)],
            "expected": {"outcome": "split", "reason": "per-item art differs"},
            "itemArtThemes": {
                "outcome": "themes",
                "name": "Manic Merge (All variants)",
                "themes": ["red", "green"],
                "files": ["bg.png", "btn-a.png", "green__bg.png", "green__btn-a.png",
                          "red__bg.png", "red__btn-a.png"],
                "items": {"red": {"iphone/edgeToEdge/portrait": {"1": "red__btn-a.png"}},
                          "green": {"iphone/edgeToEdge/portrait": {"1": "green__btn-a.png"}}},
            },
        },
        # The art files have different names in each member: a theme still swaps them.
        "per-item-art-renamed": {
            "members": [manic("Blue", BLUE), manic("Red", RED, art="red-a.png")],
            "expected": {"outcome": "alt", "reason": "`items` differs", "name": "Manic Merge (All variants)",
                         "files": ["alt__bg.png", "alt__red-a.png", "bg.png", "btn-a.png"]},
            "itemArtThemes": {
                "outcome": "themes",
                "name": "Manic Merge (All variants)",
                "themes": ["red"],
                "files": ["bg.png", "btn-a.png", "red__bg.png", "red__red-a.png"],
                "items": {"red": {"iphone/edgeToEdge/portrait": {"1": "red__red-a.png"}}},
            },
        },
        # Green draws the base's own art, so its theme names no item art; Red's does.
        "per-item-art-partial": {
            "members": [manic("Blue", BLUE), manic("Red", RED), manic("Green", BLUE)],
            "expected": {"outcome": "split", "reason": "per-item art differs"},
            "itemArtThemes": {
                "outcome": "themes",
                "name": "Manic Merge (All variants)",
                "themes": ["red", "green"],
                "files": ["bg.png", "btn-a.png", "green__bg.png", "red__bg.png", "red__btn-a.png"],
                "items": {"red": {"iphone/edgeToEdge/portrait": {"1": "red__btn-a.png"}}, "green": {}},
            },
        },
        # A theme can replace an item's art but not remove it, so this stays an alt.
        "per-item-art-removed": {
            "members": [manic("Blue", BLUE), manic("Red", RED, art=None)],
            "expected": {"outcome": "alt", "reason": "`items` differs", "name": "Manic Merge (All variants)",
                         "files": ["alt__bg.png", "bg.png", "btn-a.png"]},
            "itemArtThemes": {
                "outcome": "alt",
                "reason": "has no art, where the base draws btn-a.png",
                "name": "Manic Merge (All variants)",
                "files": ["alt__bg.png", "bg.png", "btn-a.png"],
            },
        },
        "mixed-game-types": {
            "members": [colour("Blue", BLUE), colour("Red", RED, gti=GBC)],
            "expected": {"outcome": "split", "reason": "2 game types"},
        },
        "base-missing-layout": {
            "members": [colour("Blue", BLUE), with_ipad],
            "expected": {"outcome": "split", "reason": "the base lacks ipad/standard/portrait"},
        },
        "member-carries-themes": {
            "members": [colour("Blue", BLUE), colour("Red", RED, extra={
                "themes": [{"id": "x", "name": "X", "assets": {}}]})],
            "expected": {"outcome": "split", "reason": "already carries themes"},
        },
    }


def main():
    if FIXTURES_DIR.exists():
        shutil.rmtree(FIXTURES_DIR)
    for case, spec in cases().items():
        root = FIXTURES_DIR / case
        group = f"merge-fixture:{case}"
        family = []
        for order, m in enumerate(spec["members"], 1):
            folder = f"{order}-{m['label'].lower()}"
            out = root / "members" / folder
            out.mkdir(parents=True)
            (out / "info.json").write_text(json.dumps(m["info"], indent=2, ensure_ascii=False) + "\n")
            for name, data in sorted(m["files"].items()):
                (out / name).write_bytes(data)
            family.append({
                "folder": folder,
                "entry": {
                    "id": f"{order:02x}" + hashlib.sha256(case.encode()).hexdigest()[:14],
                    "name": m["info"]["name"],
                    "author": "Provenance Emu",
                    "systems": ["gba"],
                    "source": "provenance-emu",
                    "gameTypeIdentifier": m["info"]["gameTypeIdentifier"],
                    "downloadURL": f"https://example.invalid/{case}/{folder}.deltaskin",
                    "groupId": group,
                    "groupOrder": order,
                    "variantLabel": m["label"],
                },
            })
        (root / "family.json").write_text(json.dumps({"groupId": group, "members": family}, indent=2,
                                                     ensure_ascii=False) + "\n")
        expected = copy.deepcopy(spec["expected"])
        if "itemArtThemes" in spec:
            expected["itemArtThemes"] = copy.deepcopy(spec["itemArtThemes"])
        (root / "expected.json").write_text(json.dumps(expected, indent=2, ensure_ascii=False) + "\n")
        print(f"{case}: {len(family)} members")


if __name__ == "__main__":
    main()
