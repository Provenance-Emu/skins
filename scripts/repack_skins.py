#!/usr/bin/env python3
"""
repack_skins.py — Turn zip packs into skins Provenance can install.

The app only installs an archive with `info.json` at its root. Some sources
ship skins wrapped in a .zip (one skin, or a pack of several), or one folder
down. This script downloads those archives, pulls out each skin, checks it
the way the app does, and rehosts it on the `mirror` GitHub Release.

  - one skin inside   -> the entry keeps its id; downloadURL points at the mirror
  - several inside    -> the entry is replaced by one entry per skin, grouped
                         with `groupId`/`groupOrder`
  - every rewritten entry records the archive it came from in `originalURL`

Without --upload nothing is published or written: it reports what it would do
and leaves the extracted files in --out-dir.

Usage:
    python3 scripts/repack_skins.py --from-health            # dry run
    python3 scripts/repack_skins.py --ids a1b2c3d4e5f60718   # dry run, one entry
    python3 scripts/repack_skins.py --from-health --upload   # publish + rewrite (CI)
"""

import argparse
import io
import json
import os
import re
import subprocess
import sys
import urllib.parse
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from link_health import (
    HEALTH_FILE, REPACKABLE, _is_junk, _request, classify_archive, encode_url,
    inner_skin_paths, load_health, load_skins, parse_info_json, MAX_FULL_DOWNLOAD,
)
from skin_schema import SYSTEM_MAP, make_id, normalize_entry, slugify, system_from_gti

MIRROR_TAG = "mirror"
MIRROR_BASE = f"https://github.com/Provenance-Emu/skins/releases/download/{MIRROR_TAG}/"
RELEASE_NOTES = ("Skins extracted from zip packs by scripts/repack_skins.py so Provenance "
                 "can install them. See each entry's originalURL.")


def download(url: str) -> bytes:
    with _request(encode_url(url), timeout=120) as r:
        return r.read(MAX_FULL_DOWNLOAD)


def _rezip(zf: zipfile.ZipFile, prefix: str) -> bytes:
    """Re-zip every member under `prefix` with the prefix stripped."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as out:
        for info in zf.infolist():
            name = info.filename
            if not name.startswith(prefix) or name.endswith("/") or _is_junk(name):
                continue
            out.writestr(name[len(prefix):], zf.read(name))
    return buf.getvalue()


def extract_skins(archive: bytes) -> list[dict]:
    """Return [{"path", "ext", "data", "info"}] for each installable skin inside."""
    zf = zipfile.ZipFile(io.BytesIO(archive))
    names = [n for n in zf.namelist() if not _is_junk(n)]
    candidates = []
    inner = inner_skin_paths(names)
    if inner:
        for path in inner:
            data = _rezip(zf, path) if path.endswith("/") else zf.read(path)
            candidates.append((path, data))
    else:
        # Plain folders (`A/info.json`, `B/info.json`): each is its own skin.
        # A folder inside another skin's folder belongs to that skin.
        roots = []
        for n in sorted((n for n in names if n.endswith("/info.json")), key=lambda n: n.count("/")):
            prefix = n[: -len("info.json")]
            if not any(prefix.startswith(r) for r in roots):
                roots.append(prefix)
        for prefix in roots:
            candidates.append((prefix, _rezip(zf, prefix)))

    skins, seen_identifiers = [], set()
    for path, data in candidates:
        try:
            skin_zip = zipfile.ZipFile(io.BytesIO(data))
            if classify_archive(skin_zip)["result"] != "ok":
                print(f"    skip {path}: not installable", file=sys.stderr)
                continue
            info = parse_info_json(skin_zip.read("info.json"))
        except Exception as e:
            print(f"    skip {path}: {e}", file=sys.stderr)
            continue
        identifier = info.get("identifier")
        if identifier in seen_identifiers:
            continue
        seen_identifiers.add(identifier)
        lower = path.rstrip("/").lower()
        if lower.endswith(".manicskin"):
            ext = ".manicskin"
        elif lower.endswith(".deltaskin"):
            ext = ".deltaskin"
        else:
            # Manic's game types use the `public.aoshuang.*` namespace.
            ext = ".manicskin" if str(info.get("gameTypeIdentifier", "")).startswith("public.aoshuang") else ".deltaskin"
        skins.append({"path": path, "ext": ext, "data": data, "info": info})
    return skins


def _label(path: str) -> str:
    leaf = urllib.parse.unquote(path.rstrip("/").rsplit("/", 1)[-1])
    leaf = re.sub(r"\.(deltaskin|manicskin)$", "", leaf, flags=re.IGNORECASE)
    return re.sub(r"[_\s]+", " ", leaf).strip()


# Systems Delta runs itself. Their identifiers name the real system; a skin for
# anything else that declares one is using it as a stand-in.
DELTA_NATIVE_GTIS = {f"com.rileytestut.delta.game.{s}" for s in ("nes", "snes", "n64", "gbc", "gba", "ds", "genesis")}


def _system_for_inner(gti, parent_system: str):
    """System code for one skin inside a pack, or None to keep the pack's.

    Manic identifiers are trusted (as in the crawler). A Delta identifier is
    trusted only when the pack itself is filed under a different Delta-native
    system, e.g. a GBA pack that also ships GBC variants. GB skins declare the
    shared gbc id, and 3DS/Game Gear/MAME skins borrow Delta ids, so those keep
    the pack's system.
    """
    if not gti:
        return None
    if gti.startswith("public.aoshuang.game."):
        return system_from_gti(gti)
    parent_gtis = {v[1] for v in SYSTEM_MAP.values() if v[0] == parent_system}
    if gti in DELTA_NATIVE_GTIS and parent_gtis & DELTA_NATIVE_GTIS and gti not in parent_gtis:
        return system_from_gti(gti)
    return None


def plan_entries(parent: dict, skins: list[dict], skins_dir: str = "skins") -> list[dict]:
    """New skin entries (with `_file`, `_data` for writing) for one archive."""
    base = {k: v for k, v in parent.items() if not k.startswith("_")}
    original = parent.get("originalURL") or parent["downloadURL"]

    if len(skins) == 1:
        skin = skins[0]
        entry = {**base, "downloadURL": MIRROR_BASE + parent["id"] + skin["ext"], "originalURL": original}
        entry["_file"] = parent["_source_file"]
        entry["_asset"] = parent["id"] + skin["ext"]
        entry["_data"] = skin["data"]
        return [entry]

    names = [s["info"].get("name") or _label(s["path"]) for s in skins]
    out = []
    for order, (skin, name) in enumerate(zip(skins, names), 1):
        if names.count(name) > 1:
            name = f"{name} ({_label(skin['path'])})"
        new_id = make_id(parent["source"], f"{original}#{skin['path']}")
        gti = skin["info"].get("gameTypeIdentifier")
        system = _system_for_inner(gti, parent["systems"][0])
        systems = [system] if system else parent["systems"]
        entry = normalize_entry({
            **{k: v for k, v in base.items() if k not in ("thumbnailURL", "downloadCount")},
            "id": new_id,
            "name": name,
            "systems": systems,
            "gameTypeIdentifier": gti,
            "downloadURL": MIRROR_BASE + new_id + skin["ext"],
            "originalURL": original,
            "groupId": parent.get("groupId") or parent["id"],
            "groupOrder": order,
        })
        entry["_file"] = str(Path(skins_dir) / systems[0] / f"{slugify(name)}-{new_id[:6]}.json")
        entry["_asset"] = new_id + skin["ext"]
        entry["_data"] = skin["data"]
        out.append(entry)
    return out


def upload(asset_paths: list[str]):
    if subprocess.run(["gh", "release", "view", MIRROR_TAG], capture_output=True).returncode != 0:
        subprocess.run(["gh", "release", "create", MIRROR_TAG, "--title", "Skin mirror",
                        "--notes", RELEASE_NOTES],
                       check=True)
    for i in range(0, len(asset_paths), 20):
        subprocess.run(["gh", "release", "upload", MIRROR_TAG, *asset_paths[i:i + 20], "--clobber"], check=True)


def main():
    parser = argparse.ArgumentParser(description="Extract skins from zip packs and rehost them")
    parser.add_argument("--skins-dir", default="skins")
    parser.add_argument("--health-file", default=HEALTH_FILE)
    parser.add_argument("--ids", help="Comma-separated skin ids")
    parser.add_argument("--from-health", action="store_true", help="Repack every entry link-health marks repackable")
    parser.add_argument("--out-dir", default="build/mirror")
    parser.add_argument("--upload", action="store_true", help="Publish to the mirror release and rewrite skin JSON")
    args = parser.parse_args()

    skins = {s["id"]: s for s in load_skins(args.skins_dir)}
    health = load_health(args.health_file)
    ids = set(args.ids.split(",")) if args.ids else set()
    if args.from_health:
        ids |= {sid for sid, rec in health["skins"].items()
                if rec.get("result") in REPACKABLE and sid in skins
                and rec.get("url") == skins[sid]["downloadURL"]}
    if not ids:
        print("Nothing to repack.")
        return

    os.makedirs(args.out_dir, exist_ok=True)
    plans = {}
    for sid in sorted(ids):
        parent = skins.get(sid)
        if not parent:
            print(f"{sid}: no such skin", file=sys.stderr)
            continue
        print(f"{parent['name']} ({sid})")
        try:
            extracted = extract_skins(download(parent["downloadURL"]))
        except Exception as e:
            print(f"    download/extract failed: {e}", file=sys.stderr)
            continue
        if not extracted:
            print("    no installable skins inside; leaving it for link-health to hide")
            continue
        plans[sid] = plan_entries(parent, extracted, args.skins_dir)
        for e in plans[sid]:
            print(f"    -> {e['name']}  [{e['systems'][0]}]  {e['_asset']}")

    assets = []
    for entries in plans.values():
        for e in entries:
            path = os.path.join(args.out_dir, e["_asset"])
            with open(path, "wb") as f:
                f.write(e["_data"])
            assets.append(path)
    total = sum(len(v) for v in plans.values())
    print(f"\n{len(plans)} archive(s) -> {total} skin(s); files in {args.out_dir}/")

    if not args.upload:
        print("Dry run: nothing uploaded, no skin JSON changed. Pass --upload to publish.")
        return

    upload(assets)
    for sid, entries in plans.items():
        parent_file = skins[sid]["_source_file"]
        written = set()
        for e in entries:
            out = {k: v for k, v in e.items() if not k.startswith("_")}
            os.makedirs(os.path.dirname(e["_file"]), exist_ok=True)
            with open(e["_file"], "w") as f:
                json.dump(out, f, indent=2, ensure_ascii=False)
                f.write("\n")
            written.add(os.path.normpath(e["_file"]))
        if os.path.normpath(parent_file) not in written:
            os.remove(parent_file)
        health["skins"].pop(sid, None)
    with open(args.health_file, "w") as f:
        json.dump(health, f, indent=2, ensure_ascii=False)
        f.write("\n")
    print(f"Rewrote {len(plans)} entr(ies) to point at the mirror.")


if __name__ == "__main__":
    main()
