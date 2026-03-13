#!/usr/bin/env python3
"""
process_submission.py — Process a skin submission URL and generate catalog JSON entry files.

Handles:
  - Direct skin file URL (.deltaskin / .manicskin)
  - GitHub repo URL → scans all skin files in the repo
  - GitHub release URL → finds skin file assets
  - Raw JSON metadata URL → validates and normalizes

Usage:
    python3 scripts/process_submission.py <url> --output-dir skins/
    python3 scripts/process_submission.py <url> --output-dir skins/ --github-token TOKEN
    python3 scripts/process_submission.py <url> --dry-run
"""

import argparse
import json
import os
import re
import sys
import urllib.request
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path

# Add scripts/ to path so we can import siblings
sys.path.insert(0, str(Path(__file__).parent))
from extract_metadata import stream_extract_info_json
from skin_schema import (
    make_id, slugify, normalize_entry, validate_entry,
    system_from_gti, system_from_name, GTI_TO_CODE,
)


def gh_api(path: str, token: str = "") -> dict | list:
    url = f"https://api.github.com/{path.lstrip('/')}"
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "Provenance-SkinCatalog/1.0",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read())


def detect_url_type(url: str) -> str:
    """
    Returns one of: 'skin_file', 'github_repo', 'github_release', 'json_metadata', 'unknown'
    """
    if re.search(r"\.(deltaskin|manicskin)(\?.*)?$", url, re.I):
        return "skin_file"
    m = re.match(r"https?://github\.com/([^/]+/[^/]+)/releases", url)
    if m:
        return "github_release"
    m = re.match(r"https?://github\.com/([^/]+/[^/]+)/?$", url)
    if m:
        return "github_repo"
    if re.search(r"\.json(\?.*)?$", url, re.I):
        return "json_metadata"
    # Raw github URL ending in skin file
    if "raw.githubusercontent.com" in url and re.search(r"\.(deltaskin|manicskin)", url, re.I):
        return "skin_file"
    return "unknown"


def process_skin_file(url: str, token: str = "", source: str = "manual",
                      submitted_by: str = None) -> list[dict]:
    """Extract metadata from a single skin file URL and return a list with one entry."""
    print(f"  Fetching info.json from {url}")
    info = stream_extract_info_json(url, token)

    entry = {
        "id": make_id(source, url),
        "downloadURL": url,
        "source": source,
    }

    if info:
        name = info.get("name") or Path(urllib.parse.urlparse(url).path).stem
        gti = info.get("gameTypeIdentifier", "")
        system_code = system_from_gti(gti) if gti else None

        entry.update({
            "name": name,
            "gameTypeIdentifier": gti or None,
            "systems": [system_code] if system_code else ["unofficial"],
            "version": info.get("version") or info.get("bundleVersion"),
        })
    else:
        # Minimal fallback — name from filename
        stem = Path(urllib.parse.urlparse(url).path).stem
        entry.update({
            "name": stem,
            "systems": ["unofficial"],
        })
        print(f"  Warning: could not extract info.json, using filename as name")

    if submitted_by:
        entry["submittedBy"] = submitted_by
    entry["submittedAt"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    return [normalize_entry(entry)]


def process_github_repo(repo: str, token: str = "", submitted_by: str = None) -> list[dict]:
    """Scan a GitHub repo for all skin files and return entries for each."""
    print(f"  Scanning GitHub repo: {repo}")
    try:
        tree = gh_api(f"repos/{repo}/git/trees/HEAD?recursive=1", token)
    except Exception as e:
        print(f"  Error fetching repo tree: {e}", file=sys.stderr)
        return []

    skin_paths = [
        item["path"] for item in tree.get("tree", [])
        if item["path"].lower().endswith((".deltaskin", ".manicskin"))
    ]
    print(f"  Found {len(skin_paths)} skin files")

    entries = []
    for path in skin_paths:
        raw_url = f"https://raw.githubusercontent.com/{repo}/HEAD/{path}"
        try:
            result = process_skin_file(raw_url, token, source=repo, submitted_by=submitted_by)
            entries.extend(result)
        except Exception as e:
            print(f"  Skipping {path}: {e}", file=sys.stderr)

    return entries


def process_github_release(url: str, token: str = "", submitted_by: str = None) -> list[dict]:
    """Find skin file assets in a GitHub release."""
    m = re.match(r"https?://github\.com/([^/]+/[^/]+)/releases(?:/tag/([^/]+))?", url)
    if not m:
        return []
    repo = m.group(1)
    tag = m.group(2)

    api_path = f"repos/{repo}/releases/latest" if not tag else f"repos/{repo}/releases/tags/{tag}"
    try:
        release = gh_api(api_path, token)
    except Exception as e:
        print(f"  Error fetching release: {e}", file=sys.stderr)
        return []

    entries = []
    for asset in release.get("assets", []):
        name = asset["name"]
        if name.lower().endswith((".deltaskin", ".manicskin")):
            dl_url = asset["browser_download_url"]
            try:
                result = process_skin_file(dl_url, token, source=repo, submitted_by=submitted_by)
                entries.extend(result)
            except Exception as e:
                print(f"  Skipping asset {name}: {e}", file=sys.stderr)

    return entries


def process_json_metadata(url: str, submitted_by: str = None) -> list[dict]:
    """Fetch a JSON metadata file and normalize it as a catalog entry."""
    req = urllib.request.Request(url, headers={"User-Agent": "Provenance-SkinCatalog/1.0"})
    with urllib.request.urlopen(req, timeout=15) as r:
        data = json.loads(r.read())

    if isinstance(data, list):
        entries = data
    elif isinstance(data, dict) and "skins" in data:
        entries = data["skins"]
    else:
        entries = [data]

    result = []
    for e in entries:
        if "downloadURL" not in e:
            continue
        if "id" not in e:
            e["id"] = make_id(e.get("source", "manual"), e["downloadURL"])
        if submitted_by:
            e["submittedBy"] = submitted_by
        result.append(normalize_entry(e))
    return result


def save_entries(entries: list[dict], output_dir: str, dry_run: bool = False) -> list[str]:
    """Write each entry to skins/{system}/{slug}.json. Returns list of written paths."""
    written = []
    for entry in entries:
        systems = entry.get("systems", ["unofficial"])
        system = systems[0] if systems else "unofficial"
        slug = slugify(entry.get("name", entry["id"]))
        rel_path = os.path.join(output_dir, system, f"{slug}.json")

        if dry_run:
            print(f"  [dry-run] Would write: {rel_path}")
            print(f"    {json.dumps(entry, indent=2)[:200]}...")
        else:
            os.makedirs(os.path.dirname(rel_path), exist_ok=True)
            with open(rel_path, "w") as f:
                json.dump(entry, f, indent=2, ensure_ascii=False)
                f.write("\n")
            print(f"  Written: {rel_path}")
        written.append(rel_path)
    return written


def main():
    parser = argparse.ArgumentParser(description="Process a skin submission URL")
    parser.add_argument("url", help="Skin file, GitHub repo, release, or JSON metadata URL")
    parser.add_argument("--output-dir", default="skins", help="Directory to write skin JSON files")
    parser.add_argument("--github-token", default=os.environ.get("GITHUB_TOKEN", ""))
    parser.add_argument("--submitted-by", default=None, help="GitHub username of submitter")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    url = args.url.strip()
    url_type = detect_url_type(url)
    print(f"URL type: {url_type}")

    if url_type == "skin_file":
        entries = process_skin_file(url, args.github_token, submitted_by=args.submitted_by)
    elif url_type == "github_repo":
        m = re.match(r"https?://github\.com/([^/]+/[^/]+)", url)
        repo = m.group(1) if m else url
        entries = process_github_repo(repo, args.github_token, submitted_by=args.submitted_by)
    elif url_type == "github_release":
        entries = process_github_release(url, args.github_token, submitted_by=args.submitted_by)
    elif url_type == "json_metadata":
        entries = process_json_metadata(url, submitted_by=args.submitted_by)
    else:
        # Last-ditch: try it as a skin file anyway
        print(f"Unknown URL type, attempting as skin file...")
        entries = process_skin_file(url, args.github_token, submitted_by=args.submitted_by)

    if not entries:
        print("No entries generated.", file=sys.stderr)
        sys.exit(1)

    print(f"\nGenerated {len(entries)} entr{'y' if len(entries)==1 else 'ies'}:")

    # Validate
    all_valid = True
    for e in entries:
        errors = validate_entry(e)
        if errors:
            print(f"  Validation errors for {e.get('name', e.get('id', '?'))}:")
            for err in errors:
                print(f"    - {err}")
            all_valid = False

    # Save
    written = save_entries(entries, args.output_dir, args.dry_run)

    # Output summary for GitHub Actions
    summary = {"entries": len(entries), "files": written, "valid": all_valid}
    print(f"\nSummary: {json.dumps(summary)}")

    # Write to GITHUB_OUTPUT if available
    github_output = os.environ.get("GITHUB_OUTPUT")
    if github_output:
        with open(github_output, "a") as f:
            f.write(f"entry_count={len(entries)}\n")
            f.write(f"files={json.dumps(written)}\n")
            f.write(f"valid={'true' if all_valid else 'false'}\n")

    sys.exit(0 if all_valid else 1)


if __name__ == "__main__":
    main()
