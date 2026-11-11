#!/usr/bin/env python3
"""
generate_thumbnails.py — Extract thumbnail images from skin files (.deltaskin / .manicskin).

For each skin JSON without a thumbnailURL:
  1. Download the skin ZIP (using range requests where possible)
  2. Parse info.json to find the best portrait image asset (PNG preferred, PDF fallback)
  3. Extract that asset from the ZIP
  4. Convert PDF → PNG via poppler pdftoppm if needed
  5. Upload to a GitHub Release (`thumbnails`, then `thumbnails-2`, ... as each fills
     up; scripts/thumbnail_shards.py) as primary CDN
  6. Also save to thumbnails/{id}.png in the repo as fallback
  7. Update the skin JSON with the release URL (fallback to raw.githubusercontent.com)

Usage:
    python3 scripts/generate_thumbnails.py
    python3 scripts/generate_thumbnails.py --skins-dir skins/ --limit 20
    python3 scripts/generate_thumbnails.py --dry-run
    python3 scripts/generate_thumbnails.py --force   # regenerate even if thumbnailURL already set
    python3 scripts/generate_thumbnails.py --promote --limit 100   # move repo-hosted thumbnail URLs onto the releases
"""

import argparse
import io
import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.request
import urllib.error
import zipfile
from pathlib import Path

try:
    from PIL import Image, ImageDraw
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False
    print("WARNING: Pillow not installed — thumbnails will not be enhanced", file=sys.stderr)

sys.path.insert(0, str(Path(__file__).parent))
import polite_http
import thumbnail_shards
from extract_metadata import stream_extract_info_json, _full_download_extract

GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")
REPO = os.environ.get("GITHUB_REPOSITORY", "Provenance-Emu/skins")
THUMBNAILS_TAG = thumbnail_shards.BASE_TAG   # first of the shard releases (thumbnail_shards.py)
THUMBNAILS_DIR = "thumbnails"
RAW_BASE = f"https://raw.githubusercontent.com/{REPO}/main/{THUMBNAILS_DIR}"

THUMBNAIL_SIZE = 400  # final square size in pixels

# SMPTE 75% color bars (classic broadcast standard)
_SMPTE = [
    (191, 191, 191),  # white
    (191, 191,   0),  # yellow
    (  0, 191, 191),  # cyan
    (  0, 191,   0),  # green
    (191,   0, 191),  # magenta
    (191,   0,   0),  # red
    (  0,   0, 191),  # blue
]


# ---------------------------------------------------------------------------
# Thumbnail enhancement pipeline
# ---------------------------------------------------------------------------

def _make_color_bars(width: int, height: int) -> "Image.Image":
    """Generate a classic SMPTE 75% color bars image."""
    img = Image.new("RGB", (width, height))
    n = len(_SMPTE)
    pixels = img.load()
    for x in range(width):
        color = _SMPTE[int(x * n / width)]
        for y in range(height):
            pixels[x, y] = color
    return img


def _pick_representation(info: dict, prefer_orientation: str = "portrait") -> tuple["dict | None", dict]:
    """
    Find the best single representation for thumbnail generation.

    Returns (orientation_dict, mapping_size).  Searches in priority order:
      device:      iphone > ipad > tv
      quality:     edgeToEdge > standard
      orientation: prefer_orientation first, then the other

    mappingSize is per-representation in modern skins (NOT at root level).
    Using the wrong (or missing) mappingSize is the primary cause of
    incorrectly-sized / missing NTSC color bars.
    """
    reps = info.get("representations", {})
    other = "landscape" if prefer_orientation == "portrait" else "portrait"
    for device in ("iphone", "ipad", "tv"):
        device_rep = reps.get(device)
        if not isinstance(device_rep, dict):
            continue
        for quality in ("edgeToEdge", "standard"):
            quality_rep = device_rep.get(quality)
            if not isinstance(quality_rep, dict):
                continue
            for orientation in (prefer_orientation, other):
                orient_rep = quality_rep.get(orientation)
                if not isinstance(orient_rep, dict):
                    continue
                # mappingSize: most specific wins
                mapping = (
                    orient_rep.get("mappingSize") or
                    quality_rep.get("mappingSize") or
                    device_rep.get("mappingSize") or
                    info.get("mappingSize") or {}
                )
                return orient_rep, mapping
    return None, info.get("mappingSize") or {}


def _screens_and_mapping(info: dict, rep: "dict | None", mapping: dict) -> tuple[list[dict], dict]:
    """
    Return (frames, mapping_size) for screen-bar filling.
    Uses the provided single representation if available; falls back to walking all reps
    (legacy skins that don't follow the modern per-representation layout).
    """
    if rep is not None:
        frames = [
            s["outputFrame"]
            for s in (rep.get("screens") or [])
            if isinstance(s, dict) and "outputFrame" in s
        ]
        if frames:
            return frames, mapping

    # Legacy fallback: walk every representation
    frames = []
    def _walk(obj):
        if isinstance(obj, dict):
            if "screens" in obj and isinstance(obj["screens"], list):
                for s in obj["screens"]:
                    if isinstance(s, dict) and "outputFrame" in s:
                        frames.append(s["outputFrame"])
            for v in obj.values():
                _walk(v)
        elif isinstance(obj, list):
            for item in obj:
                _walk(item)
    _walk(info.get("representations", {}))
    # Use root mappingSize for legacy skins (often present there)
    return frames, info.get("mappingSize") or {}


def _fill_screens(img: "Image.Image", frames: list[dict], mapping: dict) -> "Image.Image":
    """
    Fill transparent screen regions with NTSC color bars.
    Screen positions are read from outputFrame coords and scaled to pixel
    dimensions using the provided mappingSize (logical points → pixels).
    """
    if not frames:
        return img

    lw = mapping.get("width", img.width) or img.width
    lh = mapping.get("height", img.height) or img.height
    sx = img.width / lw
    sy = img.height / lh

    img = img.copy()
    for f in frames:
        x = int(f.get("x", 0) * sx)
        y = int(f.get("y", 0) * sy)
        w = int(f.get("width",  0) * sx)
        h = int(f.get("height", 0) * sy)
        if w <= 4 or h <= 4:
            continue
        x = max(0, min(x, img.width - 1))
        y = max(0, min(y, img.height - 1))
        w = min(w, img.width  - x)
        h = min(h, img.height - y)

        bars = _make_color_bars(w, h).convert("RGBA")
        bars.putalpha(210)  # slightly translucent so skin border shows through

        # Paint the entire outputFrame — that region IS the screen by definition.
        # Alpha-checking was too conservative: many skins fill the screen area with
        # near-opaque dark pixels (screen bezel art) instead of full transparency.
        img.paste(bars, (x, y), mask=bars)

    return img


def _smart_crop(img: "Image.Image") -> "Image.Image":
    """
    Crop to the bounding box of non-transparent content.
    For skins like Depths Mini that are mostly alpha at the top,
    this surfaces the actual controls rather than empty space.
    """
    if img.mode != "RGBA":
        img = img.convert("RGBA")
    alpha = img.split()[3]
    bbox = alpha.getbbox()
    if not bbox:
        return img
    left, top, right, bottom = bbox
    # 3% padding
    px = max(4, int((right - left) * 0.03))
    py = max(4, int((bottom - top) * 0.03))
    return img.crop((
        max(0, left - px),
        max(0, top  - py),
        min(img.width,  right  + px),
        min(img.height, bottom + py),
    ))


def _device_bezel(img: "Image.Image", info: dict) -> "Image.Image":
    """
    Composite skin onto a stylised device frame drawn with PIL.
    Detects iPhone / iPad / TV from info.json representations keys.
    Uses Provenance retrowave palette for the frame accent.
    """
    reps = info.get("representations", {})
    if "tv" in reps:
        device = "tv"
    elif "ipad" in reps:
        device = "ipad"
    else:
        device = "iphone"

    portrait = img.height >= img.width

    if device == "tv":
        bezel_frac, corner_frac = 0.04, 0.04
        dynamic_island = home_bar = False
    elif device == "ipad":
        bezel_frac, corner_frac = 0.06, 0.06
        dynamic_island = home_bar = False
    else:
        bezel_frac, corner_frac = 0.06, 0.13
        dynamic_island = portrait
        home_bar = portrait

    bx = max(14, int(img.width  * bezel_frac))
    by = max(14, int(img.height * bezel_frac))
    fw = img.width  + bx * 2
    fh = img.height + by * 2
    cr = max(10, int(min(fw, fh) * corner_frac))

    # Retrowave palette
    BG      = (13,  13,  26, 255)   # #0D0D1A
    SCREEN  = ( 0,   0,   0, 255)
    DARK_BTN= ( 28,  28,  48, 255)

    frame = Image.new("RGBA", (fw, fh), (0, 0, 0, 0))
    draw  = ImageDraw.Draw(frame)

    # Body
    draw.rounded_rectangle([0, 0, fw - 1, fh - 1], radius=cr, fill=BG)

    # Dynamic island
    if dynamic_island:
        diw = max(36, int(fw * 0.20))
        dih = max(8,  int(fh * 0.016))
        dix = (fw - diw) // 2
        diy = by // 3
        draw.rounded_rectangle([dix, diy, dix + diw, diy + dih],
                                radius=dih // 2, fill=BG)

    # Side buttons (cosmetic)
    bw = 3
    if portrait:
        draw.rectangle([0,      int(fh*.28), bw,     int(fh*.37)], fill=DARK_BTN)
        draw.rectangle([0,      int(fh*.40), bw,     int(fh*.49)], fill=DARK_BTN)
        draw.rectangle([fw - bw, int(fh*.33), fw,    int(fh*.43)], fill=DARK_BTN)

    # Home bar
    if home_bar:
        barlw = int(fw * 0.28)
        barlx = (fw - barlw) // 2
        barly = fh - by // 2 - 2
        draw.rounded_rectangle([barlx, barly, barlx + barlw, barly + 3],
                                radius=2, fill=(80, 80, 110, 200))

    # Screen backing + skin composite
    screen = Image.new("RGBA", (img.width, img.height), SCREEN)
    screen.paste(img, mask=img)
    frame.paste(screen, (bx, by))

    return frame


def _pad_square(img: "Image.Image", size: int = THUMBNAIL_SIZE) -> "Image.Image":
    """Resize to fit within size×size, centre on transparent square canvas."""
    img.thumbnail((size, size), Image.LANCZOS)
    if img.width == img.height:
        return img
    side = max(img.width, img.height)
    canvas = Image.new("RGBA", (side, side), (0, 0, 0, 0))
    canvas.paste(img, ((side - img.width) // 2, (side - img.height) // 2))
    return canvas


def enhance_thumbnail(png_bytes: bytes, info: dict,
                      rep: "dict | None" = None,
                      mapping: "dict | None" = None) -> bytes:
    """
    Full enhancement pipeline:
      1. Fill transparent screen regions with NTSC color bars
         (uses per-representation mappingSize — fixes wrong-scale bars bug)
      2. Smart-crop to non-alpha content (fixes empty-alpha-at-top issue)
      3. Composite onto a retrowave device bezel
      4. Pad to square for consistent grid display
    Returns enhanced PNG bytes.
    """
    if not PIL_AVAILABLE:
        return png_bytes

    try:
        img = Image.open(io.BytesIO(png_bytes)).convert("RGBA")
        frames, eff_mapping = _screens_and_mapping(info, rep, mapping or {})
        img = _fill_screens(img, frames, eff_mapping)
        img = _smart_crop(img)
        img = _device_bezel(img, info)
        img = _pad_square(img)
        buf = io.BytesIO()
        img.save(buf, "PNG", optimize=True)
        enhanced = buf.getvalue()
        print(f"    Enhanced: {len(png_bytes):,} → {len(enhanced):,} bytes")
        return enhanced
    except Exception as e:
        print(f"    Enhancement failed ({e}), using raw PNG", file=sys.stderr)
        return png_bytes


# ---------------------------------------------------------------------------
# info.json asset discovery
# ---------------------------------------------------------------------------

def _assets_from_rep(rep: dict) -> list[str]:
    """Return unique asset filenames from a single orientation dict, PNGs before PDFs."""
    assets = rep.get("assets") or {}
    seen: dict[str, None] = {}
    pngs, pdfs = [], []
    for v in assets.values():
        if not isinstance(v, str) or v in seen:
            continue
        seen[v] = None
        if v.lower().endswith(".png"):
            pngs.append(v)
        elif v.lower().endswith(".pdf"):
            pdfs.append(v)
    return pngs + pdfs


def find_image_assets(info: dict, rep: "dict | None" = None) -> list[str]:
    """
    Return asset filenames to use for thumbnail generation.

    If *rep* (a specific orientation dict from _pick_representation) is given,
    prefer its assets.  Falls back to walking all representations so legacy
    skins that put assets at a different level still work.
    """
    if rep is not None:
        assets = _assets_from_rep(rep)
        if assets:
            return assets

    # Legacy / fallback: walk all representations
    pngs: list[str] = []
    pdfs: list[str] = []
    seen: set[str] = set()

    def _walk(obj):
        if isinstance(obj, dict):
            for k, v in obj.items():
                if k == "assets" and isinstance(v, dict):
                    for asset_name in v.values():
                        if isinstance(asset_name, str) and asset_name not in seen:
                            seen.add(asset_name)
                            if asset_name.lower().endswith(".png"):
                                pngs.append(asset_name)
                            elif asset_name.lower().endswith(".pdf"):
                                pdfs.append(asset_name)
                else:
                    _walk(v)
        elif isinstance(obj, list):
            for item in obj:
                _walk(item)

    _walk(info.get("representations", {}))

    def score(name):
        n = name.lower()
        if "portrait" in n or "resizable" in n:
            return 0
        if "small" in n:
            return 1
        if "medium" in n:
            return 2
        return 3

    pngs.sort(key=score)
    pdfs.sort(key=score)
    return pngs + pdfs


# ---------------------------------------------------------------------------
# ZIP asset extraction
# ---------------------------------------------------------------------------

def extract_asset_from_url(skin_url: str, asset_filename: str) -> bytes | None:
    """Extract a specific asset file from the skin ZIP.

    The archive comes from the shared download cache (polite_http), so it is
    fetched at most once per run however many assets we pull from it, and not
    at all when the health check already downloaded it."""
    try:
        fetched = polite_http.get_client().get_file(skin_url, token=GITHUB_TOKEN, component="thumbnails")
        with zipfile.ZipFile(fetched.path) as zf:
            # Case-insensitive match
            for name in zf.namelist():
                if Path(name).name.lower() == Path(asset_filename).name.lower():
                    return zf.read(name)
    except Exception as e:
        print(f"    Failed to extract {asset_filename}: {e}", file=sys.stderr)
    return None


# ---------------------------------------------------------------------------
# PDF → PNG conversion
# ---------------------------------------------------------------------------

def pdf_to_png(pdf_bytes: bytes) -> bytes | None:
    """Convert PDF bytes to PNG using pdftoppm (poppler-utils)."""
    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            pdf_path = os.path.join(tmpdir, "skin.pdf")
            out_prefix = os.path.join(tmpdir, "thumb")
            png_path = out_prefix + ".png"
            with open(pdf_path, "wb") as f:
                f.write(pdf_bytes)

            # Try pdftoppm first (poppler) — lower DPI keeps it fast for thumbnails
            pdftoppm_ok = False
            try:
                result = subprocess.run(
                    ["pdftoppm", "-png", "-r", "36", "-singlefile", pdf_path, out_prefix],
                    capture_output=True, timeout=60
                )
                pdftoppm_ok = result.returncode == 0 and os.path.exists(png_path)
            except subprocess.TimeoutExpired:
                print("    pdftoppm timed out, trying ghostscript", file=sys.stderr)
            except FileNotFoundError:
                pass

            # Ghostscript fallback
            if not pdftoppm_ok:
                try:
                    gs_result = subprocess.run(
                        ["gs", "-dNOPAUSE", "-dBATCH", "-sDEVICE=pnggray",
                         "-dFIRSTPAGE=1", "-dLASTPAGE=1",
                         "-r36", f"-sOutputFile={png_path}", pdf_path],
                        capture_output=True, timeout=60
                    )
                    if gs_result.returncode != 0 or not os.path.exists(png_path):
                        return None
                except subprocess.TimeoutExpired:
                    print("    ghostscript also timed out", file=sys.stderr)
                    return None
                except FileNotFoundError:
                    print("    neither pdftoppm nor gs found", file=sys.stderr)
                    return None

            if os.path.exists(png_path):
                with open(png_path, "rb") as f:
                    return f.read()
    except Exception as e:
        print(f"    PDF conversion failed: {e}", file=sys.stderr)
    return None


def extract_thumbnail_png(url: str, assets: list[str]) -> bytes | None:
    """Return the first usable asset, rasterizing PDFs even when named .png."""
    for asset in assets:
        raw = extract_asset_from_url(url, asset)
        if not raw:
            continue
        if raw.startswith(b"%PDF-") or asset.lower().endswith(".pdf"):
            print(f"    Converting PDF: {asset} ({len(raw):,} bytes)")
            png = pdf_to_png(raw)
            if png:
                print(f"    Converted to PNG ({len(png):,} bytes)")
                return png
        elif asset.lower().endswith(".png"):
            print(f"    Extracted PNG: {asset} ({len(raw):,} bytes)")
            return raw
    return None


# ---------------------------------------------------------------------------
# GitHub Releases upload
# ---------------------------------------------------------------------------

def get_or_create_release(repo: str, tag: str, token: str) -> dict | None:
    """Get or create one release of the thumbnail family (`thumbnails`,
    `thumbnails-2`, ...). Returns release dict or None."""
    headers = {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {token}",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "Provenance-SkinCatalog/1.0",
    }

    # Try to get existing release
    try:
        req = urllib.request.Request(
            f"https://api.github.com/repos/{repo}/releases/tags/{tag}",
            headers=headers
        )
        with urllib.request.urlopen(req, timeout=10) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        if e.code != 404:
            return None

    # Create it
    try:
        body = json.dumps({
            "tag_name": tag,
            "name": ("Skin Thumbnails" if tag == THUMBNAILS_TAG
                     else f"Skin Thumbnails ({thumbnail_shards.shard_number(tag)})"),
            "body": "Auto-generated skin thumbnail images. Do not edit manually.",
            "draft": False,
            "prerelease": True,
        }).encode()
        req = urllib.request.Request(
            f"https://api.github.com/repos/{repo}/releases",
            data=body, headers={**headers, "Content-Type": "application/json"},
            method="POST"
        )
        with urllib.request.urlopen(req, timeout=15) as r:
            return json.loads(r.read())
    except Exception as e:
        print(f"    Failed to create release: {e}", file=sys.stderr)
        return None


def upload_release_asset(upload_url: str, filename: str,
                         data: bytes, token: str) -> str | None:
    """Upload a PNG to a GitHub release. Returns the browser_download_url or None."""
    # upload_url looks like: https://uploads.github.com/repos/.../assets{?name,label}
    base_url = upload_url.split("{")[0]
    url = f"{base_url}?name={filename}"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "image/png",
        "User-Agent": "Provenance-SkinCatalog/1.0",
    }
    global _release_rate_limited
    try:
        req = urllib.request.Request(url, data=data, headers=headers, method="POST")
        with urllib.request.urlopen(req, timeout=30) as r:
            result = json.loads(r.read())
            return result.get("browser_download_url")
    except urllib.error.HTTPError as e:
        body = e.read()
        # 403 with "rate limit exceeded" — stop trying releases for the rest of the run
        if e.code == 403 and b"rate limit" in body.lower():
            print(f"    GitHub API rate limit hit — switching to repo-only storage", file=sys.stderr)
            _release_rate_limited = True
        # 422 = asset already exists with that name
        elif e.code == 422:
            print(f"    Asset {filename} already exists in release", file=sys.stderr)
        else:
            print(f"    Upload failed HTTP {e.code}: {body[:200]}", file=sys.stderr)
    except Exception as e:
        print(f"    Upload failed: {e}", file=sys.stderr)
    return None


# Module-level flag: set to True when GitHub API rate limit is hit.
# Once rate-limited, all subsequent release uploads are skipped and
# repo storage (raw.githubusercontent.com) is used instead.
_release_rate_limited = False


def delete_cached_asset(asset_id: int, token: str):
    """Delete a single release asset by ID (no extra list call needed)."""
    headers = {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {token}",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "Provenance-SkinCatalog/1.0",
    }
    try:
        req = urllib.request.Request(
            f"https://api.github.com/repos/{REPO}/releases/assets/{asset_id}",
            headers=headers, method="DELETE",
        )
        urllib.request.urlopen(req, timeout=10)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# deltastyles.com thumbnail mirror
# ---------------------------------------------------------------------------

def fetch_deltastyles_thumbnail(url: str) -> bytes | None:
    """
    Fetch a deltastyles.com image through the polite client: our own User-Agent,
    1-2 requests at a time, each image once per run, and no retries after a
    403/429 (the host is then left alone until the next run). We don't send a
    browser User-Agent or a Referer to get past their hotlink protection.
    """
    try:
        data = polite_http.get_client().get_bytes(
            url, component="thumbnails", headers={"Accept": "image/png,image/webp,image/*,*/*"})
        # Verify we got an image, not an HTML error page
        if data[:4] in (b'\x89PNG', b'RIFF') or data[:3] == b'\xff\xd8\xff':
            return data
        print(f"    Response doesn't look like an image ({data[:32]})", file=sys.stderr)
    except Exception as e:
        print(f"    Failed to fetch deltastyles thumbnail: {e}", file=sys.stderr)
    return None


# ---------------------------------------------------------------------------
# Main processing
# ---------------------------------------------------------------------------

def process_skin(json_path: str, shards: "thumbnail_shards.ShardSet | None",
                 thumbnails_dir: str, dry_run: bool, force: bool, **kwargs) -> bool:
    """
    Process one skin JSON. Returns True if thumbnail was generated/updated.

    Two paths:
      A) skin has a deltastyles.com/images/ thumbnailURL → mirror it (hotlink bypass)
      B) normal path → download skin ZIP and extract an image asset
    """
    with open(json_path) as f:
        entry = json.load(f)

    skin_id = entry.get("id") or ""
    name = entry.get("name") or json_path
    dl_url = entry.get("downloadURL") or ""
    thumb_url = entry.get("thumbnailURL") or ""

    # deltastyles.com hosts their thumbnails but blocks cross-origin loads (hotlink 403).
    # Re-host those images ourselves so they work on the skins site.
    needs_mirror = "deltastyles.com/images/" in thumb_url

    if not force and thumb_url and not needs_mirror:
        return False  # Already has a self-hosted thumbnail

    if not dl_url and not needs_mirror:
        print(f"  Skipping {name}: no downloadURL")
        return False

    # deltastyles.com files come from the cache link-health.yml hands to this job
    # (or one polite fetch when the run is allowed to fetch). Skip what the host has
    # refused this run, or what isn't cached when the run is cache-only (a push-
    # triggered run); link-health.yml delivers those on its next pass.
    if not needs_mirror and polite_http.get_client().unavailable(dl_url):
        print(f"  Skipping {name}: not in the download cache, and {dl_url.split('/')[2]} "
              f"is only fetched by the link-health run (or refused us); retry next run")
        return False

    print(f"  Processing: {name}")
    info = {}
    landscape_png = None

    if needs_mirror:
        # ── Path A: mirror deltastyles.com thumbnail ──────────────────────────
        print(f"    Mirroring deltastyles thumbnail: {thumb_url}")
        png_bytes = fetch_deltastyles_thumbnail(thumb_url)
        if not png_bytes:
            print(f"    Could not mirror deltastyles thumbnail")
            return False
        # Resize to max 400×400 for grid consistency (no bezel — it's a real screenshot)
        if PIL_AVAILABLE:
            try:
                img = Image.open(io.BytesIO(png_bytes)).convert("RGBA")
                img = _smart_crop(img)
                img = _pad_square(img)
                buf = io.BytesIO()
                img.save(buf, "PNG", optimize=True)
                png_bytes = buf.getvalue()
                print(f"    Resized: {len(png_bytes):,} bytes")
            except Exception as e:
                print(f"    Resize failed ({e}), using original", file=sys.stderr)

    else:
        # ── Path B: extract image from skin ZIP ──────────────────────────────

        # Step 1: Get info.json
        info = stream_extract_info_json(dl_url, GITHUB_TOKEN)
        if not info:
            print(f"    Could not extract info.json")
            return False

        # Step 2: Pick the best portrait representation (correct mappingSize + screens)
        portrait_rep, portrait_mapping = _pick_representation(info, "portrait")
        assets = find_image_assets(info, portrait_rep)
        if not assets:
            print(f"    No image assets found in info.json")
            return False

        print(f"    Assets found: {assets[:3]}")
        if portrait_rep:
            print(f"    Using per-rep mappingSize: {portrait_mapping}")

        # Step 3: Extract the portrait asset
        png_bytes = extract_thumbnail_png(dl_url, assets)

        if not png_bytes:
            print(f"    Could not extract any usable image")
            return False

        # Step 3b: Enhance — fill screens with correct mapping, smart-crop, bezel, square
        if not kwargs.get("no_enhance"):
            png_bytes = enhance_thumbnail(png_bytes, info, portrait_rep, portrait_mapping)

        # Step 3c: Generate landscape screenshot for screenshotURLs
        landscape_png = None
        landscape_rep, landscape_mapping = _pick_representation(info, "landscape")
        if landscape_rep and landscape_rep is not portrait_rep:
            land_assets = find_image_assets(info, landscape_rep)
            # Only generate if it uses a different asset from portrait
            portrait_asset_set = set(assets)
            different_assets = [a for a in land_assets if a not in portrait_asset_set]
            landscape_png = extract_thumbnail_png(dl_url, different_assets)
            if landscape_png and not kwargs.get("no_enhance"):
                landscape_png = enhance_thumbnail(landscape_png, info,
                                                  landscape_rep, landscape_mapping)

    thumb_filename = f"{skin_id}.png"
    land_filename  = f"{skin_id}-landscape.png"

    if dry_run:
        print(f"    [dry-run] Would save {thumb_filename} ({len(png_bytes):,} bytes)")
        if landscape_png:
            print(f"    [dry-run] Would save {land_filename} ({len(landscape_png):,} bytes)")
        return True

    # Step 4a: Save to repo thumbnails dir (always)
    os.makedirs(thumbnails_dir, exist_ok=True)
    local_path = os.path.join(thumbnails_dir, thumb_filename)
    with open(local_path, "wb") as f:
        f.write(png_bytes)
    repo_url = f"{RAW_BASE}/{thumb_filename}"
    print(f"    Saved to repo: {local_path}")

    # Step 4b: Try GitHub Releases upload. The shard (thumbnails, thumbnails-2, ...) is
    # the one already holding the asset, else the first with room for this skin's
    # portrait and landscape images together.
    release_url = None
    shard_tag = None
    if shards and GITHUB_TOKEN and not _release_rate_limited:
        shard_tag = shards.tag_for(thumb_filename, need=2 if landscape_png else 1)
        release_url = shards.upload(thumb_filename, png_bytes, tag=shard_tag)
        if release_url:
            print(f"    Uploaded to release: {release_url}")

    # Step 4c: Save / upload landscape screenshot if generated
    landscape_url = None
    if landscape_png:
        land_local = os.path.join(thumbnails_dir, land_filename)
        with open(land_local, "wb") as f:
            f.write(landscape_png)
        landscape_url = f"{RAW_BASE}/{land_filename}"
        print(f"    Saved landscape to repo: {land_local}")
        if shards and GITHUB_TOKEN and not _release_rate_limited and release_url:
            lu = shards.upload(land_filename, landscape_png, tag=shard_tag)
            if lu:
                landscape_url = lu
                print(f"    Uploaded landscape to release: {lu}")

    # Step 5: Update JSON — prefer release URLs, fallback to repo URLs
    entry["thumbnailURL"] = release_url or repo_url
    # Populate screenshotURLs: landscape view (if generated) goes here
    existing_shots = [u for u in (entry.get("screenshotURLs") or [])
                      if u and not u.endswith(("-landscape.png",))]
    if landscape_url:
        entry["screenshotURLs"] = existing_shots + [landscape_url]
    elif not existing_shots:
        entry["screenshotURLs"] = []
    with open(json_path, "w") as f:
        json.dump(entry, f, indent=2, ensure_ascii=False)
        f.write("\n")

    return True


def raw_thumbnail_names(entry: dict) -> list[str]:
    """File names of this skin's images that are served from the repo's thumbnails/
    folder (the fallback used while the release was full or rate limited): the
    portrait `thumbnailURL` first, then landscape `screenshotURLs`. Only names built
    from the skin's own id count."""
    sid = entry.get("id") or ""
    names = []
    for url in [entry.get("thumbnailURL")] + list(entry.get("screenshotURLs") or []):
        name = thumbnail_shards.parse_raw_url(url, REPO)
        parsed = thumbnail_shards.parse_asset_name(name) if name else None
        if parsed and parsed[0] == sid and name not in names:
            names.append(name)
    return names


def promote_skin(json_path: str, shards: "thumbnail_shards.ShardSet | None",
                 thumbnails_dir: str, dry_run: bool) -> bool:
    """Move a skin's repo-hosted thumbnail URLs onto the release shards, from the
    files already in thumbnails/ (no skin download, no regeneration). The raw files
    stay in the repo, so catalogs that shipped with those URLs keep working. Only a
    URL whose upload succeeded is rewritten. Returns True if the JSON changed (or
    would, in a dry run)."""
    with open(json_path) as f:
        entry = json.load(f)
    names = [n for n in raw_thumbnail_names(entry) if os.path.isfile(os.path.join(thumbnails_dir, n))]
    if not names:
        return False

    portrait = f"{entry.get('id')}.png"
    if dry_run or not shards or not GITHUB_TOKEN or _release_rate_limited:
        for n in names:
            print(f"    [dry-run] Would upload {n} to {shards.tag_for(n) if shards else 'a thumbnail release'}")
        return bool(dry_run)

    tag = shards.tag_for(portrait, need=len(names)) if portrait in names else None
    new_urls: dict[str, str] = {}
    for n in names:
        if _release_rate_limited:
            break
        with open(os.path.join(thumbnails_dir, n), "rb") as f:
            url = shards.upload(n, f.read(), tag=tag)
        if url:
            new_urls[n] = url
            print(f"    Promoted {n}: {url}")
    if not new_urls:
        return False

    def swap(url):
        name = thumbnail_shards.parse_raw_url(url, REPO)
        return new_urls.get(name, url) if name else url

    if entry.get("thumbnailURL"):
        entry["thumbnailURL"] = swap(entry["thumbnailURL"])
    if entry.get("screenshotURLs"):
        entry["screenshotURLs"] = [swap(u) for u in entry["screenshotURLs"]]
    with open(json_path, "w") as f:
        json.dump(entry, f, indent=2, ensure_ascii=False)
        f.write("\n")
    return True


def open_shards(token: str) -> "thumbnail_shards.ShardSet | None":
    """The thumbnail releases and their assets (a few API calls, not N). None when
    they can't be read: uploads then fall back to repo storage."""
    def delete(asset_id):
        delete_cached_asset(asset_id, token)
        time.sleep(0.3)

    try:
        return thumbnail_shards.ShardSet.load(
            create_release=lambda tag: get_or_create_release(REPO, tag, token),
            upload=lambda release, name, data: upload_release_asset(
                release["upload_url"], name, data, token),
            delete=delete, token=token, repo=REPO)
    except Exception as e:
        print(f"  Could not read the thumbnail releases: {e}", file=sys.stderr)
        return None


def main():
    parser = argparse.ArgumentParser(description="Generate skin thumbnails")
    parser.add_argument("--skins-dir", default="skins")
    parser.add_argument("--thumbnails-dir", default=THUMBNAILS_DIR)
    parser.add_argument("--limit", type=int, default=0, help="Max skins to process (0=all)")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--force", action="store_true",
                        help="Regenerate even if thumbnailURL already set")
    parser.add_argument("--no-enhance", action="store_true",
                        help="Skip thumbnail enhancement (raw PNG only)")
    parser.add_argument("--no-release", action="store_true",
                        help="Skip GitHub Releases upload, repo storage only")
    parser.add_argument("--promote", action="store_true",
                        help="Only move thumbnailURLs served from the repo's thumbnails/ folder "
                             "onto the release shards (uses the files already there; use --limit "
                             "to upload in batches)")
    parser.add_argument("--cache-dir", default=None,
                        help="downloaded skin archives (default: $SKIN_CACHE_DIR, else a temp dir)")
    args = parser.parse_args()

    if args.cache_dir:
        polite_http.set_client(polite_http.PoliteClient(cache_dir=args.cache_dir))

    # Find skins needing thumbnails
    to_process = []
    for root, dirs, files in os.walk(args.skins_dir):
        dirs.sort()
        for fname in sorted(files):
            if not fname.endswith(".json"):
                continue
            path = os.path.join(root, fname)
            entry = json.load(open(path))
            thumb = entry.get("thumbnailURL") or ""
            # Process if: forced, no thumbnail, or thumbnail is deltastyles.com-hosted
            # (deltastyles blocks cross-origin image loads — we need to mirror them)
            needs_mirror = "deltastyles.com/images/" in thumb
            if args.promote:
                if raw_thumbnail_names(entry):
                    to_process.append(path)
            elif args.force or not thumb or needs_mirror:
                to_process.append(path)

    print(f"Skins needing thumbnails: {len(to_process)}")
    if args.limit:
        to_process = to_process[:args.limit]
        print(f"Processing first {args.limit}")

    # Read the thumbnail releases and their assets once (a few API calls, not N)
    shards = None
    if not args.dry_run and not args.no_release and GITHUB_TOKEN:
        print("Reading the thumbnail releases...")
        shards = open_shards(GITHUB_TOKEN)
        if shards:
            sizes = shards.sizes()
            print(f"  {len(sizes)} release(s): " + ", ".join(f"{t} ({n})" for t, n in sizes.items()))
        else:
            print("  Could not read the releases — will use repo storage only")
    elif args.promote and not args.dry_run:
        print("--promote needs GITHUB_TOKEN and a release upload; nothing to do", file=sys.stderr)
        return

    # Process each skin
    updated = 0
    failed = 0
    for path in to_process:
        if args.promote and _release_rate_limited:
            print("Rate limited: stopping; run --promote again later for the rest")
            break
        try:
            if args.promote:
                done = promote_skin(path, shards, args.thumbnails_dir, args.dry_run)
            else:
                done = process_skin(path, shards, args.thumbnails_dir, args.dry_run, args.force,
                                    no_enhance=args.no_enhance)
            if done:
                updated += 1
        except Exception as e:
            print(f"  ERROR processing {path}: {e}", file=sys.stderr)
            failed += 1

    print(f"\nDone: {updated} updated, {failed} failed")
    print(polite_http.get_client().summary())

    # Write summary for Actions
    github_output = os.environ.get("GITHUB_OUTPUT")
    if github_output:
        with open(github_output, "a") as f:
            f.write(f"updated={updated}\n")
            f.write(f"failed={failed}\n")

    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_path:
        with open(summary_path, "a") as f:
            f.write(f"## Thumbnail Generation\n\n")
            f.write(f"- **Updated:** {updated}\n")
            f.write(f"- **Failed:** {failed}\n")
            f.write(f"- **Storage:** {'Releases + repo' if shards else 'Repo only'}\n")


if __name__ == "__main__":
    main()
