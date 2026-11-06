#!/usr/bin/env python3
"""
disputed.py — `disputed.json`: skins a maintainer upheld a copied-work report on.

A report ("Copied from another author without credit", filed with
`.github/ISSUE_TEMPLATE/report-skin.yml`) that a maintainer upholds gets the
`disputed` label. `.github/workflows/dispute.yml` then runs this script, which
adds the skin's id to `disputed.json`, and later removes it when the maintainer
labels the same issue `resolved`:

    {"version": 1, "disputed": {"<skin id>": {"issue": 123, "since": "2026-11-05"}}}

The file is data for `compute_creator_stats.py`: a disputed entry stays in the
catalog and on its page, but counts toward no creator's stats or badges. Edits
by hand are fine (keep it sorted); the bot writes it sorted, one id per record.

Everything the workflow passes in comes from `env:` (the issue body is
untrusted text); the only thing taken from it is a 16-character hex id.

    python3 scripts/disputed.py apply          # reads env, edits disputed.json
    python3 scripts/disputed.py check          # validate disputed.json
"""

import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent))

DISPUTED_FILE = "disputed.json"
DISPUTED_VERSION = 1
REPORT_LABEL = "content-report"
DISPUTE_LABEL = "disputed"
RESOLVE_LABEL = "resolved"

_ID_RE = re.compile(r"^[0-9a-f]{16}$")
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_SKIN_ID_FIELD = re.compile(r"^###\s+Skin ID\s*\n+([^\n]*)", re.MULTILINE)


class DisputedError(Exception):
    """disputed.json is unreadable or invalid."""


def validate_disputed(doc) -> list[str]:
    """Error strings for a parsed disputed.json (empty = valid)."""
    if not isinstance(doc, dict):
        return ["must be a JSON object"]
    errors = []
    if doc.get("version") != DISPUTED_VERSION:
        errors.append(f"version must be {DISPUTED_VERSION}, got {doc.get('version')!r}")
    for key in sorted(set(doc) - {"version", "disputed"}):
        errors.append(f"unknown top-level key: {key}")
    records = doc.get("disputed")
    if not isinstance(records, dict):
        errors.append('"disputed" must be an object keyed by skin id')
        return errors
    for skin_id, rec in records.items():
        if not isinstance(skin_id, str) or not _ID_RE.fullmatch(skin_id):
            errors.append(f"{skin_id!r}: skin ids are 16 lowercase hex characters")
        if not isinstance(rec, dict):
            errors.append(f"{skin_id}: record must be an object")
            continue
        issue = rec.get("issue")
        if not isinstance(issue, int) or isinstance(issue, bool) or issue < 1:
            errors.append(f"{skin_id}: issue must be a positive integer")
        since = rec.get("since")
        if not isinstance(since, str) or not _DATE_RE.fullmatch(since):
            errors.append(f"{skin_id}: since must be a YYYY-MM-DD date")
        for key in sorted(set(rec) - {"issue", "since"}):
            errors.append(f"{skin_id}: unknown field: {key}")
    return errors


def load_disputed(path: str = DISPUTED_FILE) -> dict:
    """The disputed records as {skin id: {"issue": int, "since": str}}.
    A missing file is an empty list. An invalid one raises DisputedError: a
    silent {} would put disputed work back into every creator's stats."""
    if not os.path.exists(path):
        return {}
    try:
        with open(path, encoding="utf-8") as f:
            doc = json.load(f)
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        raise DisputedError(f"{path}: invalid JSON: {e}") from e
    errors = validate_disputed(doc)
    if errors:
        raise DisputedError(f"{path}: " + "; ".join(errors))
    return doc["disputed"]


def save_disputed(records: dict, path: str = DISPUTED_FILE) -> None:
    doc = {"version": DISPUTED_VERSION, "disputed": {k: records[k] for k in sorted(records)}}
    with open(path, "w", encoding="utf-8") as f:
        json.dump(doc, f, indent=2, ensure_ascii=False)
        f.write("\n")


def add_dispute(records: dict, skin_id: str, issue: int, today: str) -> bool:
    """Record `skin_id` as disputed by `issue`. True if the file changed. An id
    that is already listed keeps its first issue and date (labelling twice, or
    a second report of the same skin, changes nothing)."""
    if skin_id in records:
        return False
    records[skin_id] = {"issue": issue, "since": today}
    return True


def remove_dispute(records: dict, skin_id: str) -> bool:
    """Drop `skin_id`. True if it was listed."""
    return records.pop(skin_id, None) is not None


def parse_skin_id(issue_body: Optional[str]) -> Optional[str]:
    """The id from the report form's "Skin ID" field, or None when it is not a
    16-character hex id. Nothing else in the body is read."""
    m = _SKIN_ID_FIELD.search((issue_body or "").replace("\r\n", "\n"))
    if not m:
        return None
    value = m.group(1).strip().strip("`").lower()
    return value if _ID_RE.fullmatch(value) else None


def known_skin_ids(skins_dir: str = "skins") -> set:
    """Ids of every skin file, hidden-download ones included."""
    ids = set()
    for root, _dirs, files in os.walk(skins_dir):
        for name in files:
            if not name.endswith(".json"):
                continue
            try:
                with open(os.path.join(root, name), encoding="utf-8") as f:
                    skin_id = json.load(f).get("id")
            except (json.JSONDecodeError, UnicodeDecodeError, AttributeError):
                continue
            if isinstance(skin_id, str):
                ids.add(skin_id)
    return ids


def apply_label(label: str, issue_labels: list, issue_body: str, issue_number: int,
                records: dict, known_ids: set, today: str) -> tuple[str, str]:
    """What labelling an issue does. Returns (outcome, message); outcome is one of
    "added", "removed", "unchanged", "ignored" (not for us) or "error". `resolved`
    only ever yields "removed" or "ignored"."""
    if label not in (DISPUTE_LABEL, RESOLVE_LABEL):
        return "ignored", f"label {label!r} is not {DISPUTE_LABEL!r} or {RESOLVE_LABEL!r}"
    if REPORT_LABEL not in issue_labels:
        return "ignored", f"issue #{issue_number} is not labelled {REPORT_LABEL!r}"
    skin_id = parse_skin_id(issue_body)
    if skin_id is None:
        if label == RESOLVE_LABEL:
            return "ignored", "no readable skin id, nothing to resolve"
        return "error", "could not read a 16-character skin id from the issue's Skin ID field"
    if label == DISPUTE_LABEL:
        if skin_id not in known_ids:
            return "error", f"no skin has the id {skin_id}"
        if add_dispute(records, skin_id, issue_number, today):
            return "added", f"{skin_id} is now disputed (issue #{issue_number})"
        return "unchanged", f"{skin_id} was already disputed"
    # `resolved` is a general label. Only the issue that raised the dispute can lift it:
    # a resolved broken-download report on the same skin, a mature-tag report or a
    # mistyped id leaves it alone and the bot stays quiet.
    record = records.get(skin_id)
    if record is not None and record.get("issue") == issue_number:
        remove_dispute(records, skin_id)
        return "removed", f"{skin_id} is no longer disputed"
    if record is not None:
        return "ignored", f"{skin_id} is disputed by issue #{record.get('issue')}, not #{issue_number}"
    return "ignored", f"{skin_id} was not disputed"


def _set_output(name: str, value: str) -> None:
    path = os.environ.get("GITHUB_OUTPUT")
    if path:
        with open(path, "a", encoding="utf-8") as f:
            f.write(f"{name}={value}\n")


def main(argv=None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    command = args[0] if args else "apply"
    path = os.environ.get("DISPUTED_FILE", DISPUTED_FILE)

    if command == "check":
        try:
            load_disputed(path)
        except DisputedError as e:
            print(f"INVALID: {e}", file=sys.stderr)
            return 1
        print(f"{path} is valid.")
        return 0
    if command != "apply":
        print("usage: disputed.py [apply|check]", file=sys.stderr)
        return 2

    try:
        labels = json.loads(os.environ.get("ISSUE_LABELS") or "[]")
        number = int(os.environ["ISSUE_NUMBER"])
        label = os.environ["LABEL_NAME"]
    except (KeyError, ValueError, json.JSONDecodeError) as e:
        print(f"bad environment: {e!r}", file=sys.stderr)
        return 2
    try:
        records = load_disputed(path)
    except DisputedError as e:
        print(f"INVALID: {e}", file=sys.stderr)
        return 1

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    outcome, message = apply_label(label, labels, os.environ.get("ISSUE_BODY", ""), number,
                                   records, known_skin_ids(), today)
    print(f"{outcome}: {message}")
    _set_output("outcome", outcome)
    _set_output("message", message)
    if outcome in ("added", "removed"):
        save_disputed(records, path)
    return 1 if outcome == "error" else 0


if __name__ == "__main__":
    sys.exit(main())
