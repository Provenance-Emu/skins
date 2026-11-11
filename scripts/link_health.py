#!/usr/bin/env python3
"""
link_health.py — Check every skin download the way Provenance installs it.

The app (SkinCatalogDetailView.downloadSkin + DeltaSkin.init) fails a catalog
install when:
  - the final HTTP status is not 2xx
  - the body is not a ZIP archive
  - the archive has no `info.json` at its root, or it does not parse

Every skin whose info.json it reads also gets a record in `variants.json`
(see variants_sidecar.py), pass or fail. Variant artwork (alt layouts, theme
assets and theme item art, per-game layouts) is checked like base artwork, but a gap only lands
under `partialArtwork`: the base layout still works, so nothing is hidden.

Results go to `link-health.json`. Only failing entries are recorded; an entry
that passes again is dropped from the file. A skin missing artwork for every
layout fails; one missing it for only some layouts stays listed and is
recorded under `partialArtwork`. `build_catalog.py` hides an entry
once it has failed with a deterministic error on `HIDE_AFTER` consecutive
runs, and only while its downloadURL still matches the URL that was checked.

Usage:
    python3 scripts/link_health.py                    # check all, update link-health.json
    python3 scripts/link_health.py --ids a1b2,c3d4    # check a subset
    python3 scripts/link_health.py --force            # skip the circuit breaker
"""

import argparse
import io
import json
import os
import random
import re
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import polite_http
from verify_format2 import verify_format2
from variants_sidecar import VARIANTS_FILE, compute_variants, has_dual_screen, load_variants, save_variants, update_from_results

HEALTH_FILE = "link-health.json"
HIDE_AFTER = 2
# Abort without writing when more than this share of checked skins newly
# fails in one run — that is an outage or a block, not 200 dead links.
MAX_NEW_FAILURE_RATIO = 0.10
MAX_FULL_DOWNLOAD = 150 * 1024 * 1024
_UA = polite_http.user_agent("link-health")

# Deterministic failures: the same URL will fail the same way next week.
PERMANENT = {
    "http_404", "http_410", "not_zip", "bad_zip", "no_info_json",
    "bad_info_json", "info_missing_keys", "pack", "nested_folder",
    "missing_artwork", "invalid_format2",
}
# Failures `repack_skins.py` can fix by extracting the inner skin(s).
REPACKABLE = {"pack", "nested_folder"}

# Not a verdict on the skin: the host refused us, so it was not checked this run.
# Such skins are left out of the run (their old records stay) and never hide anything.
HOST_BLOCKED = "host_blocked"

REQUIRED_INFO_KEYS = ("identifier", "name", "gameTypeIdentifier", "representations")
SKIN_EXTS = (".deltaskin", ".manicskin")


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------

def encode_url(url: str) -> str:
    """Percent-encode the characters iOS 17's URL(string:) would encode.

    `#` is left alone on purpose: URL(string:) treats it as a fragment too,
    so a filename containing `#` fails in the app and should fail here.
    """
    return urllib.parse.quote(url, safe=":/?&=%#+@!$,;~*'()[]")


def _request(url: str, byte_range: str = None, timeout: int = 40):
    headers = {"User-Agent": _UA}
    if byte_range:
        headers["Range"] = byte_range
    req = urllib.request.Request(url, headers=headers)
    return urllib.request.urlopen(req, timeout=timeout, context=ssl.create_default_context())


class RangeFile(io.RawIOBase):
    """Seekable file over HTTP range requests, so zipfile reads only the index."""

    def __init__(self, url: str, size: int):
        self.url, self.size, self.pos = url, size, 0

    def seekable(self):
        return True

    def readable(self):
        return True

    def tell(self):
        return self.pos

    def seek(self, offset, whence=0):
        if whence == 0:
            self.pos = offset
        elif whence == 1:
            self.pos += offset
        else:
            self.pos = self.size + offset
        return self.pos

    def read(self, n=-1):
        if n is None or n < 0:
            n = self.size - self.pos
        if n <= 0 or self.pos >= self.size:
            return b""
        end = min(self.pos + n, self.size) - 1
        with _request(self.url, f"bytes={self.pos}-{end}") as r:
            data = r.read()
        self.pos += len(data)
        return data

    def readinto(self, b):
        data = self.read(len(b))
        b[:len(data)] = data
        return len(data)


def open_remote_zip(url: str):
    """Return (ZipFile or None, detail dict). Raises urllib errors."""
    client = polite_http.get_client()
    if client.is_polite(url):
        # deltastyles.com: one polite download per URL per run, shared with the
        # thumbnail and repack steps; the zip is then read from the local copy.
        f = client.get_file(url, component="link-health", max_bytes=MAX_FULL_DOWNLOAD)
        detail = {"finalURL": f.final_url, "contentType": f.content_type}
        with open(f.path, "rb") as fh:
            if fh.read(4) != b"PK\x03\x04":
                return None, detail
        return zipfile.ZipFile(f.path), detail
    r = _request(url, "bytes=0-3")
    detail = {"finalURL": r.geturl(), "contentType": r.headers.get("Content-Type", "")}
    head = r.read(4)
    if r.status == 206:
        content_range = r.headers.get("Content-Range", "")
        r.close()
        if head != b"PK\x03\x04":
            return None, detail
        total = content_range.rsplit("/", 1)[-1]
        if total.isdigit():
            return zipfile.ZipFile(RangeFile(detail["finalURL"], int(total))), detail
        r = _request(url)
        head = b""
    # Server ignored the range: read the whole body.
    body = head + r.read(MAX_FULL_DOWNLOAD)
    r.close()
    if not body.startswith(b"PK\x03\x04"):
        return None, detail
    return zipfile.ZipFile(io.BytesIO(body)), detail


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------

def parse_info_json(raw: bytes) -> dict:
    """Parse info.json as leniently as Foundation does.

    The app strips `//` comment lines (sanitizeJSON) and Apple's JSON parser
    accepts trailing commas, so neither counts as a failure here.
    """
    text = raw.decode("utf-8-sig")
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    lines = []
    for line in text.splitlines():
        if '"_comment"' not in line and "//" in line:
            line = line[:line.index("//")]
        lines.append(line)
    text = re.sub(r",(\s*[}\]])", r"\1", "\n".join(lines))
    return json.loads(text)


def _is_junk(name: str) -> bool:
    return name.startswith("__MACOSX/") or name.rsplit("/", 1)[-1] == ".DS_Store"


def classify_archive(zf: zipfile.ZipFile, *, record_device_support: bool = False) -> dict:
    """Classify an opened archive. Returns {"result": ..., ...}."""
    try:
        names = [n for n in zf.namelist() if not _is_junk(n)]
    except zipfile.BadZipFile as e:
        return {"result": "bad_zip", "error": str(e)[:200]}

    if "info.json" not in names:
        inner = inner_skin_paths(names)
        if inner:
            return {"result": "pack", "inner": inner}
        nested = [n for n in names if n.endswith("/info.json")]
        if nested:
            return {"result": "nested_folder", "inner": nested[:5]}
        return {"result": "no_info_json", "sample": names[:8]}

    try:
        info = parse_info_json(zf.read("info.json"))
    except Exception as e:
        return {"result": "bad_info_json", "error": str(e)[:200]}
    if not isinstance(info, dict):
        return {"result": "bad_info_json", "error": "info.json is not an object"}
    # info.json was read: whatever the verdict, the sidecar learns its variants.
    variants = compute_variants(info)
    # Present only when true, like the sidecar record it feeds.
    seen = {"variants": variants, **({"dualScreen": True} if has_dual_screen(info) else {})}
    missing = [k for k in REQUIRED_INFO_KEYS if k not in info]
    if missing:
        return {"result": "info_missing_keys", "missing": missing, **seen}

    if "format2" in info:
        verdict = verify_format2(zf, info)
        if verdict.get("unavailable"):
            return {"result": "format2_check_unavailable", "error": verdict["error"]}
        if not verdict["ok"]:
            return {"result": "invalid_format2", "error": verdict["error"][:200], **seen}
        seen["format2"] = True

    layouts = list(_layouts(info.get("representations")))
    files = [n for n in zf.namelist() if not n.endswith("/")]
    broken = []
    device_support = set()
    for name, assets in layouts:
        if not _has_artwork(files, assets):
            broken.append(name)
            continue
        parts = name.split("/")
        if record_device_support and len(parts) == 3:
            device, _, orientation = parts
            if device in {"iphone", "ipad", "tv"} and orientation in {"portrait", "landscape"}:
                device_support.update((device, f"{device}-{orientation}"))
    if device_support:
        seen["deviceSupport"] = sorted(device_support)
    if broken and len(broken) == len(layouts):
        return {"result": "missing_artwork", "layouts": broken, **seen}
    # Variant artwork never hides a skin; its gaps join the partial list.
    variant_layouts = list(_variant_layouts(info))
    broken += [name for name, assets, strict in variant_layouts
               if not _variant_has_artwork(files, assets, strict)]
    # Theme item art (`items` beside a theme's backgrounds) gets the same flag-only check.
    broken += _theme_item_gaps(files, info)
    if broken:
        # Still installs and works in its other layouts, so it stays listed;
        # link-health.json records the gaps under `partialArtwork`.
        return {"result": "ok", "partialArtwork": broken,
                "layoutCount": len(layouts) + len(variant_layouts), **seen}
    return {"result": "ok", **seen}


ASSET_SIZE_KEYS = ("resizable", "large", "medium", "small")


# Keys of the app's OrientationRepresentations. A dict with any of them is a
# layout; the app decodes `assets` with decodeIfPresent, so a layout without
# it loads and draws nothing.
LAYOUT_KEYS = {"assets", "items", "screens", "mappingSize", "extendedEdges",
               "translucent", "gameScreenFrame", "backgroundAnimation"}


def _layouts(representations, path=()):
    """Yield ("iphone/edgeToEdge/portrait", assets) for every layout.

    Representations nest device → display type → orientation. `assets` is
    {} when the layout omits it or it isn't an object.
    """
    if not isinstance(representations, dict):
        return
    if LAYOUT_KEYS & representations.keys():
        assets = representations.get("assets")
        yield "/".join(path), assets if isinstance(assets, dict) else {}
        return
    for key, value in representations.items():
        yield from _layouts(value, path + (str(key),))


def _variant_layouts(info: dict):
    """Yield (label, assets, strict) for every variant layout in an info.json.

    Labels carry the variant: "alt:iphone/standard/portrait",
    "theme:dark:iphone/standard/portrait", "game:Doom:iphone/standard/portrait".
    `alt` and `game` hold whole representations, checked like base layouts
    (`strict`: a layout naming no artwork is a gap). A theme holds artwork
    only (device -> display type -> orientation -> assets) and may override
    just some layouts, so one that names no files is not a gap.
    """
    alt = info.get("altRepresentations")
    for name, assets in _layouts(alt):
        yield f"alt:{name}", assets, True

    themes = info.get("themes")
    for theme in themes if isinstance(themes, list) else []:
        if not isinstance(theme, dict) or not isinstance(theme.get("assets"), dict):
            continue
        for device, displays in theme["assets"].items():
            for display, orientations in (displays.items() if isinstance(displays, dict) else ()):
                for orientation, assets in (orientations.items() if isinstance(orientations, dict) else ()):
                    if isinstance(assets, dict):
                        yield f"theme:{theme.get('id')}:{device}/{display}/{orientation}", assets, False

    games = info.get("gameOverrides")
    for game, representations in games.items() if isinstance(games, dict) else ():
        for name, assets in _layouts(representations):
            yield f"game:{game}:{name}", assets, True


def _theme_item_gaps(files: list[str], info: dict) -> list[str]:
    """Labels of theme item artwork the archive lacks, e.g. "theme:red:iphone/standard/portrait:item 3".

    A theme layout's `assets.items` maps an item index to the art that replaces
    it, `{"3": {"resizable": "red__stick.png"}}` (merge_variants --item-art-themes).
    An entry naming no file at all is not a gap, as with theme backgrounds.
    """
    gaps = []
    themes = info.get("themes")
    for theme in themes if isinstance(themes, list) else []:
        if not isinstance(theme, dict) or not isinstance(theme.get("assets"), dict):
            continue
        for device, displays in theme["assets"].items():
            for display, orientations in (displays.items() if isinstance(displays, dict) else ()):
                for orientation, assets in (orientations.items() if isinstance(orientations, dict) else ()):
                    items = assets.get("items") if isinstance(assets, dict) else None
                    for index, art in (items.items() if isinstance(items, dict) else ()):
                        if isinstance(art, dict) and not _variant_has_artwork(files, art, False):
                            gaps.append(f"theme:{theme.get('id')}:{device}/{display}/{orientation}:item {index}")
    return gaps


def _variant_has_artwork(files: list[str], assets: dict, strict: bool) -> bool:
    if not strict and not any(isinstance(assets.get(k), str) and assets[k] for k in ASSET_SIZE_KEYS):
        return True
    return _has_artwork(files, assets)


def find_asset(files: list[str], filename: str):
    """Mirror Archive.entry(matchingAssetNamed:) in the app's DeltaSkin.swift.

    Exact path, then a case-insensitive match on the file name anywhere in
    the archive, then the same stem as .pdf, .png or .svg.
    """
    if filename in files:
        return filename
    wanted = filename.rsplit("/", 1)[-1].lower()
    if not wanted:
        return None
    by_name = {}
    for f in files:
        by_name.setdefault(f.rsplit("/", 1)[-1].lower(), f)
    if wanted in by_name:
        return by_name[wanted]
    stem = wanted.rsplit(".", 1)[0] if "." in wanted else wanted
    for ext in ("pdf", "png", "svg"):
        candidate = f"{stem}.{ext}"
        if candidate != wanted and candidate in by_name:
            return by_name[candidate]
    return None


def _has_artwork(files: list[str], assets: dict) -> bool:
    """The app tries resizable, large, medium, small and uses the first it finds."""
    names = [assets[k] for k in ASSET_SIZE_KEYS if isinstance(assets.get(k), str) and assets[k]]
    return any(find_asset(files, n) for n in names)


def inner_skin_paths(names: list[str]) -> list[str]:
    """Skins packed inside an archive: files, or folders (`X.deltaskin/`)."""
    out = []
    for n in names:
        lower = n.lower()
        if lower.endswith(SKIN_EXTS):
            out.append(n)
        else:
            # Folder skin: any entry under a `*.deltaskin/` directory.
            m = re.match(r"(.*?\.(?:deltaskin|manicskin)/)", n, re.IGNORECASE)
            if m and m.group(1) not in out:
                out.append(m.group(1))
    return out


def check_url(url: str) -> dict:
    try:
        zf, detail = open_remote_zip(encode_url(url))
    except polite_http.HostBlocked as e:
        return {"result": HOST_BLOCKED, "host": e.host, "status": e.status, "url": e.url}
    except urllib.error.HTTPError as e:
        return {"result": f"http_{e.code}"}
    except Exception as e:
        return {"result": "network_error", "error": f"{type(e).__name__}: {e}"[:200]}
    if zf is None:
        return {"result": "not_zip", "contentType": detail.get("contentType")}
    try:
        return classify_archive(zf, record_device_support=True)
    except Exception as e:
        return {"result": "network_error", "error": f"{type(e).__name__}: {e}"[:200]}
    finally:
        zf.close()


# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------

def load_health(path: str) -> dict:
    if not os.path.exists(path):
        return {"lastRun": None, "skins": {}}
    with open(path) as f:
        return json.load(f)


def is_hidden(record: dict, download_url: str) -> bool:
    """Whether build_catalog should drop the entry this record belongs to."""
    if not record or record.get("url") != download_url:
        return False
    return record.get("result") in PERMANENT and record.get("failures", 0) >= HIDE_AFTER


def update_health(health: dict, skins: list[dict], results: dict[str, dict], today: str) -> dict:
    """Fold one run's results into the state. Returns the new state."""
    old = health.get("skins", {})
    new = {}
    checked = {s["id"] for s in skins}
    for skin in skins:
        sid, url = skin["id"], skin["downloadURL"]
        res = results[sid]
        if res["result"] == "ok":
            continue
        prev = old.get(sid)
        same = prev and prev.get("url") == url and prev.get("result") == res["result"]
        new[sid] = {
            "url": url,
            **{k: v for k, v in res.items() if k not in ("variants", "dualScreen", "format2", "deviceSupport")},
            "failures": prev["failures"] + 1 if same else 1,
            "firstFailedAt": prev["firstFailedAt"] if same else today,
            "lastCheckedAt": today,
        }
    # Keep records for skins this run did not check (subset runs).
    for sid, rec in old.items():
        if sid not in checked:
            new[sid] = rec

    # A record goes away only when the archive was inspected and the gap is
    # gone; a network error or 5xx this run says nothing about the artwork.
    partial = dict(health.get("partialArtwork", {}))
    for skin in skins:
        res = results[skin["id"]]
        if res["result"] == "ok" and not res.get("partialArtwork"):
            partial.pop(skin["id"], None)
        elif res["result"] in PERMANENT:
            partial.pop(skin["id"], None)  # tracked as a failure instead
        if res.get("partialArtwork"):
            partial[skin["id"]] = {"url": skin["downloadURL"], "layouts": res["partialArtwork"],
                                   "layoutCount": res["layoutCount"], "lastCheckedAt": today}
    return {"lastRun": today, "skins": dict(sorted(new.items())),
            "partialArtwork": dict(sorted(partial.items()))}


def check_all(skins: list[dict], workers: int = 8, client=None) -> dict[str, dict]:
    """Check every skin. deltastyles.com downloads go through their own pool of
    1-2 workers (the polite client also caps and spaces them); everything else
    keeps the wide pool. Returns {skin id: result}.

    The polite-host order is shuffled: if one file always makes the host refuse
    us, the same skins don't go unchecked every week."""
    client = client or polite_http.get_client()
    slow = [s for s in skins if client.is_polite(s["downloadURL"])]
    random.shuffle(slow)
    fast = [s for s in skins if not client.is_polite(s["downloadURL"])]
    with ThreadPoolExecutor(workers) as fast_pool, ThreadPoolExecutor(client.concurrency) as slow_pool:
        futures = [(s, slow_pool.submit(check_url, s["downloadURL"])) for s in slow]
        futures += [(s, fast_pool.submit(check_url, s["downloadURL"])) for s in fast]
        return {s["id"]: f.result() for s, f in futures}


def needs_thumbnail(entry: dict) -> bool:
    """Skins generate_thumbnails.py will build from the archive (no thumbnail yet)."""
    return not entry.get("thumbnailURL")


def load_skins(skins_dir: str) -> list[dict]:
    out = []
    for path in sorted(Path(skins_dir).rglob("*.json")):
        with open(path) as f:
            entry = json.load(f)
        if entry.get("id") and entry.get("downloadURL"):
            entry["_source_file"] = str(path)
            out.append(entry)
    return out


def main():
    parser = argparse.ArgumentParser(description="Check skin download links")
    parser.add_argument("--skins-dir", default="skins")
    parser.add_argument("--health-file", default=HEALTH_FILE)
    parser.add_argument("--ids", help="Comma-separated skin ids to check (default: all)")
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--variants-file", default=VARIANTS_FILE,
                        help="Sidecar of single-file variants found in each inspected archive")
    parser.add_argument("--force", action="store_true", help="Write even if the circuit breaker trips")
    parser.add_argument("--cache-dir", default=None,
                        help="download cache shared with the other steps (default: $SKIN_CACHE_DIR, else a temp dir)")
    parser.add_argument("--polite-workers", type=int, default=None,
                        help="concurrent deltastyles.com downloads, 1 or 2 (default 2)")
    parser.add_argument("--export-cache", default=None,
                        help="copy cached archives of skins that still need a thumbnail here (for generate-thumbnails.yml)")
    parser.add_argument("--cache-max-mb", type=int, default=3072,
                        help="prune the cache to this size at the end of the run")
    args = parser.parse_args()

    if args.cache_dir or args.polite_workers:
        polite_http.set_client(polite_http.PoliteClient(
            cache_dir=args.cache_dir or os.environ.get("SKIN_CACHE_DIR") or None,
            concurrency=args.polite_workers or polite_http.MAX_POLITE_CONCURRENCY))
    client = polite_http.get_client()

    skins = load_skins(args.skins_dir)
    catalog_ids = {s["id"] for s in skins}
    if args.ids:
        wanted = set(args.ids.split(","))
        skins = [s for s in skins if s["id"] in wanted]
    print(f"Checking {len(skins)} skins...")

    results = check_all(skins, args.workers, client)

    # A host that refused us isn't a verdict on its skins: leave them out of this
    # run entirely so their old records stay and the failure ratio ignores them.
    refused = [s for s in skins if results[s["id"]]["result"] == HOST_BLOCKED]
    if refused:
        skins = [s for s in skins if results[s["id"]]["result"] != HOST_BLOCKED]
        first = next(r for r in (results[s["id"]] for s in refused) if r.get("url"))
        print(f"::warning::{first['host']} refused us (HTTP {first['status']}, first at {first['url']}); "
              f"{len(refused)} skin(s) not checked this run")
    print(client.summary())

    # Variants come from archives that were read, so a tripped breaker does not
    # make them wrong; they are written either way.
    sidecar = load_variants(args.variants_file)
    stats = update_from_results(sidecar, skins, results, PERMANENT, prune=not args.ids,
                                live_ids=catalog_ids)
    save_variants(sidecar, args.variants_file)
    print(f"Variants: {len(sidecar)} skins with variants "
          f"({stats['recorded']} recorded or changed, {stats['dropped']} dropped)")

    health = load_health(args.health_file)
    old = health.get("skins", {})
    failing = [s for s in skins if results[s["id"]]["result"] != "ok"]
    newly = [s for s in failing if s["id"] not in old]
    ratio = len(newly) / len(skins) if skins else 0
    print(f"{len(failing)} failing, {len(newly)} newly failing ({ratio:.1%})")

    tripped = ratio > MAX_NEW_FAILURE_RATIO and not args.force
    if tripped:
        print(f"Circuit breaker: more than {MAX_NEW_FAILURE_RATIO:.0%} newly failing. "
              f"Not writing {args.health_file}.", file=sys.stderr)
    else:
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        health = update_health(health, skins, results, today)
        with open(args.health_file, "w") as f:
            json.dump(health, f, indent=2, ensure_ascii=False)
            f.write("\n")

    by_id = {s["id"]: s for s in load_skins(args.skins_dir)}
    records = health["skins"]
    hidden = [sid for sid, rec in records.items() if sid in by_id and is_hidden(rec, by_id[sid]["downloadURL"])]
    repackable = sorted(sid for sid, rec in records.items()
                        if rec.get("result") in REPACKABLE and sid in by_id
                        and rec.get("url") == by_id[sid]["downloadURL"])

    from collections import Counter
    counts = Counter(rec["result"] for rec in records.values())
    print("Failing by result:", dict(counts))
    partial = health.get("partialArtwork", {})
    print(f"Hidden from catalog: {len(hidden)}  Repackable: {len(repackable)}  "
          f"Missing some layouts' artwork (still listed): {len(partial)}")

    exported = 0
    if args.export_cache:
        wanted = [s["downloadURL"] for s in load_skins(args.skins_dir) if needs_thumbnail(s)]
        exported = client.export(wanted, args.export_cache)
        print(f"Exported {exported} cached archive(s) for the thumbnail job to {args.export_cache}")
    if os.environ.get("SKIN_CACHE_DIR") or args.cache_dir:
        pruned = client.prune(args.cache_max_mb * 1024 * 1024)
        if pruned:
            print(f"Pruned {pruned} old cache entr(ies)")

    gh_out = os.environ.get("GITHUB_OUTPUT")
    if gh_out:
        with open(gh_out, "a") as f:
            f.write(f"exported={exported}\n")
            f.write(f"blocked_hosts={','.join(sorted(client.blocked_hosts()))}\n")
            f.write(f"repackable={','.join(repackable)}\n")
            f.write(f"tripped={'true' if tripped else 'false'}\n")
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a") as f:
            f.write("## Link Health\n\n")
            f.write(f"- **Checked:** {len(skins)}\n- **Failing:** {len(failing)} "
                    f"({len(newly)} new)\n- **Hidden:** {len(hidden)}\n"
                    f"- **Repackable:** {len(repackable)}\n"
                    f"- **Missing artwork for some layouts (still listed):** {len(partial)}\n"
                    f"- **Not checked (host refused us):** {len(refused)}"
                    + (f" (first refusal at {next(r for r in (results[s['id']] for s in refused) if r.get('url'))['url']})"
                       if refused else "") + "\n"
                    f"- **Network:** {client.summary()}\n\n")
            if tripped:
                f.write("**Circuit breaker tripped — state not updated.**\n\n")
            f.write("| Skin | Result | Failures | Since |\n|---|---|---|---|\n")
            for sid, rec in records.items():
                name = by_id.get(sid, {}).get("name", sid)
                f.write(f"| {name} | {rec['result']} | {rec['failures']} | {rec['firstFailedAt']} |\n")

    sys.exit(1 if tripped else 0)


if __name__ == "__main__":
    main()
