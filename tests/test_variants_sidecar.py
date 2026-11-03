"""Tests for the variants.json sidecar: computing variants from info.json, the
health check recording them and checking their artwork, import-time records,
and build_catalog merging only when the URL matches. No network access."""

import io
import json
import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

import pytest
import build_catalog as bc
import link_health as lh
import process_submission as ps
import variants_sidecar as vs
from skin_schema import validate_entry, validate_variants
from .test_link_health import INFO, layout, make_zip

ALT = {"kind": "alt", "key": "alt", "label": "Alternate layout"}
URL = "https://example.com/Skin.deltaskin"
SKIN = {"id": "aaaaaaaaaaaaaaaa", "downloadURL": URL}

REPS = {"iphone": {"standard": {"portrait": layout(resizable="base.pdf")}}}


def classify(info: dict, files: dict) -> dict:
    data = make_zip({"info.json": json.dumps({**INFO, "representations": REPS, **info}), **files})
    return lh.classify_archive(zipfile.ZipFile(io.BytesIO(data)))


# ---------------------------------------------------------------------------
# compute_variants
# ---------------------------------------------------------------------------

class TestComputeVariants:
    def test_plain_skin_has_none(self):
        assert vs.compute_variants(INFO) == []

    @pytest.mark.parametrize("junk", [None, [], "x", 5])
    def test_not_an_object(self, junk):
        assert vs.compute_variants(junk) == []

    def test_alt_representations(self):
        assert vs.compute_variants({"altRepresentations": REPS}) == [ALT]

    @pytest.mark.parametrize("alt", [{}, None, [], "yes"])
    def test_empty_or_odd_alt_is_ignored(self, alt):
        assert vs.compute_variants({"altRepresentations": alt}) == []

    def test_themes_use_id_and_name(self):
        info = {"themes": [{"id": "dark", "name": "Dark"}, {"id": "neon", "name": "Neon Pink"}]}
        assert vs.compute_variants(info) == [
            {"kind": "theme", "key": "dark", "label": "Dark"},
            {"kind": "theme", "key": "neon", "label": "Neon Pink"},
        ]

    def test_theme_without_name_labels_with_id_and_without_id_is_skipped(self):
        info = {"themes": [{"id": "dark"}, {"name": "No id"}, "junk", {"id": ""}]}
        assert vs.compute_variants(info) == [{"kind": "theme", "key": "dark", "label": "dark"}]

    def test_game_overrides_use_the_keys(self):
        info = {"gameOverrides": {"Doom": {}, "Wolfenstein 3D": {}, "0123456789abcdef0123456789abcdef": {}}}
        assert [(v["kind"], v["key"], v["label"]) for v in vs.compute_variants(info)] == [
            ("game", "Doom", "Doom"),
            ("game", "Wolfenstein 3D", "Wolfenstein 3D"),
            ("game", "0123456789abcdef0123456789abcdef", "0123456789abcdef0123456789abcdef"),
        ]

    def test_order_is_alt_themes_games_and_duplicates_collapse(self):
        info = {
            "gameOverrides": {"Doom": {}},
            "themes": [{"id": "a", "name": "A"}, {"id": "a", "name": "A again"}],
            "altRepresentations": REPS,
        }
        assert [v["kind"] for v in vs.compute_variants(info)] == ["alt", "theme", "game"]
        assert len(vs.compute_variants(info)) == 3

    def test_output_validates(self):
        info = {"altRepresentations": REPS, "themes": [{"id": "a", "name": "A"}], "gameOverrides": {"G": {}}}
        assert validate_variants(vs.compute_variants(info)) == []


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

class TestValidateVariants:
    @pytest.mark.parametrize("value", [None, [], "x", {}, [5], [{}], [{"kind": "nope", "key": "k", "label": "l"}],
                                       [{"kind": "theme", "key": "", "label": "l"}],
                                       [{"kind": "theme", "key": "k", "label": " "}],
                                       [{"kind": "alt", "key": "other", "label": "l"}]])
    def test_invalid(self, value):
        assert validate_variants(value) != []

    def test_duplicates_are_invalid(self):
        v = {"kind": "theme", "key": "k", "label": "l"}
        assert any("duplicate" in e for e in validate_variants([v, dict(v)]))

    def test_same_key_in_two_kinds_is_fine(self):
        assert validate_variants([{"kind": "theme", "key": "k", "label": "l"},
                                  {"kind": "game", "key": "k", "label": "k"}]) == []

    def test_entry_validation_checks_variants(self):
        entry = {"id": "0123456789abcdef", "name": "n", "systems": ["nds"], "downloadURL": URL, "source": "x"}
        assert validate_entry({**entry, "variants": [ALT]}) == []
        assert validate_entry({**entry, "variants": [{"kind": "x"}]}) != []

    def test_store_validation(self):
        assert vs.validate_store({"a" * 16: {"url": URL, "variants": [ALT]}}) == []
        assert vs.validate_store([]) != []
        assert vs.validate_store({"a" * 16: {"url": URL, "variants": []}}) != []
        assert vs.validate_store({"a" * 16: {"variants": [ALT]}}) != []


# ---------------------------------------------------------------------------
# Health check: variants and variant artwork
# ---------------------------------------------------------------------------

def alt_reps(**assets):
    return {"iphone": {"standard": {"portrait": layout(**assets)}}}


class TestHealthCheckVariants:
    def test_ok_skin_reports_variants(self):
        r = classify({"altRepresentations": alt_reps(resizable="alt.pdf")}, {"base.pdf": b"x", "alt.pdf": b"x"})
        assert r == {"result": "ok", "variants": [ALT]}

    def test_skin_without_variants_reports_an_empty_list(self):
        assert classify({}, {"base.pdf": b"x"}) == {"result": "ok", "variants": []}

    def test_failed_skins_still_report_variants(self):
        info = {"altRepresentations": alt_reps(resizable="alt.pdf")}
        r = classify(info, {})  # no artwork at all
        assert r["result"] == "missing_artwork" and r["variants"] == [ALT]
        data = make_zip({"info.json": json.dumps({"name": "x", "themes": [{"id": "t", "name": "T"}]})})
        r = lh.classify_archive(zipfile.ZipFile(io.BytesIO(data)))
        assert r["result"] == "info_missing_keys" and r["variants"][0]["key"] == "t"

    def test_unreadable_archives_report_no_variants_key(self):
        for files in ({"readme.txt": "hi"}, {"info.json": "{nope"}):
            r = lh.classify_archive(zipfile.ZipFile(io.BytesIO(make_zip(files))))
            assert "variants" not in r

    def test_missing_alt_artwork_is_partial_not_a_failure(self):
        r = classify({"altRepresentations": alt_reps(resizable="gone.pdf")}, {"base.pdf": b"x"})
        assert r["result"] == "ok"
        assert r["partialArtwork"] == ["alt:iphone/standard/portrait"]
        assert r["layoutCount"] == 2

    def test_missing_theme_artwork_is_partial(self):
        themes = [{"id": "dark", "name": "Dark", "assets": {"iphone": {"standard": {"portrait": {"resizable": "dark.pdf"}}}}},
                  {"id": "ok", "name": "Fine", "assets": {"iphone": {"standard": {"portrait": {"resizable": "base.pdf"}}}}}]
        r = classify({"themes": themes}, {"base.pdf": b"x"})
        assert r["partialArtwork"] == ["theme:dark:iphone/standard/portrait"]
        assert [v["key"] for v in r["variants"]] == ["dark", "ok"]

    def test_theme_that_names_no_files_is_not_a_gap(self):
        themes = [{"id": "t", "name": "T", "assets": {"iphone": {"standard": {"portrait": {}}}}}, {"id": "u", "name": "U"}]
        r = classify({"themes": themes}, {"base.pdf": b"x"})
        assert r["result"] == "ok" and "partialArtwork" not in r

    def test_missing_game_override_artwork_is_partial(self):
        overrides = {"Doom": alt_reps(resizable="doom.pdf"), "Quake": alt_reps(resizable="base.pdf")}
        r = classify({"gameOverrides": overrides}, {"base.pdf": b"x"})
        assert r["result"] == "ok"
        assert r["partialArtwork"] == ["game:Doom:iphone/standard/portrait"]

    def test_variant_gaps_join_base_gaps(self):
        reps = {"iphone": {"standard": {"portrait": layout(resizable="base.pdf"),
                                        "landscape": layout(resizable="gone.pdf")}}}
        r = classify({"representations": reps, "altRepresentations": alt_reps(resizable="gone.pdf")}, {"base.pdf": b"x"})
        assert r["partialArtwork"] == ["iphone/standard/landscape", "alt:iphone/standard/portrait"]
        assert r["layoutCount"] == 3

    def test_variant_art_never_rescues_or_condemns_the_base(self):
        # Base art all missing: the skin fails, variants or not.
        r = classify({"altRepresentations": alt_reps(resizable="alt.pdf")}, {"alt.pdf": b"x"})
        assert r["result"] == "missing_artwork"
        # Variant art all missing: the skin still passes.
        r = classify({"altRepresentations": alt_reps(resizable="gone.pdf")}, {"base.pdf": b"x"})
        assert r["result"] == "ok"

    def test_variants_stay_out_of_link_health_json(self):
        res = {SKIN["id"]: {"result": "missing_artwork", "layouts": ["x"], "variants": [ALT]}}
        h = lh.update_health({"skins": {}}, [SKIN], res, "d1")
        assert "variants" not in h["skins"][SKIN["id"]]
        assert h["skins"][SKIN["id"]]["layouts"] == ["x"]


# ---------------------------------------------------------------------------
# Sidecar upkeep
# ---------------------------------------------------------------------------

def run_update(store, result, prune=False):
    return vs.update_from_results(store, [SKIN], {SKIN["id"]: result}, lh.PERMANENT, prune)


class TestUpdateFromResults:
    def test_records_a_skin_that_passed(self):
        store = {}
        run_update(store, {"result": "ok", "variants": [ALT]})
        assert store == {SKIN["id"]: {"url": URL, "variants": [ALT]}}

    def test_records_a_skin_that_failed_but_was_read(self):
        store = {}
        run_update(store, {"result": "missing_artwork", "variants": [ALT]})
        assert SKIN["id"] in store

    def test_replaces_the_record_each_run(self):
        store = {SKIN["id"]: {"url": URL, "variants": [ALT]}}
        theme = {"kind": "theme", "key": "t", "label": "T"}
        stats = run_update(store, {"result": "ok", "variants": [theme]})
        assert store[SKIN["id"]]["variants"] == [theme] and stats["recorded"] == 1

    def test_unchanged_record_is_not_counted(self):
        store = {SKIN["id"]: {"url": URL, "variants": [ALT]}}
        assert run_update(store, {"result": "ok", "variants": [ALT]}) == {"recorded": 0, "dropped": 0}

    def test_drops_the_record_when_variants_are_gone(self):
        store = {SKIN["id"]: {"url": URL, "variants": [ALT]}}
        stats = run_update(store, {"result": "ok", "variants": []})
        assert store == {} and stats["dropped"] == 1

    def test_keeps_the_record_through_a_network_error(self):
        store = {SKIN["id"]: {"url": URL, "variants": [ALT]}}
        run_update(store, {"result": "network_error"})
        run_update(store, {"result": "http_503"})
        assert SKIN["id"] in store

    def test_drops_the_record_when_the_archive_is_permanently_unreadable(self):
        for result in ("http_404", "not_zip", "no_info_json", "pack"):
            store = {SKIN["id"]: {"url": URL, "variants": [ALT]}}
            run_update(store, {"result": result})
            assert store == {}, result

    def test_drops_the_record_when_the_url_changed(self):
        store = {SKIN["id"]: {"url": "https://old.example.com/a.deltaskin", "variants": [ALT]}}
        run_update(store, {"result": "network_error"})
        assert store == {}

    def test_prune_drops_skins_that_left_the_catalog(self):
        store = {"b" * 16: {"url": "https://x/y.deltaskin", "variants": [ALT]}}
        run_update(store, {"result": "ok", "variants": []}, prune=False)
        assert "b" * 16 in store  # subset run (--ids): leave others alone
        run_update(store, {"result": "ok", "variants": []}, prune=True)
        assert store == {}

    def test_save_and_load_roundtrip_is_sorted(self, tmp_path):
        path = str(tmp_path / "variants.json")
        vs.save_variants({"b" * 16: {"url": "u2", "variants": [ALT]}, "a" * 16: {"url": "u1", "variants": [ALT]}}, path)
        assert list(vs.load_variants(path)) == ["a" * 16, "b" * 16]
        assert vs.load_variants(str(tmp_path / "missing.json")) == {}


# ---------------------------------------------------------------------------
# Import time
# ---------------------------------------------------------------------------

class TestImport:
    @pytest.fixture(autouse=True)
    def _clean(self):
        vs._IMPORTED.clear()
        yield
        vs._IMPORTED.clear()

    def test_process_skin_file_notes_variants_and_flush_writes_them(self, monkeypatch, tmp_path):
        info = {**INFO, "altRepresentations": REPS}
        monkeypatch.setattr(ps, "stream_extract_info_json", lambda url, token="": info)
        entries = ps.process_skin_file(URL)
        path = str(tmp_path / "variants.json")
        assert vs.flush_imports(entries, path) == 1
        assert vs.load_variants(path) == {entries[0]["id"]: {"url": URL, "variants": [ALT]}}

    def test_skin_without_variants_gets_no_record(self, monkeypatch, tmp_path):
        monkeypatch.setattr(ps, "stream_extract_info_json", lambda url, token="": INFO)
        entries = ps.process_skin_file(URL)
        path = str(tmp_path / "variants.json")
        assert vs.flush_imports(entries, path) == 0
        assert not Path(path).exists()

    def test_reimport_without_variants_drops_an_old_record(self, monkeypatch, tmp_path):
        path = str(tmp_path / "variants.json")
        monkeypatch.setattr(ps, "stream_extract_info_json", lambda url, token="": {**INFO, "altRepresentations": REPS})
        entries = ps.process_skin_file(URL)
        vs.flush_imports(entries, path)
        monkeypatch.setattr(ps, "stream_extract_info_json", lambda url, token="": INFO)
        entries = ps.process_skin_file(URL)
        vs.flush_imports(entries, path)
        assert vs.load_variants(path) == {}

    def test_unreadable_info_json_leaves_the_sidecar_alone(self, monkeypatch, tmp_path):
        monkeypatch.setattr(ps, "stream_extract_info_json", lambda url, token="": None)
        entries = ps.process_skin_file(URL)
        assert vs.flush_imports(entries, str(tmp_path / "v.json")) == 0

    def test_dry_run_writes_nothing(self, monkeypatch, tmp_path):
        monkeypatch.setattr(ps, "stream_extract_info_json", lambda url, token="": {**INFO, "altRepresentations": REPS})
        entries = ps.process_skin_file(URL)
        path = tmp_path / "variants.json"
        vs.flush_imports(entries, str(path), dry_run=True)
        assert not path.exists()

    def test_crawler_reads_info_through_the_same_registry(self, monkeypatch):
        import crawl_sources as cs
        monkeypatch.setattr(cs, "stream_extract_info_json", lambda url: {**INFO, "themes": [{"id": "t", "name": "T"}]})
        cs._deltastyles_system_from_info(URL)
        assert vs._IMPORTED[URL] == [{"kind": "theme", "key": "t", "label": "T"}]


# ---------------------------------------------------------------------------
# build_catalog
# ---------------------------------------------------------------------------

def entry(**extra):
    return {"id": "aaaaaaaaaaaaaaaa", "name": "Skin", "systems": ["nds"], "downloadURL": URL, "source": "x", **extra}


class TestBuildMerge:
    def test_merges_when_url_matches(self):
        entries = [entry()]
        assert vs.merge_variants(entries, {entries[0]["id"]: {"url": URL, "variants": [ALT]}}) == 1
        assert entries[0]["variants"] == [ALT]

    def test_ignores_a_record_for_another_url(self):
        entries = [entry()]
        store = {entries[0]["id"]: {"url": "https://example.com/Old.deltaskin", "variants": [ALT]}}
        assert vs.merge_variants(entries, store) == 0
        assert "variants" not in entries[0]

    def test_entries_without_a_record_publish_without_variants(self):
        entries = [entry(), entry(id="bbbbbbbbbbbbbbbb", downloadURL="https://example.com/B.deltaskin")]
        vs.merge_variants(entries, {"aaaaaaaaaaaaaaaa": {"url": URL, "variants": [ALT]}})
        assert "variants" not in entries[1]

    def test_end_to_end_build(self, tmp_path, monkeypatch):
        skins = tmp_path / "skins" / "nds"
        skins.mkdir(parents=True)
        (skins / "a.json").write_text(json.dumps(entry()))
        b = entry(id="bbbbbbbbbbbbbbbb", name="Other", downloadURL="https://example.com/B.deltaskin")
        (skins / "b.json").write_text(json.dumps(b))
        side = tmp_path / "variants.json"
        vs.save_variants({
            "aaaaaaaaaaaaaaaa": {"url": URL, "variants": [ALT]},
            "bbbbbbbbbbbbbbbb": {"url": "https://example.com/Moved.deltaskin", "variants": [ALT]},
        }, str(side))
        out = tmp_path / "catalog.json"
        monkeypatch.setattr(bc, "fetch_release_download_counts", lambda: {})
        monkeypatch.setattr(sys, "argv", ["build_catalog", "--skins-dir", str(tmp_path / "skins"), "--output", str(out),
                                          "--variants-file", str(side), "--health-file", str(tmp_path / "none.json")])
        bc.main()
        by_id = {s["id"]: s for s in json.loads(out.read_text())["skins"]}
        assert by_id["aaaaaaaaaaaaaaaa"]["variants"] == [ALT]
        assert "variants" not in by_id["bbbbbbbbbbbbbbbb"]

    def test_check_only_rejects_a_bad_sidecar(self, tmp_path, monkeypatch, capsys):
        skins = tmp_path / "skins" / "nds"
        skins.mkdir(parents=True)
        (skins / "a.json").write_text(json.dumps(entry()))
        side = tmp_path / "variants.json"
        side.write_text(json.dumps({"aaaaaaaaaaaaaaaa": {"url": URL, "variants": [{"kind": "bogus"}]}}))
        monkeypatch.setattr(sys, "argv", ["build_catalog", "--skins-dir", str(tmp_path / "skins"), "--check-only",
                                          "--variants-file", str(side)])
        with pytest.raises(SystemExit) as exc:
            bc.main()
        assert exc.value.code == 1
        assert "variants" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# Committed data
# ---------------------------------------------------------------------------

REPO = Path(__file__).parent.parent


class TestSeededSidecar:
    def test_sidecar_is_valid(self):
        assert vs.validate_store(vs.load_variants(str(REPO / "variants.json"))) == []

    def test_the_five_alt_representations_ds_skins_get_variants(self):
        entries = bc.load_all_skins(str(REPO / "skins"))
        names = {"Ignited DS", "epicpal DS+ — IGNITED-ds+", "OBSIDIAN NDS",
                 "TITANIUM ONE — titanium L nds", "TITANIUM ONE — titanium R nds"}
        wanted = [e for e in entries if e["name"] in names and "nds" in e["systems"]]
        assert len(wanted) == 5
        assert vs.merge_variants(wanted, vs.load_variants(str(REPO / "variants.json"))) == 5
        assert all(e["variants"] == [ALT] for e in wanted)
