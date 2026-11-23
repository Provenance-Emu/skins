"""Line cards on author and system pages, and the link from a member's skin page."""

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

import family_cards as fc
import generate_author_pages as ap
import generate_skin_pages as skp
import generate_system_pages as sp

CASES = json.loads((Path(__file__).parent.parent / "fixtures" / "lines" / "resolve-cases.json").read_text())
LINE = CASES["line"]


def members():
    return [{**m, "lineId": LINE["id"], "systems": ["mame"], "author": "Ann", "creator": "ann",
             "variantLabel": m["options"]["colour"].title(),
             "downloadURL": f"https://example.com/{m['id']}.manicskin",
             "thumbnailURL": f"https://example.com/{m['id']}.png"} for m in CASES["members"]]


def single(sid="s1", name="Lone Wolf"):
    return {"id": sid, "name": name, "systems": ["mame"], "author": "Ann", "creator": "ann",
            "downloadURL": f"https://example.com/{sid}.deltaskin"}


def paw():
    return [{**single("f1", "Paw — Doom"), "groupId": "paw", "groupOrder": 0, "variantLabel": "Doom"},
            {**single("f2", "Paw — AvP"), "groupId": "paw", "groupOrder": 1, "variantLabel": "AvP"}]


def cards(html):
    return re.findall(r'<article class="skin-card[^"]*"', html)


class TestSplitLines:
    def test_a_line_collapses_to_one_item_where_its_first_family_stood(self):
        clusters = ap.cluster_groups([single("s0", "Zero")] + members() + paw())
        out = fc.split_lines(clusters, [LINE])
        assert [("line" if fc.is_line_item(o) else o[0]["id"]) for o in out] == ["s0", "line", "f1"]
        assert [m["id"] for m in out[1][2]] == ["a1", "a2", "b1", "c1", "d1", "d2", "e1", "e2"]

    def test_without_lines_nothing_changes(self):
        clusters = ap.cluster_groups(members() + paw())
        assert fc.split_lines(clusters, []) == clusters
        assert fc.split_lines(clusters, None) == clusters

    def test_members_of_an_unknown_line_stay_ordinary_families(self):
        clusters = ap.cluster_groups(members())
        assert fc.split_lines(clusters, [{**LINE, "id": "other"}]) == clusters


class TestLineCard:
    def test_links_to_the_line_page_with_badge_and_default_thumbnail(self):
        html = fc.line_card_html(LINE, list(reversed(members())), "../")
        assert html.count('href="../l/a-pad.html"') == 3
        assert "6 layouts · 2 colours" in html and ">Toy Pad</a>" in html
        assert "a1.png" in html                                   # the default member, wherever it is listed
        assert "Download all" not in html and "data-download-all" not in html
        assert not re.search(r"\bline\b", re.sub(r"<[^>]+>", " ", html), re.I)

    def test_name_is_escaped(self):
        html = fc.line_card_html({**LINE, "name": "A <b> & co"}, members())
        assert "A &lt;b&gt; &amp; co" in html and "<b>" not in html

    def test_default_member_missing_uses_the_first_listed(self):
        ms = [m for m in members() if m["id"] != "a1"]
        assert "a2.png" in fc.line_card_html(LINE, ms)

    def test_design_count(self):
        assert fc.design_count(members() + paw() + [single()], [LINE]) == 3
        assert fc.design_count(members() + paw() + [single()], []) == 8      # 6 families + paw + single


class TestAuthorPage:
    def page(self, lines=(LINE,)):
        return ap.generate_author_page("Ann", "ann", members() + paw() + [single()], lines=list(lines))

    def test_one_card_for_the_line(self):
        html = self.page()
        assert len(cards(html)) == 3
        assert html.count('class="skin-card line-card"') == 1
        assert "6 layouts · 2 colours" in html
        assert "3 designs &middot; 11 skins" in html

    def test_modal_data_leaves_out_line_members_but_knows_their_ids(self):
        html = self.page()
        override = json.loads(re.search(r"window\.CATALOG_OVERRIDE=(.*?);\n</script>", html, re.S).group(1))
        assert [s["id"] for s in override] == ["f1", "f2", "s1"]
        table = json.loads(re.search(r"window\.LINE_MEMBERS=(.*?);\n</script>", html, re.S).group(1))
        assert table["c1"] == "a-pad" and len(table) == 8
        assert ".skin-card:not(.line-card)" in html              # modal indexes skip the line card

    def test_without_lines_the_page_is_as_before(self):
        html = self.page(lines=())
        assert len(cards(html)) == 8 and "line-card\"" not in html
        assert "LINE_MEMBERS" not in html and "designs" not in html


class TestSystemPage:
    def test_one_card_for_the_line_and_modal_indexes_stay_dense(self):
        skins = sorted(members() + paw() + [single()], key=lambda s: s["name"].lower())
        html = sp.generate_system_page("mame", "MAME", skins, lines=[LINE])
        assert len(cards(html)) == 3 and html.count('class="skin-card line-card"') == 1
        data = json.loads(re.search(r"window\.SKINS_DATA = (.*?);\n</script>", html, re.S).group(1))
        assert [d["idx"] for d in data] == [0, 1]
        assert sorted(re.findall(r'data-idx="(\d+)"', html)) == ["0", "1"]
        assert all("Toy Pad" not in d["name"] for d in data)

    def test_without_lines_every_family_is_a_card(self):
        skins = members() + paw() + [single()]
        html = sp.generate_system_page("mame", "MAME", skins)
        assert len(cards(html)) == 8


class TestSkinPage:
    def test_member_page_links_to_its_line_with_itself_selected(self):
        b1 = next(m for m in members() if m["id"] == "b1")
        html = skp.generate_skin_page(b1, set(), set(), (), line=LINE)
        assert 'href="../l/a-pad.html?skin=b1"' in html
        assert "Part of <a" in html and "Toy Pad</a>: 6 layouts · 2 colours." in html

    def test_page_without_a_line_has_no_such_link(self):
        html = skp.generate_skin_page(single(), set(), set(), ())
        assert "Part of" not in html and "../l/" not in html
