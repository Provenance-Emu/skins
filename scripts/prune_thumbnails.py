#!/usr/bin/env python3
"""prune_thumbnails.py — delete thumbnail release assets of skins that are gone (SkinKit#128).

The `thumbnails` release is capped at 1000 assets by GitHub and held assets for skins
that left the catalog. This lists every release of the family (`thumbnails`,
`thumbnails-2`, ...), finds the assets nobody uses and, with --apply, deletes them.

An asset is named `{skin id}.png` or `{skin id}-landscape.png`. It is an orphan when
its skin id is not in catalog.json. Two guards keep a skin that only looks gone:

  - the catalog leaves out hidden skins (link-health), and a hidden skin comes back
    when its download passes again. Its `skins/**/*.json` file is still there, with
    a thumbnailURL that generate_thumbnails.py will not regenerate. Any id with a
    skin file is kept;
  - any asset a skin file's thumbnailURL or screenshotURLs points at is kept.

Names that are not `{16 hex}(-landscape).png` are reported and never deleted.

DRY RUN BY DEFAULT: it reads the public API and changes nothing. Deleting needs
--apply and a GITHUB_TOKEN that can write releases:

    python3 scripts/prune_thumbnails.py                  # report only
    python3 scripts/prune_thumbnails.py --report r.md    # also write the report
    GITHUB_TOKEN=$(gh auth token) python3 scripts/prune_thumbnails.py --apply

Deleting an asset frees its slot at once. The raw files in the repo's thumbnails/
folder are not touched.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import thumbnail_shards as shards  # noqa: E402

# A run that would delete more than this share of what it listed stops: the catalog
# or skins/ it was given is probably wrong, not the releases.
MAX_PRUNE_FRACTION = 0.5


class PruneError(Exception):
    pass


@dataclass
class Plan:
    prune: list[dict] = field(default_factory=list)          # assets to delete
    kept_hidden: list[dict] = field(default_factory=list)    # not in the catalog, but a skin file has the id
    kept_referenced: list[dict] = field(default_factory=list)  # a skin file's URL points at it
    unrecognized: list[dict] = field(default_factory=list)   # name isn't {id}[-landscape].png
    current: int = 0                                         # id is in the catalog
    total: int = 0
    not_in_catalog: int = 0                                  # prune + kept_hidden + kept_referenced
    per_release: dict = field(default_factory=dict)          # tag -> {"assets": n, "prune": n}


def catalog_ids(catalog_path: str) -> set[str]:
    with open(catalog_path, encoding="utf-8") as f:
        skins = json.load(f).get("skins", [])
    return {s["id"] for s in skins if isinstance(s, dict) and isinstance(s.get("id"), str)}


def skin_file_info(skins_dir: str, repo: str = shards.REPO) -> tuple[set[str], set[tuple[str, str]]]:
    """(ids of every skins/**/*.json, (tag, asset name) pairs their URLs point at)."""
    ids, refs = set(), set()
    for path in sorted(Path(skins_dir).rglob("*.json")):
        try:
            entry = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not isinstance(entry, dict):
            continue
        if isinstance(entry.get("id"), str):
            ids.add(entry["id"])
        for url in [entry.get("thumbnailURL")] + list(entry.get("screenshotURLs") or []):
            parsed = shards.parse_release_url(url, repo)
            if parsed:
                refs.add(parsed)
    return ids, refs


def plan_prune(releases: dict[str, list[dict]], in_catalog: set[str], skin_ids: set[str],
               referenced: set[tuple[str, str]]) -> Plan:
    """`releases` maps tag -> its assets (dicts with name, id, download_count, size)."""
    plan = Plan()
    for tag in shards.sort_tags(releases):
        counts = {"assets": 0, "prune": 0}
        for asset in releases[tag]:
            plan.total += 1
            counts["assets"] += 1
            item = {"tag": tag, "name": asset["name"], "id": asset["id"],
                    "download_count": asset.get("download_count", 0)}
            parsed = shards.parse_asset_name(asset["name"])
            if not parsed:
                plan.unrecognized.append(item)
                continue
            skin_id = parsed[0]
            if skin_id in in_catalog:
                plan.current += 1
                continue
            plan.not_in_catalog += 1
            if skin_id in skin_ids:
                plan.kept_hidden.append(item)
            elif (tag, asset["name"]) in referenced:
                plan.kept_referenced.append(item)
            else:
                plan.prune.append(item)
                counts["prune"] += 1
        plan.per_release[tag] = counts
    return plan


def check_plan(plan: Plan, in_catalog: set[str], skin_ids: set[str],
               max_fraction: float = MAX_PRUNE_FRACTION) -> None:
    """Refuse to go on when the inputs look wrong. Raises PruneError."""
    if not in_catalog:
        raise PruneError("catalog.json holds no skin ids; refusing to treat every asset as an orphan")
    if not skin_ids:
        raise PruneError("skins/ holds no skin files; refusing to go on without the hidden-skin guard")
    if plan.total and len(plan.prune) > plan.total * max_fraction:
        raise PruneError(
            f"{len(plan.prune)} of {plan.total} assets would be deleted (over {max_fraction:.0%}); "
            "check --catalog and --skins-dir, or raise --max-fraction")


def fetch_releases(get_json=None, repo: str = shards.REPO) -> dict[str, list[dict]]:
    """tag -> assets for every release of the family. Raises on any request error:
    a partial listing must not be mistaken for a complete one."""
    get_json = get_json or (lambda url: shards.http_get_json(url, os.environ.get("GITHUB_TOKEN", "")))
    return {rel["tag_name"]: shards.list_release_assets(rel, get_json)
            for rel in shards.discover_shard_releases(get_json, repo)}


def format_report(plan: Plan, applied: bool = False, deleted: int = 0, failures=()) -> str:
    lines = [
        "## Thumbnail release assets",
        "",
        f"- Assets listed: **{plan.total}** across {len(plan.per_release)} release(s)",
        f"- Id is in `catalog.json`: **{plan.current}**",
        f"- Id is not in `catalog.json`: **{plan.not_in_catalog}**",
        f"  - kept, a `skins/**/*.json` file still has the id (hidden skins): {len(plan.kept_hidden)}",
        f"  - kept, a skin file's URL points at the asset: {len(plan.kept_referenced)}",
        f"  - **orphans to delete: {len(plan.prune)}**",
        f"- Names that are not `{{id}}[-landscape].png` (never deleted): {len(plan.unrecognized)}",
        "",
        "| Release | Assets | Orphans | Left after prune |",
        "| --- | ---: | ---: | ---: |",
    ]
    for tag, c in plan.per_release.items():
        lines.append(f"| `{tag}` | {c['assets']} | {c['prune']} | {c['assets'] - c['prune']} |")
    if applied:
        lines += ["", f"Deleted {deleted} asset(s)." + (f" Failed: {', '.join(failures)}" if failures else "")]
    else:
        lines += ["", "Dry run: nothing was deleted."]
    return "\n".join(lines) + "\n"


def delete_asset(asset_id: int, token: str, repo: str = shards.REPO) -> None:
    req = urllib.request.Request(
        f"https://api.github.com/repos/{repo}/releases/assets/{asset_id}", method="DELETE",
        headers={"Accept": "application/vnd.github+json", "Authorization": f"Bearer {token}",
                 "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "Provenance-SkinCatalog/1.0"})
    urllib.request.urlopen(req, timeout=15).close()


def apply_plan(plan: Plan, delete, sleep=time.sleep) -> tuple[int, list[str]]:
    """Delete each orphan with `delete(asset id)`. Returns (deleted, failures).
    A failure is recorded and the run goes on."""
    deleted, failures = 0, []
    for item in plan.prune:
        try:
            delete(item["id"])
            deleted += 1
        except Exception as exc:  # urllib errors, 404 for an asset already gone
            if getattr(exc, "code", None) == 404:
                continue
            failures.append(f"{item['tag']}/{item['name']}")
            print(f"  ! could not delete {item['tag']}/{item['name']}: {exc}", file=sys.stderr)
        sleep(0.3)
    return deleted, failures


def main(argv=None, get_json=None, delete=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--catalog", default="catalog.json")
    parser.add_argument("--skins-dir", default="skins")
    parser.add_argument("--repo", default=shards.REPO)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="report only (the default)")
    mode.add_argument("--apply", action="store_true", help="delete the orphans (needs GITHUB_TOKEN)")
    parser.add_argument("--max-fraction", type=float, default=MAX_PRUNE_FRACTION,
                        help="stop when more than this share of the assets would go (default 0.5)")
    parser.add_argument("--report", help="also write the report (Markdown) to this file")
    parser.add_argument("--list", action="store_true", help="print every asset to delete")
    args = parser.parse_args(argv)

    token = os.environ.get("GITHUB_TOKEN", "")
    if args.apply and not token and delete is None:
        print("--apply needs GITHUB_TOKEN", file=sys.stderr)
        return 2

    try:
        in_catalog = catalog_ids(args.catalog)
        skin_ids, referenced = skin_file_info(args.skins_dir, args.repo)
        releases = fetch_releases(get_json, args.repo)
        plan = plan_prune(releases, in_catalog, skin_ids, referenced)
        check_plan(plan, in_catalog, skin_ids, args.max_fraction)
    except (PruneError, OSError, ValueError) as exc:
        print(f"prune_thumbnails: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:  # a request failed: say so rather than act on a partial list
        print(f"prune_thumbnails: could not read the releases: {exc}", file=sys.stderr)
        return 1

    deleted, failures = 0, []
    if args.apply:
        deleter = delete or (lambda aid: delete_asset(aid, token, args.repo))
        deleted, failures = apply_plan(plan, deleter)
    report = format_report(plan, applied=args.apply, deleted=deleted, failures=failures)
    print(report)
    if args.list:
        for item in plan.prune:
            print(f"{item['tag']}/{item['name']}  downloads={item['download_count']}")
    if args.report:
        Path(args.report).write_text(report, encoding="utf-8")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
