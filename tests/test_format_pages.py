"""The format 2.0 documentation (docs/format/) and its entry points.

The pages' behaviour is JavaScript: tests/skin2/format-docs.test.js validates and renders every example, and
tests/browser/format-docs.cjs drives the tutorial and the playground in Chromium and WebKit. This file holds what
Python can check: every page carries the chrome scripts/generate_format_reference.py writes, the links inside
the section resolve, the playground's script and page agree on ids, and the site links to the section.
"""

import json
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
DOCS = ROOT / "docs"
FORMAT = DOCS / "format"
sys.path.insert(0, str(ROOT / "scripts"))

import generate_format_reference as reference  # noqa: E402

# The tab each page marks as current (None: reachable from the overview, with no tab of its own).
PAGES = {
    "index.html": "./",
    "tutorial.html": "tutorial.html",
    "examples.html": "examples.html",
    "playground.html": "playground.html",
    "reference.html": "reference.html",
    "migration.html": None,
}


def chrome(html):
    """The part of a page above its <main>, without the per-page <head> fields."""
    top = html[:html.index("<main")]
    top = re.sub(r"<title>.*?</title>|<meta name=\"description\"[^>]*>|<link rel=\"canonical\"[^>]*>", "", top)
    return re.sub(r' aria-current="page"', "", top)


def test_every_format_page_is_listed():
    assert {path.name for path in FORMAT.glob("*.html")} == set(PAGES)


@pytest.mark.parametrize("name,current", PAGES.items())
def test_page_has_the_shared_chrome_and_marks_its_tab(name, current):
    html = (FORMAT / name).read_text(encoding="utf-8")
    blank = reference.page(current=None, file="", title="", description="", heading="", lede="", body="")
    assert chrome(html) == chrome(blank), f"{name} drifted from generate_format_reference.page()"
    marked = re.findall(r'<a href="([^"]+)" aria-current="page">', html)
    assert marked == ([current] if current else [])
    assert html.count("<h1>") == 1
    assert f'<link rel="canonical" href="https://emuskins.com/format/{"" if name == "index.html" else name}">' in html


@pytest.mark.parametrize("name", PAGES)
def test_local_links_resolve(name):
    html = (FORMAT / name).read_text(encoding="utf-8")
    for target in re.findall(r'(?:href|src|data-skin-example)="([^"#?:]+)(?:[#?][^"]*)?"', html):
        path = (FORMAT / target).resolve()
        if target.endswith("/"):
            path = path / "index.html"
        assert path.is_file(), f"{name} links to {target}, which doesn't exist"
    ids = set(re.findall(r'\bid="([^"]+)"', html))
    for anchor in re.findall(r'href="#([^"]+)"', html):
        assert anchor in ids, f"{name} links to #{anchor}, which it doesn't define"


def test_examples_named_by_pages_and_the_playground_exist():
    names = set()
    for name in PAGES:
        html = (FORMAT / name).read_text(encoding="utf-8")
        names.update(re.findall(r'playground\.html\?example=([a-z0-9-]+)', html))
    playground = (FORMAT / "playground.html").read_text(encoding="utf-8")
    names.update(value for value in re.findall(r'<option value="([^"]*)"', playground) if value)
    names.add(re.search(r'DEFAULT_EXAMPLE = "([^"]+)"', (FORMAT / "playground.js").read_text(encoding="utf-8")).group(1))
    assert names, "the pages link examples into the playground"
    for example in sorted(names):
        source = json.loads((FORMAT / "examples" / f"{example}.json").read_text(encoding="utf-8"))
        assert source["formatVersion"] == "2.0"


def test_playground_ids_the_script_uses_exist():
    html = (FORMAT / "playground.html").read_text(encoding="utf-8")
    ids = set(re.findall(r'\bid="([^"]+)"', html))
    used = set(re.findall(r'\$\("([^"]+)"\)', (FORMAT / "playground.js").read_text(encoding="utf-8")))
    assert used and not used - ids, f"playground.js reads ids that playground.html lacks: {sorted(used - ids)}"
    assert '<script type="module" src="playground.js"></script>' in html


def test_site_links_to_the_format_section():
    for name in ["index.html", "submit.html", "edit.html", "retroarch.html", "404.html"]:
        assert '<a href="format/">Create</a>' in (DOCS / name).read_text(encoding="utf-8"), name
    for script in ["generate_system_pages.py", "generate_author_pages.py"]:
        assert "../format/" in (ROOT / "scripts" / script).read_text(encoding="utf-8"), script
    sitemap = (ROOT / "scripts" / "generate_sitemap.py").read_text(encoding="utf-8")
    for name, current in PAGES.items():
        if current:
            assert f'"format/{"" if name == "index.html" else name}"' in sitemap, name
