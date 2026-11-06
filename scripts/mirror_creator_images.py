#!/usr/bin/env python3
"""
mirror_creator_images.py — fetch a creator's avatar and banner once, resize
them, and publish the copies to the `creators` GitHub Release.

Pages and apps load the mirrored copy and never the creator-supplied URL, so a
dead or swapped origin image cannot break or vandalise a profile later
(design §1, SkinKit docs/specs/2026-11-03-creator-profiles-design.md).

  - The URL must pass `creator_policy.url_problem` (https, no IP literal, no
    denied host), on every redirect hop too, and its host must resolve to a
    public address.
  - The body is at most 2 MB and must decode as PNG, JPEG, GIF or WebP
    (SVG is refused).
  - Avatar: 256x256, banner: 1200x400, both centre-cropped to fill and saved as PNG.
  - Assets are `<slug>-avatar.png` and `<slug>-banner.png` on release tag
    `creators`; `mirror_url()` is the address the site and apps load.

Used by process_claim.py; also runnable on its own:

    python3 scripts/mirror_creator_images.py aphaits --avatar https://github.com/aphaits.png [--dry-run]
"""

import argparse
import io
import ipaddress
import os
import socket
import sys
import tempfile
import urllib.error
from pathlib import Path
from urllib.parse import urljoin, urlsplit

sys.path.insert(0, str(Path(__file__).parent))
import polite_http
from creator_policy import url_problem
from github_ownership import default_run

REPO = "Provenance-Emu/skins"
RELEASE_TAG = "creators"
MAX_BYTES = 2 * 1024 * 1024
MAX_PIXELS = 24_000_000          # refuse decompression bombs before decoding
MAX_REDIRECTS = 4
SIZES = {"avatar": (256, 256), "banner": (1200, 400)}
ALLOWED_FORMATS = {"PNG", "JPEG", "GIF", "WEBP"}


class ImageError(Exception):
    """The image can't be mirrored; the message is safe to show the creator."""


def asset_name(slug: str, kind: str) -> str:
    return f"{slug}-{kind}.png"


def mirror_url(slug: str, kind: str, repo: str = REPO) -> str:
    return f"https://github.com/{repo}/releases/download/{RELEASE_TAG}/{asset_name(slug, kind)}"


def _resolve_public(host: str) -> "str | None":
    """Why `host` can't be fetched, or None. Every address it resolves to must be public."""
    try:
        infos = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
    except OSError:
        return f"{host} doesn't resolve"
    for info in infos:
        try:
            ip = ipaddress.ip_address(info[4][0])
        except ValueError:
            return f"{host} resolves to an unusable address"
        if not ip.is_global:
            return f"{host} resolves to a private address"
    return None


def fetch_image_bytes(url: str, *, client=None, resolve=_resolve_public) -> bytes:
    """GET `url` (following up to MAX_REDIRECTS hops, each checked) and return the body.
    Raises ImageError. `client` is a polite_http.PoliteClient; `resolve` checks a host."""
    client = client or polite_http.get_client()
    current = url
    for _ in range(MAX_REDIRECTS + 1):
        problem = url_problem(current, "image URL")
        if problem:
            raise ImageError(problem)
        problem = resolve(urlsplit(current).hostname or "")
        if problem:
            raise ImageError(f"image URL: {problem}")
        try:
            resp = client.request(current, follow_redirects=False, max_bytes=MAX_BYTES + 1,
                                  component="creator-images")
        except urllib.error.HTTPError as e:
            raise ImageError(f"{current} returned HTTP {e.code}")
        except polite_http.HostBlocked as e:
            raise ImageError(f"{urlsplit(current).hostname} is refusing requests right now ({e})")
        except (OSError, ValueError) as e:
            raise ImageError(f"couldn't download {current}: {e}")
        if 300 <= resp.status < 400:
            location = resp.headers.get("location")
            if not location:
                raise ImageError(f"{current} redirected without a location")
            current = urljoin(current, location)
            continue
        if len(resp.body) > MAX_BYTES:
            raise ImageError(f"image is larger than {MAX_BYTES // (1024 * 1024)} MB")
        return resp.body
    raise ImageError("too many redirects")


def resize_image(data: bytes, kind: str) -> bytes:
    """Decode `data`, centre-crop to the size for `kind`, return PNG bytes."""
    from PIL import Image, ImageOps, UnidentifiedImageError

    if kind not in SIZES:
        raise ValueError(f"unknown image kind {kind!r}")
    if len(data) > MAX_BYTES:
        raise ImageError(f"image is larger than {MAX_BYTES // (1024 * 1024)} MB")
    try:
        with Image.open(io.BytesIO(data)) as img:
            if img.format not in ALLOWED_FORMATS:
                raise ImageError(f"{kind} must be a PNG, JPEG, GIF or WebP image")
            if img.width * img.height > MAX_PIXELS:
                raise ImageError(f"{kind} is {img.width}x{img.height}; the limit is {MAX_PIXELS // 1_000_000} megapixels")
            img.load()
            img = ImageOps.exif_transpose(img)
            has_alpha = "A" in img.getbands() or "transparency" in img.info
            img = img.convert("RGBA" if has_alpha else "RGB")
            out = ImageOps.fit(img, SIZES[kind], method=Image.LANCZOS)
    except ImageError:
        raise
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError):
        raise ImageError(f"{kind} isn't an image I can read")
    buf = io.BytesIO()
    out.save(buf, "PNG", optimize=True)
    return buf.getvalue()


def prepare(url: str, kind: str, *, client=None, resolve=_resolve_public) -> bytes:
    """Fetch and resize one image. Raises ImageError with a message naming `kind`."""
    try:
        return resize_image(fetch_image_bytes(url, client=client, resolve=resolve), kind)
    except ImageError as e:
        if kind in str(e):
            raise
        raise ImageError(f"{kind}: {e}")


def upload(run, repo: str, slug: str, images: "dict[str, bytes]", dry_run: bool = False) -> list[str]:
    """Publish `images` ({kind: png bytes}) to the `creators` release, creating it
    on first use and replacing assets of the same name. Returns asset names.
    Raises RuntimeError when `gh` fails."""
    names = [asset_name(slug, kind) for kind in images]
    if dry_run:
        for name in names:
            print(f"  [dry-run] gh release upload {RELEASE_TAG} {name} --clobber --repo {repo}")
        return names
    if not images:
        return []
    if run(["gh", "release", "view", RELEASE_TAG, "--repo", repo]).returncode != 0:
        r = run(["gh", "release", "create", RELEASE_TAG, "--repo", repo, "--prerelease",
                 "--title", "Creator images",
                 "--notes", "Avatars and banners mirrored by the claim bot. Do not edit manually."])
        if r.returncode != 0:
            raise RuntimeError(f"could not create the `{RELEASE_TAG}` release: {(r.stderr or '').strip()}")
    with tempfile.TemporaryDirectory() as tmp:
        for kind, data in images.items():
            path = os.path.join(tmp, asset_name(slug, kind))
            with open(path, "wb") as f:
                f.write(data)
            r = run(["gh", "release", "upload", RELEASE_TAG, path, "--clobber", "--repo", repo])
            if r.returncode != 0:
                raise RuntimeError(f"could not upload {asset_name(slug, kind)}: {(r.stderr or '').strip()}")
    return names


def main():
    parser = argparse.ArgumentParser(description="Mirror a creator's avatar/banner to the `creators` release")
    parser.add_argument("slug")
    parser.add_argument("--avatar", help="https URL of the avatar")
    parser.add_argument("--banner", help="https URL of the banner")
    parser.add_argument("--repo", default=os.environ.get("GITHUB_REPOSITORY", REPO))
    parser.add_argument("--dry-run", action="store_true", help="fetch and resize, upload nothing")
    args = parser.parse_args()
    if not (args.avatar or args.banner):
        parser.error("give --avatar and/or --banner")

    images = {}
    try:
        for kind in ("avatar", "banner"):
            url = getattr(args, kind)
            if url:
                images[kind] = prepare(url, kind)
                print(f"{kind}: {len(images[kind])} bytes after resize")
        for name in upload(default_run, args.repo, args.slug, images, dry_run=args.dry_run):
            print(f"published {name}")
    except (ImageError, RuntimeError) as e:
        print(f"error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
