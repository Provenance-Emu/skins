#!/usr/bin/env python3
"""
validate_creator.py — Validate creators/<slug>.json files. Used by CI on PRs.

Usage:
    python3 scripts/validate_creator.py creators/aphaits.json
    python3 scripts/validate_creator.py --diff-base origin/main --pr-author SOMEONE

The second form is what validate-pr.yml runs. It finds the creator files the PR
adds, changes or deletes and checks, besides the schema, who may do so:

  - A maintainer (an @user in CODEOWNERS) may change anything.
  - A new profile must come from a maintainer: claims go through the claim bot,
    which proves ownership first (design §3).
  - Otherwise the PR author must be the `githubLogin` the file has on the base
    branch, and may not touch the fields that grant or prove ownership
    (`slug`, `githubLogin`, `aliases`, `claim`, `hidden`). Letting a creator edit
    their own aliases would let them take over an author name nobody verified.
    To change those, refile the claim form or ask a maintainer.
"""

import argparse
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from skin_schema import validate_creator

REPO_ROOT = Path(__file__).resolve().parent.parent
CREATORS_DIR = "creators"

# Only a maintainer may change these. Everything else is the creator's to edit.
PROTECTED_FIELDS = ("slug", "githubLogin", "aliases", "claim", "hidden")


def load_maintainers(codeowners: Path = REPO_ROOT / "CODEOWNERS") -> set[str]:
    """Lower-cased user logins named in CODEOWNERS (teams and e-mail owners are ignored)."""
    users = set()
    try:
        text = codeowners.read_text(encoding="utf-8")
    except OSError:
        return users
    for line in text.splitlines():
        line = line.split("#", 1)[0]
        for token in line.split()[1:]:
            if token.startswith("@") and "/" not in token:
                users.add(token[1:].lower())
    return users


def check_change(status: str, base: "dict | None", head: "dict | None",
                 pr_author: str, maintainers: set[str]) -> list[str]:
    """Authorization errors for one creator file. `status` is git's A, M or D;
    `base`/`head` are the parsed files on each side (None when absent or unparsable)."""
    author = (pr_author or "").lower()
    if author in maintainers:
        return []
    if status == "A":
        return ["new creator profiles come from the claim form (a maintainer can add one directly)"]
    owner = ((base or {}).get("githubLogin") or "").lower()
    if not owner or author != owner:
        return [f"only the profile's githubLogin ({owner or 'unknown'}) or a maintainer may change it; PR author is {pr_author or 'unknown'}"]
    if status == "D" or head is None:
        return []
    base = base or {}
    return [f"{f} can only be changed by a maintainer" for f in PROTECTED_FIELDS
            if base.get(f) != head.get(f)]


def _git(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], capture_output=True, text=True, cwd=REPO_ROOT)


def _parse(text: "str | None") -> "dict | None":
    try:
        obj = json.loads(text) if text is not None else None
    except ValueError:
        return None
    return obj if isinstance(obj, dict) else None


def changed_files(base_ref: str) -> list[tuple[str, str]]:
    """(status, path) for creators/*.json the PR changes relative to `base_ref`."""
    out = _git("diff", "--name-status", "--no-renames", f"{base_ref}...HEAD", "--", f"{CREATORS_DIR}/")
    if out.returncode != 0:
        raise SystemExit(f"git diff failed: {out.stderr.strip()}")
    changes = []
    for line in out.stdout.splitlines():
        status, _, path = line.partition("\t")
        if path.endswith(".json") and path.count("/") == 1:
            changes.append((status[:1], path))
    return changes


def validate_file(path: Path) -> list[str]:
    try:
        obj = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        return [f"cannot read as JSON: {e}"]
    return validate_creator(obj, filename_slug=path.stem)


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate creator profile files")
    parser.add_argument("files", nargs="*", help="creators/<slug>.json files")
    parser.add_argument("--diff-base", help="git ref of the PR base; validates every creator file the PR changes")
    parser.add_argument("--pr-author", default="", help="GitHub login of the PR author (checked with --diff-base)")
    args = parser.parse_args()
    if not args.files and not args.diff_base:
        parser.error("give files or --diff-base")

    total = 0
    for f in args.files:
        errors = validate_file(Path(f))
        print(("INVALID: " if errors else "OK: ") + f)
        for e in errors:
            print(f"  - {e}")
        total += len(errors)

    if args.diff_base:
        maintainers = load_maintainers()
        for status, path in changed_files(args.diff_base):
            errors = []
            head = None
            if status != "D":
                errors += validate_file(REPO_ROOT / path)
                head = _parse((REPO_ROOT / path).read_text(encoding="utf-8")) if (REPO_ROOT / path).exists() else None
            base_show = _git("show", f"{args.diff_base}:{path}")
            base = _parse(base_show.stdout) if base_show.returncode == 0 else None
            errors += check_change(status, base, head, args.pr_author, maintainers)
            print(("INVALID: " if errors else "OK: ") + f"{path} ({status})")
            for e in errors:
                print(f"  - {e}")
            total += len(errors)

    if total:
        print(f"\n{total} error(s) found.")
        sys.exit(1)
    print("\nAll creator files valid.")


if __name__ == "__main__":
    main()
