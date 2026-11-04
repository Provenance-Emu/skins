#!/usr/bin/env python3
"""
skin_schema.py — Shared schema, system map, and ID generation for the skin catalog.
"""

import datetime
import hashlib
import re
from typing import Optional

from creator_policy import (
    BIO_MAX, DISPLAY_NAME_MAX, LINK_LABEL_MAX, MAX_LINKS, SLUG_MAX, SLUG_RE,
    bio_problem, url_problem,
)

CATALOG_VERSION = 3  # 3: optional `variantLabel` (and `variants`, see variants_sidecar.py)

# ---------------------------------------------------------------------------
# System map: name form → (short_code, primary_gameTypeIdentifier)
#
# short_code matches DeltaSkinGameType raw values from the Provenance app.
# primary_gameTypeIdentifier is the Delta (com.rileytestut.delta.game.*) or
# Manic (public.aoshuang.game.*) identifier used inside info.json files.
# ---------------------------------------------------------------------------

SYSTEM_MAP = {
    # Nintendo handhelds
    "gb":                               ("gb",              "com.rileytestut.delta.game.gbc"),
    "game boy":                         ("gb",              "com.rileytestut.delta.game.gbc"),
    "gbc":                              ("gbc",             "com.rileytestut.delta.game.gbc"),
    "game boy color":                   ("gbc",             "com.rileytestut.delta.game.gbc"),
    "game boy colour":                  ("gbc",             "com.rileytestut.delta.game.gbc"),
    "gba":                              ("gba",             "com.rileytestut.delta.game.gba"),
    "game boy advance":                 ("gba",             "com.rileytestut.delta.game.gba"),

    # Nintendo consoles
    "nes":                              ("nes",             "com.rileytestut.delta.game.nes"),
    "fds":                              ("nes",             "com.rileytestut.delta.game.nes"),
    "famicom":                          ("nes",             "com.rileytestut.delta.game.nes"),
    "nintendo entertainment system":    ("nes",             "com.rileytestut.delta.game.nes"),
    "snes":                             ("snes",            "com.rileytestut.delta.game.snes"),
    "super nintendo":                   ("snes",            "com.rileytestut.delta.game.snes"),
    "super famicom":                    ("snes",            "com.rileytestut.delta.game.snes"),
    "n64":                              ("n64",             "com.rileytestut.delta.game.n64"),
    "nintendo 64":                      ("n64",             "com.rileytestut.delta.game.n64"),
    "nds":                              ("nds",             "com.rileytestut.delta.game.ds"),
    "ds":                               ("nds",             "com.rileytestut.delta.game.ds"),
    "nintendo ds":                      ("nds",             "com.rileytestut.delta.game.ds"),
    "virtualboy":                       ("virtualBoy",      "public.aoshuang.game.vb"),
    "virtual boy":                      ("virtualBoy",      "public.aoshuang.game.vb"),
    "3ds":                              ("threeDS",         "public.aoshuang.game.3ds"),
    "nintendo 3ds":                     ("threeDS",         "public.aoshuang.game.3ds"),
    "gamecube":                         ("gamecube",        "public.aoshuang.game.ngc"),
    "game cube":                        ("gamecube",        "public.aoshuang.game.ngc"),
    "nintendo gamecube":                ("gamecube",        "public.aoshuang.game.ngc"),
    "ngc":                              ("gamecube",        "public.aoshuang.game.ngc"),
    "wii":                              ("wii",             "public.aoshuang.game.wii"),
    "pokemonmini":                      ("pokemonMini",     "public.aoshuang.game.pm"),
    "pokemon mini":                     ("pokemonMini",     "public.aoshuang.game.pm"),

    # Sega
    "genesis":                          ("genesis",         "com.rileytestut.delta.game.genesis"),
    "sega genesis":                     ("genesis",         "com.rileytestut.delta.game.genesis"),
    "mega drive":                       ("genesis",         "com.rileytestut.delta.game.genesis"),
    "md":                               ("genesis",         "com.rileytestut.delta.game.genesis"),
    "gamegear":                         ("gamegear",        "com.rileytestut.delta.game.gg"),
    "game gear":                        ("gamegear",        "com.rileytestut.delta.game.gg"),
    "sega game gear":                   ("gamegear",        "com.rileytestut.delta.game.gg"),
    "ms":                               ("masterSystem",    "com.rileytestut.delta.game.ms"),
    "mastersystem":                     ("masterSystem",    "com.rileytestut.delta.game.ms"),
    "master system":                    ("masterSystem",    "com.rileytestut.delta.game.ms"),
    "sega master system":               ("masterSystem",    "com.rileytestut.delta.game.ms"),
    "sg1000":                           ("sg1000",          "public.aoshuang.game.sg1000"),
    "sega sg-1000":                     ("sg1000",          "public.aoshuang.game.sg1000"),
    "segacd":                           ("segaCD",          "public.aoshuang.game.mcd"),
    "sega cd":                          ("segaCD",          "public.aoshuang.game.mcd"),
    "mega cd":                          ("segaCD",          "public.aoshuang.game.mcd"),
    "32x":                              ("sega32X",         "public.aoshuang.game.32x"),
    "sega 32x":                         ("sega32X",         "public.aoshuang.game.32x"),
    "saturn":                           ("saturn",          "public.aoshuang.game.ss"),
    "sega saturn":                      ("saturn",          "public.aoshuang.game.ss"),
    "dreamcast":                        ("dreamcast",       "public.aoshuang.game.dc"),
    "sega dreamcast":                   ("dreamcast",       "public.aoshuang.game.dc"),

    # Sony
    "psx":                              ("psx",             "com.rileytestut.delta.game.psx"),
    "ps1":                              ("psx",             "com.rileytestut.delta.game.psx"),
    "ps2":                              ("psx",             "com.rileytestut.delta.game.psx"),
    "ps3":                              ("psx",             "com.rileytestut.delta.game.psx"),
    "playstation":                      ("psx",             "com.rileytestut.delta.game.psx"),
    "psp":                              ("psp",             "public.aoshuang.game.psp"),
    "playstation portable":             ("psp",             "public.aoshuang.game.psp"),

    # NEC
    "pce":                              ("pce",             None),
    "pc engine":                        ("pce",             None),
    "turbografx":                       ("pce",             None),
    "turbografx-16":                    ("pce",             None),
    "pcecd":                            ("pcecd",           None),
    "pc engine cd":                     ("pcecd",           None),
    "turbografx-cd":                    ("pcecd",           None),
    "pcfx":                             ("pcfx",            None),
    "pc-fx":                            ("pcfx",            None),
    "sgfx":                             ("sgfx",            None),
    "supergrafx":                       ("sgfx",            None),

    # Atari
    "atari2600":                        ("atari2600",       None),
    "atari 2600":                       ("atari2600",       None),
    "atari5200":                        ("atari5200",       None),
    "atari 5200":                       ("atari5200",       None),
    "atari7800":                        ("atari7800",       None),
    "atari 7800":                       ("atari7800",       None),
    "jaguar":                           ("jaguar",          None),
    "atari jaguar":                     ("jaguar",          None),
    "jaguarcd":                         ("jaguarcd",        None),
    "atari jaguar cd":                  ("jaguarcd",        None),
    "lynx":                             ("lynx",            None),
    "atari lynx":                       ("lynx",            None),
    "atari8bit":                        ("atari8bit",       None),
    "atari 8-bit":                      ("atari8bit",       None),
    "atarist":                          ("atarist",         None),
    "atari st":                         ("atarist",         None),

    # SNK
    "neogeo":                           ("neogeo",          None),
    "neo geo":                          ("neogeo",          None),
    "ngp":                              ("ngp",             None),
    "neo geo pocket":                   ("ngp",             None),
    "ngpc":                             ("ngpc",            None),
    "neo geo pocket color":             ("ngpc",            None),

    # Bandai
    "wonderswan":                       ("wonderswan",      None),
    "wonder swan":                      ("wonderswan",      None),
    "wonderswancolor":                  ("wonderswancolor", None),
    "wonderswan color":                 ("wonderswancolor", None),

    # Vectrex
    "vectrex":                          ("vectrex",         None),

    # Misc classics
    "3do":                              ("_3do",            None),
    "appleii":                          ("appleII",         None),
    "apple ii":                         ("appleII",         None),
    "c64":                              ("c64",             None),
    "commodore 64":                     ("c64",             None),
    "cdi":                              ("cdi",             None),
    "cd-i":                             ("cdi",             None),
    "colecovision":                     ("colecovision",    None),
    "cps1":                             ("cps1",            None),
    "cps2":                             ("cps2",            None),
    "cps3":                             ("cps3",            None),
    "doom":                             ("doom",            None),
    "dos":                              ("dos",             None),
    "ep128":                            ("ep128",           None),
    "enterprise 128":                   ("ep128",           None),
    "intellivision":                    ("intellivision",   None),
    "macintosh":                        ("macintosh",       None),
    "arcade":                           ("mame",            "public.aoshuang.game.mame"),
    "mame":                             ("mame",            "public.aoshuang.game.mame"),
    "megaduck":                         ("megaduck",        None),
    "mega duck":                        ("megaduck",        None),
    "msx":                              ("msx",             None),
    "msx2":                             ("msx2",            None),
    "odyssey2":                         ("odyssey2",        None),
    "odyssey 2":                        ("odyssey2",        None),
    "quake":                            ("quake",           None),
    "quake2":                           ("quake2",          None),
    "supervision":                      ("supervision",     None),
    "tic80":                            ("tic80",           None),
    "tic-80":                           ("tic80",           None),
    "wolf3d":                           ("wolf3d",          None),
    "wolfenstein 3d":                   ("wolf3d",          None),
    "zxspectrum":                       ("zxspectrum",      None),
    "zx spectrum":                      ("zxspectrum",      None),
    "retroarch":                        ("retroarch",       None),

    # Fallback
    "unofficial":                       ("unofficial",      None),
}

# Reverse map: gameTypeIdentifier → short_code
# When multiple codes share the same GTI (e.g. "gb" and "gbc" both map to
# com.rileytestut.delta.game.gbc), prefer the more specific (longer) code.
GTI_TO_CODE: dict[str, str] = {}
for _v in SYSTEM_MAP.values():
    if _v[1]:
        existing = GTI_TO_CODE.get(_v[1])
        if existing is None or len(_v[0]) > len(existing):
            GTI_TO_CODE[_v[1]] = _v[0]

# Also map Manic variants not in SYSTEM_MAP values
_MANIC_EXTRA = {
    # Core Manic/Provenance GTI identifiers (confirmed from DeltaSkinTypes.swift)
    "public.aoshuang.game.gbc": "gbc",
    "public.aoshuang.game.gba": "gba",
    "public.aoshuang.game.nes": "nes",
    "public.aoshuang.game.snes": "snes",
    "public.aoshuang.game.n64": "n64",
    "public.aoshuang.game.ds": "nds",
    "public.aoshuang.game.md": "genesis",
    "public.aoshuang.game.gg": "gamegear",
    "public.aoshuang.game.ms": "masterSystem",
    "public.aoshuang.game.ps1": "psx",
    "public.aoshuang.game.psp": "psp",
    "public.aoshuang.game.ss": "saturn",
    "public.aoshuang.game.dc": "dreamcast",
    "public.aoshuang.game.mcd": "segaCD",
    "public.aoshuang.game.32x": "sega32X",
    "public.aoshuang.game.sg1000": "sg1000",
    "public.aoshuang.game.vb": "virtualBoy",
    "public.aoshuang.game.3ds": "threeDS",
    "public.aoshuang.game.pm": "pokemonMini",
    "public.aoshuang.game.ngc": "gamecube",
    "public.aoshuang.game.gc": "gamecube",  # legacy alias; Manic's canonical GTI is .ngc
    "public.aoshuang.game.wii": "wii",
    # Extended Provenance-supported systems — GTI strings recognized by DeltaSkinTypes.swift
    # even though the gameTypeIdentifier property returns nil for these (newer additions).
    # Skin creators use these as gameTypeIdentifier in info.json.
    "public.aoshuang.game.pce": "pce",
    "public.aoshuang.game.pcecd": "pcecd",
    "public.aoshuang.game.pcfx": "pcfx",
    "public.aoshuang.game.sgfx": "sgfx",
    "public.aoshuang.game.2600": "atari2600",
    "public.aoshuang.game.5200": "atari5200",
    "public.aoshuang.game.7800": "atari7800",
    "public.aoshuang.game.jaguar": "jaguar",
    "public.aoshuang.game.jaguarcd": "jaguarcd",
    "public.aoshuang.game.lynx": "lynx",
    "public.aoshuang.game.atari8bit": "atari8bit",
    "public.aoshuang.game.atarist": "atarist",
    "public.aoshuang.game.neogeo": "neogeo",
    "public.aoshuang.game.ngp": "ngp",
    "public.aoshuang.game.ngpc": "ngpc",
    "public.aoshuang.game.ws": "wonderswan",
    "public.aoshuang.game.wsc": "wonderswancolor",
    "public.aoshuang.game.vectrex": "vectrex",
    "public.aoshuang.game.colecovision": "colecovision",
    "public.aoshuang.game.intellivision": "intellivision",
    "public.aoshuang.game.3do": "_3do",
    "public.aoshuang.game.c64": "c64",
    "public.aoshuang.game.cdi": "cdi",
    "public.aoshuang.game.mame": "mame",
    # Canonical identifiers defined by Manic-EMU/ManicEMU (Sources/Tools/Cores/*.swift)
    # that real skins declare; some of our guesses above (e.g. .mame, .gc) are not
    # in Manic at all, so keep both spellings routable.
    "public.aoshuang.game.arcade": "mame",
    "public.aoshuang.game.gb": "gb",
    "public.aoshuang.game.fds": "nes",
    "public.aoshuang.game.dos": "dos",
    "public.aoshuang.game.doom": "doom",
    "public.aoshuang.game.turbografx_16": "pce",
    "public.aoshuang.game.turbografx_cd": "pcecd",
    "public.aoshuang.game.supergrafx": "sgfx",
    "public.aoshuang.game.msx": "msx",
    "public.aoshuang.game.msx2": "msx2",
}
GTI_TO_CODE.update({k: v for k, v in _MANIC_EXTRA.items() if k not in GTI_TO_CODE})

REQUIRED_FIELDS = {"id", "name", "systems", "downloadURL", "source"}

# Tags are free-form (`portrait`, `animated`, ...) except this one, which the
# website and the apps act on: mature skins are hidden unless the viewer opts in.
# scripts/content_policy.py sets it from scripts/mature_keywords.json; it can
# also be added to or removed from a skin's JSON by hand.
MATURE_TAG = "mature"
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


_NON_PROVENANCE_SYSTEMS = {
    "playstation 5", "ps5", "playstation 4", "ps4",
    "xbox", "xbox one", "xbox 360", "xbox series x", "xbox series s",
    "switch", "nintendo switch",
}


def system_from_name(name: str) -> Optional[str]:
    """Fuzzy-match a system name to a short code."""
    key = name.lower().strip()
    if key in _NON_PROVENANCE_SYSTEMS:
        return None
    if key in SYSTEM_MAP:
        return SYSTEM_MAP[key][0]
    for k, v in SYSTEM_MAP.items():
        if k in key or key in k:
            return v[0]
    return None


# Whole-token short codes used in filenames (e.g. `BelmonT_TacoMS_Dark.manicskin`).
# Conservative: only unambiguous abbreviations that map cleanly to a catalog
# system. Loose substring matching would mis-route game-name variants
# (e.g. "jp-doom" is a Jaguar skin, not a "doom" system).
_TOKEN_TO_SYSTEM = {
    "nes": "nes",
    "snes": "snes",
    "gba": "gba",
    "gbc": "gbc",
    "n64": "n64",
    "nds": "nds",
    "ds": "nds",
    "3ds": "threeDS",
    "psx": "psx",
    "ps1": "psx",
    "psp": "psp",
    "md": "genesis",
    "genesis": "genesis",
    "32x": "sega32X",
    "sega32x": "sega32X",
    "cd": "genesis",  # Sega CD packs commonly catalogued under genesis
    "dc": "dreamcast",
    "dreamcast": "dreamcast",
    "ss": "saturn",
    "saturn": "saturn",
    "gg": "gamegear",
    "gamegear": "gamegear",
    "ms": "masterSystem",
    "mastersystem": "masterSystem",
    "sg1000": "sg1000",
    "jaguar": "jaguar",
    "lynx": "lynx",
    "mame": "mame",
    "ngc": "gamecube",
    "gamecube": "gamecube",
    "wii": "wii",
    "vb": "virtualBoy",
    "virtualboy": "virtualBoy",
    "pce": "pce",
}


def system_from_token(label: str) -> Optional[str]:
    """Return a system code if any whitespace/dash/underscore-delimited token in
    `label` matches a curated short-code table. Used to route bundle variants
    whose filenames embed their target system (e.g. `BelmonT_TacoGBA.deltaskin`).
    Returns None when no strong match — caller should fall back to the umbrella's
    declared system.
    """
    for tok in re.split(r"[\s\-_]+", label.lower()):
        code = _TOKEN_TO_SYSTEM.get(tok)
        if code:
            return code
    return None


# ---------------------------------------------------------------------------
# Variant labels
#
# `variantLabel` is a variant's own name inside its group ("Doom" for
# "Atari Jaguar Paw — Doom"). The functions below are a line-for-line port of
# the website's `stripVariantSuffix()` / `variantLabel()` (docs/js/browse.js),
# so the backfill stores what the site already shows.
# ---------------------------------------------------------------------------

VARIANT_SEPARATORS = (" — ", " - ")
MAX_VARIANT_LABEL_LENGTH = 120


def strip_variant_suffix(full_name: str) -> str:
    """The name before the first " — " / " - " separator, else the whole name."""
    if not full_name:
        return full_name
    for sep in VARIANT_SEPARATORS:
        i = full_name.find(sep)
        if i > 0:
            return full_name[:i].strip()
    return full_name


def fit_variant_label(label: Optional[str]) -> Optional[str]:
    """Trim `label` and cut it to MAX_VARIANT_LABEL_LENGTH; None if nothing is left."""
    label = (label or "").strip()[:MAX_VARIANT_LABEL_LENGTH].strip()
    return label or None


def derive_variant_label(full_name: str, base_name: str = "") -> Optional[str]:
    """A variant's label within its group, or None when nothing can be derived.

    Takes the text after the first " — " / " - " separator. Without one, strips
    `base_name` (the group's name) from the front of `full_name`, case
    insensitively. None means the UI should show the full name: no separator,
    the name doesn't start with the group name, or stripping it leaves nothing.
    """
    if not full_name:
        return None
    for sep in VARIANT_SEPARATORS:
        i = full_name.find(sep)
        if i > 0:
            return full_name[i + len(sep):].strip() or None
    if base_name and full_name.lower().startswith(base_name.lower()):
        rest = re.sub(r"^[\s\-—:]+", "", full_name[len(base_name):]).strip()
        return rest or None
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
        # Sibling-variant clustering: entries sharing the same `groupId` are
        # variants of one umbrella release (e.g. a Delta Styles bundle). The
        # website collapses them into a single card; `catalog.json` stays flat.
        # `groupOrder` (1-based) preserves the source's own variant ordering.
        "groupId": None,
        "groupOrder": None,
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

    if "tags" in entry and entry["tags"] is not None:
        tags = entry["tags"]
        if not isinstance(tags, list) or not all(isinstance(t, str) and t.strip() for t in tags):
            errors.append("tags must be an array of non-empty strings")
        elif MATURE_TAG in tags and tags.count(MATURE_TAG) > 1:
            errors.append(f"tag {MATURE_TAG!r} listed more than once")

    if "downloadURL" in entry and entry["downloadURL"]:
        url = entry["downloadURL"]
        if not url.startswith(("http://", "https://")):
            errors.append(f"downloadURL must be http(s): {url!r}")
        # Allow direct file URLs, plus Google Drive `uc?export=download`, which
        # 303-redirects to the binary. Store pages (Gumroad) and deltastyles
        # landing pages serve HTML, so the app cannot install from them.
        TRUSTED_INDIRECT_HOSTS = (
            "drive.google.com/uc",
        )
        is_trusted_indirect = any(h in url for h in TRUSTED_INDIRECT_HOSTS)
        if not is_trusted_indirect and not any(url.endswith(ext) for ext in (".deltaskin", ".manicskin", ".zip")):
            errors.append(f"downloadURL should end in .deltaskin or .manicskin: {url!r}")

    creator = entry.get("creator")
    if creator is not None and not (isinstance(creator, str) and SLUG_RE.fullmatch(creator)):
        errors.append(f"creator must be a creator slug ([a-z0-9-], max {SLUG_MAX} chars), got: {creator!r}")

    errors.extend(validate_variant_label(entry))
    if "variants" in entry:
        errors.extend(validate_variants(entry["variants"]))

    return errors


VARIANT_KINDS = ("alt", "theme", "game")


def validate_variants(variants) -> list[str]:
    """`variants` (single-file skins; generated, see variants_sidecar.py) is a
    non-empty list of {kind: alt|theme|game, key, label}, unique per
    (kind, key). `alt` has the key "alt" and appears at most once."""
    if not isinstance(variants, list) or not variants:
        return ["variants must be a non-empty array"]
    errors, seen = [], set()
    for i, v in enumerate(variants):
        where = f"variants[{i}]"
        if not isinstance(v, dict):
            errors.append(f"{where} must be an object")
            continue
        kind, key, label = v.get("kind"), v.get("key"), v.get("label")
        if kind not in VARIANT_KINDS:
            errors.append(f"{where}.kind must be one of {list(VARIANT_KINDS)}, got {kind!r}")
        for field, value in (("key", key), ("label", label)):
            if not isinstance(value, str) or not value.strip():
                errors.append(f"{where}.{field} must be a non-empty string")
        if kind == "alt" and key != "alt":
            errors.append(f'{where}: an alt variant\'s key must be "alt"')
        if (kind, key) in seen:
            errors.append(f"{where}: duplicate {kind} variant {key!r}")
        seen.add((kind, key))
    return errors


def validate_variant_label(entry: dict) -> list[str]:
    """`variantLabel` is optional (None counts as unset). When set it is a
    trimmed, non-empty string on an entry that has a `groupId`."""
    label = entry.get("variantLabel")
    if label is None:
        return []
    if not isinstance(label, str):
        return [f"variantLabel must be a string, got {type(label).__name__}"]
    errors = []
    if not label.strip():
        errors.append("variantLabel must not be empty")
    elif label != label.strip():
        errors.append(f"variantLabel has leading or trailing whitespace: {label!r}")
    elif len(label) > MAX_VARIANT_LABEL_LENGTH:
        errors.append(f"variantLabel longer than {MAX_VARIANT_LABEL_LENGTH} chars: {label[:40]!r}...")
    if not entry.get("groupId"):
        errors.append("variantLabel requires groupId")
    return errors


# ---------------------------------------------------------------------------
# Creator profiles: creators/<slug>.json
# Design: SkinKit docs/specs/2026-11-03-creator-profiles-design.md §1
# ---------------------------------------------------------------------------

# `socials` holds handles, never URLs. Each key maps to (handle pattern, URL
# template). The site and the apps build links from this table, so a profile
# cannot smuggle an arbitrary link in as a social icon. A None template means
# the service has no profile URL for a handle (Discord): show the handle as text.
_DOMAIN = r"(?:[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.)+[A-Za-z][A-Za-z0-9-]{0,61}[A-Za-z0-9]"
SOCIAL_HANDLES = {
    "github": (r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})", "https://github.com/{handle}"),
    "discord": (r"[A-Za-z0-9_.]{2,32}", None),
    "x": (r"[A-Za-z0-9_]{1,15}", "https://x.com/{handle}"),
    "bluesky": (_DOMAIN, "https://bsky.app/profile/{handle}"),
    "mastodon": (r"[A-Za-z0-9_]{1,30}@" + _DOMAIN, "https://{host}/@{user}"),
    "instagram": (r"[A-Za-z0-9_.]{1,30}", "https://www.instagram.com/{handle}"),
    "youtube": (r"[A-Za-z0-9_.-]{3,30}", "https://www.youtube.com/@{handle}"),
    "twitch": (r"[A-Za-z0-9_]{4,25}", "https://www.twitch.tv/{handle}"),
    "tiktok": (r"[A-Za-z0-9_.]{2,24}", "https://www.tiktok.com/@{handle}"),
    "kofi": (r"[A-Za-z0-9_]{1,40}", "https://ko-fi.com/{handle}"),
    "patreon": (r"[A-Za-z0-9_-]{1,40}", "https://www.patreon.com/{handle}"),
    "buymeacoffee": (r"[A-Za-z0-9_-]{1,40}", "https://buymeacoffee.com/{handle}"),
    # The crawler only ever sees `/user/<name>` links on deltastyles.com; the
    # profile URL shape itself is unverified (design, "What exists today").
    "deltastyles": (r"[A-Za-z0-9_.-]{1,40}", "https://deltastyles.com/user/{handle}"),
    "reddit": (r"[A-Za-z0-9_-]{3,20}", "https://www.reddit.com/user/{handle}"),
}
SOCIAL_KEYS = tuple(SOCIAL_HANDLES)

CLAIM_METHODS = ("source", "file", "manual")
_GITHUB_LOGIN_RE = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})")
CREATOR_FIELDS = {
    "slug", "displayName", "aliases", "githubLogin", "bio", "avatarURL",
    "bannerURL", "links", "socials", "claim", "hidden",
}
CREATOR_REQUIRED_FIELDS = ("slug", "displayName", "aliases", "githubLogin")


def social_url(key: str, handle: str) -> Optional[str]:
    """Profile URL for a social handle, or None (unknown key, bad handle, or no URL form)."""
    spec = SOCIAL_HANDLES.get(key)
    if spec is None or not isinstance(handle, str) or not re.fullmatch(spec[0], handle):
        return None
    template = spec[1]
    if template is None:
        return None
    if key == "mastodon":
        user, host = handle.split("@", 1)
        return template.format(user=user, host=host.lower())
    return template.format(handle=handle)


def validate_creator(obj, filename_slug: Optional[str] = None) -> list[str]:
    """
    Validate a creators/<slug>.json object. Returns error strings (empty = valid).
    `filename_slug` is the file's name without `.json`; it must equal `slug`.
    Cross-file rules (duplicate aliases, case-colliding slugs) live in
    creator_directory.validate_creators.
    """
    if not isinstance(obj, dict):
        return ["creator file must be a JSON object"]
    errors = []

    for f in CREATOR_REQUIRED_FIELDS:
        if f not in obj or obj[f] in (None, "", []):
            errors.append(f"Missing required field: {f}")
    for f in sorted(set(obj) - CREATOR_FIELDS):
        errors.append(f"Unknown field: {f}")

    slug = obj.get("slug")
    if slug not in (None, ""):
        if not isinstance(slug, str) or not SLUG_RE.fullmatch(slug):
            errors.append(f"slug must be lowercase [a-z0-9-], 1-{SLUG_MAX} chars, got: {slug!r}")
        elif filename_slug is not None and slug != filename_slug:
            errors.append(f"slug {slug!r} must match the file name {filename_slug + '.json'!r}")

    name = obj.get("displayName")
    if name not in (None, ""):
        if not isinstance(name, str) or not name.strip() or name != name.strip():
            errors.append("displayName must be a non-empty string without leading or trailing spaces")
        elif len(name) > DISPLAY_NAME_MAX:
            errors.append(f"displayName is {len(name)} characters; the limit is {DISPLAY_NAME_MAX}")

    aliases = obj.get("aliases")
    if aliases not in (None, "", []):
        if not isinstance(aliases, list) or not all(isinstance(a, str) and a.strip() for a in aliases):
            errors.append("aliases must be an array of non-empty strings")
        else:
            if any(a != a.strip() for a in aliases):
                errors.append("aliases must match the catalog `author` exactly, with no leading or trailing spaces")
            if len(set(aliases)) != len(aliases):
                errors.append("aliases lists the same name more than once")

    login = obj.get("githubLogin")
    if login not in (None, "") and not (isinstance(login, str) and _GITHUB_LOGIN_RE.fullmatch(login)):
        errors.append(f"githubLogin is not a valid GitHub login: {login!r}")

    if obj.get("bio") is not None:
        problem = bio_problem(obj["bio"])
        if problem:
            errors.append(problem)

    for field in ("avatarURL", "bannerURL"):
        if obj.get(field) is not None:
            problem = url_problem(obj[field], field)
            if problem:
                errors.append(problem)

    links = obj.get("links")
    if links is not None:
        if not isinstance(links, list):
            errors.append("links must be an array")
        else:
            if len(links) > MAX_LINKS:
                errors.append(f"links has {len(links)} items; the limit is {MAX_LINKS}")
            for i, link in enumerate(links):
                where = f"links[{i}]"
                if not isinstance(link, dict) or set(link) != {"label", "url"}:
                    errors.append(f"{where} must be an object with exactly `label` and `url`")
                    continue
                label = link["label"]
                if not isinstance(label, str) or not label.strip():
                    errors.append(f"{where}.label must be a non-empty string")
                elif len(label) > LINK_LABEL_MAX:
                    errors.append(f"{where}.label is {len(label)} characters; the limit is {LINK_LABEL_MAX}")
                problem = url_problem(link["url"], f"{where}.url")
                if problem:
                    errors.append(problem)

    socials = obj.get("socials")
    if socials is not None:
        if not isinstance(socials, dict):
            errors.append("socials must be an object of handles")
        else:
            for key, handle in socials.items():
                spec = SOCIAL_HANDLES.get(key)
                if spec is None:
                    errors.append(f"Unknown social: {key!r}. Valid: {list(SOCIAL_KEYS)}")
                elif not isinstance(handle, str) or not re.fullmatch(spec[0], handle):
                    errors.append(f"socials.{key} is not a valid {key} handle (handles only, no URLs or @): {handle!r}")

    claim = obj.get("claim")
    if claim is not None:
        if not isinstance(claim, dict):
            errors.append("claim must be an object or null")
        else:
            for f in sorted(set(claim) - {"issue", "method", "verifiedAt"}):
                errors.append(f"Unknown claim field: {f}")
            issue = claim.get("issue")
            if issue is not None and (not isinstance(issue, int) or isinstance(issue, bool) or issue < 1):
                errors.append("claim.issue must be a positive issue number")
            if claim.get("method") not in CLAIM_METHODS:
                errors.append(f"claim.method must be one of {list(CLAIM_METHODS)}")
            verified = claim.get("verifiedAt")
            try:
                if not (isinstance(verified, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", verified)):
                    raise ValueError
                datetime.date.fromisoformat(verified)
            except ValueError:
                errors.append("claim.verifiedAt must be a YYYY-MM-DD date")

    if "hidden" in obj and not isinstance(obj["hidden"], bool):
        errors.append("hidden must be true or false")

    return errors
