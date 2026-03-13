#!/usr/bin/env python3
"""
generate_thumbnails.py — Extract thumbnail images from skin files (.deltaskin / .manicskin).

For each skin JSON without a thumbnailURL:
  1. Download the skin ZIP (using range requests where possible)
  2. Parse info.json to find the best portrait image asset (PNG preferred, PDF fallback)
  3. Extract that asset from the ZIP
  4. Convert PDF → PNG via poppler pdftoppm if needed
  5. Upload to GitHub Releases (thumbnails tag) as primary CDN
  6. Also save to thumbnails/{id}.png in the repo as fallback
  7. Update the skin JSON with the release URL (fallback to raw.githubusercontent.com)

Usage:
    python3 scripts/generate_thumbnails.py
    python3 scripts/generate_thumbnails.py --skins-dir skins/ --limit 20
    python3 scripts/generate_thumbnails.py --dry-run
    python3 scripts/generate_thumbnails.py --force   # regenerate even if thumbnailURL already set
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

sys.path.insert(0, str(Path(__file__).parent))
from extract_metadata import stream_extract_info_json, _full_download_extract

GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")
REPO = os.environ.get("GITHUB_REPOSITORY", "Provenance-Emu/skins")
THUMBNAILS_TAG = "thumbnails"
THUMBNAILS_DIR = "thumbnails"
RAW_BASE = f"https://raw.githubusercontent.com/{REPO}/main/{THUMBNAILS_DIR}"


# ---------------------------------------------------------------------------
# info.json asset discovery
# ---------------------------------------------------------------------------

def find_image_assets(info: dict) -> list[str]:
    """
    Walk the representations tree and return all asset filenames found,
    PNGs first, then PDFs.
    """
    pngs = []
    pdfs = []

    def _walk(obj):
        if isinstance(obj, dict):
            for k, v in obj.items():
                if k == "assets" and isinstance(v, dict):
                    for asset_name in v.values():
                        if isinstance(asset_name, str):
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
    # Prefer "resizable" or "small" assets
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
    """Download the skin ZIP and extract a specific asset file from it."""
    try:
        req = urllib.request.Request(
            skin_url,
            headers={"User-Agent": "Provenance-SkinCatalog/1.0",
                     **({"Authorization": f"Bearer {GITHUB_TOKEN}"} if GITHUB_TOKEN else {})}
        )
        with urllib.request.urlopen(req, timeout=30) as r:
            data = r.read()
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
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
            with open(pdf_path, "wb") as f:
                f.write(pdf_bytes)
            result = subprocess.run(
                ["pdftoppm", "-png", "-r", "72", "-singlefile", pdf_path, out_prefix],
                capture_output=True, timeout=15
            )
            if result.returncode != 0:
                # Try ghostscript fallback
                png_path = out_prefix + ".png"
                gs_result = subprocess.run(
                    ["gs", "-dNOPAUSE", "-dBATCH", "-sDEVICE=png16m",
                     "-r72", f"-sOutputFile={png_path}", pdf_path],
                    capture_output=True, timeout=15
                )
                if gs_result.returncode != 0:
                    return None
            else:
                png_path = out_prefix + ".png"
            if os.path.exists(png_path):
                with open(png_path, "rb") as f:
                    return f.read()
    except FileNotFoundError:
        print("    pdftoppm not found — install poppler-utils", file=sys.stderr)
    except Exception as e:
        print(f"    PDF conversion failed: {e}", file=sys.stderr)
    return None


# ---------------------------------------------------------------------------
# GitHub Releases upload
# ---------------------------------------------------------------------------

def get_or_create_release(repo: str, tag: str, token: str) -> dict | None:
    """Get or create the thumbnails release. Returns release dict or None."""
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
            "name": "Skin Thumbnails",
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
    try:
        req = urllib.request.Request(url, data=data, headers=headers, method="POST")
        with urllib.request.urlopen(req, timeout=30) as r:
            result = json.loads(r.read())
            return result.get("browser_download_url")
    except urllib.error.HTTPError as e:
        # 422 = asset already exists with that name
        if e.code == 422:
            print(f"    Asset {filename} already exists in release", file=sys.stderr)
        else:
            print(f"    Upload failed HTTP {e.code}: {e.read()[:200]}", file=sys.stderr)
    except Exception as e:
        print(f"    Upload failed: {e}", file=sys.stderr)
    return None


def delete_existing_asset(repo: str, release_id: int,
                           filename: str, token: str):
    """Delete an existing release asset by filename so we can re-upload."""
    headers = {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {token}",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "Provenance-SkinCatalog/1.0",
    }
    try:
        req = urllib.request.Request(
            f"https://api.github.com/repos/{repo}/releases/{release_id}/assets",
            headers=headers
        )
        with urllib.request.urlopen(req, timeout=10) as r:
            assets = json.loads(r.read())
        for asset in assets:
            if asset["name"] == filename:
                del_req = urllib.request.Request(
                    f"https://api.github.com/repos/{repo}/releases/assets/{asset['id']}",
                    headers=headers, method="DELETE"
                )
                urllib.request.urlopen(del_req, timeout=10)
                return
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Main processing
# ---------------------------------------------------------------------------

def process_skin(json_path: str, release: dict | None,
                 thumbnails_dir: str, dry_run: bool, force: bool) -> bool:
    """
    Process one skin JSON. Returns True if thumbnail was generated/updated.
    """
    with open(json_path) as f:
        entry = json.load(f)

    skin_id = entry.get("id", "")
    name = entry.get("name", json_path)
    dl_url = entry.get("downloadURL", "")

    if not force and entry.get("thumbnailURL"):
        return False  # Already has one

    if not dl_url:
        print(f"  Skipping {name}: no downloadURL")
        return False

    print(f"  Processing: {name}")

    # Step 1: Get info.json
    info = stream_extract_info_json(dl_url, GITHUB_TOKEN)
    if not info:
        print(f"    Could not extract info.json")
        return False

    # Step 2: Find best image asset
    assets = find_image_assets(info)
    if not assets:
        print(f"    No image assets found in info.json")
        return False

    print(f"    Assets found: {assets[:3]}")

    # Step 3: Extract the asset
    png_bytes = None
    for asset in assets:
        raw = extract_asset_from_url(dl_url, asset)
        if not raw:
            continue
        if asset.lower().endswith(".png"):
            png_bytes = raw
            print(f"    Extracted PNG: {asset} ({len(raw):,} bytes)")
            break
        elif asset.lower().endswith(".pdf"):
            print(f"    Converting PDF: {asset} ({len(raw):,} bytes)")
            png_bytes = pdf_to_png(raw)
            if png_bytes:
                print(f"    Converted to PNG ({len(png_bytes):,} bytes)")
                break

    if not png_bytes:
        print(f"    Could not extract any usable image")
        return False

    thumb_filename = f"{skin_id}.png"

    if dry_run:
        print(f"    [dry-run] Would save {thumb_filename} ({len(png_bytes):,} bytes)")
        return True

    # Step 4a: Save to repo thumbnails dir (always)
    os.makedirs(thumbnails_dir, exist_ok=True)
    local_path = os.path.join(thumbnails_dir, thumb_filename)
    with open(local_path, "wb") as f:
        f.write(png_bytes)
    repo_url = f"{RAW_BASE}/{thumb_filename}"
    print(f"    Saved to repo: {local_path}")

    # Step 4b: Try GitHub Releases upload
    release_url = None
    if release and GITHUB_TOKEN:
        # Delete existing asset if any (so we can re-upload)
        delete_existing_asset(REPO, release["id"], thumb_filename, GITHUB_TOKEN)
        time.sleep(0.5)  # brief pause to avoid rate limits
        release_url = upload_release_asset(
            release["upload_url"], thumb_filename, png_bytes, GITHUB_TOKEN
        )
        if release_url:
            print(f"    Uploaded to release: {release_url}")

    # Step 5: Update JSON — prefer release URL, fallback to repo URL
    entry["thumbnailURL"] = release_url or repo_url
    with open(json_path, "w") as f:
        json.dump(entry, f, indent=2, ensure_ascii=False)
        f.write("\n")

    return True


def main():
    parser = argparse.ArgumentParser(description="Generate skin thumbnails")
    parser.add_argument("--skins-dir", default="skins")
    parser.add_argument("--thumbnails-dir", default=THUMBNAILS_DIR)
    parser.add_argument("--limit", type=int, default=0, help="Max skins to process (0=all)")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--force", action="store_true",
                        help="Regenerate even if thumbnailURL already set")
    parser.add_argument("--no-release", action="store_true",
                        help="Skip GitHub Releases upload, repo storage only")
    args = parser.parse_args()

    # Find skins needing thumbnails
    to_process = []
    for root, dirs, files in os.walk(args.skins_dir):
        dirs.sort()
        for fname in sorted(files):
            if not fname.endswith(".json"):
                continue
            path = os.path.join(root, fname)
            entry = json.load(open(path))
            if args.force or not entry.get("thumbnailURL"):
                to_process.append(path)

    print(f"Skins needing thumbnails: {len(to_process)}")
    if args.limit:
        to_process = to_process[:args.limit]
        print(f"Processing first {args.limit}")

    # Get/create GitHub release
    release = None
    if not args.dry_run and not args.no_release and GITHUB_TOKEN:
        print("Getting thumbnails release...")
        release = get_or_create_release(REPO, THUMBNAILS_TAG, GITHUB_TOKEN)
        if release:
            print(f"  Release: {release.get('html_url')}")
        else:
            print("  Could not get/create release — will use repo storage only")

    # Process each skin
    updated = 0
    failed = 0
    for path in to_process:
        try:
            if process_skin(path, release, args.thumbnails_dir, args.dry_run, args.force):
                updated += 1
        except Exception as e:
            print(f"  ERROR processing {path}: {e}", file=sys.stderr)
            failed += 1

    print(f"\nDone: {updated} updated, {failed} failed")

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
            f.write(f"- **Storage:** {'Releases + repo' if release else 'Repo only'}\n")


if __name__ == "__main__":
    main()
