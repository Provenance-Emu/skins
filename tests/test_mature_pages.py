"""Generated pages hide `mature` skins by default and gate the ones that exist.

Runs each generator's main() against a small catalog in a temp dir, so it doesn't
depend on the committed (CI-generated) pages.
"""

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import content_policy  # noqa: E402
import generate_author_pages as authors  # noqa: E402
import generate_rss as rss  # noqa: E402
import generate_sitemap as sitemap  # noqa: E402
import generate_skin_pages as skin_pages  # noqa: E402
import generate_system_pages as systems  # noqa: E402
from share_meta import SITE_URL  # noqa: E402

MATURE_ID = "9" * 16
MATURE_NAME = "Zebra Mature Pad"


def make(i, name, author="Test Author", tags=(), system="snes"):
    return {
        "id": f"{i:016x}", "name": name, "author": author, "systems": [system],
        "source": "manual", "downloadURL": f"https://example.com/{i}.deltaskin",
        "thumbnailURL": f"https://example.com/thumb-{i}.png", "tags": list(tags),
        "downloadCount": 5, "lastUpdated": f"2026-01-0{i}T00:00:00Z",
    }


CATALOG = {"version": 2, "skins": [
    make(1, "Alpha Pad"), make(2, "Beta Pad"), make(3, "Gamma Pad"),
    {**make(9, MATURE_NAME, tags=["portrait", "mature"]), "id": MATURE_ID,
     "thumbnailURL": "https://example.com/mature-art.png"},
]}


@pytest.fixture
def catalog_file(tmp_path):
    path = tmp_path / "catalog.json"
    path.write_text(json.dumps(CATALOG))
    return path


def test_system_page_leaves_out_mature_and_offers_opt_in(catalog_file, tmp_path, monkeypatch):
    monkeypatch.setattr(systems, "CATALOG_PATH", catalog_file)
    monkeypatch.setattr(systems, "SYSTEMS_DIR", tmp_path / "systems")
    systems.main()
    html = (tmp_path / "systems" / "snes.html").read_text(encoding="utf-8")
    assert "Alpha Pad" in html
    assert MATURE_NAME not in html and MATURE_ID not in html
    assert "example.com/thumb-1.png" in html and "mature-art" not in html
    assert 'data-scope="system" data-key="snes" data-count="1"' in html
    assert '<script src="../js/mature.js" defer>' in html
    assert "3 community-created skins" in html  # the count is the visible ones


def test_system_page_without_mature_skins_has_no_opt_in(catalog_file, tmp_path, monkeypatch):
    clean = {**CATALOG, "skins": CATALOG["skins"][:3]}
    catalog_file.write_text(json.dumps(clean))
    monkeypatch.setattr(systems, "CATALOG_PATH", catalog_file)
    monkeypatch.setattr(systems, "SYSTEMS_DIR", tmp_path / "systems")
    systems.main()
    html = (tmp_path / "systems" / "snes.html").read_text(encoding="utf-8")
    assert "mature-note" not in html.split("<style>")[1].split("</style>")[1]
    assert "mature.js" not in html


def test_author_page_leaves_out_mature_and_offers_opt_in(catalog_file, tmp_path, monkeypatch):
    monkeypatch.setattr(authors, "CATALOG_PATH", catalog_file)
    monkeypatch.setattr(authors, "AUTHORS_DIR", tmp_path / "authors")
    authors.main()
    html = (tmp_path / "authors" / "test-author.html").read_text(encoding="utf-8")
    assert "Alpha Pad" in html
    assert MATURE_NAME not in html and MATURE_ID not in html
    assert 'data-scope="author" data-key="test-author" data-count="1"' in html
    assert '<script src="../js/mature.js" defer>' in html


def test_rss_leaves_out_mature(catalog_file, tmp_path, monkeypatch):
    monkeypatch.setattr(rss, "CATALOG_PATH", str(catalog_file))
    monkeypatch.setattr(rss, "OUTPUT_PATH", str(tmp_path / "feed.xml"))
    rss.main()
    xml = (tmp_path / "feed.xml").read_text(encoding="utf-8")
    assert "Alpha Pad" in xml
    assert MATURE_NAME not in xml and MATURE_ID not in xml


def test_sitemap_leaves_out_mature_skin_page(catalog_file, tmp_path, monkeypatch):
    monkeypatch.setattr(sitemap, "CATALOG_PATH", catalog_file)
    monkeypatch.setattr(sitemap, "SITEMAP_PATH", tmp_path / "sitemap.xml")
    sitemap.main()
    xml = (tmp_path / "sitemap.xml").read_text(encoding="utf-8")
    assert f"s/{make(1, 'x')['id']}.html" in xml
    assert MATURE_ID not in xml


def test_skin_pages_gate_the_mature_one_only(catalog_file, tmp_path, monkeypatch):
    monkeypatch.setattr(skin_pages, "CATALOG_PATH", catalog_file)
    monkeypatch.setattr(skin_pages, "SKIN_DIR", tmp_path / "s")
    skin_pages.main()

    plain = (tmp_path / "s" / f"{make(1, 'x')['id']}.html").read_text(encoding="utf-8")
    assert 'id="mature-gate"' not in plain and "noindex" not in plain
    assert 'src="https://example.com/thumb-1.png"' in plain

    gated = (tmp_path / "s" / f"{MATURE_ID}.html").read_text(encoding="utf-8")
    assert 'id="mature-gate"' in gated
    assert '<main class="skin-page" data-mature hidden>' in gated
    assert '<meta name="robots" content="noindex">' in gated
    assert '<script src="../js/mature.js" defer>' in gated
    # Nothing about the skin reaches the head, and the image waits for the gate.
    head = gated.split("</head>")[0]
    assert MATURE_NAME not in head
    assert "mature-art" not in head
    assert 'data-src="https://example.com/mature-art.png"' in gated
    assert ' src="https://example.com/mature-art.png"' not in gated
    assert f"{SITE_URL}cards/home.jpg" in gated


def test_every_skin_page_has_a_report_link(catalog_file, tmp_path, monkeypatch):
    monkeypatch.setattr(skin_pages, "CATALOG_PATH", catalog_file)
    monkeypatch.setattr(skin_pages, "SKIN_DIR", tmp_path / "s")
    skin_pages.main()
    for page in (tmp_path / "s").glob("*.html"):
        html = page.read_text(encoding="utf-8")
        assert "issues/new?template=report-skin.yml" in html, page.name


def test_static_cards_have_a_report_link():
    card = systems.build_card(make(1, "Alpha Pad"), 0)
    assert 'class="report-link"' in card and "report-skin.yml" in card
    assert 'class="report-link"' in authors.build_card(make(1, "Alpha Pad"))


def test_style_css_carries_the_system_page_css():
    css = (ROOT / "docs" / "style.css").read_text(encoding="utf-8")
    flat = "".join(css.split())
    for rule in content_policy.MATURE_CSS.split("}"):
        assert "".join(rule.split()) in flat, rule
