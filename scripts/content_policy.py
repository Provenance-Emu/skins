#!/usr/bin/env python3
"""
content_policy.py — the `mature` tag: keyword matching, filtering, report links.

A skin tagged `mature` stays in `catalog.json` (the apps filter on the tag), but
the website hides it unless the viewer opts in. Two ways a skin gets the tag:

  1. Automatically: `save_entries()` in process_submission.py (used by the crawler
     and by issue submissions) runs `apply_mature_tag()`, which checks the entry
     against `scripts/mature_keywords.json`.
  2. By hand: add "mature" to the `tags` array of the skin's JSON file in a PR.
     Take it out the same way. Nothing re-adds it, because the crawler only
     tags entries it is about to create.

    python3 scripts/content_policy.py            # list keyword matches in skins/
    python3 scripts/content_policy.py --json     # same, machine readable
"""

import argparse
import json
import re
import sys
from html import escape
from pathlib import Path
from urllib.parse import urlencode

sys.path.insert(0, str(Path(__file__).parent))
from skin_schema import MATURE_TAG  # noqa: E402

KEYWORDS_PATH = Path(__file__).parent / "mature_keywords.json"
SKINS_DIR = Path(__file__).parent.parent / "skins"

# Entry fields searched for keywords (lists are searched item by item).
SEARCHED_FIELDS = ("name", "description", "author", "tags", "source", "downloadURL", "originalURL")

REPORT_ISSUE_URL = "https://github.com/Provenance-Emu/skins/issues/new"
REPORT_TEMPLATE = "report-skin.yml"
SITE_URL = "https://emuskins.com/"


def _normalize(text: str) -> str:
    """Lowercase, `+` spelled out ("18+" -> "18 plus"), every other non-alphanumeric a space."""
    text = text.lower().replace("+", " plus ")
    return " ".join(re.sub(r"[^a-z0-9]+", " ", text).split())


class Keywords:
    """Compiled `mature_keywords.json`."""

    def __init__(self, words=(), substrings=()):
        self.words = [w for w in (_normalize(w) for w in words) if w]
        self.substrings = [s for s in (_normalize(s) for s in substrings) if s]
        self._word_re = [(w, re.compile(rf"(?:^| ){re.escape(w)}(?: |$)")) for w in self.words]

    @classmethod
    def load(cls, path=KEYWORDS_PATH) -> "Keywords":
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return cls(data.get("words", []), data.get("substrings", []))

    def find(self, text: str) -> list[str]:
        """Keywords found in `text`."""
        norm = _normalize(text)
        if not norm:
            return []
        hits = [w for w, rx in self._word_re if rx.search(norm)]
        hits += [s for s in self.substrings if s in norm]
        return hits


_default_keywords = None


def default_keywords() -> Keywords:
    global _default_keywords
    if _default_keywords is None:
        _default_keywords = Keywords.load()
    return _default_keywords


def _field_values(entry: dict, field: str):
    value = entry.get(field)
    if isinstance(value, list):
        return [v for v in value if isinstance(v, str)]
    return [value] if isinstance(value, str) else []


def is_mature(entry: dict) -> bool:
    """True when the entry carries the `mature` tag (however it got there)."""
    return MATURE_TAG in (entry.get("tags") or [])


def mature_matches(entry: dict, keywords: Keywords = None) -> list[tuple[str, str]]:
    """(field, keyword) pairs for every keyword found in the entry's searched fields."""
    keywords = keywords or default_keywords()
    found = []
    for field in SEARCHED_FIELDS:
        for value in _field_values(entry, field):
            for hit in keywords.find(value):
                if (field, hit) not in found:
                    found.append((field, hit))
    return found


def apply_mature_tag(entry: dict, keywords: Keywords = None) -> bool:
    """Add `mature` to `entry["tags"]` when a keyword matches. True if it was added."""
    if is_mature(entry) or not mature_matches(entry, keywords):
        return False
    entry["tags"] = list(entry.get("tags") or []) + [MATURE_TAG]
    return True


def split_mature(skins: list[dict]) -> tuple[list[dict], list[dict]]:
    """(visible, mature) with the input order kept."""
    visible, mature = [], []
    for s in skins:
        (mature if is_mature(s) else visible).append(s)
    return visible, mature


def report_url(skin: dict) -> str:
    """Prefilled GitHub issue form for reporting a skin (docs/js/browse.js builds the same URL)."""
    name = skin.get("name") or "Unnamed skin"
    params = {
        "template": REPORT_TEMPLATE,
        "title": f"Report: {name}",
        "skin_id": skin.get("id") or "",
        "skin_name": name,
        "skin_page": f"{SITE_URL}s/{skin['id']}.html" if skin.get("id") else "",
    }
    return f"{REPORT_ISSUE_URL}?{urlencode(params)}"


# Styles for the opt-in note, skin-page gate and Report link. docs/style.css carries
# the same rules (home, author and skin pages link it); system pages inline this
# string. tests/test_content_policy.py checks the two stay in step.
MATURE_CSS = (
    ".mature-note{max-width:1200px;margin:0 auto;padding:4px 24px 16px;display:flex;gap:12px;"
    "align-items:center;flex-wrap:wrap;color:var(--text-muted);font-size:14px}"
    ".mature-note[hidden],.mature-gate[hidden],.skin-page[hidden],#mature-wrap[hidden]{display:none}"
    "#mature-wrap h2{max-width:1200px;margin:0 auto 12px;padding:0 24px;font-size:18px}"
    ".mature-gate{max-width:520px;margin:72px auto;padding:0 24px;text-align:center}"
    ".mature-gate h1{font-size:26px;margin-bottom:10px}"
    ".mature-gate p{color:var(--text-muted);margin-bottom:20px}"
    ".mature-gate .actions{display:flex;gap:10px;justify-content:center;flex-wrap:wrap}"
    ".report-link{margin-left:auto;font-size:12px;color:var(--text-muted);"
    "text-decoration:underline dotted;white-space:nowrap}"
    ".report-link:hover{color:var(--accent)}"
)


def report_link_html(skin: dict, css_class: str = "report-link", label: str = "Report") -> str:
    """The 'Report' anchor used on static cards and skin pages."""
    return (f'<a class="{css_class}" href="{escape(report_url(skin))}" target="_blank" '
            f'rel="noopener" onclick="event.stopPropagation()" title="Report this skin">{escape(label)}</a>')


def mature_listing_html(scope: str, key: str, count: int) -> str:
    """Note and (empty) list that docs/js/mature.js fills in for viewers who opt in.
    `scope` is "system" or "author"; `key` the system code or author name."""
    if not count:
        return ""
    return (
        f'<div class="mature-note" id="mature-note" data-scope="{scope}" data-key="{escape(key)}" '
        f'data-count="{count}" hidden>\n'
        '  <span id="mature-note-text"></span>\n'
        '  <button type="button" class="btn btn-outline btn-sm" id="mature-toggle"></button>\n'
        '</div>\n'
        '<div id="mature-wrap" hidden>\n'
        '  <h2>Mature skins</h2>\n'
        '  <div class="grid-wrap"><div class="skin-grid" id="mature-grid"></div></div>\n'
        '</div>\n'
    )


def scan(skins_dir: Path = SKINS_DIR, keywords: Keywords = None) -> list[dict]:
    """Every skin file under `skins_dir` with keyword matches or the tag, for review."""
    keywords = keywords or default_keywords()
    rows = []
    for path in sorted(Path(skins_dir).rglob("*.json")):
        try:
            entry = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        matches = mature_matches(entry, keywords)
        if matches or is_mature(entry):
            rows.append({
                "file": str(path),
                "id": entry.get("id"),
                "name": entry.get("name"),
                "author": entry.get("author"),
                "tagged": is_mature(entry),
                "matches": [f"{field}:{kw}" for field, kw in matches],
            })
    return rows


def main():
    parser = argparse.ArgumentParser(description="List skins matching the mature keyword list")
    parser.add_argument("--skins-dir", default=str(SKINS_DIR))
    parser.add_argument("--keywords", default=str(KEYWORDS_PATH))
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    rows = scan(Path(args.skins_dir), Keywords.load(args.keywords))
    if args.json:
        print(json.dumps(rows, indent=2, ensure_ascii=False))
        return
    for r in rows:
        flag = "tagged" if r["tagged"] else "match "
        print(f"{flag}  {r['id']}  {r['name']!r}  by {r['author']!r}  [{', '.join(r['matches'])}]  {r['file']}")
    print(f"\n{len(rows)} skin(s) matched or tagged.")


if __name__ == "__main__":
    main()
