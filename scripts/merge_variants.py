#!/usr/bin/env python3
"""
merge_variants.py — Publish one "All variants" file for families of split skins.

A family is the entries sharing a `groupId` (a Delta Styles bundle, a repacked
pack). When the members are the same skin in different colours, or two layouts
of one skin, this job merges them into a single archive that Provenance and
Ignited read as themes or as an alternate layout, and adds it to the family as
one more entry. The split files stay in the catalog unchanged.

Design: SkinKit docs/specs/2026-11-03-skin-editing-tools-design.md §3.

  - The merged `representations` is the base member's (the first by
    `groupOrder`), with the base's artwork under its original names, so Delta
    and Manic load the base exactly as before. Everything else is additive:
    `themes` or `altRepresentations`, plus artwork renamed `<theme id>__<name>`
    or `alt__<name>`.
  - Classification, over the family's original members only (entries without
    `mergedFrom`):
      split   different game types, a member with variants of its own, or a
              base missing a layout another member has
      themes  every layout matches the base (frames, inputs, screens and
              per-item art) except the representation's `assets`
      alt     exactly two members that differ in layout
      split   anything else
  - The merged entry: id `make_id("emuskins-merge", "<groupId>#allinone")`,
    identifier `<base identifier>.allinone`, `groupOrder` 0, `variantLabel`
    "All variants", `mergedFrom` (member ids, base first) and `mergedHash`
    (member ids, URLs and archive validators), hosted on the `mirror` release.
  - Idempotent: a family whose `mergedHash` is unchanged is skipped without
    downloading anything; a changed family is rebuilt and re-uploaded; a family
    that becomes split or drops below two visible members loses its merged entry.
  - Only families whose members link-health checked `ok` this run are built,
    and only when the merged file stays under MAX_MERGED_BYTES.
    The job never adds a toggle button or other artwork of its own.
  - `--item-art-themes` (off by default; SkinKit 0.3.0 and later read it): families
    whose members also differ in per-item art (Manic's `asset.normal`) merge as
    `themes` instead of `alt` or `split`. Each theme's layout then carries an
    `items` map, `{"<item index>": {"resizable": "<theme id>__<name>"}}`, for the
    items whose art differs from the base's (SkinKit#78). Art a theme cannot
    express still keeps the family out of themes: thumbstick art, an item the base
    draws that the member leaves bare, and any other difference.

Without --upload nothing is published or written: it prints every family's
outcome and reason and leaves the built archives in --out-dir.

Usage:
    python3 scripts/merge_variants.py                     # dry run
    python3 scripts/merge_variants.py --groups g1,g2      # dry run, some families
    python3 scripts/merge_variants.py --upload            # publish + write skin JSON (CI)
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import io
import json
import os
import re
import sys
import zipfile
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

sys.path.insert(0, str(Path(__file__).parent))
import blocklist
import polite_http
from link_health import (
    ASSET_SIZE_KEYS, HEALTH_FILE, LAYOUT_KEYS, _is_junk, _request, encode_url, find_asset, is_hidden,
    load_health, load_skins, parse_info_json,
)
from repack_skins import MIRROR_BASE, download, upload
from skin_schema import MATURE_TAG, make_id, slugify

MERGE_SOURCE = "emuskins-merge"
ALL_VARIANTS_LABEL = "All variants"
IDENTIFIER_SUFFIX = ".allinone"
VARIANT_KEYS = ("altRepresentations", "themes", "gameOverrides")
ALT_PREFIX = "alt__"
# A merged file this big is a lot to install for one skin (the site's RetroArch
# converter refuses 80 MB); such a family stays split. Design open question 4.
MAX_MERGED_BYTES = 40 * 1024 * 1024
_ZIP_DATE = (1980, 1, 1, 0, 0, 0)


# ---------------------------------------------------------------------------
# One family's archives -> outcome and merged archive (no network, no catalog)
# ---------------------------------------------------------------------------

@dataclass
class Member:
    entry: dict                 # the catalog entry
    info: dict                  # parsed info.json
    files: dict[str, bytes]     # every other file in the archive, by path
    ext: str                    # ".deltaskin" or ".manicskin"


@dataclass
class Merge:
    kind: str                   # "themes", "alt" or "split"
    reason: str
    info: Optional[dict] = None
    files: dict[str, bytes] = field(default_factory=dict)

    def archive(self) -> bytes:
        """The merged skin as a zip; byte-identical for identical input."""
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as out:
            entries = {"info.json": (json.dumps(self.info, indent=2, ensure_ascii=False) + "\n").encode()}
            entries.update(self.files)
            for name in sorted(entries):
                out.writestr(zipfile.ZipInfo(name, _ZIP_DATE), entries[name], zipfile.ZIP_DEFLATED)
        return buf.getvalue()


def read_member(entry: dict, data: bytes) -> Member:
    """A member from its archive bytes (info.json at the root, as link-health requires)."""
    zf = zipfile.ZipFile(io.BytesIO(data))
    info = parse_info_json(zf.read("info.json"))
    if not isinstance(info, dict):
        raise ValueError("info.json is not an object")
    files = {n: zf.read(n) for n in zf.namelist()
             if n != "info.json" and not n.endswith("/") and not _is_junk(n)}
    url = entry.get("downloadURL", "").split("?", 1)[0].lower()
    if url.endswith(".manicskin"):
        ext = ".manicskin"
    elif url.endswith(".deltaskin"):
        ext = ".deltaskin"
    else:
        ext = ".manicskin" if str(info.get("gameTypeIdentifier", "")).startswith("public.aoshuang") else ".deltaskin"
    return Member(entry, info, files, ext)


def layouts(representations, path=()) -> dict[tuple, dict]:
    """{(device, displayType, orientation): layout} for a representations tree."""
    out = {}
    if not isinstance(representations, dict):
        return out
    if LAYOUT_KEYS & representations.keys():
        out[path] = representations
        return out
    for key, value in representations.items():
        out.update(layouts(value, path + (str(key),)))
    return out


def _item_art(item) -> list[str]:
    """File names an item draws itself: Manic's per-item `asset`, a thumbstick image."""
    names = []
    if isinstance(item, dict):
        asset = item.get("asset")
        if isinstance(asset, dict):
            names += [v for _, v in sorted(asset.items()) if isinstance(v, str) and v]
        stick = item.get("thumbstick")
        if isinstance(stick, dict) and isinstance(stick.get("name"), str) and stick["name"]:
            names.append(stick["name"])
    return names


def _art_bytes(member: Member, name: str) -> Optional[bytes]:
    found = find_asset(list(member.files), name)
    return member.files[found] if found else None


def _normal_art(item) -> Optional[str]:
    """The file name of an item's Manic `asset.normal`, the one art a theme can replace."""
    asset = item.get("asset") if isinstance(item, dict) else None
    name = asset.get("normal") if isinstance(asset, dict) else None
    return name if isinstance(name, str) and name else None


def _without_normal_art(item):
    """`item` minus `asset.normal`: what must still match when a theme swaps that art."""
    if not isinstance(item, dict) or not isinstance(item.get("asset"), dict):
        return item
    rest = {k: v for k, v in item["asset"].items() if k != "normal"}
    out = {k: v for k, v in item.items() if k != "asset"}
    if rest:
        out["asset"] = rest
    return out


def _item_art_mismatch(base: Member, b: dict, other: Member, o: dict) -> Optional[str]:
    """Like the strict `items` check, except that `asset.normal` may differ, since a theme can
    swap it. Why the items are more than a re-skin of the base's, or None."""
    base_items, other_items = b.get("items") or [], o.get("items") or []
    if len(base_items) != len(other_items):
        return "`items` differs"
    for i, (x, y) in enumerate(zip(base_items, other_items)):
        if _without_normal_art(x) != _without_normal_art(y):
            return "`items` differs"
        # Same names now, so the thumbstick and any other art must also be the same bytes.
        for name in _item_art(_without_normal_art(x)):
            if _art_bytes(base, name) != _art_bytes(other, name):
                return f"per-item art differs (item {i}, {name})"
        if _art_of(base, x) is not None and _art_of(other, y) is None:
            return f"item {i} has no art, where the base draws {_normal_art(x)}"
    return None


def _art_of(member: Member, item) -> Optional[bytes]:
    """The bytes of an item's `asset.normal`, None when it has none or the file is missing."""
    name = _normal_art(item)
    return _art_bytes(member, name) if name else None


def _layout_mismatch(base: Member, b: dict, other: Member, o: dict, item_art_themes: bool = False) -> Optional[str]:
    """Why layout `o` of `other` is more than a recolour of layout `b` of `base`, or None.
    With `item_art_themes`, differing `asset.normal` art is a recolour too."""
    if item_art_themes:
        mismatch = _item_art_mismatch(base, b, other, o)
        if mismatch:
            return mismatch
    for key in sorted((set(b) | set(o)) - {"assets"} - ({"items"} if item_art_themes else set())):
        if b.get(key) != o.get(key):
            return f"`{key}` differs"
    if not item_art_themes:
        for i, item in enumerate(b.get("items") or []):
            for name in _item_art(item):
                if _art_bytes(base, name) != _art_bytes(other, name):
                    return f"per-item art differs (item {i}, {name})"
    return None


def _theme_item_art(base: Member, b: dict, other: Member, o: dict) -> dict[int, str]:
    """{item index: file name in `other`} for the items of layout `o` whose `asset.normal`
    art a theme must replace: `other` has art there and it is not the base's bytes."""
    out = {}
    for i, (x, y) in enumerate(zip(b.get("items") or [], o.get("items") or [])):
        mine = _art_of(other, y)
        if mine is not None and mine != _art_of(base, x):
            out[i] = _normal_art(y)
    return out


def _differs_in_item_art(members: list[Member]) -> bool:
    base = members[0]
    base_layouts = layouts(base.info.get("representations"))
    return any(_theme_item_art(base, base_layouts[trait], m, layout)
               for m in members[1:] for trait, layout in layouts(m.info.get("representations")).items())


def classify(members: list[Member], item_art_themes: bool = False) -> tuple[str, str]:
    """("themes" | "alt" | "split", reason) for original members, base first."""
    if len(members) < 2:
        return "split", "fewer than two members"
    gtis = {m.info.get("gameTypeIdentifier") for m in members}
    if len(gtis) != 1:
        return "split", f"members declare {len(gtis)} game types"
    for m in members:
        carried = [k for k in VARIANT_KEYS if m.info.get(k)]
        if carried:
            return "split", f"{m.entry['id']} already carries {', '.join(carried)}"
    base = members[0]
    base_layouts = layouts(base.info.get("representations"))
    if not base_layouts:
        return "split", "the base has no layouts"
    for m in members[1:]:
        extra = sorted(set(layouts(m.info.get("representations"))) - set(base_layouts))
        if extra:
            return "split", f"the base lacks {'/'.join(extra[0])}, which {m.entry['id']} has"

    why_not_themes = None
    for m in members[1:]:
        theirs = layouts(m.info.get("representations"))
        if set(theirs) != set(base_layouts):
            why_not_themes = f"{m.entry['id']} has fewer layouts than the base"
            break
        for trait in sorted(base_layouts):
            mismatch = _layout_mismatch(base, base_layouts[trait], m, theirs[trait], item_art_themes)
            if mismatch:
                why_not_themes = f"{m.entry['id']} {'/'.join(trait)}: {mismatch}"
                break
        if why_not_themes:
            break
    if why_not_themes is None:
        return "themes", f"{len(members)} members differ only in {'background and per-item' if item_art_themes and _differs_in_item_art(members) else 'background'} artwork"
    if len(members) == 2:
        return "alt", f"two layouts ({why_not_themes})"
    return "split", f"{len(members)} members and not themes ({why_not_themes})"


def _renamed(path: str, prefix: str) -> str:
    folder, _, leaf = path.rpartition("/")
    return f"{folder}/{prefix}{leaf}" if folder else prefix + leaf


class _Files:
    """The merged archive's files: the base's, plus renamed copies from other members."""

    def __init__(self, base: Member):
        self.files = dict(base.files)
        self._taken = {n.lower() for n in self.files} | {"info.json"}
        self._copied: dict[tuple[int, str, str], str] = {}

    def add(self, member: Member, name: str, prefix: str) -> Optional[str]:
        """Copy `name` (resolved as the app would) from `member` under `prefix`; the new
        path, or None when the member doesn't have it."""
        found = find_asset(list(member.files), name)
        if not found:
            return None
        key = (id(member), found, prefix)
        if key in self._copied:
            return self._copied[key]
        new, n = _renamed(found, prefix), 2
        while new.lower() in self._taken:   # case-insensitive filesystems and lookups
            new, n = _renamed(found, f"{prefix}{n}_"), n + 1
        self._taken.add(new.lower())
        self.files[new] = member.files[found]
        self._copied[key] = new
        return new


def family_name(entry: dict) -> str:
    """The family's title: the base's name without its own label (browse.js `familyName`)."""
    name = entry.get("name") or ""
    label = entry.get("variantLabel") or ""
    if label and len(name) > len(label) and name.lower().endswith(label.lower()):
        return re.sub(r"[\s\-—:]+$", "", name[: len(name) - len(label)]) or name
    return name


def _theme_ids(members: list[Member]) -> list[str]:
    ids, seen = [], set()
    for i, m in enumerate(members, 1):
        tid = slugify(m.entry.get("variantLabel") or m.entry.get("name") or "") or f"variant-{i}"
        if tid == ALT_PREFIX.rstrip("_"):
            tid = f"{tid}-{i}"
        while tid in seen:
            tid = f"{tid}-{i}"
        seen.add(tid)
        ids.append(tid)
    return ids


def merge_family(members: list[Member], item_art_themes: bool = False) -> Merge:
    """Classify a family (base first) and, for themes or alt, build the merged skin."""
    kind, reason = classify(members, item_art_themes)
    if kind == "split":
        return Merge(kind, reason)
    base = members[0]
    out = _Files(base)
    info = copy.deepcopy(base.info)
    info["identifier"] = f"{base.info.get('identifier', '')}{IDENTIFIER_SUFFIX}"
    info["name"] = f"{family_name(base.entry)} ({ALL_VARIANTS_LABEL})"

    if kind == "themes":
        base_layouts = layouts(base.info["representations"])
        themes = []
        for m, tid in zip(members[1:], _theme_ids(members[1:])):
            assets: dict = {}
            for (device, display, orientation), layout in sorted(layouts(m.info["representations"]).items()):
                source = layout.get("assets") if isinstance(layout.get("assets"), dict) else {}
                renamed = {}
                for size in ASSET_SIZE_KEYS:
                    name = source.get(size)
                    new = out.add(m, name, f"{tid}__") if isinstance(name, str) and name else None
                    if new:
                        renamed[size] = new
                if item_art_themes:
                    base_layout = base_layouts[(device, display, orientation)]
                    items = {str(i): {"resizable": out.add(m, name, f"{tid}__")}
                             for i, name in _theme_item_art(base, base_layout, m, layout).items()}
                    if items:
                        renamed["items"] = items
                if renamed:
                    assets.setdefault(device, {}).setdefault(display, {})[orientation] = renamed
            label = m.entry.get("variantLabel") or m.entry.get("name") or tid
            themes.append({"id": tid, "name": label, "assets": assets})
        info["themes"] = themes
    else:
        alt_member = members[1]
        alt = copy.deepcopy(alt_member.info["representations"])
        for layout in layouts(alt).values():
            assets = layout.get("assets")
            if isinstance(assets, dict):
                for size, name in list(assets.items()):
                    if isinstance(name, str) and name:
                        assets[size] = out.add(alt_member, name, ALT_PREFIX) or name
            for item in layout.get("items") or []:
                if not isinstance(item, dict):
                    continue
                if isinstance(item.get("asset"), dict):
                    for key, name in list(item["asset"].items()):
                        if isinstance(name, str) and name:
                            item["asset"][key] = out.add(alt_member, name, ALT_PREFIX) or name
                stick = item.get("thumbstick")
                if isinstance(stick, dict) and isinstance(stick.get("name"), str) and stick["name"]:
                    stick["name"] = out.add(alt_member, stick["name"], ALT_PREFIX) or stick["name"]
        info["altRepresentations"] = alt
    return Merge(kind, reason, info, out.files)


# ---------------------------------------------------------------------------
# Catalog: families, hashes, entries
# ---------------------------------------------------------------------------

def merged_id(group_id: str) -> str:
    return make_id(MERGE_SOURCE, f"{group_id}#allinone")


def merged_hash(members: list[dict], digests: list[str], item_art_themes: bool = False) -> str:
    """sha256 over each member's id, downloadURL, archive digest and mature tag, base first
    (a member tagged mature later rebuilds the entry so it carries the tag). A run with
    `--item-art-themes` hashes differently, so switching the flag rebuilds every family."""
    h = hashlib.sha256()
    for entry, digest in zip(members, digests):
        mature = MATURE_TAG in (entry.get("tags") or [])
        h.update(f"{entry['id']}\0{entry['downloadURL']}\0{digest}\0{int(mature)}\n".encode())
    if item_art_themes:
        h.update(b"item-art-themes\n")
    return h.hexdigest()


def _order_key(entry: dict):
    order = entry.get("groupOrder")
    return (order if isinstance(order, int) else float("inf"), entry.get("_source_file", ""), entry["id"])


def find_families(entries: list[dict]) -> tuple[dict[str, list[dict]], dict[str, list[dict]]]:
    """({groupId: original members by groupOrder}, {groupId: merged entries})."""
    originals: dict[str, list[dict]] = {}
    merged: dict[str, list[dict]] = {}
    for e in entries:
        group = e.get("groupId")
        if not group:
            continue
        (merged if e.get("mergedFrom") else originals).setdefault(group, []).append(e)
    return {g: sorted(m, key=_order_key) for g, m in originals.items()}, merged


def is_visible(entry: dict, health: dict) -> bool:
    """Shown in the catalog (build_catalog.split_hidden's rule)."""
    record = health.get("skins", {}).get(entry["id"])
    return not blocklist.is_blocked(entry) and not is_hidden(record, entry.get("downloadURL"))


def is_healthy(entry: dict, health: dict) -> bool:
    """Checked `ok` by link-health at its current downloadURL."""
    record = health.get("skins", {}).get(entry["id"])
    return bool(record) and record.get("result") == "ok" and record.get("url") == entry.get("downloadURL")


def merged_entry(group_id: str, members: list[Member], merge: Merge, mhash: str,
                 skins_dir: str = "skins") -> dict:
    """The catalog entry for a merged family (`_file`, `_asset` for writing)."""
    base = members[0]
    new_id = merged_id(group_id)
    tags = list(base.entry.get("tags") or [])
    # The file carries every member's art, so it is mature when any member is.
    if MATURE_TAG not in tags and any(MATURE_TAG in (m.entry.get("tags") or []) for m in members):
        tags.append(MATURE_TAG)
    entry = {
        "id": new_id,
        # "<family> — All variants": browse.js familyName and SkinKit stripSuffix both
        # read this primary's name back as the family title.
        "name": f"{family_name(base.entry)} — {ALL_VARIANTS_LABEL}",
        "author": base.entry.get("author"),
        "systems": list(base.entry["systems"]),
        "source": base.entry["source"],
        "gameTypeIdentifier": base.entry.get("gameTypeIdentifier"),
        "downloadURL": MIRROR_BASE + new_id + base.ext,
        "tags": tags,
        "groupId": group_id,
        "groupOrder": 0,
        "variantLabel": ALL_VARIANTS_LABEL,
        "mergedFrom": [m.entry["id"] for m in members],
        "mergedHash": mhash,
    }
    entry["_file"] = str(Path(skins_dir) / entry["systems"][0] / f"{slugify(family_name(base.entry))}-allinone-{new_id[:6]}.json")
    entry["_asset"] = new_id + base.ext
    return entry


@dataclass
class Plan:
    group: str
    outcome: str                # themes, alt, split, unchanged, skipped, removed
    reason: str
    entry: Optional[dict] = None
    archive: Optional[bytes] = None
    remove: list[str] = field(default_factory=list)   # merged entry files to delete


def plan_family(group: str, members: list[dict], existing: list[dict], health: dict,
                fetch: Callable[[str], bytes], digest: Callable[[str], Optional[str]],
                skins_dir: str = "skins", item_art_themes: bool = False) -> Plan:
    """What to do for one family. `fetch` returns archive bytes; `digest` returns a
    validator for a URL without downloading it, or None."""
    stale = [e["_source_file"] for e in existing if e.get("_source_file")]
    visible = [m for m in members if is_visible(m, health)]
    if len(visible) < 2:
        return Plan(group, "removed" if stale else "skipped",
                    f"{len(visible)} visible member(s)", remove=stale)
    unhealthy = [m["id"] for m in visible if not is_healthy(m, health)]
    if unhealthy:
        return Plan(group, "skipped", f"not checked ok this run: {', '.join(unhealthy)}")

    data: dict[str, bytes] = {}
    digests = []
    for m in visible:
        d = digest(m["downloadURL"])
        if d is None:
            data[m["id"]] = fetch(m["downloadURL"])
            d = "sha256:" + hashlib.sha256(data[m["id"]]).hexdigest()
        digests.append(d)
    mhash = merged_hash(visible, digests, item_art_themes)
    current = [e for e in existing if e["id"] == merged_id(group)]
    if len(existing) == 1 and current and current[0].get("mergedHash") == mhash:
        return Plan(group, "unchanged", "mergedHash matches")

    loaded = [read_member(m, data.get(m["id"]) or fetch(m["downloadURL"])) for m in visible]
    merge = merge_family(loaded, item_art_themes)
    archive = merge.archive() if merge.kind != "split" else None
    if archive and len(archive) > MAX_MERGED_BYTES:
        merge = Merge("split", f"{merge.kind} would be {len(archive) // (1024 * 1024)} MB, "
                               f"over {MAX_MERGED_BYTES // (1024 * 1024)} MB")
    if merge.kind == "split":
        return Plan(group, "removed" if stale else "split", merge.reason, remove=stale)
    entry = merged_entry(group, loaded, merge, mhash, skins_dir)
    remove = [p for p in stale if os.path.normpath(p) != os.path.normpath(entry["_file"])]
    return Plan(group, merge.kind, merge.reason, entry, archive, remove)


def archive_digest(url: str) -> Optional[str]:
    """`etag:` / `last-modified:` validator for `url`, or None (the caller hashes the bytes).

    deltastyles.com: from the copy link-health cached this run. Other hosts: the
    headers of a one-byte range request, which also follows GitHub's redirect."""
    client = polite_http.get_client()
    if client.is_polite(url):
        fetched = client.get_file(encode_url(url), component="merge")
        meta_path = fetched.path.with_suffix(".json")
        try:
            meta = json.loads(meta_path.read_text())
        except (OSError, json.JSONDecodeError):
            meta = {}
    else:
        try:
            with _request(encode_url(url), byte_range="bytes=0-0") as r:
                meta = {"etag": r.headers.get("ETag"), "lastModified": r.headers.get("Last-Modified")}
        except Exception:
            return None
    if meta.get("etag"):
        return f"etag:{meta['etag']}"
    if meta.get("lastModified"):
        return f"last-modified:{meta['lastModified']}"
    return None


def write_entry(entry: dict):
    out = {k: v for k, v in entry.items() if not k.startswith("_")}
    os.makedirs(os.path.dirname(entry["_file"]), exist_ok=True)
    with open(entry["_file"], "w") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)
        f.write("\n")


def main():
    parser = argparse.ArgumentParser(description="Merge split variant families into one file")
    parser.add_argument("--skins-dir", default="skins")
    parser.add_argument("--health-file", default=HEALTH_FILE)
    parser.add_argument("--groups", help="Comma-separated groupIds (default: every family)")
    parser.add_argument("--out-dir", default="build/merged")
    parser.add_argument("--item-art-themes", action="store_true",
                        help="Merge families that differ in per-item art as themes carrying `items` "
                             "(needs SkinKit 0.3.0+ to show the item art; older readers keep the base's)")
    parser.add_argument("--upload", action="store_true", help="Publish to the mirror release and write skin JSON")
    args = parser.parse_args()

    entries = load_skins(args.skins_dir)
    health = load_health(args.health_file)
    families, merged = find_families(entries)
    wanted = set(args.groups.split(",")) if args.groups else None
    groups = sorted((set(families) | set(merged)) & wanted if wanted else set(families) | set(merged))

    os.makedirs(args.out_dir, exist_ok=True)
    plans, assets = [], []
    for group in groups:
        try:
            plan = plan_family(group, families.get(group, []), merged.get(group, []), health,
                               download, archive_digest, args.skins_dir, args.item_art_themes)
        except Exception as e:
            plan = Plan(group, "skipped", f"error: {type(e).__name__}: {e}"[:200])
        size = ""
        if plan.archive:
            # Written now and dropped, so one family's archive is in memory at a time.
            path = os.path.join(args.out_dir, plan.entry["_asset"])
            with open(path, "wb") as f:
                f.write(plan.archive)
            assets.append(path)
            size = f", {len(plan.archive) // 1024} KB"
            plan.archive = None
        plans.append(plan)
        print(f"{group}: {plan.outcome} ({plan.reason}{size})")

    counts = Counter(p.outcome for p in plans)
    print("\n" + (", ".join(f"{n} {k}" for k, n in sorted(counts.items())) or "No families."))

    built = [p for p in plans if p.entry]

    if not args.upload:
        print(f"Dry run: {len(assets)} archive(s) in {args.out_dir}/, nothing uploaded, no skin JSON changed.")
        return

    if assets:
        upload(assets)
    for p in plans:
        if p.entry:
            write_entry(p.entry)
        for path in p.remove:
            if os.path.exists(path):
                os.remove(path)
    print(f"Wrote {len(built)} merged entr(ies); removed {sum(len(p.remove) for p in plans)}.")


if __name__ == "__main__":
    main()
