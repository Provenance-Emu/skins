#!/usr/bin/env python3
"""
generate_variant_fixtures.py — Draw the sample variant skins in fixtures/variants/.

Test skins for the formats that carry variants (SkinKit design, section 4):

  sample-alt-ds.deltaskin                 DS, two layouts, `toggleAltRepresentations` button
  sample-themes-gba.deltaskin             GBA, base artwork plus 2 `themes`
  sample-gameoverrides-jaguar.manicskin   Jaguar keypad plus `gameOverrides` (3 titles, 1 md5)
  sample-split-family/                    GBA, 3 separate skins sharing a `groupId`
  sample-split-family-dc/                 Dreamcast, same
  sample-split-family-gc/                 GameCube, same

All artwork is solid shapes and text drawn here with Pillow, so the files can be
published and bundled without a licensing question. Each skin's base
`representations` is a complete skin (Delta and Manic read nothing else); the
variant keys are additive. The same run can write the catalog entries
(`skins/<system>/*.json`) and their `variants.json` records.

Hosting: each catalog entry's `downloadURL` is the raw GitHub URL of the committed
fixture on `main` (it resolves once the file is merged; nothing is published
outside the PR). Output is deterministic (fixed zip timestamps, sorted entries), so re-running
changes nothing unless this script does.

Usage:
    python3 scripts/generate_variant_fixtures.py                  # fixtures only
    python3 scripts/generate_variant_fixtures.py --entries        # + skins/*.json + variants.json
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import sys
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
from skin_schema import make_id, normalize_entry, system_from_gti  # noqa: E402
from variants_sidecar import compute_variants, load_variants, save_variants, set_record  # noqa: E402

FIXTURES_DIR = REPO_ROOT / "fixtures" / "variants"
SKINS_DIR = REPO_ROOT / "skins"
SOURCE = "provenance-emu"
AUTHOR = "Provenance Emu"
RAW_BASE = "https://raw.githubusercontent.com/Provenance-Emu/skins/main/fixtures/variants/"
ID_PREFIX = "com.provenance-emu.sample"

DELTA = "com.rileytestut.delta.game."
MANIC = "public.aoshuang.game."
RETINA = {"iphone": 2, "ipad": 1}  # artwork pixels per mapping point, by device (keeps iPad files small)

# device, display type, orientation, mapping size (points)
LAYOUTS = [
    ("iphone", "edgeToEdge", "portrait", (414, 896)),
    ("iphone", "edgeToEdge", "landscape", (896, 414)),
    ("iphone", "standard", "portrait", (414, 736)),
    ("iphone", "standard", "landscape", (736, 414)),
    ("ipad", "standard", "portrait", (768, 1024)),
    ("ipad", "standard", "landscape", (1024, 768)),
]


# ---------------------------------------------------------------------------
# Palettes
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Palette:
    name: str
    bg: tuple
    panel: tuple
    key: tuple
    accent: tuple
    text: tuple


GRAPHITE = Palette("Graphite", (38, 40, 46), (58, 61, 70), (92, 97, 110), (236, 190, 70), (240, 240, 245))
DARK = Palette("Dark", (8, 8, 10), (24, 24, 28), (46, 46, 54), (90, 200, 250), (225, 230, 235))
NEON = Palette("Neon", (22, 8, 48), (48, 16, 92), (96, 32, 168), (60, 255, 150), (255, 240, 255))
RED = Palette("Red", (96, 18, 24), (140, 28, 36), (190, 56, 64), (255, 214, 120), (255, 240, 236))
GREEN = Palette("Green", (16, 74, 40), (24, 110, 60), (44, 160, 92), (255, 236, 130), (236, 255, 240))
BLUE = Palette("Blue", (16, 40, 100), (24, 62, 150), (48, 100, 208), (255, 180, 100), (236, 244, 255))
GAME_COLORS = {
    "Doom": Palette("Doom", (70, 14, 10), (112, 26, 18), (168, 52, 30), (255, 150, 40), (255, 238, 224)),
    "Alien vs Predator": Palette("AvP", (10, 54, 36), (16, 84, 56), (30, 130, 84), (190, 255, 60), (232, 255, 240)),
    "Wolfenstein 3D": Palette("Wolf3D", (40, 44, 52), (66, 72, 84), (110, 118, 134), (255, 220, 60), (240, 242, 248)),
    "md5": Palette("md5", (52, 22, 84), (80, 36, 124), (124, 64, 180), (255, 120, 200), (250, 238, 255)),
}


# ---------------------------------------------------------------------------
# Control layout
#
# A layout is the screens plus the controls, in mapping points. The same
# geometry feeds info.json (frames) and the artwork (shapes), so they agree.
# ---------------------------------------------------------------------------

Rect = tuple  # (x, y, w, h)


@dataclass
class Control:
    label: str
    frame: Rect
    shape: str                    # round | pill | dpad | stick | key
    inputs: object                # list[str] or dict (d-pad, stick, touch)
    thumbstick: bool = False


@dataclass
class Layout:
    size: tuple
    screens: list = field(default_factory=list)   # (input_frame | None, output_frame)
    controls: list = field(default_factory=list)


def _r(x, y, w, h) -> Rect:
    return (round(x), round(y), round(w), round(h))


@dataclass(frozen=True)
class Kit:
    """What a system's controller has."""
    screens: int = 1                 # 1, or 2 for the DS
    aspect: float = 4 / 3            # width / height of one screen
    input_size: tuple = (240, 160)   # the emulated screen, for inputFrame
    face: tuple = ("a", "b")         # face buttons
    shoulders: tuple = ()            # input names: left, right, then an optional third (Z)
    start: tuple = ("start",)        # centre buttons, left to right
    sticks: tuple = ()               # ("left",) or ("left", "right")
    keypad: tuple = ()               # key labels, 3 per row
    touch: bool = False              # DS: the bottom screen is a touch screen
    toggle: bool = False             # a button that flips to the alt layout


DIRS = {"up": "up", "down": "down", "left": "left", "right": "right"}
KEYPAD = ("1", "2", "3", "4", "5", "6", "7", "8", "9", "*", "0", "#")
FACE_SLOTS = {   # offsets, in units of the diamond's spread
    4: [(1, 0), (0, 1), (0, -1), (-1, 0)],           # a right, b bottom, x top, y left
    3: [(1.0, -0.5), (0, 0.7), (-1.0, -0.5)],
    2: [(0.8, -0.6), (-0.8, 0.6)],
}


def _stick_inputs(side: str) -> dict:
    return {d: f"{side}Thumbstick{d.capitalize()}" for d in ("up", "down", "left", "right")}


def _keypad_inputs(label: str) -> list:
    return [{"*": "star", "#": "pound"}.get(label, f"num{label}")]


def _screens(kit: Kit, size: tuple, swapped: bool, keypad: tuple) -> tuple[list, float]:
    """Screen rectangles (input, output) and the y where the controls may start."""
    w, h = size
    landscape = w > h
    n = kit.screens
    if landscape:
        sh = min((0.52 if n == 2 else 0.40 if keypad else 0.76) * h, (0.32 if n == 2 else 0.60) * w / kit.aspect)
    else:
        sh = min((0.285 if n == 2 else 0.30) * h, 0.92 * w / kit.aspect)
    sw = sh * kit.aspect
    top = 0.05 * h
    if n == 1:
        rects = [_r((w - sw) / 2, top, sw, sh)]
    elif landscape:
        gap = 0.02 * w
        x0 = (w - 2 * sw - gap) / 2
        rects = [_r(x0, top, sw, sh), _r(x0 + sw + gap, top, sw, sh)]
    else:
        gap = 0.012 * h
        rects = [_r((w - sw) / 2, top, sw, sh), _r((w - sw) / 2, top + sh + gap, sw, sh)]
    if swapped and n == 2:
        rects.reverse()
    iw, ih = kit.input_size
    inputs = [(0, 0, iw, ih)] if n == 1 else [(0, 0, iw, ih), (0, ih, iw, ih)]
    bottom = max(r[1] + r[3] for r in rects)
    return list(zip(inputs, rects)), bottom


def build_layout(kit: Kit, size: tuple, swapped: bool = False, keys: tuple = None) -> Layout:
    """Screens and controls for `kit` on a canvas of `size` points.

    `swapped` exchanges a dual-screen skin's two screens (the alt layout).
    `keys` limits the keypad to those labels (a per-game override).
    """
    w, h = size
    landscape = w > h
    keypad = kit.keypad if keys is None else tuple(keys)
    margin = 0.03 * w
    lay = Layout(size)
    lay.screens, screens_bottom = _screens(kit, size, swapped, keypad)
    if kit.touch and kit.screens == 2:
        lay.controls.append(Control("touch", lay.screens[1][1], "touch", {"x": "touchScreenX", "y": "touchScreenY"}))

    # Bottom row: centre buttons, then MENU.
    pill_w, pill_h = (0.11 * w, 0.065 * h) if landscape else (0.20 * w, 0.034 * h)
    row_y = h - (0.085 if landscape else 0.05) * h - pill_h
    row = [*kit.start, "menu"]
    x0 = (w - (len(row) * pill_w + (len(row) - 1) * 8)) / 2
    for i, name in enumerate(row):
        lay.controls.append(Control(name.upper(), _r(x0 + i * (pill_w + 8), row_y, pill_w, pill_h), "pill", [name]))

    def dpad(cx, cy, size_):
        lay.controls.append(Control("D", _r(cx - size_ / 2, cy - size_ / 2, size_, size_), "dpad", dict(DIRS)))

    def stick(side, cx, cy, size_):
        lay.controls.append(Control(f"{side[0].upper()}S", _r(cx - size_ / 2, cy - size_ / 2, size_, size_), "stick",
                                    _stick_inputs(side), thumbstick=True))

    def face(cx, cy, unit):
        b = unit * (0.36 if len(kit.face) == 4 else 0.42)
        spread = unit * 0.39
        for name, (dx, dy) in zip(kit.face, FACE_SLOTS[len(kit.face)]):
            lay.controls.append(Control(name.upper(), _r(cx + dx * spread - b / 2, cy + dy * spread - b / 2, b, b), "round", [name]))

    def face_extent(unit):
        b = unit * (0.36 if len(kit.face) == 4 else 0.42)
        return max(abs(dx) for dx, _dy in FACE_SLOTS[len(kit.face)]) * unit * 0.39 + b / 2

    def shoulders(y, unit):
        if not kit.shoulders:
            return
        pw, ph = unit * 0.62, unit * 0.2
        lay.controls.append(Control("L", _r(margin, y, pw, ph), "pill", [kit.shoulders[0]]))
        lay.controls.append(Control("R", _r(w - margin - pw, y, pw, ph), "pill", [kit.shoulders[1]]))
        if len(kit.shoulders) > 2:
            lay.controls.append(Control("Z", _r(w - margin - pw, y + ph * 1.4, pw, ph), "pill", [kit.shoulders[2]]))

    if kit.sticks:
        # Two columns: stick over d-pad on the left; face buttons over the
        # second stick (or nothing) on the right.
        if landscape:
            free = (w - lay.screens[0][1][2]) / 2
            unit = min(0.30 * h, 0.8 * free)
            left_cx, right_cx = free / 2, w - free / 2
            y1, y2, sy = 0.38 * h, 0.78 * h, 0.05 * h
        else:
            zone_top = screens_bottom + 0.02 * h + 0.05 * h      # room for the shoulders above
            zone_h = row_y - zone_top - 0.03 * h
            unit = min(0.30 * w, 0.40 * zone_h)
            left_cx, right_cx = 0.25 * w, 0.75 * w
            y1, y2, sy = zone_top + 0.27 * zone_h, zone_top + 0.73 * zone_h, screens_bottom + 0.02 * h
        stick("left", left_cx, y1, unit)
        dpad(left_cx, y2, unit * 0.8)
        face(right_cx, y1, unit * 0.9)
        if len(kit.sticks) > 1:
            stick("right", right_cx, y2, unit)
        shoulders(sy, unit * 0.9)
    elif landscape:
        # Controls flank the screens, in the free margin on each side.
        free = min(r[0] for _i, r in lay.screens)
        unit = max(min(0.30 * h, (free - 2 * margin) / 1.15), 40)
        cy = 0.62 * h
        dpad(margin + unit / 2, cy, unit)
        face(w - margin - face_extent(unit), cy, unit)
        shoulders(0.06 * h, unit)
    else:
        zone_top = screens_bottom + 0.02 * h
        reserved = 0.05 * h if kit.shoulders else 0    # shoulders sit above the d-pad and buttons
        area_h = row_y - zone_top - reserved - 0.02 * h
        unit = min(0.34 * w if not keypad else 0.30 * w, area_h / 1.15)
        cy = zone_top + reserved + (unit * 0.62 if keypad else area_h / 2)
        dpad(margin + unit / 2, cy, unit)
        face(w - margin - face_extent(unit), cy, unit)
        shoulders(zone_top, unit)

    if keypad:
        cols = 3
        if landscape:
            kw, kh = 0.065 * w, 0.075 * h
            ky0 = screens_bottom + 0.03 * h
        else:
            kw, kh = 0.20 * w, 0.062 * h
            ky0 = cy + unit / 2 + 0.02 * h
        kx0 = (w - cols * kw - (cols - 1) * 6) / 2
        for i, label in enumerate(keypad):
            r_, c_ = divmod(i, cols)
            lay.controls.append(Control(label, _r(kx0 + c_ * (kw + 6), ky0 + r_ * (kh + 6), kw, kh), "key", _keypad_inputs(label)))

    if kit.toggle:
        tw, th = (0.16 * w, 0.034 * h) if not landscape else (0.12 * w, 0.065 * h)
        ty = screens_bottom + (0.01 * h if landscape else 0.02 * h)
        if not landscape:
            ty = screens_bottom + 0.02 * h
        lay.controls.append(Control("ALT", _r(w / 2 - tw / 2, ty, tw, th), "pill", ["toggleAltRepresentations"]))
    return lay


# ---------------------------------------------------------------------------
# Artwork
# ---------------------------------------------------------------------------

def _font(size: int):
    try:
        return ImageFont.load_default(size=size)
    except TypeError:  # Pillow < 10.1: fixed-size bitmap font
        return ImageFont.load_default()


def draw_artwork(lay: Layout, palette: Palette, title: str, scale: int = 2) -> Image.Image:
    """The skin image: opaque panel with the game screens cut out."""
    w, h = lay.size
    SCALE = scale
    img = Image.new("RGBA", (w * SCALE, h * SCALE), palette.bg + (255,))
    d = ImageDraw.Draw(img)

    def box(r: Rect, pad=0):
        x, y, rw, rh = r
        return [(x - pad) * SCALE, (y - pad) * SCALE, (x + rw + pad) * SCALE - 1, (y + rh + pad) * SCALE - 1]

    d.rounded_rectangle([6 * SCALE, 6 * SCALE, (w - 6) * SCALE, (h - 6) * SCALE], radius=24 * SCALE, outline=palette.panel, width=3 * SCALE)
    for _inp, out in lay.screens:  # bezel, then the cutout the emulator draws into
        d.rounded_rectangle(box(out, 4), radius=6 * SCALE, fill=palette.panel)
    for _inp, out in lay.screens:
        d.rectangle(box(out), fill=(0, 0, 0, 0))

    small = _font(10 * SCALE)
    for c in lay.controls:
        if c.shape == "touch":
            continue
        x0, y0, x1, y1 = box(c.frame)
        if c.shape == "round":
            d.ellipse([x0, y0, x1, y1], fill=palette.key, outline=palette.accent, width=2 * SCALE)
        elif c.shape == "pill":
            d.rounded_rectangle([x0, y0, x1, y1], radius=(y1 - y0) // 2, fill=palette.key, outline=palette.panel, width=2 * SCALE)
        elif c.shape == "key":
            d.rounded_rectangle([x0, y0, x1, y1], radius=6 * SCALE, fill=palette.key, outline=palette.panel, width=2 * SCALE)
        elif c.shape == "stick":
            d.ellipse([x0, y0, x1, y1], fill=palette.panel, outline=palette.key, width=3 * SCALE)
        elif c.shape == "dpad":
            third_x, third_y = (x1 - x0) // 3, (y1 - y0) // 3
            d.rounded_rectangle([x0 + third_x, y0, x1 - third_x, y1], radius=6 * SCALE, fill=palette.key)
            d.rounded_rectangle([x0, y0 + third_y, x1, y1 - third_y], radius=6 * SCALE, fill=palette.key)
            d.ellipse([x0 + third_x * 1.1, y0 + third_y * 1.1, x1 - third_x * 1.1, y1 - third_y * 1.1], fill=palette.panel)
        if c.shape != "dpad":
            d.text(((x0 + x1) / 2, (y0 + y1) / 2), c.label, font=small, fill=palette.text, anchor="mm")

    # title strip: which variant this artwork belongs to
    d.text((w * SCALE / 2, (h - 14) * SCALE), title, font=_font(11 * SCALE), fill=palette.accent, anchor="mm")
    return img


def png_bytes(img: Image.Image) -> bytes:
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


# ---------------------------------------------------------------------------
# info.json
# ---------------------------------------------------------------------------

def _frame(r: Rect) -> dict:
    return {"x": r[0], "y": r[1], "width": r[2], "height": r[3]}


def _item(c: Control) -> dict:
    item = {"inputs": c.inputs, "frame": _frame(c.frame), "extendedEdges": {"top": 4, "bottom": 4, "left": 4, "right": 4}}
    if c.thumbstick:
        item["thumbstick"] = {"name": "thumbstick.png", "width": c.frame[2], "height": c.frame[3]}
        item["extendedEdges"] = {"top": 0, "bottom": 0, "left": 0, "right": 0}
    return item


def representation(lay: Layout, art_name: str) -> dict:
    screens = []
    for inp, out in lay.screens:
        s = {"outputFrame": _frame(out)}
        if inp:
            s = {"inputFrame": _frame(inp), **s}
        screens.append(s)
    return {
        "assets": {"small": art_name, "medium": art_name, "large": art_name},
        "items": [_item(c) for c in lay.controls],
        "screens": screens,
        "mappingSize": {"width": lay.size[0], "height": lay.size[1]},
        "extendedEdges": {"top": 4, "bottom": 4, "left": 4, "right": 4},
        "translucent": False,
    }


def thumbstick_png(palette: Palette) -> bytes:
    img = Image.new("RGBA", (128, 128), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.ellipse([4, 4, 123, 123], fill=palette.accent, outline=palette.text, width=4)
    d.ellipse([34, 34, 93, 93], fill=palette.key)
    return png_bytes(img)


def _set(tree: dict, device: str, display: str, orientation: str, value: dict) -> None:
    tree.setdefault(device, {}).setdefault(display, {})[orientation] = value


def art_name(prefix: str, device: str, display: str, orientation: str) -> str:
    return f"{prefix}-{device}-{display}-{orientation}.png"


# ---------------------------------------------------------------------------
# Skins
# ---------------------------------------------------------------------------

@dataclass
class Built:
    """A skin ready to write: info.json plus the files beside it."""
    info: dict
    files: dict           # archive name -> bytes


def base_info(slug: str, name: str, gti: str) -> dict:
    return {"name": name, "identifier": f"{ID_PREFIX}.{slug}", "gameTypeIdentifier": gti, "debug": False, "representations": {}}


def build_skin(slug: str, name: str, gti: str, kit: Kit, palette: Palette, title: str) -> Built:
    """A plain skin: every layout, one palette."""
    info, files = base_info(slug, name, gti), {}
    for device, display, orientation, size in LAYOUTS:
        lay = build_layout(kit, size)
        art = art_name("skin", device, display, orientation)
        files[art] = png_bytes(draw_artwork(lay, palette, title, RETINA[device]))
        _set(info["representations"], device, display, orientation, representation(lay, art))
    if kit.sticks:
        files["thumbstick.png"] = thumbstick_png(palette)
    return Built(info, files)


GBA_KIT = Kit(aspect=3 / 2, face=("a", "b"), shoulders=("l", "r"), start=("select", "start"))
DS_KIT = Kit(screens=2, aspect=4 / 3, input_size=(256, 192), face=("a", "b", "x", "y"), shoulders=("l", "r"),
             start=("select", "start"), touch=True)
JAGUAR_KIT = Kit(aspect=4 / 3, input_size=(320, 240), face=("a", "b", "y"), start=("select", "start"), keypad=KEYPAD)
DC_KIT = Kit(aspect=4 / 3, input_size=(640, 480), face=("a", "b", "x", "y"), shoulders=("l1", "r1"), start=("start",),
             sticks=("left",))
GC_KIT = Kit(aspect=4 / 3, input_size=(640, 480), face=("a", "b", "x", "y"), shoulders=("l2", "r2", "r1"), start=("start",),
             sticks=("left", "right"))


def build_alt_ds() -> Built:
    """DS with a second layout (the screens swapped) behind a toggle button."""
    kit = Kit(**{**DS_KIT.__dict__, "toggle": True})
    info = base_info("alt-ds", "Sample Alt Layout DS", DELTA + "ds")
    alt, files = {}, {}
    for device, display, orientation, size in LAYOUTS:
        for tree, swapped, prefix, title in ((info["representations"], False, "layout-a", "LAYOUT A"),
                                             (alt, True, "layout-b", "LAYOUT B (ALT)")):
            lay = build_layout(kit, size, swapped=swapped)
            art = art_name(prefix, device, display, orientation)
            files[art] = png_bytes(draw_artwork(lay, GRAPHITE if not swapped else DARK, f"SAMPLE ALT DS - {title}", RETINA[device]))
            _set(tree, device, display, orientation, representation(lay, art))
    info["altRepresentations"] = alt
    return Built(info, files)


def build_themes_gba() -> Built:
    """GBA with its own artwork plus two themes that swap the artwork only."""
    built = build_skin("themes-gba", "Sample Themes GBA", DELTA + "gba", GBA_KIT, GRAPHITE, "SAMPLE THEMES GBA - BASE")
    themes = []
    for theme_id, theme_name, palette in (("dark", "Dark", DARK), ("neon", "Neon", NEON)):
        assets: dict = {}
        for device, display, orientation, size in LAYOUTS:
            art = art_name(f"theme-{theme_id}", device, display, orientation)
            built.files[art] = png_bytes(draw_artwork(build_layout(GBA_KIT, size), palette, f"SAMPLE THEMES GBA - {theme_name.upper()}", RETINA[device]))
            _set(assets, device, display, orientation, {"small": art, "medium": art, "large": art})
        themes.append({"id": theme_id, "name": theme_name, "assets": assets})
    built.info["themes"] = themes
    return built


# Jaguar per-game keypads. Keys: a game title, or an md5 (a ROM hash). The md5
# here is derived from a made-up string, not a real ROM, so no dump is implied.
JAGUAR_MD5_SOURCE = "sample-gameoverrides-jaguar:Iron Soldier"
JAGUAR_MD5 = hashlib.md5(JAGUAR_MD5_SOURCE.encode()).hexdigest()
JAGUAR_GAMES = [
    ("Doom", ("1", "2", "3", "4", "5", "6", "7"), "Doom"),
    ("Alien vs Predator", ("1", "2", "3", "5", "0"), "Alien vs Predator"),
    ("Wolfenstein 3D", ("1", "2", "3", "4"), "Wolfenstein 3D"),
    (JAGUAR_MD5, ("1", "4", "7", "*", "0", "#"), "md5"),
]


def build_gameoverrides_jaguar() -> Built:
    """Jaguar keypad skin; each override replaces the whole layout for one game."""
    built = build_skin("gameoverrides-jaguar", "Sample Game Overrides Jaguar", MANIC + "jaguar", JAGUAR_KIT, GRAPHITE,
                       "SAMPLE JAGUAR - BASE KEYPAD")
    overrides = {}
    for key, keys, palette_key in JAGUAR_GAMES:
        label = "MD5 " + key[:8] if palette_key == "md5" else key
        reps: dict = {}
        for device, display, orientation, size in LAYOUTS:
            if device != "iphone" or display != "edgeToEdge":
                continue
            lay = build_layout(JAGUAR_KIT, size, keys=keys)
            slug = hashlib.sha1(key.encode()).hexdigest()[:8]
            art = art_name(f"game-{slug}", device, display, orientation)
            built.files[art] = png_bytes(draw_artwork(lay, GAME_COLORS[palette_key], f"SAMPLE JAGUAR - {label}", RETINA[device]))
            _set(reps, device, display, orientation, representation(lay, art))
        overrides[key] = reps
    built.info["gameOverrides"] = overrides
    return built


# ---------------------------------------------------------------------------
# Manifest
# ---------------------------------------------------------------------------

@dataclass
class Fixture:
    path: str                    # relative to fixtures/variants/
    name: str
    system: str
    gti: str
    build: callable
    group: str = None            # groupId
    order: int = None
    label: str = None            # variantLabel


def _family(tag: str, system: str, gti: str, kit: Kit, folder: str, ext: str) -> list[Fixture]:
    out = []
    for i, palette in enumerate((RED, GREEN, BLUE), 1):
        slug = f"split-{tag}-{palette.name.lower()}"
        out.append(Fixture(
            path=f"{folder}/sample-{slug}.{ext}",
            name=f"Sample Split Family {tag.upper()} — {palette.name}",
            system=system, gti=gti,
            build=(lambda slug=slug, palette=palette, tag=tag, kit=kit, gti=gti, name=f"Sample Split Family {tag.upper()} — {palette.name}":
                   build_skin(slug, name, gti, kit, palette, f"SAMPLE SPLIT {tag.upper()} - {palette.name.upper()}")),
            group=f"sample:split-family-{tag}", order=i, label=palette.name,
        ))
    return out


FIXTURES: list[Fixture] = [
    Fixture("sample-alt-ds.deltaskin", "Sample Alt Layout DS", "nds", DELTA + "ds", build_alt_ds),
    Fixture("sample-themes-gba.deltaskin", "Sample Themes GBA", "gba", DELTA + "gba", build_themes_gba),
    Fixture("sample-gameoverrides-jaguar.manicskin", "Sample Game Overrides Jaguar", "jaguar", MANIC + "jaguar",
            build_gameoverrides_jaguar),
    *_family("gba", "gba", DELTA + "gba", GBA_KIT, "sample-split-family", "deltaskin"),
    *_family("dc", "dreamcast", MANIC + "dc", DC_KIT, "sample-split-family-dc", "manicskin"),
    *_family("gc", "gamecube", MANIC + "ngc", GC_KIT, "sample-split-family-gc", "manicskin"),
]


def zip_skin(built: Built) -> bytes:
    """Deterministic archive: info.json first, then files by name, fixed timestamps."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        members = {"info.json": (json.dumps(built.info, indent=2) + "\n").encode(), **built.files}
        for name in ["info.json", *sorted(n for n in members if n != "info.json")]:
            zi = zipfile.ZipInfo(name, date_time=(2026, 1, 1, 0, 0, 0))
            zi.compress_type = zipfile.ZIP_DEFLATED
            zi.external_attr = 0o644 << 16
            z.writestr(zi, members[name])
    return buf.getvalue()


def download_url(fx: Fixture) -> str:
    return RAW_BASE + fx.path


def entry_for(fx: Fixture, size: int) -> dict:
    url = download_url(fx)
    entry = {
        "name": fx.name,
        "author": AUTHOR,
        "downloadURL": url,
        "systems": [fx.system],
        "gameTypeIdentifier": fx.gti,
        "source": SOURCE,
        "version": "1.0",
        "tags": ["sample"],
        "fileSize": size,
    }
    if fx.group:
        entry.update(groupId=fx.group, groupOrder=fx.order, variantLabel=fx.label)
    entry["id"] = make_id(SOURCE, url)
    return normalize_entry(entry)


def entry_path(fx: Fixture, skins_dir: Path = SKINS_DIR) -> Path:
    return skins_dir / fx.system / (Path(fx.path).stem + ".json")


def generate(out_dir: Path = FIXTURES_DIR) -> dict[str, bytes]:
    """Write every fixture under `out_dir`; returns {relative path: bytes}."""
    written = {}
    for fx in FIXTURES:
        data = zip_skin(fx.build())
        path = out_dir / fx.path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        written[fx.path] = data
    return written


def write_entries(written: dict[str, bytes], skins_dir: Path = SKINS_DIR, variants_file: Path = REPO_ROOT / "variants.json") -> None:
    store = load_variants(str(variants_file))
    for fx in FIXTURES:
        entry = entry_for(fx, len(written[fx.path]))
        path = entry_path(fx, skins_dir)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(entry, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        info = json.loads(zipfile.ZipFile(io.BytesIO(written[fx.path])).read("info.json"))
        set_record(store, entry["id"], entry["downloadURL"], compute_variants(info))
    save_variants(store, str(variants_file))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out-dir", type=Path, default=FIXTURES_DIR)
    ap.add_argument("--entries", action="store_true", help="Also write skins/<system>/*.json and variants.json records")
    args = ap.parse_args()

    written = generate(args.out_dir)
    for rel, data in written.items():
        print(f"  {rel}  {len(data) / 1024:.0f} KB")
    if args.entries:
        write_entries(written)
        print(f"Wrote {len(FIXTURES)} catalog entries and their variants.json records")
    return 0


if __name__ == "__main__":
    sys.exit(main())
