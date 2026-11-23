"""Line pages (docs/l/<id>.html): content without JavaScript, share tags, stale-page cleanup, sitemap."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

import family_cards
import generate_line_pages as lp
import generate_sitemap
from share_meta import SITE_URL
from .test_share_meta import check_page

CASES = json.loads((Path(__file__).parent.parent / "fixtures" / "lines" / "resolve-cases.json").read_text())
LINE = CASES["line"]


def members():
    return [{**m, "lineId": LINE["id"], "systems": ["mame"], "author": "Designer", "creator": "designer",
             "downloadURL": f"https://example.com/{m['id']}.manicskin",
             "thumbnailURL": f"https://example.com/{m['id']}.png"} for m in CASES["members"]]


def catalog():
    return {"lines": [LINE], "skins": members() + [
        {"id": "s1", "name": "Lone", "systems": ["gba"], "downloadURL": "https://example.com/s1.deltaskin"}]}


def test_page_has_name_badge_default_download_and_scripts():
    default = members()[0]
    html = lp.generate_line_page(LINE, default, {"a"})     # the line's creator slug
    assert "<h1>Toy Pad</h1>" in html
    assert "6 layouts · 2 colours" in html
    assert 'href="https://example.com/a1.manicskin"' in html
    assert 'href="../authors/a.html"' in html
    assert 'src="../js/lines.js"' in html and 'src="../js/line-page.js"' in html
    assert 'data-line-id="a-pad"' in html and 'data-default-skin="a1"' in html
    assert html.index("js/lines.js") < html.index("js/line-page.js")
    assert 'href="../s/a1.html"' in html


def test_page_embeds_no_member_table():
    html = lp.generate_line_page(LINE, members()[0])
    assert "a2.manicskin" not in html and "e2.manicskin" not in html


def test_name_and_description_are_escaped():
    line = {**LINE, "name": "A <b> & co", "description": 'Say "hi" <script>'}
    html = lp.generate_line_page(line, members()[0])
    assert "<h1>A &lt;b&gt; &amp; co</h1>" in html
    assert "<script>" not in html.split("</main>")[0].split("<main")[1]


def test_share_tags():
    p = check_page(lp.generate_line_page(LINE, members()[0]), SITE_URL + "l/a-pad.html")
    assert "Toy Pad" in p.meta["og:title"]


def test_default_member_is_the_one_that_fits_the_default():
    ms = list(reversed(members()))
    assert lp.default_member_of(LINE, ms)["id"] == "a1"
    without = [m for m in ms if m["id"] != "a1"]
    assert lp.default_member_of(LINE, without)["id"] == "a2"      # first in line order
    assert lp.default_member_of(LINE, []) is None


def test_multi_valued_member_can_be_the_default():
    line = {**LINE, "default": {"device": "notch", "game": "tate", "hand": "right", "colour": "red"}}
    assert lp.default_member_of(line, members())["id"] == "d1"


def test_write_pages_one_per_line_and_stale_removed(tmp_path):
    out = tmp_path / "l"
    out.mkdir()
    (out / "gone.html").write_text("old")
    written = lp.write_pages(catalog(), out)
    assert [p.name for p in written] == ["a-pad.html"]
    assert not (out / "gone.html").exists()
    assert "Toy Pad" in (out / "a-pad.html").read_text()


def test_no_lines_writes_nothing_and_clears_old_pages(tmp_path):
    out = tmp_path / "l"
    assert lp.write_pages({"skins": []}, out) == [] and not out.exists()
    out.mkdir()
    (out / "old.html").write_text("old")
    lp.write_pages({"skins": []}, out)
    assert list(out.iterdir()) == []


def test_sitemap_lists_line_pages():
    assert generate_sitemap.line_pages(catalog()) == ["l/a-pad.html"]
    assert generate_sitemap.line_pages({"skins": []}) == []


def test_line_badge():
    assert family_cards.line_badge(LINE) == "6 layouts · 2 colours"
    no_colour = {**LINE, "axes": [a for a in LINE["axes"] if a["role"] != "colour"], "layoutCount": 1}
    assert family_cards.line_badge(no_colour) == "1 layout"
