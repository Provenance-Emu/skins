"""Share-card and SEO tags on every page type.

Checks the hand-written pages in docs/ and pages rendered in-process by the
generators (so it doesn't depend on the committed, CI-generated copies):
every required tag is present, canonical == og:url, twitter:image ==
og:image, the image is a local file whose real size matches the tags and is
under the size cap, and JSON-LD parses.
"""

import json
import re
import sys
from html.parser import HTMLParser
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from PIL import Image  # noqa: E402

import generate_author_pages as authors  # noqa: E402
import generate_system_pages as systems  # noqa: E402
from generate_share_cards import MAX_BYTES  # noqa: E402
from generate_sitemap import BASE_URL  # noqa: E402
from share_meta import SITE_URL  # noqa: E402

REQUIRED = [
    "description", "og:type", "og:site_name", "og:title", "og:description", "og:url",
    "og:image", "og:image:type", "og:image:width", "og:image:height", "og:image:alt",
    "twitter:card", "twitter:title", "twitter:description", "twitter:image", "twitter:image:alt",
]


class HeadParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.meta, self.canonical, self.titles, self.jsonld = {}, None, 0, []
        self._in_jsonld = False

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "meta":
            key = a.get("property") or a.get("name")
            if key:
                self.meta[key] = a.get("content", "")
        elif tag == "link" and a.get("rel") == "canonical":
            self.canonical = a.get("href")
        elif tag == "title":
            self.titles += 1
        elif tag == "script" and a.get("type") == "application/ld+json":
            self._in_jsonld = True
            self.jsonld.append("")

    def handle_endtag(self, tag):
        if tag == "script":
            self._in_jsonld = False

    def handle_data(self, data):
        if self._in_jsonld:
            self.jsonld[-1] += data


def parse(html):
    p = HeadParser()
    p.feed(html)
    return p


def check_page(html, expected_url):
    p = parse(html)
    assert p.titles == 1
    missing = [k for k in REQUIRED if not p.meta.get(k)]
    assert not missing, f"missing tags: {missing}"
    assert p.canonical == expected_url
    assert p.meta["og:url"] == p.canonical
    assert p.meta["twitter:card"] == "summary_large_image"
    assert p.meta["twitter:image"] == p.meta["og:image"]
    assert p.meta["og:image"].startswith(SITE_URL)
    image = ROOT / "docs" / p.meta["og:image"][len(SITE_URL):]
    assert image.exists(), image
    assert image.stat().st_size <= MAX_BYTES
    with Image.open(image) as im:
        assert im.size == (int(p.meta["og:image:width"]), int(p.meta["og:image:height"]))
        assert im.size == (1200, 630)
    for block in p.jsonld:
        json.loads(block)
    return p


SKINS = [
    {"id": f"{i:016x}", "name": f"Skin {i}", "author": "Test Author", "systems": ["snes"],
     "downloadURL": f"https://example.com/{i}.deltaskin", "source": "test"}
    for i in range(3)
]


@pytest.mark.parametrize("page,url", [
    ("index.html", SITE_URL),
    ("submit.html", SITE_URL + "submit.html"),
])
def test_hand_written_pages(page, url):
    check_page((ROOT / "docs" / page).read_text(encoding="utf-8"), url)


def test_system_page():
    p = check_page(systems.generate_system_page("snes", "SNES", SKINS), SITE_URL + "systems/snes.html")
    assert p.meta["og:image"] == SITE_URL + "cards/systems/snes.jpg"
    types = {json.loads(b).get("@type") for b in p.jsonld}
    assert "BreadcrumbList" in types


def test_systems_index():
    html = systems.generate_systems_index([{"code": "snes", "label": "SNES", "count": 3, "thumbnail": ""}])
    check_page(html, SITE_URL + "systems/")


def test_author_page():
    p = check_page(authors.generate_author_page("Test Author", "test-author", SKINS),
                   SITE_URL + "authors/test-author.html")
    types = {json.loads(b).get("@type") for b in p.jsonld}
    assert "BreadcrumbList" in types


def test_authors_index():
    html = authors.generate_authors_index(
        [{"author": "Test Author", "slug": "test-author", "count": 3, "systems": ["snes"]}])
    check_page(html, SITE_URL + "authors/")


def test_sitemap_uses_canonical_forms():
    assert BASE_URL == SITE_URL
    src = (ROOT / "scripts" / "generate_sitemap.py").read_text(encoding="utf-8")
    assert '"index.html",' not in src
    assert '"systems/index.html",' not in src


def test_every_system_card_is_valid():
    cards = sorted((ROOT / "docs" / "cards").rglob("*.jpg"))
    assert cards, "no share cards generated"
    for card in cards:
        assert card.stat().st_size <= MAX_BYTES, card
        with Image.open(card) as im:
            assert im.size == (1200, 630), card
            assert im.mode == "RGB", card


def test_404_is_noindex():
    html = (ROOT / "docs" / "404.html").read_text(encoding="utf-8")
    assert re.search(r'<meta name="robots" content="noindex">', html)
