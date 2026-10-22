"""Tests for link_health.py classification/state and repack_skins.py extraction.

Archives are built in memory; no network access.
"""

import io
import json
import os
import sys
import tempfile
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

import pytest
import link_health as lh
import repack_skins as rp
from build_catalog import check_for_issues, split_hidden
from crawl_sources import load_existing_urls

INFO = {
    "identifier": "com.example.skin",
    "name": "Example",
    "gameTypeIdentifier": "com.rileytestut.delta.game.gba",
    "representations": {},
}


def make_zip(files: dict) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for name, data in files.items():
            z.writestr(name, data if isinstance(data, bytes) else data.encode())
    return buf.getvalue()


def skin_zip(**info) -> bytes:
    return make_zip({"info.json": json.dumps({**INFO, **info}), "image.png": b"png"})


def classify(data: bytes) -> dict:
    return lh.classify_archive(zipfile.ZipFile(io.BytesIO(data)))


# ---------------------------------------------------------------------------
# classify_archive
# ---------------------------------------------------------------------------

class TestClassify:
    def test_valid_skin(self):
        assert classify(skin_zip())["result"] == "ok"

    def test_trailing_commas_and_comments_are_ok(self):
        # Foundation accepts trailing commas; the app strips `//` comments.
        raw = '{\n"identifier": "a", // id\n"name": "n",\n"gameTypeIdentifier": "g",\n"representations": {},\n}'
        assert classify(make_zip({"info.json": raw}))["result"] == "ok"

    def test_missing_keys(self):
        r = classify(make_zip({"info.json": json.dumps({"name": "x"})}))
        assert r["result"] == "info_missing_keys"
        assert "identifier" in r["missing"]

    def test_unparseable_info(self):
        assert classify(make_zip({"info.json": "{nope"}))["result"] == "bad_info_json"

    def test_pack_of_skin_files(self):
        data = make_zip({"A.deltaskin": skin_zip(), "B.deltaskin": skin_zip(identifier="b")})
        r = classify(data)
        assert r["result"] == "pack"
        assert r["inner"] == ["A.deltaskin", "B.deltaskin"]

    def test_pack_of_skin_folders(self):
        data = make_zip({"Pack/A.deltaskin/info.json": json.dumps(INFO), "Pack/A.deltaskin/a.png": b"x"})
        r = classify(data)
        assert r["result"] == "pack"
        assert r["inner"] == ["Pack/A.deltaskin/"]

    def test_nested_folder(self):
        r = classify(make_zip({"Skin/info.json": json.dumps(INFO)}))
        assert r["result"] == "nested_folder"

    def test_macosx_junk_ignored(self):
        data = make_zip({"__MACOSX/._info.json": b"x", "Skin/info.json": json.dumps(INFO)})
        assert classify(data)["result"] == "nested_folder"

    def test_no_info(self):
        assert classify(make_zip({"readme.txt": "hi"}))["result"] == "no_info_json"


def layout(**assets):
    return {"assets": assets, "items": [], "mappingSize": {"width": 414, "height": 896}}


def art_zip(representations: dict, files: dict) -> bytes:
    return make_zip({"info.json": json.dumps({**INFO, "representations": representations}), **files})


PORTRAIT_LANDSCAPE = {"iphone": {"edgeToEdge": {
    "portrait": layout(resizable="portrait.pdf"),
    "landscape": layout(resizable="landscape.pdf"),
}}}


class TestArtwork:
    def test_all_artwork_present(self):
        data = art_zip(PORTRAIT_LANDSCAPE, {"portrait.pdf": b"%PDF", "landscape.pdf": b"%PDF"})
        assert classify(data)["result"] == "ok"

    def test_no_artwork_at_all(self):
        r = classify(art_zip(PORTRAIT_LANDSCAPE, {}))
        assert r["result"] == "missing_artwork"
        assert sorted(r["layouts"]) == ["iphone/edgeToEdge/landscape", "iphone/edgeToEdge/portrait"]

    def test_some_layouts_missing_stays_ok(self):
        r = classify(art_zip(PORTRAIT_LANDSCAPE, {"portrait.pdf": b"%PDF"}))
        assert r["result"] == "ok"
        assert r["partialArtwork"] == ["iphone/edgeToEdge/landscape"] and r["layoutCount"] == 2

    def test_partial_artwork_recorded_not_failing(self):
        res = {SKIN["id"]: {"result": "ok", "partialArtwork": ["iphone/edgeToEdge/landscape"], "layoutCount": 2}}
        h = lh.update_health({"skins": {}}, [SKIN], res, "d1")
        assert h["skins"] == {}
        assert h["partialArtwork"][SKIN["id"]]["layouts"] == ["iphone/edgeToEdge/landscape"]
        # Fixed on the next run: the record goes away.
        h = lh.update_health(h, [SKIN], {SKIN["id"]: {"result": "ok"}}, "d2")
        assert h["partialArtwork"] == {}

    def test_repack_keeps_pack_skins_with_partial_artwork(self):
        inner = art_zip(PORTRAIT_LANDSCAPE, {"portrait.pdf": b"%PDF"})
        assert [s["path"] for s in rp.extract_skins(make_zip({"A.deltaskin": inner}))] == ["A.deltaskin"]

    def test_repack_skips_pack_skins_without_artwork(self):
        inner = art_zip(PORTRAIT_LANDSCAPE, {})
        assert rp.extract_skins(make_zip({"A.deltaskin": inner})) == []

    def test_any_size_is_enough(self):
        reps = {"iphone": {"standard": {"portrait": layout(small="s.png", medium="m.png", large="l.png")}}}
        assert classify(art_zip(reps, {"m.png": b"png"}))["result"] == "ok"

    # Lenient matching copied from Archive.entry(matchingAssetNamed:) in the app.
    @pytest.mark.parametrize("named, packed", [
        ("art/portrait.pdf", {"art/portrait.pdf": b"x"}),   # exact path
        ("portrait.pdf", {"Skin/Portrait.PDF": b"x"}),      # other folder, other case
        ("portrait.png", {"portrait.pdf": b"x"}),           # same stem as pdf
        ("portrait", {"portrait.svg": b"x"}),               # bare stem
    ])
    def test_lenient_asset_matching(self, named, packed):
        reps = {"iphone": {"edgeToEdge": {"portrait": layout(resizable=named)}}}
        assert classify(art_zip(reps, packed))["result"] == "ok"

    def test_unrelated_file_does_not_count(self):
        # "My ds skin" names a PDF but only ships a file called Untitled.
        reps = {"iphone": {"edgeToEdge": {"portrait": layout(resizable="iphone_edgetoedge_portrait.pdf")}}}
        assert classify(art_zip(reps, {"Untitled": b"x"}))["result"] == "missing_artwork"

    def test_missing_artwork_hides(self):
        rec = {"url": "u", "result": "missing_artwork", "failures": 2}
        assert lh.is_hidden(rec, "u")


def test_encode_url_keeps_hash_as_fragment():
    # URL(string:) treats `#` as a fragment, so the app 404s on these too.
    assert lh.encode_url("https://x/a b#1.deltaskin") == "https://x/a%20b#1.deltaskin"


# ---------------------------------------------------------------------------
# State + hiding
# ---------------------------------------------------------------------------

SKIN = {"id": "a1b2c3d4e5f60718", "downloadURL": "https://example.com/A.deltaskin"}


class TestHealthState:
    def test_hidden_after_consecutive_permanent_failures(self):
        h = {"skins": {}}
        h = lh.update_health(h, [SKIN], {SKIN["id"]: {"result": "http_404"}}, "2026-10-01")
        assert not lh.is_hidden(h["skins"][SKIN["id"]], SKIN["downloadURL"])
        h = lh.update_health(h, [SKIN], {SKIN["id"]: {"result": "http_404"}}, "2026-10-08")
        rec = h["skins"][SKIN["id"]]
        assert rec["failures"] == 2 and rec["firstFailedAt"] == "2026-10-01"
        assert lh.is_hidden(rec, SKIN["downloadURL"])

    def test_transient_failures_never_hide(self):
        h = {"skins": {}}
        for day in ("01", "08", "15"):
            h = lh.update_health(h, [SKIN], {SKIN["id"]: {"result": "network_error"}}, f"2026-10-{day}")
        assert not lh.is_hidden(h["skins"][SKIN["id"]], SKIN["downloadURL"])

    def test_recovery_clears_record(self):
        h = lh.update_health({"skins": {}}, [SKIN], {SKIN["id"]: {"result": "http_404"}}, "d1")
        h = lh.update_health(h, [SKIN], {SKIN["id"]: {"result": "ok"}}, "d2")
        assert SKIN["id"] not in h["skins"]

    def test_changed_url_unhides(self):
        rec = {"url": SKIN["downloadURL"], "result": "http_404", "failures": 5}
        assert not lh.is_hidden(rec, "https://example.com/new.deltaskin")

    def test_subset_run_keeps_other_records(self):
        other = {"url": "u", "result": "http_404", "failures": 3, "firstFailedAt": "d", "lastCheckedAt": "d"}
        h = lh.update_health({"skins": {"ffff": other}}, [SKIN], {SKIN["id"]: {"result": "ok"}}, "d2")
        assert h["skins"]["ffff"] == other

    def test_split_hidden(self):
        health = {"skins": {SKIN["id"]: {"url": SKIN["downloadURL"], "result": "not_zip", "failures": 2}}}
        shown, hidden = split_hidden([dict(SKIN), {"id": "b" * 16, "downloadURL": "x"}], health)
        assert [e["id"] for e in hidden] == [SKIN["id"]]
        assert [e["id"] for e in shown] == ["b" * 16]


def test_case_colliding_paths_flagged(capsys):
    base = {"name": "n", "systems": ["gba"], "source": "manual"}
    entries = [
        {**base, "id": "a" * 16, "downloadURL": "https://x/a.deltaskin", "_source_file": "skins/virtualBoy/x.json"},
        {**base, "id": "b" * 16, "downloadURL": "https://x/b.deltaskin", "_source_file": "skins/virtualboy/x.json"},
    ]
    assert check_for_issues(entries) == 1
    assert "differs only by case" in capsys.readouterr().out


def test_crawler_dedupes_against_skins_dir_and_original_urls():
    with tempfile.TemporaryDirectory() as d:
        os.makedirs(os.path.join(d, "gba"))
        with open(os.path.join(d, "gba", "s.json"), "w") as f:
            json.dump({"downloadURL": "https://mirror/a.deltaskin", "originalURL": "https://x/pack.zip"}, f)
        urls = load_existing_urls(os.path.join(d, "missing.json"), d)
    assert urls == {"https://mirror/a.deltaskin", "https://x/pack.zip"}


# ---------------------------------------------------------------------------
# repack_skins
# ---------------------------------------------------------------------------

PARENT = {
    "id": "c0ffee0000000001", "name": "Big Pack", "systems": ["gba"], "source": "deltastyles.com",
    "author": "someone", "downloadURL": "https://deltastyles.com/files/skins/pack.zip",
    "thumbnailURL": "https://thumb/c0ffee.png", "_source_file": "skins/gba/big-pack.json",
}


class TestRepack:
    def test_single_skin_keeps_id(self):
        skins = rp.extract_skins(make_zip({"Only.deltaskin": skin_zip()}))
        [entry] = rp.plan_entries(PARENT, skins)
        assert entry["id"] == PARENT["id"]
        assert entry["downloadURL"] == rp.MIRROR_BASE + PARENT["id"] + ".deltaskin"
        assert entry["originalURL"] == PARENT["downloadURL"]
        assert entry["thumbnailURL"] == PARENT["thumbnailURL"]
        assert entry["_file"] == PARENT["_source_file"]

    def test_pack_splits_into_grouped_entries(self):
        data = make_zip({
            "A.deltaskin": skin_zip(identifier="a", name="Alpha"),
            "B.manicskin": skin_zip(identifier="b", name="Beta",
                                    gameTypeIdentifier="com.rileytestut.delta.game.snes"),
        })
        entries = rp.plan_entries(PARENT, rp.extract_skins(data))
        assert [e["name"] for e in entries] == ["Alpha", "Beta"]
        assert {e["groupId"] for e in entries} == {PARENT["id"]}
        assert [e["groupOrder"] for e in entries] == [1, 2]
        # A GBA pack shipping a real SNES variant files it under SNES.
        assert entries[1]["systems"] == ["snes"]
        assert entries[1]["downloadURL"].endswith(".manicskin")
        assert all(e["thumbnailURL"] is None for e in entries)
        assert len({e["id"] for e in entries}) == 2
        assert all(e["author"] == "someone" for e in entries)

    def test_manic_identifier_sets_system(self):
        data = make_zip({
            "A.manicskin": skin_zip(identifier="a", name="A", gameTypeIdentifier="public.aoshuang.game.gb"),
            "B.manicskin": skin_zip(identifier="b", name="B", gameTypeIdentifier="public.aoshuang.game.gb"),
        })
        entries = rp.plan_entries(PARENT, rp.extract_skins(data), "custom/skins")
        assert [e["systems"] for e in entries] == [["gb"], ["gb"]]
        assert all(e["_file"].startswith("custom/skins/gb/") for e in entries)

    @pytest.mark.parametrize("parent_system, gti, expected", [
        ("gb", "com.rileytestut.delta.game.gbc", None),          # shared GB/GBC id
        ("threeDS", "com.rileytestut.delta.game.ds", None),      # stand-in
        ("gamegear", "com.rileytestut.delta.game.ds", None),     # stand-in
        ("gba", "com.rileytestut.delta.game.gbc", "gbc"),        # mixed Delta pack
        ("gba", "com.rileytestut.delta.game.gba", None),         # same system
        ("nds", "public.aoshuang.game.3ds", "threeDS"),          # Manic is trusted
        ("gba", None, None),
    ])
    def test_system_for_inner(self, parent_system, gti, expected):
        assert rp._system_for_inner(gti, parent_system) == expected

    def test_plain_folder_pack_keeps_every_skin(self):
        data = make_zip({
            "A/info.json": json.dumps({**INFO, "identifier": "a"}),
            "B/info.json": json.dumps({**INFO, "identifier": "b"}),
            "B/extra/info.json": "{}",
        })
        assert [s["path"] for s in rp.extract_skins(data)] == ["A/", "B/"]

    def test_folder_skins_are_rezipped_with_root_info(self):
        data = make_zip({"P/A.deltaskin/info.json": json.dumps(INFO), "P/A.deltaskin/a.png": b"x"})
        [skin] = rp.extract_skins(data)
        assert classify(skin["data"])["result"] == "ok"

    def test_nested_folder_rezipped(self):
        data = make_zip({"__MACOSX/._x": b"", "Skin/info.json": json.dumps(INFO), "Skin/i.png": b"x"})
        [skin] = rp.extract_skins(data)
        names = zipfile.ZipFile(io.BytesIO(skin["data"])).namelist()
        assert sorted(names) == ["i.png", "info.json"]

    def test_duplicate_identifiers_and_broken_inner_skipped(self):
        data = make_zip({
            "A.deltaskin": skin_zip(),
            "A copy.deltaskin": skin_zip(),
            "Broken.deltaskin": make_zip({"readme.txt": "x"}),
        })
        assert [s["path"] for s in rp.extract_skins(data)] == ["A.deltaskin"]

    def test_duplicate_names_get_variant_label(self):
        data = make_zip({
            "Red_Dark.deltaskin": skin_zip(identifier="r", name="Same"),
            "Blue_Dark.deltaskin": skin_zip(identifier="b", name="Same"),
        })
        names = [e["name"] for e in rp.plan_entries(PARENT, rp.extract_skins(data))]
        assert names == ["Same (Red Dark)", "Same (Blue Dark)"]
