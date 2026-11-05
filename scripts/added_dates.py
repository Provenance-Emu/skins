#!/usr/bin/env python3
"""
added_dates.py — `addedAt` for catalog entries, from the git history of their JSON files.

`addedAt` is the UTC date (YYYY-MM-DD, the same shape as the per-skin
`lastUpdated`) on which a skin's JSON file first entered this repo, following
renames: `git log --follow --diff-filter=A` for that one file. It means "added to
EmuSkins", not "published": deltastyles skins were live elsewhere long before the
crawler found them. Sorts and "new" badges use `effective_date`: `lastUpdated`,
else `addedAt`.

Asking git about every file on every build is slow, so answers are cached in
`added-dates.json` (committed by the build workflow, never hand-edited):

    {"version": 1, "dates": {"skins/gba/x.json": "2026-03-13"}}

A build reads the cache first and asks git only about files the cache lacks: the
first run after this ships backfills every file once, and later runs look up just
the skins added since. A file's first-commit date never changes, so cached dates
are never re-checked.

This is only true if history is complete. In a shallow clone git reports the
grafted root commit as having added every file, which would stamp the whole
catalog with one date; and because cached dates are never re-checked the mistake
would be permanent. So in a shallow clone, outside a git repository, or with no
git, nothing is looked up and nothing is cached: entries the cache cannot answer
get no `addedAt`, and consumers fall back to `lastUpdated` or sort last.
build-catalog.yml checks out with `fetch-depth: 0` for this reason.

Why one `--follow` per file instead of one `git log` over `skins/`: whole-tree
rename detection pairs each deleted file with a single added one, so when a
migration turned one bundle file into many, only one member inherited the
bundle's date and the rest looked brand new. `--follow` on each file gives every
member the date of the file it came from.
"""

import json
import os
import subprocess
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from typing import Optional

ADDED_DATES_FILE = "added-dates.json"
CACHE_VERSION = 1
LOOKUP_WORKERS = 8


def effective_date(entry: dict) -> Optional[str]:
    """The date recents and "new" use: `lastUpdated`, else `addedAt`, else None.
    Both are bare YYYY-MM-DD dates, so string order is date order."""
    return entry.get("lastUpdated") or entry.get("addedAt") or None


def sort_recent(entries: list[dict]) -> list[dict]:
    """Newest effective date first, undated last. Ties (a bulk import gives hundreds
    of skins the same date) break by name, then id, so the order never depends on
    the input order."""
    by_name = sorted(entries, key=lambda e: ((e.get("name") or "").casefold(), e.get("id") or ""))
    # reverse=True keeps the order of equal elements, so the name order survives within a date.
    return sorted(by_name, key=lambda e: effective_date(e) or "", reverse=True)


def _git(cwd: str, *args: str) -> Optional[subprocess.CompletedProcess]:
    """Run git; None when git is not installed."""
    try:
        return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True,
                              encoding="utf-8", errors="replace")
    except (FileNotFoundError, NotADirectoryError):
        return None


def _out(proc: Optional[subprocess.CompletedProcess]) -> Optional[str]:
    return proc.stdout.strip() if proc is not None and proc.returncode == 0 else None


def _utc_day(timestamp: str) -> Optional[str]:
    try:
        return datetime.fromtimestamp(int(timestamp), timezone.utc).strftime("%Y-%m-%d")
    except (ValueError, OverflowError, OSError):
        return None


class Repo:
    """The checkout that holds the skins directory."""

    def __init__(self, skins_dir: str):
        self.top: Optional[str] = None
        self.shallow = False
        skins_dir = os.path.abspath(skins_dir)
        if not os.path.isdir(skins_dir):
            return
        top = _out(_git(skins_dir, "rev-parse", "--show-toplevel"))
        if not top:
            return
        self.top = os.path.realpath(top)
        self.shallow = _out(_git(self.top, "rev-parse", "--is-shallow-repository")) == "true"

    @property
    def can_look_up(self) -> bool:
        """True only when history is complete enough to trust."""
        return self.top is not None and not self.shallow

    def relpath(self, file_path: str) -> str:
        """Repo-relative, forward-slash path: the cache key."""
        real = os.path.realpath(os.path.abspath(file_path))
        return os.path.relpath(real, self.top).replace(os.sep, "/")

    def first_added(self, rel_path: str) -> Optional[str]:
        """UTC date of the earliest commit that added `rel_path` (or the file it was
        renamed from). None when git has no such commit, e.g. an uncommitted file."""
        proc = _git(self.top, "log", "--follow", "--diff-filter=A", "--format=%ct", "--", rel_path)
        if proc is None or proc.returncode != 0:
            return None
        days = [d for d in (_utc_day(t) for t in proc.stdout.split()) if d]
        return min(days) if days else None


def load_cache(path: str) -> dict:
    """path -> date from the cache file; empty when it is missing, unreadable or malformed."""
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict) or data.get("version") != CACHE_VERSION or not isinstance(data.get("dates"), dict):
        return {}
    return {k: v for k, v in data["dates"].items() if isinstance(k, str) and isinstance(v, str)}


def save_cache(path: str, dates: dict) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"version": CACHE_VERSION, "dates": dict(sorted(dates.items()))},
                  f, indent=1, ensure_ascii=False)
        f.write("\n")


def apply_added_dates(entries: list[dict], skins_dir: str, cache_path: str = ADDED_DATES_FILE) -> dict:
    """Set `addedAt` on every entry whose date is known. An entry that already has
    one (set by hand in its skin JSON) keeps it. Entries are matched to history by
    `_source_file`. The cache file is rewritten only when git supplied new dates.

    Returns counts: dated (entries that now have `addedAt`), looked_up (dates newly
    read from git), missing (entries without one), unavailable (some dates were
    missing and history is incomplete, so git was not asked)."""
    stats = {"dated": 0, "looked_up": 0, "missing": 0, "unavailable": False}
    repo = Repo(skins_dir)
    dates = load_cache(cache_path)

    def key(entry: dict) -> Optional[str]:
        path = entry.get("_source_file")
        return repo.relpath(path) if path and repo.top else None

    if repo.top is None:
        stats["unavailable"] = any(not e.get("addedAt") for e in entries)
    need = sorted({k for e in entries if not e.get("addedAt") and (k := key(e)) and k not in dates})
    if need and repo.can_look_up:
        with ThreadPoolExecutor(max_workers=LOOKUP_WORKERS) as pool:
            found = {k: d for k, d in zip(need, pool.map(repo.first_added, need)) if d}
        if found:
            dates.update(found)
            save_cache(cache_path, dates)
        stats["looked_up"] = len(found)
    elif need:
        stats["unavailable"] = True

    for e in entries:
        if e.get("addedAt"):
            continue
        date = dates.get(key(e) or "")
        if date:
            e["addedAt"] = date
            stats["dated"] += 1
        else:
            stats["missing"] += 1
    return stats
