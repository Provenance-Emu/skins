#!/usr/bin/env python3
"""
blocklist.py — repos that opted out of EmuSkins (SkinKit#34).

`blocklist.json` at the repo root is a top-level JSON array, one entry per line:

    [
      {"match": "owner/repo", "issue": 12, "verifiedBy": "login", "method": "owner", "date": "2026-11-02"},
      {"match": "owner/*", "issue": 15, "verifiedBy": "login", "method": "org-member", "date": "2026-11-02"}
    ]

`match` is `owner/repo` or `owner/*` (every repo under that account), compared
case-insensitively. `method` is how `process_optout.py` verified the request:
`owner` (the account is the issue author), `org-member` (public member of the
org), or `file` (`.emuskins-optout` committed to the repo). Only `owner` and
`org-member` can carry `owner/*`.

To undo an opt-out, delete its line (and the trailing comma on the new last
line). The file must stay valid JSON: `load_blocklist` raises instead of
treating a broken file as empty, so a bad edit fails the crawl and the catalog
build loudly rather than quietly letting everything back in. Git history is not
rewritten, so older commits still contain the entries.

`is_blocked(entry)` checks a skin entry against `source`, the owner/repo in
`downloadURL`, and the owner/repo in `originalURL` (mirror rehosts keep the
real origin there).
"""

import json
import re
import sys
from pathlib import Path
from urllib.parse import unquote, urlsplit

BLOCKLIST_PATH = Path(__file__).resolve().parent.parent / "blocklist.json"

# The catalog's own repo. Mirror and thumbnail release URLs live here, so a
# `downloadURL` on it says nothing about who made the skin, and it can never be
# opted out (that would hide every mirrored skin).
SELF_REPO = "provenance-emu/skins"

_OWNER = r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})"
_REPO = r"[A-Za-z0-9._-]{1,100}"
OWNER_RE = re.compile(rf"^{_OWNER}$")
OWNER_REPO_RE = re.compile(rf"^({_OWNER})/({_REPO})$")
MATCH_RE = re.compile(rf"^({_OWNER})/(\*|{_REPO})$")

# Hosts whose path starts with /{owner}/{repo}/. github.com additionally needs
# a recognised next segment so `github.com/orgs/x/...` isn't read as a repo.
_RAW_HOSTS = {"raw.githubusercontent.com", "raw.github.com", "media.githubusercontent.com"}
_GITHUB_SEGMENTS = {"raw", "releases", "blob", "tree", "archive", "download"}


def _clean_repo(name: str) -> str:
    return name[:-4] if name.lower().endswith(".git") else name


def parse_owner_repo(url: str) -> str | None:
    """`owner/repo` (lowercased) for any GitHub URL form we store, else None.

    Handles `raw.githubusercontent.com/{o}/{r}/...`, `github.com/{o}/{r}/raw|releases|blob|...`,
    a bare `github.com/{o}/{r}` (with or without `.git` or a trailing slash),
    and `media.githubusercontent.com/media/{o}/{r}/...`.
    """
    if not url or not isinstance(url, str):
        return None
    try:
        parts = urlsplit(url.strip())
    except ValueError:
        return None
    if parts.scheme not in ("http", "https"):
        return None
    host = (parts.hostname or "").lower()
    if host.startswith("www."):
        host = host[4:]
    segs = [unquote(s) for s in parts.path.split("/") if s]

    if host == "media.githubusercontent.com":
        segs = segs[1:] if segs and segs[0] == "media" else []
        host = "raw.githubusercontent.com"
    if host in _RAW_HOSTS:
        if len(segs) < 3:  # needs owner, repo and at least a ref
            return None
    elif host == "github.com":
        if len(segs) < 2:
            return None
        if len(segs) > 2 and segs[2].lower() not in _GITHUB_SEGMENTS:
            return None
    else:
        return None

    owner, repo = segs[0], _clean_repo(segs[1])
    if not OWNER_RE.match(owner) or not re.match(rf"^{_REPO}$", repo) or repo in (".", ".."):
        return None
    return f"{owner}/{repo}".lower()


def parse_source(source: str) -> str | None:
    """A catalog `source` that is itself `owner/repo` (not `deltastyles.com`)."""
    if not source or not isinstance(source, str):
        return None
    m = OWNER_REPO_RE.match(source.strip())
    if not m:
        return None
    return f"{m.group(1)}/{m.group(2)}".lower()


def normalize_match(match: str) -> str:
    """Validate and lowercase a blocklist `match`. Raises ValueError if malformed."""
    m = MATCH_RE.match((match or "").strip())
    if not m:
        raise ValueError(f"bad blocklist match {match!r}: expected owner/repo or owner/*")
    return f"{m.group(1)}/{m.group(2)}".lower()


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------

_cache: dict[str, tuple] = {}


def clear_cache() -> None:
    _cache.clear()


def load_blocklist(path=None) -> list[dict]:
    """Entries from `blocklist.json`. Missing file is empty; invalid JSON raises."""
    p = Path(path) if path else BLOCKLIST_PATH
    try:
        stat = p.stat()
    except FileNotFoundError:
        return []
    key = str(p)
    sig = (stat.st_mtime_ns, stat.st_size)
    hit = _cache.get(key)
    if hit and hit[0] == sig:
        return hit[1]
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise ValueError(f"{p} is not valid JSON ({e}); fix or restore it before continuing") from e
    if isinstance(data, dict):  # tolerate {"entries": [...]}
        data = data.get("entries", [])
    if not isinstance(data, list):
        raise ValueError(f"{p} must be a JSON array of entries")
    for e in data:
        if not isinstance(e, dict):
            raise ValueError(f"{p}: every entry must be an object")
        normalize_match(e.get("match", ""))
    _cache[key] = (sig, data)
    return data


def save_blocklist(entries: list[dict], path=None) -> None:
    """Write entries one per line so removing a line undoes one opt-out."""
    p = Path(path) if path else BLOCKLIST_PATH
    if entries:
        lines = ",\n".join("  " + json.dumps(e, ensure_ascii=False) for e in entries)
        text = f"[\n{lines}\n]\n"
    else:
        text = "[]\n"
    p.write_text(text, encoding="utf-8")
    clear_cache()


# ---------------------------------------------------------------------------
# Matching
# ---------------------------------------------------------------------------

def _rules(blocklist) -> list[str]:
    return [normalize_match(e["match"]) for e in (blocklist if blocklist is not None else load_blocklist())]


def _repo_hit(owner_repo: str, rules: list[str]) -> str | None:
    if not owner_repo or owner_repo == SELF_REPO:
        return None
    owner = owner_repo.split("/", 1)[0]
    for rule in rules:
        if rule == owner_repo or rule == f"{owner}/*":
            return rule
    return None


def is_repo_blocked(owner_repo: str, blocklist=None) -> bool:
    """True if `owner/repo` is covered by an entry (case-insensitive, honours `owner/*`)."""
    return _repo_hit((owner_repo or "").strip().lower(), _rules(blocklist)) is not None


def entry_repos(entry: dict) -> set[str]:
    """Every owner/repo an entry can be traced to: source, downloadURL, originalURL."""
    found = {
        parse_source(entry.get("source")),
        parse_owner_repo(entry.get("downloadURL")),
        parse_owner_repo(entry.get("originalURL")),
    }
    found.discard(None)
    found.discard(SELF_REPO)
    return found


def blocking_rule(entry: dict, blocklist=None) -> str | None:
    rules = _rules(blocklist)
    for repo in sorted(entry_repos(entry)):
        hit = _repo_hit(repo, rules)
        if hit:
            return hit
    return None


def is_blocked(entry: dict, blocklist=None) -> bool:
    """True if any of the entry's source / downloadURL / originalURL is opted out."""
    return blocking_rule(entry, blocklist) is not None


def is_url_blocked(url: str, blocklist=None) -> bool:
    """True if a GitHub URL (skin file, repo, release, raw) belongs to an opted-out repo."""
    repo = parse_owner_repo(url)
    return bool(repo) and is_repo_blocked(repo, blocklist)


def filter_blocked(entries: list[dict], blocklist=None, label: str = "") -> list[dict]:
    """Entries minus the opted-out ones, printing how many were dropped."""
    rules = blocklist if blocklist is not None else load_blocklist()
    kept = [e for e in entries if not is_blocked(e, rules)]
    dropped = len(entries) - len(kept)
    if dropped:
        print(f"  Dropped {dropped} opted-out skin(s){' from ' + label if label else ''}", file=sys.stderr)
    return kept


if __name__ == "__main__":
    # `python3 scripts/blocklist.py <url-or-owner/repo>...` for a quick check.
    for arg in sys.argv[1:]:
        repo = parse_owner_repo(arg) or parse_source(arg) or arg
        print(f"{arg} -> {repo}: {'BLOCKED' if is_repo_blocked(repo) else 'ok'}")
