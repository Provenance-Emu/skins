"""Prepare and publish an explicitly approved migration to a creator's canonical releases.

Preparation writes a reviewable inventory in a local staging directory. Publication
uploads the staged assets, preserves unambiguous existing skin IDs, then replaces
only this creator's old listings. Old pack links redirect to the creator page.
"""

import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import threading
import time
from urllib.parse import unquote, urlsplit
from zipfile import ZipFile

import blocklist
from creator_policy import author_slug
from generate_thumbnails import upload_release_asset, delete_cached_asset
from import_release_skins import MAX_FULL_DOWNLOAD, name_key, plan_import, release_assets
from link_health import classify_archive, load_skins
import polite_http
from repack_skins import MIRROR_BASE
from thumbnail_shards import list_release_assets, http_get_json
from skin_schema import derive_variant_label, fit_variant_label, make_id, slugify, validate_entry
from variants_sidecar import flush_imports, note_import


def reconcile(source, existing, plans):
    """Retain an ID only for a unique same-system name match to an actual skin."""
    old = [entry for entry in existing
           if (entry.get("author") or "").casefold() == source["attribution"].casefold()
           or (entry.get("source") or "").casefold() == source["repo"].casefold()]
    old_by_name, new_by_name = {}, {}
    for entry in old:
        # ZIP pack records have no one-to-one equivalence to their contained skins.
        if urlsplit(entry["downloadURL"]).path.lower().endswith((".deltaskin", ".manicskin")):
            old_by_name.setdefault(name_key(entry), []).append(entry)
    for plan in plans:
        new_by_name.setdefault(name_key(plan["entry"]), []).append(plan)
    retained = []
    for key, matches in new_by_name.items():
        candidates = old_by_name.get(key, [])
        if len(matches) != 1 or len(candidates) != 1:
            continue
        plan, previous = matches[0], candidates[0]
        old_id = previous["id"]
        plan["entry"]["id"] = old_id
        extension = Path(plan["asset"]).suffix
        plan["asset"] = old_id + extension
        plan["entry"]["downloadURL"] = MIRROR_BASE + plan["asset"]
        plan["destination"] = previous["_source_file"]
        for field in ("thumbnailURL", "screenshotURLs", "submittedAt", "submittedBy", "addedAt"):
            if previous.get(field):
                plan["entry"][field] = previous[field]
        retained.append(old_id)
    # Preserve all retirement information for review. It also keeps old shared URLs usable.
    retired = [entry for entry in old if entry["id"] not in retained]
    return old, retained, retired


def group_plans(repo, plans):
    for index, plan in enumerate(plans, 1):
        entry = plan["entry"]
        asset_name = Path(unquote(urlsplit(entry["originalURL"]).path)).name
        group_name = re.sub(r"[._]+", " ", Path(asset_name).stem)
        group_name = re.sub(r"\s*-?\s*Part\s+\d+$", "", group_name, flags=re.I).strip()
        entry["groupId"] = make_id(repo, "release-group:" + group_name.casefold())
        entry["groupOrder"] = index
        entry["variantLabel"] = fit_variant_label(
            derive_variant_label(entry["name"], group_name) or entry["name"]
        )


def prepare(source, tags, directory, skins_dir):
    if blocklist.is_repo_blocked(source["repo"]):
        raise ValueError("This source is opted out")
    directory.mkdir(parents=True, exist_ok=True)
    stage = directory / "assets"
    stage.mkdir(exist_ok=True)
    existing = load_skins(str(skins_dir))
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN", "")
    assets = release_assets(source["repo"], tags, token)
    if not assets:
        raise ValueError("No published release assets found")
    client = polite_http.get_client()

    def download(asset):
        result = client.get_file(asset["browser_download_url"], component="release-migration",
                                 max_bytes=MAX_FULL_DOWNLOAD)
        return asset["browser_download_url"], result.path

    downloaded = {}
    with ThreadPoolExecutor(max_workers=4) as executor:
        for url, path in executor.map(download, assets):
            downloaded[url] = path
            print(f"Downloaded {len(downloaded)}/{len(assets)}", flush=True)
    # The selected releases explicitly replace this creator's previous catalog source.
    # Duplicates across releases and starter packs are reconciled before any publication.
    plans, skipped = plan_import(source, [], assets, lambda url: downloaded[url].read_bytes(),
                                 stage_dir=stage)
    if not plans:
        raise ValueError("Migration inventory contains no skins")
    old, retained, retired = reconcile(source, existing, plans)
    planned_ids = [plan["entry"]["id"] for plan in plans]
    unrelated_ids = {entry["id"] for entry in existing} - {entry["id"] for entry in old}
    if len(planned_ids) != len(set(planned_ids)) or set(planned_ids) & unrelated_ids:
        raise ValueError("Migration would introduce a duplicate catalog ID")
    group_plans(source["repo"], plans)
    for index, plan in enumerate(plans):
        tag = f"mirror-{author_slug(source['attribution'])}-{index // 900 + 1}"
        plan["mirrorTag"] = tag
        plan["entry"]["downloadURL"] = (
            f"https://github.com/Provenance-Emu/skins/releases/download/{tag}/{plan['asset']}"
        )
    for plan in plans:
        if not plan.get("destination"):
            entry = plan["entry"]
            plan["destination"] = str(skins_dir / entry["systems"][0] /
                                      f"{slugify(entry['name'])}-{entry['id']}.json")
        plan["sha256"] = hashlib.sha256(plan["skin"]["staged"].read_bytes()).hexdigest()
        errors = validate_entry(plan["entry"])
        if errors:
            raise ValueError(str(errors))
    report = {
        "source": source, "tags": tags, "assets": len(assets), "new_count": len(plans),
        "retained_ids": retained,
        "retired": [{"id": entry["id"], "name": entry["name"], "path": entry["_source_file"],
                     "url": entry["downloadURL"]} for entry in retired],
        "original_files": {entry["_source_file"]: hashlib.sha256(
            Path(entry["_source_file"]).read_bytes()).hexdigest() for entry in old},
        "skipped": skipped, "plans": plans,
    }
    (directory / "plan.json").write_text(json.dumps(report, indent=2, default=str) + "\n")
    print(json.dumps({key: value for key, value in report.items()
                      if key not in ("plans", "original_files", "retired")}, indent=2))
    print(f"Retiring {len(retired)} pack/obsolete listings; plan in {directory / 'plan.json'}")



def publish_assets(plans, directory):
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN", "")
    published = 0
    gate = threading.Lock()
    next_request = [time.monotonic()]
    tags = dict.fromkeys(plan["mirrorTag"] for plan in plans)
    for tag in tags:
        view = subprocess.run(
            ["gh", "release", "view", tag, "--repo", "Provenance-Emu/skins",
             "--json", "databaseId"], capture_output=True, text=True
        )
        if view.returncode:
            if "release not found" not in view.stderr.lower():
                raise RuntimeError(view.stderr)
            subprocess.run(["gh", "release", "create", tag, "--repo", "Provenance-Emu/skins",
                            "--target", "main", "--title", tag,
                            "--notes", "Installable skins extracted from the creator's GitHub releases. "
                            "Original release URLs are recorded in each catalog entry."], check=True)
        release = http_get_json(
            f"https://api.github.com/repos/Provenance-Emu/skins/releases/tags/{tag}", token
        )
        remote = {asset["name"]: asset for asset in list_release_assets(
            release, lambda url: http_get_json(url, token))}
        selected = [plan for plan in plans if plan["mirrorTag"] == tag]
        if len(set(remote) | {plan["asset"] for plan in selected}) > 950:
            raise ValueError(f"Mirror release is full: {tag}")
        pending = [plan for plan in selected if
                   remote.get(plan["asset"], {}).get("digest") != "sha256:" + plan["sha256"]]
        published += len(selected) - len(pending)
        def send(plan):
            with gate:
                time.sleep(max(0, next_request[0] - time.monotonic()))
                next_request[0] = time.monotonic() + 1.1
            previous = remote.get(plan["asset"])
            if previous:
                delete_cached_asset(previous["id"], token)
            result = upload_release_asset(
                release["upload_url"], plan["asset"],
                (directory / "publish" / plan["asset"]).read_bytes(),
                token, content_type="application/zip", raise_rate_limit=True
            )
            if result != plan["entry"]["downloadURL"]:
                raise RuntimeError(f"Upload was not confirmed: {plan['asset']}. Rerun to resume.")
            return result

        with ThreadPoolExecutor(max_workers=2) as executor:
            for _ in executor.map(send, pending):
                published += 1
                if published % 20 == 0 or published == len(plans):
                    print(f"Uploaded {published}/{len(plans)}", flush=True)


def publish(directory):
    report = json.loads((directory / "plan.json").read_text())
    source, plans = report["source"], report["plans"]
    if blocklist.is_repo_blocked(source["repo"]):
        raise ValueError("This source is opted out")
    # A local marker permits resuming an interrupted application of this exact plan.
    # Unexpected edits still stop before any upload or metadata overwrite.
    marker = directory / "publication-started"
    resumed = marker.exists()
    expected = {plan["destination"]: plan["entry"] for plan in plans}
    retired_paths = {entry["path"] for entry in report["retired"]}
    for name, digest in report["original_files"].items():
        path = Path(name)
        if not path.exists():
            if resumed and name in retired_paths:
                continue
            raise ValueError(f"Existing catalog file disappeared: {name}")
        if hashlib.sha256(path.read_bytes()).hexdigest() == digest:
            continue
        if resumed and name in expected and json.loads(path.read_text()) == expected[name]:
            continue
        raise ValueError(f"Existing catalog file changed: {name}")
    for plan in plans:
        staged = Path(plan["skin"]["staged"])
        if hashlib.sha256(staged.read_bytes()).hexdigest() != plan["sha256"]:
            raise ValueError(f"Staged asset changed: {staged}")
        destination = Path(plan["destination"])
        if destination.exists() and str(destination) not in report["original_files"]:
            if not resumed or json.loads(destination.read_text()) != plan["entry"]:
                raise ValueError(f"Destination exists: {destination}")
        asset = directory / "publish" / plan["asset"]
        asset.parent.mkdir(exist_ok=True)
        if asset.exists():
            asset.unlink()
        os.link(staged, asset)
    publish_assets(plans, directory)
    marker.touch()
    for plan in plans:
        with ZipFile(plan["skin"]["staged"]) as archive:
            verified = classify_archive(archive, record_device_support=True)
        if verified["result"] != "ok":
            raise ValueError(f"Staged skin is no longer installable: {plan['asset']}")
        plan["entry"]["deviceSupport"] = verified.get("deviceSupport", [])
    # Write the sidecar first. Orphan records are harmless until referenced by metadata.
    for plan in plans:
        note_import(plan["entry"]["downloadURL"], plan["skin"]["info"])
    flush_imports([plan["entry"] for plan in plans])
    for plan in plans:
        destination = Path(plan["destination"])
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(json.dumps(plan["entry"], indent=2, ensure_ascii=False) + "\n")
    for entry in report["retired"]:
        Path(entry["path"]).unlink(missing_ok=True)
    redirects_path = Path("skin-redirects.json")
    redirects = json.loads(redirects_path.read_text()) if redirects_path.exists() else {}
    target = "authors/" + author_slug(source["attribution"]) + ".html"
    for entry in report["retired"]:
        redirects[entry["id"]] = target
    redirects_path.write_text(json.dumps(redirects, indent=2, sort_keys=True) + "\n")
    (directory / "plan.json").write_text(json.dumps(report, indent=2) + "\n")
    summary = {key: value for key, value in report.items()
               if key not in ("plans", "original_files")}
    summary_path = Path("docs/maintainers") / (author_slug(source["attribution"]) + "-migration.json")
    summary_path.write_text(json.dumps(summary, indent=2) + "\n")
    print(f"Published {len(plans)} skins; retired {len(report['retired'])} source listings.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", required=True)
    parser.add_argument("--tag", action="append", default=[])
    parser.add_argument("--stage", type=Path, required=True)
    parser.add_argument("--sources", type=Path, default=Path("sources.json"))
    parser.add_argument("--skins-dir", type=Path, default=Path("skins"))
    parser.add_argument("--publish", action="store_true")
    args = parser.parse_args()
    sources = json.loads(args.sources.read_text())["repos"]
    matches = [source for source in sources if source["repo"] == args.repo]
    if len(matches) != 1:
        parser.error("Choose one registered source")
    if args.publish:
        report = json.loads((args.stage / "plan.json").read_text())
        if report["source"] != matches[0]:
            parser.error("Staged source no longer matches registration")
        publish(args.stage)
    else:
        if not args.tag:
            parser.error("Specify current release tags, newest first")
        prepare(matches[0], args.tag, args.stage, args.skins_dir)


if __name__ == "__main__":
    main()
