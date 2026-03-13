#!/usr/bin/env python3
"""
skin_schema.py — Shared schema, system map, and ID generation for the skin catalog.
"""

import hashlib
import re
from typing import Optional

CATALOG_VERSION = 2

# Map from various name forms → (short_code, gameTypeIdentifier)
SYSTEM_MAP = {
    "gba":                          ("gba",      "com.rileytestut.delta.game.gba"),
    "game boy advance":             ("gba",      "com.rileytestut.delta.game.gba"),
    "gbc":                          ("gbc",      "com.rileytestut.delta.game.gbc"),
    "game boy color":               ("gbc",      "com.rileytestut.delta.game.gbc"),
    "game boy colour":              ("gbc",      "com.rileytestut.delta.game.gbc"),
    "game boy":                     ("gbc",      "com.rileytestut.delta.game.gbc"),
    "gb":                           ("gbc",      "com.rileytestut.delta.game.gbc"),
    "nes":                          ("nes",      "com.rileytestut.delta.game.nes"),
    "nintendo entertainment system": ("nes",     "com.rileytestut.delta.game.nes"),
    "snes":                         ("snes",     "com.rileytestut.delta.game.snes"),
    "super nintendo":               ("snes",     "com.rileytestut.delta.game.snes"),
    "super famicom":                ("snes",     "com.rileytestut.delta.game.snes"),
    "n64":                          ("n64",      "com.rileytestut.delta.game.n64"),
    "nintendo 64":                  ("n64",      "com.rileytestut.delta.game.n64"),
    "nds":                          ("nds",      "com.rileytestut.delta.game.ds"),
    "nintendo ds":                  ("nds",      "com.rileytestut.delta.game.ds"),
    "ds":                           ("nds",      "com.rileytestut.delta.game.ds"),
    "genesis":                      ("genesis",  "com.rileytestut.delta.game.genesis"),
    "sega genesis":                 ("genesis",  "com.rileytestut.delta.game.genesis"),
    "mega drive":                   ("genesis",  "com.rileytestut.delta.game.genesis"),
    "unofficial":                   ("unofficial", None),
}

# Reverse map: gameTypeIdentifier → short_code
GTI_TO_CODE = {v[1]: v[0] for v in SYSTEM_MAP.values() if v[1]}

REQUIRED_FIELDS = {"id", "name", "systems", "downloadURL", "source"}
VALID_SYSTEM_CODES = {v[0] for v in SYSTEM_MAP.values()}


def make_id(source: str, download_url: str) -> str:
    """Generate a stable 16-char hex ID from source + downloadURL."""
    return hashlib.sha256(f"{source}:{download_url}".encode()).hexdigest()[:16]


def slugify(name: str) -> str:
    """Convert skin name to a safe filename slug."""
    s = name.lower()
    s = re.sub(r"[^\w\s-]", "", s)
    s = re.sub(r"[\s_-]+", "-", s)
    return s.strip("-")[:64]


def system_from_gti(gti: str) -> Optional[str]:
    """Map a gameTypeIdentifier to a short system code."""
    return GTI_TO_CODE.get(gti)


def system_from_name(name: str) -> Optional[str]:
    """Fuzzy-match a system name to a short code."""
    key = name.lower().strip()
    if key in SYSTEM_MAP:
        return SYSTEM_MAP[key][0]
    for k, v in SYSTEM_MAP.items():
        if k in key or key in k:
            return v[0]
    return None


def normalize_entry(entry: dict) -> dict:
    """Fill in defaults for optional fields."""
    defaults = {
        "author": None,
        "gameTypeIdentifier": None,
        "version": None,
        "thumbnailURL": None,
        "screenshotURLs": [],
        "tags": [],
        "deviceSupport": [],
        "downloadCount": None,
        "rating": None,
        "lastUpdated": None,
        "fileSize": None,
        "submittedBy": None,
        "submittedAt": None,
    }
    return {**defaults, **entry}


def validate_entry(entry: dict, catalog_ids: set = None) -> list[str]:
    """
    Validate a skin entry dict. Returns list of error strings (empty = valid).
    """
    errors = []

    for f in REQUIRED_FIELDS:
        if f not in entry or not entry[f]:
            errors.append(f"Missing required field: {f}")

    if "id" in entry:
        if not re.fullmatch(r"[0-9a-f]{16}", entry["id"]):
            errors.append(f"id must be exactly 16 lowercase hex chars, got: {entry['id']!r}")
        if catalog_ids and entry["id"] in catalog_ids:
            errors.append(f"Duplicate id: {entry['id']}")

    if "systems" in entry:
        if not isinstance(entry["systems"], list) or not entry["systems"]:
            errors.append("systems must be a non-empty array")
        else:
            for s in entry["systems"]:
                if s not in VALID_SYSTEM_CODES:
                    errors.append(f"Unknown system code: {s!r}. Valid: {sorted(VALID_SYSTEM_CODES)}")

    if "downloadURL" in entry and entry["downloadURL"]:
        url = entry["downloadURL"]
        if not url.startswith(("http://", "https://")):
            errors.append(f"downloadURL must be http(s): {url!r}")
        if not any(url.endswith(ext) for ext in (".deltaskin", ".manicskin", ".zip")):
            errors.append(f"downloadURL should end in .deltaskin or .manicskin: {url!r}")

    return errors
