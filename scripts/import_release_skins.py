"""Import registered creators' release skins and ZIP packs without duplicating catalog skins.

Dry-run by default. Index every existing skin by the same author before planning
new entries. An unavailable existing archive aborts the import before publication.
"""

import argparse
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import tempfile
from urllib.parse import quote, urlsplit
from zipfile import ZipFile

import blocklist
from content_policy import apply_mature_tag
import polite_http
from link_health import MAX_FULL_DOWNLOAD, classify_archive, load_skins, parse_info_json
from process_submission import gh_api
from repack_skins import MIRROR_BASE, upload
from thumbnail_shards import list_release_assets
from skin_schema import make_id, normalize_entry, slugify, system_from_gti, validate_entry
from variants_sidecar import flush_imports, note_import

MAX_EXPANDED = 512 * 1024 * 1024
MAX_FILES = 10000
SKIN_EXTENSIONS = (".deltaskin", ".manicskin")


def unpack_skins(data):
    """Read nested packs with shared byte/entry budgets. Never extract archive paths."""
    budget = {"bytes": 0, "files": 0}

    def visit(body, depth, label):
        if depth > 3:
            raise ValueError(f"{label}: packs are nested more than three levels")
        with ZipFile(io.BytesIO(body)) as archive:
            members = [entry for entry in archive.infolist() if not entry.is_dir()
                       and "__MACOSX" not in PurePosixPath(entry.filename).parts
                       and PurePosixPath(entry.filename).name != ".DS_Store"]
            names = [entry.filename for entry in members]
            if len(names) != len(set(names)):
                raise ValueError(f"{label}: duplicate archive paths")
            if any("\\" in name or PurePosixPath(name).is_absolute()
                   or ".." in PurePosixPath(name).parts for name in names):
                raise ValueError(f"{label}: unsafe archive path")
            budget["files"] += len(members)
            budget["bytes"] += sum(entry.file_size for entry in members)
            if budget["files"] > MAX_FILES or budget["bytes"] > MAX_EXPANDED:
                raise ValueError(f"{label}: archive expansion limit exceeded")

            # A root skin takes precedence over any incidental ZIP assets it carries.
            if "info.json" in names:
                result = classify_archive(archive, record_device_support=True)
                if result["result"] != "ok":
                    raise ValueError(f"{label}: skin is not installable ({result['result']})")
                info = parse_info_json(archive.read("info.json"))
                digest = hashlib.sha256()
                for name in sorted(names):
                    content = archive.read(name)
                    if name == "info.json":
                        content = json.dumps(info, sort_keys=True, separators=(",", ":")).encode()
                    digest.update(json.dumps(name).encode())
                    digest.update(hashlib.sha256(content).digest())
                return [{"data": body, "info": info, "fingerprint": digest.hexdigest(), "path": label,
                         "deviceSupport": result.get("deviceSupport", [])}]

            result = []
            roots = []
            for name in sorted(names, key=lambda item: item.count("/")):
                if name.endswith("/info.json"):
                    prefix = name[:-len("info.json")]
                    if not any(prefix.startswith(root) for root in roots):
                        roots.append(prefix)
            if roots:
                for prefix in roots:
                    wrapped = io.BytesIO()
                    with ZipFile(wrapped, "w") as out:
                        for name in names:
                            if name.startswith(prefix):
                                out.writestr(name[len(prefix):], archive.read(name))
                    result.extend(visit(wrapped.getvalue(), depth + 1, label + "/" + prefix))
            for name in names:
                if any(name.startswith(prefix) for prefix in roots):
                    continue
                if name.lower().endswith((*SKIN_EXTENSIONS, ".zip")):
                    result.extend(visit(archive.read(name), depth + 1, label + "/" + name))
            return result

    return visit(data, 0, "archive")


def identity(info):
    gti = str(info.get("gameTypeIdentifier") or "")
    identifier = info.get("identifier")
    return (gti, identifier) if isinstance(identifier, str) and identifier.strip() else None


def name_key(info):
    name = re.sub(r"\s+", " ", str(info.get("name") or "")).strip().casefold()
    gti = str(info.get("gameTypeIdentifier") or "")
    return (system_from_gti(gti) or gti, name) if name else None


def plan_import(source, existing, assets, read, baseline_dir=None, stage_dir=None):
    """All comparisons are scoped to this source's credited author."""
    author = source["attribution"]
    fingerprints, identities, names = set(), set(), set()
    relevant = [entry for entry in existing
                if (entry.get("author") or "").casefold() == author.casefold()
                or (entry.get("source") or "").casefold() == source["repo"].casefold()]
    for entry in relevant:
        baseline = baseline_dir / f"{entry['id']}.zip" if baseline_dir else None
        if baseline and baseline.is_file():
            if baseline.stat().st_size > MAX_FULL_DOWNLOAD:
                raise ValueError(f"{entry['id']}: baseline archive exceeds download limit")
            data = baseline.read_bytes()
        else:
            try:
                data = read(entry["downloadURL"])
            except Exception as error:
                raise ValueError(
                    f"Cannot compare existing listing {entry['id']} ({entry['downloadURL']}): {error}. "
                    "No imports published. Supply its original archive using --baseline-dir."
                ) from error
        skins = unpack_skins(data)
        if not skins:
            raise ValueError(f"Cannot index existing listing {entry['id']}: no skins found")
        for skin in skins:
            fingerprints.add(skin["fingerprint"])
            if identity(skin["info"]):
                identities.add(identity(skin["info"]))
            if name_key(skin["info"]):
                names.add(name_key(skin["info"]))

    plans, skipped = [], {"identical": 0, "existing_identity": 0, "existing_name": 0}
    for asset in assets:
        skins = unpack_skins(read(asset["browser_download_url"]))
        if not skins:
            raise ValueError(f"{asset['name']}: no installable skins found")
        for skin in skins:
            info, fingerprint = skin["info"], skin["fingerprint"]
            ident, name = identity(info), name_key(info)
            if fingerprint in fingerprints:
                skipped["identical"] += 1
                continue
            # Changed data under an existing identifier/name needs a separately reviewed
            # update to that listing, preserving its id. Never add a second listing.
            if ident and ident in identities:
                skipped["existing_identity"] += 1
                continue
            if name and name in names:
                skipped["existing_name"] += 1
                continue
            system = system_from_gti(info.get("gameTypeIdentifier", ""))
            if not system or not info.get("name"):
                raise ValueError(f"{asset['name']}: missing skin name or supported game type")
            sid = make_id(source["repo"], fingerprint)
            extension = ".manicskin" if (
                skin["path"].lower().endswith(".manicskin")
                or str(info.get("gameTypeIdentifier", "")).startswith("public.aoshuang")
            ) else ".deltaskin"
            entry = normalize_entry({
                "id": sid, "name": info["name"], "author": author,
                "source": source["repo"], "systems": [system],
                "gameTypeIdentifier": info["gameTypeIdentifier"],
                "downloadURL": MIRROR_BASE + sid + extension,
                "originalURL": asset["browser_download_url"],
                "fileSize": len(skin["data"]),
                "deviceSupport": skin.get("deviceSupport", []),
                "version": info.get("version") or info.get("bundleVersion"),
            })
            apply_mature_tag(entry)
            if blocklist.is_blocked(entry):
                continue
            errors = validate_entry(entry)
            if errors:
                raise ValueError(f"{asset['name']}: {errors}")
            if stage_dir:
                staged = stage_dir / (sid + extension)
                staged.write_bytes(skin["data"])
                skin = {key: value for key, value in skin.items() if key != "data"}
                skin["staged"] = staged
            plans.append({"entry": entry, "skin": skin, "asset": sid + extension})
            fingerprints.add(fingerprint)
            if ident:
                identities.add(ident)
            if name:
                names.add(name)
    return plans, skipped


def release_assets(repo, tags, token):
    assets, seen = [], set()
    for tag in tags:
        release = gh_api(f"repos/{repo}/releases/tags/{quote(tag, safe='')}", token)
        if release.get("draft") or release.get("prerelease"):
            raise ValueError(f"{tag}: expected a published, stable release")
        assets_in_release = list_release_assets(
            release, lambda url: gh_api(url.removeprefix("https://api.github.com/"), token)
        )
        for asset in assets_in_release:
            if not asset["name"].lower().endswith((*SKIN_EXTENSIONS, ".zip")):
                continue
            url = asset["browser_download_url"]
            parsed = urlsplit(url)
            if parsed.scheme != "https" or parsed.netloc != "github.com" or not parsed.path.startswith(f"/{repo}/releases/download/"):
                raise ValueError("Unexpected release asset URL")
            if asset.get("size", MAX_FULL_DOWNLOAD + 1) > MAX_FULL_DOWNLOAD:
                raise ValueError(f"{asset['name']}: download limit exceeded")
            if url not in seen:
                assets.append(asset)
                seen.add(url)
    return assets


def run_source(source, existing, skins_dir, publish, tags=None, baseline_dir=None):
    if blocklist.is_repo_blocked(source["repo"]):
        raise ValueError(f"{source['repo']}: source is opted out")
    if not source.get("attribution"):
        raise ValueError("Release sources require an attribution name")
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN", "")
    tags = tags or source.get("releaseTags")
    if not isinstance(tags, list) or not tags or not all(isinstance(tag, str) and tag for tag in tags):
        raise ValueError("Specify release tags explicitly, newest first, excluding legacy packs")
    client = polite_http.get_client()

    def read(url):
        return client.get_bytes(url, component="release-import", max_bytes=MAX_FULL_DOWNLOAD)

    assets = release_assets(source["repo"], tags, token)
    with tempfile.TemporaryDirectory(prefix="release-skins-") as directory:
        plans, skipped = plan_import(source, existing, assets, read, baseline_dir, Path(directory))
        print(json.dumps({"repo": source["repo"], "assets": len(assets),
                          "new_skins": len(plans), "skipped": skipped}, indent=2))
        if not publish:
            print("Dry run: nothing uploaded or written.")
            return
        # Check output paths before uploading anything. All downloads and duplicate
        # checks have completed, so failures cannot leave partially indexed packs.
        paths = []
        for plan in plans:
            entry = plan["entry"]
            path = skins_dir / entry["systems"][0] / f"{slugify(entry['name'])}-{entry['id']}.json"
            if path.exists():
                raise ValueError(f"Output already exists: {path}")
            paths.append(path)
        if not plans:
            return
        upload([str(plan["skin"]["staged"]) for plan in plans])
        for plan in plans:
            note_import(plan["entry"]["downloadURL"], plan["skin"]["info"])
        flush_imports([plan["entry"] for plan in plans])
        for plan, path in zip(plans, paths):
            path.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, delete=False) as pending:
                pending.write(json.dumps(plan["entry"], indent=2, ensure_ascii=False) + "\n")
            os.replace(pending.name, path)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sources", type=Path, default=Path("sources.json"))
    parser.add_argument("--skins-dir", type=Path, default=Path("skins"))
    parser.add_argument("--repo", help="A registered source; default: every source with releaseTags")
    parser.add_argument("--tag", action="append", help="Release tag, newest first. Repeat for more releases.")
    parser.add_argument("--publish", action="store_true")
    parser.add_argument("--baseline-dir", type=Path,
                        help="Original existing packs as <catalog-id>.zip, when their host is unavailable")
    args = parser.parse_args()
    sources = json.loads(args.sources.read_text())["repos"]
    if args.repo:
        selected = [source for source in sources
                    if source["repo"].casefold() == args.repo.casefold()]
    else:
        selected = [source for source in sources if source.get("releaseTags")]
    if args.repo and not selected:
        parser.error("Repository must be registered in sources.json")
    if args.tag and not args.repo:
        parser.error("--tag requires --repo")
    for source in selected:
        if not args.repo and blocklist.is_repo_blocked(source["repo"]):
            print(f"Skipping opted-out release source: {source['repo']}")
            continue
        try:
            existing = load_skins(str(args.skins_dir))
            run_source(source, existing, args.skins_dir, args.publish, args.tag, args.baseline_dir)
        except Exception as error:
            parser.exit(1, f"Release import stopped for {source['repo']}: {error}\n")


if __name__ == "__main__":
    main()
