#!/usr/bin/env python3
"""
skin_schema.py — Shared schema, system map, and ID generation for the skin catalog.
"""

import hashlib
import re
from typing import Optional

CATALOG_VERSION = 2

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
    "gamecube":                         ("gamecube",        "public.aoshuang.game.gc"),
    "game cube":                        ("gamecube",        "public.aoshuang.game.gc"),
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
    "mame":                             ("mame",            None),
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

# Reverse map: gameTypeIdentifier → short_code (first mapping wins)
GTI_TO_CODE: dict[str, str] = {}
for _v in SYSTEM_MAP.values():
    if _v[1] and _v[1] not in GTI_TO_CODE:
        GTI_TO_CODE[_v[1]] = _v[0]

# Also map Manic variants not in SYSTEM_MAP values
_MANIC_EXTRA = {
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
    "public.aoshuang.game.gc": "gamecube",
    "public.aoshuang.game.wii": "wii",
}
GTI_TO_CODE.update({k: v for k, v in _MANIC_EXTRA.items() if k not in GTI_TO_CODE})

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
