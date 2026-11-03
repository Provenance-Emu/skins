"""Family cards on the system and author pages: labels, badges, Download all, sample hiding."""

import json
import sys
from html import unescape
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

import family_cards as fc
import generate_author_pages as ap
import generate_system_pages as sp


def skin(sid, name, **kw):
    return {
        "id": sid, "name": name, "systems": ["gba"], "author": "Ann",
        "downloadURL": f"https://example.com/{sid}.deltaskin", **kw,
    }


def family():
    return [
        skin("a1", "Paw — Doom", groupId="g", groupOrder=1, variantLabel="Doom"),
        skin("a2", "Paw — AvP", groupId="g", groupOrder=2, variantLabel="AvP"),
        skin("a3", "Paw — Wolf3D", groupId="g", groupOrder=3, variantLabel="Wolf3D"),
    ]


class TestLabels:
    def test_variant_label_prefers_field_then_name(self):
        assert fc.variant_label({"name": "Paw — Doom", "variantLabel": "Doom"}) == "Doom"
        assert fc.variant_label({"name": "Whole Name"}) == "Whole Name"

    def test_family_name_drops_own_label(self):
        assert fc.family_name({"name": "Paw — Doom", "variantLabel": "Doom"}) == "Paw"
        assert fc.family_name({"name": "Matte GBA Red", "variantLabel": "Red"}) == "Matte GBA"
        assert fc.family_name({"name": "Paw"}) == "Paw"
        # A label equal to the whole name leaves the name alone.
        assert fc.family_name({"name": "Doom", "variantLabel": "Doom"}) == "Doom"

    def test_inner_variant_labels(self):
        s = {"variants": [
            {"kind": "alt", "key": "alt", "label": "ignored"},
            {"kind": "theme", "key": "dark", "label": "Dark"},
            {"kind": "game", "key": "doom", "label": "Doom"},
        ]}
        assert fc.inner_variant_labels(s) == ["Alternate layout", "Dark", "Doom"]
        assert fc.inner_variant_labels({}) == []


class TestSampleHiding:
    def test_listed_drops_sample_tagged(self):
        skins = [skin("a", "A"), skin("b", "B", tags=["sample", "gba"]), skin("c", "C", tags=["x"])]
        assert [s["id"] for s in fc.listed(skins)] == ["a", "c"]


class TestSystemPage:
    def test_family_card_lists_variants_with_download_all(self):
        html = sp.generate_system_page("gba", "Game Boy Advance", family() + [skin("z", "Solo")])
        card = html.split('<article class="skin-card"')[1].split("</article>")[0]
        assert 'itemprop="name">Paw</div>' in card
        assert "3 variants" in card
        for label in ("Doom", "AvP", "Wolf3D"):
            assert f"⬇ {label}</a>" in card
        assert "Download all (3)" in card
        urls = json.loads(unescape(card.split('data-download-all="')[1].split('"')[0]))
        assert urls == [f"https://example.com/a{i}.deltaskin" for i in (1, 2, 3)]
        # The solo skin keeps its single Download button.
        solo = html.split('<article class="skin-card"')[2].split("</article>")[0]
        assert "Download all" not in solo and "btn-download" in solo

    def test_single_file_with_variants_shows_includes(self):
        s = skin("x", "Multi", variants=[
            {"kind": "alt", "key": "alt", "label": "Alt"},
            {"kind": "theme", "key": "dark", "label": "Dark"},
        ])
        html = sp.generate_system_page("gba", "Game Boy Advance", [s])
        assert "Includes 2 variants" in html
        assert "Alternate layout, Dark" in html
        card = html.split('<article class="skin-card"')[1].split("</article>")[0]
        assert "data-download-all" not in card

    def test_modal_data_uses_variant_label(self):
        data = sp.build_skins_data_script(sp.cluster_groups(family()), "gba")
        payload = json.loads(data.split("window.SKINS_DATA = ")[1].rsplit(";\n</script>", 1)[0])
        assert payload[0]["groupName"] == "Paw"
        assert [v["label"] for v in payload[0]["members"]] == ["Doom", "AvP", "Wolf3D"]

    def test_unlabeled_member_falls_back_to_full_name(self):
        members = family()
        del members[1]["variantLabel"]
        data = sp.build_skins_data_script(sp.cluster_groups(members), "gba")
        data = data.replace("\\u2014", "\u2014")
        assert "Paw \u2014 AvP" in data


class TestAuthorPage:
    def test_family_card(self):
        html = ap.generate_author_page("Ann", "ann", family() + [skin("z", "Solo")])
        card = html.split('<article class="skin-card"')[1].split("</article>")[0]
        assert 'itemprop="name">Paw</div>' in card
        assert "Download all (3)" in card
        assert "⬇ AvP</a>" in card

    def test_sample_skins_are_filtered_by_main_inputs(self):
        # main() filters with listed(); the page itself renders what it is given.
        kept = fc.listed([skin("a", "A"), skin("s", "S", tags=["sample"])])
        html = ap.generate_author_page("Ann", "ann", kept)
        assert 'itemprop="name">S</div>' not in html


class TestSamplesDontCreatePages:
    """Sample skins keep their own docs/s/ page but must not tip a system or author
    over the page threshold: the generators that build those pages leave samples out,
    so a sitemap URL or a skin-page link counting them would point at a 404."""

    def catalog(self):
        real = [skin(f"r{i}", f"Real {i}", systems=["gamecube"], author=f"Real Author {i}") for i in range(2)]
        samples = [skin(f"s{i}", f"Sample {i}", systems=["gamecube"], author="Provenance Emu", tags=["sample"])
                   for i in range(5)]
        return {"skins": real + samples}

    def test_sitemap_lists_neither_page_but_keeps_sample_skin_pages(self, tmp_path, monkeypatch):
        import generate_sitemap as gsm
        cat, out = tmp_path / "catalog.json", tmp_path / "sitemap.xml"
        cat.write_text(json.dumps(self.catalog()))
        monkeypatch.setattr(gsm, "CATALOG_PATH", cat)
        monkeypatch.setattr(gsm, "SITEMAP_PATH", out)
        gsm.main()
        xml = out.read_text()
        assert "systems/gamecube.html" not in xml          # 2 real skins: no page is generated
        assert "authors/provenance-emu.html" not in xml    # only samples
        assert "/s/s0.html" in xml                         # the sample's own page stays

    def test_skin_pages_do_not_link_to_pages_that_are_not_built(self, tmp_path, monkeypatch):
        import generate_skin_pages as gsp
        cat = tmp_path / "catalog.json"
        cat.write_text(json.dumps(self.catalog()))
        monkeypatch.setattr(gsp, "CATALOG_PATH", cat)
        monkeypatch.setattr(gsp, "SKIN_DIR", tmp_path / "s")
        gsp.main()
        page = (tmp_path / "s" / "s0.html").read_text()
        assert "systems/gamecube.html" not in page
        assert "authors/provenance-emu.html" not in page
