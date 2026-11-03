"""Opt-outs are enforced at every entry point (SkinKit#34)."""

import json
import sys
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

import pytest
import blocklist as bl
import process_submission as ps
import crawl_sources as cs
import build_catalog as bc


def rule(match):
    return {"match": match, "issue": 1, "verifiedBy": "x", "method": "owner", "date": "2026-11-02"}


def skin(sid, source, url, **kw):
    return {"id": sid, "name": sid, "systems": ["gba"], "downloadURL": url, "source": source, **kw}


@pytest.fixture
def blocked_alice(set_blocklist):
    return set_blocklist([rule("alice/skins")])


# ---------------------------------------------------------------------------
# process_submission
# ---------------------------------------------------------------------------

class TestProcessSubmission:
    def test_process_github_repo_returns_nothing_without_touching_the_api(self, blocked_alice):
        with mock.patch.object(ps, "gh_api", side_effect=AssertionError("API called")), \
             mock.patch.object(ps, "stream_extract_info_json", side_effect=AssertionError("fetched")):
            assert ps.process_github_repo("Alice/Skins") == []

    def test_unblocked_repo_still_works(self, blocked_alice):
        tree = {"tree": [{"path": "a.deltaskin"}]}
        with mock.patch.object(ps, "gh_api", return_value=tree), \
             mock.patch.object(ps, "stream_extract_info_json", return_value={"name": "A"}):
            [e] = ps.process_github_repo("bob/skins")
        assert e["name"] == "A"

    def test_process_skin_file_blocked_by_url(self, blocked_alice):
        with mock.patch.object(ps, "stream_extract_info_json", side_effect=AssertionError("fetched")):
            assert ps.process_skin_file("https://raw.githubusercontent.com/alice/skins/HEAD/a.deltaskin") == []
            assert ps.process_skin_file("https://github.com/alice/skins/releases/download/v1/a.deltaskin",
                                        source="deltastyles.com") == []

    def test_process_skin_file_blocked_by_source(self, blocked_alice):
        with mock.patch.object(ps, "stream_extract_info_json", side_effect=AssertionError("fetched")):
            assert ps.process_skin_file("https://example.com/a.deltaskin", source="alice/skins") == []

    def test_process_github_release_blocked(self, blocked_alice):
        with mock.patch.object(ps, "gh_api", side_effect=AssertionError("API called")):
            assert ps.process_github_release("https://github.com/alice/skins/releases/tag/v1") == []

    def test_owner_wildcard_covers_every_path(self, set_blocklist):
        set_blocklist([rule("alice/*")])
        with mock.patch.object(ps, "gh_api", side_effect=AssertionError("API called")):
            assert ps.process_github_repo("alice/anything") == []
            assert ps.process_github_release("https://github.com/ALICE/anything/releases") == []

    def test_main_reports_blocked_instead_of_failing(self, blocked_alice, tmp_path, monkeypatch, capsys):
        out = tmp_path / "gh_output"
        monkeypatch.setenv("GITHUB_OUTPUT", str(out))
        monkeypatch.setattr(sys, "argv", ["process_submission.py", "--output-dir", str(tmp_path / "skins"),
                                          "--", "https://github.com/alice/skins"])
        with mock.patch.object(ps, "gh_api", side_effect=AssertionError("API called")), \
             pytest.raises(SystemExit) as exc:
            ps.main()
        assert exc.value.code == 0
        assert "blocked=true" in out.read_text()
        assert "opted out of EmuSkins" in capsys.readouterr().out
        assert not (tmp_path / "skins").exists()

    def test_main_blocks_each_url_form(self, blocked_alice, tmp_path, monkeypatch):
        for url in ("https://raw.githubusercontent.com/alice/skins/HEAD/a.deltaskin",
                    "https://github.com/alice/skins/raw/main/a.deltaskin",
                    "https://github.com/alice/skins/releases/tag/v1"):
            monkeypatch.setattr(sys, "argv", ["process_submission.py", "--output-dir", str(tmp_path), "--", url])
            with mock.patch.object(ps, "stream_extract_info_json", side_effect=AssertionError("fetched")), \
                 pytest.raises(SystemExit) as exc:
                ps.main()
            assert exc.value.code == 0

    def test_main_filters_blocked_json_metadata(self, blocked_alice, tmp_path, monkeypatch):
        meta = [skin("a" * 16, "alice/skins", "https://raw.githubusercontent.com/alice/skins/HEAD/a.deltaskin"),
                skin("b" * 16, "bob/skins", "https://raw.githubusercontent.com/bob/skins/HEAD/b.deltaskin")]
        monkeypatch.setattr(sys, "argv", ["process_submission.py", "--output-dir", str(tmp_path),
                                          "--dry-run", "--", "https://example.com/skins.json"])
        with mock.patch.object(ps, "process_json_metadata", return_value=meta), \
             mock.patch.object(ps, "save_entries", return_value=[]) as save:
            with pytest.raises(SystemExit):
                ps.main()
        [kept] = save.call_args[0][0]
        assert kept["source"] == "bob/skins"


# ---------------------------------------------------------------------------
# crawl_sources
# ---------------------------------------------------------------------------

class TestCrawl:
    def _run_main(self, tmp_path, monkeypatch, sources):
        (tmp_path / "sources.json").write_text(json.dumps(sources))
        monkeypatch.setattr(sys, "argv", ["crawl_sources.py", "--sources", str(tmp_path / "sources.json"),
                                          "--existing-catalog", str(tmp_path / "none.json"),
                                          "--output-dir", str(tmp_path / "skins")])
        saved = []
        monkeypatch.setattr(cs, "save_entries", lambda entries, *a, **k: saved.extend(entries))
        cs.main()
        return saved

    def test_site_scraper_results_filtered(self, blocked_alice, tmp_path, monkeypatch):
        aggregator = [
            skin("a" * 16, "delta-skins.github.io", "https://raw.githubusercontent.com/alice/skins/HEAD/a.deltaskin"),
            skin("b" * 16, "delta-skins.github.io", "https://raw.githubusercontent.com/bob/skins/HEAD/b.deltaskin"),
        ]
        monkeypatch.setattr(cs, "scrape_delta_skins", lambda: aggregator)
        saved = self._run_main(tmp_path, monkeypatch, {"sites": [{"type": "delta-skins-site"}]})
        assert [e["id"] for e in saved] == ["b" * 16]

    def test_aggregator_repo_block_drops_its_skins_from_the_site_scrape(self, set_blocklist, tmp_path, monkeypatch):
        set_blocklist([rule("delta-skins/delta-skins.github.io")])
        entries = [skin("c" * 16, "delta-skins.github.io",
                        "https://github.com/delta-skins/delta-skins.github.io/raw/master/gba/x.deltaskin")]
        monkeypatch.setattr(cs, "scrape_delta_skins", lambda: entries)
        assert self._run_main(tmp_path, monkeypatch, {"sites": [{"type": "delta-skins-site"}]}) == []

    def test_blocked_repo_in_sources_is_not_scraped(self, blocked_alice, tmp_path, monkeypatch):
        monkeypatch.setattr(cs, "scrape_github_repo", mock.Mock(side_effect=AssertionError("scraped")))
        saved = self._run_main(tmp_path, monkeypatch, {"repos": [{"repo": "Alice/Skins"}]})
        assert saved == []

    def test_deleted_skin_is_not_recrawled(self, blocked_alice, tmp_path, monkeypatch):
        """The JSON is gone, so dedup by downloadURL no longer protects it. The block does."""
        monkeypatch.setattr(cs, "GITHUB_TOKEN", "")
        with mock.patch.object(ps, "gh_api", side_effect=AssertionError("API called")):
            assert cs.scrape_github_repo("alice/skins") == []

    def test_deltastyles_skips_blocked_release_before_reading_it(self, blocked_alice, monkeypatch):
        url = "https://github.com/alice/skins/releases/download/v1/a.deltaskin"
        monkeypatch.setattr(cs.time, "sleep", lambda *_: None)
        monkeypatch.setattr(cs, "_deltastyles_parse_listing",
                            lambda html: [{"_detail_path": "/skins/1-a", "name": "A"}])
        monkeypatch.setattr(cs, "_deltastyles_resolve_variants",
                            lambda path: [{"downloadURL": url, "label": "a"}])
        monkeypatch.setattr(cs, "_deltastyles_system_from_info",
                            lambda u: (_ for _ in ()).throw(AssertionError("downloaded " + u)))
        monkeypatch.setattr(cs, "_ds_fetch", lambda u: "<html></html>")
        assert cs.scrape_deltastyles(["gba"], set()) == []


# ---------------------------------------------------------------------------
# build_catalog
# ---------------------------------------------------------------------------

class TestBuildCatalog:
    def test_split_hidden_drops_blocked(self, blocked_alice):
        entries = [
            skin("1" * 16, "alice/skins", "https://raw.githubusercontent.com/alice/skins/HEAD/a.deltaskin"),
            skin("2" * 16, "deltastyles.com", "https://github.com/ALICE/skins/releases/download/v1/b.deltaskin"),
            skin("3" * 16, "deltastyles.com",
                 "https://github.com/Provenance-Emu/skins/releases/download/mirror/c.deltaskin",
                 originalURL="https://raw.githubusercontent.com/alice/skins/HEAD/pack.zip"),
            skin("4" * 16, "bob/skins", "https://raw.githubusercontent.com/bob/skins/HEAD/d.deltaskin"),
        ]
        shown, hidden = bc.split_hidden(entries, {"skins": {}})
        assert [e["id"] for e in shown] == ["4" * 16]
        assert len(hidden) == 3

    def test_split_hidden_without_blocklist_is_unchanged(self):
        entries = [skin("4" * 16, "bob/skins", "https://raw.githubusercontent.com/bob/skins/HEAD/d.deltaskin")]
        shown, hidden = bc.split_hidden(entries, {"skins": {}})
        assert shown == entries and hidden == []

    def test_main_leaves_blocked_out_of_catalog(self, blocked_alice, tmp_path, monkeypatch):
        skins = tmp_path / "skins" / "gba"
        skins.mkdir(parents=True)
        (skins / "a.json").write_text(json.dumps(skin(
            "a1b2c3d4e5f60718", "alice/skins", "https://raw.githubusercontent.com/alice/skins/HEAD/a.deltaskin")))
        (skins / "b.json").write_text(json.dumps(skin(
            "b1b2c3d4e5f60718", "bob/skins", "https://raw.githubusercontent.com/bob/skins/HEAD/b.deltaskin")))
        out = tmp_path / "catalog.json"
        monkeypatch.setattr(bc, "fetch_release_download_counts", lambda: {})
        monkeypatch.setattr(sys, "argv", ["build_catalog.py", "--skins-dir", str(tmp_path / "skins"),
                                          "--output", str(out), "--health-file", str(tmp_path / "h.json")])
        bc.main()
        catalog = json.loads(out.read_text())
        assert [s["id"] for s in catalog["skins"]] == ["b1b2c3d4e5f60718"]
        assert catalog["totalSkins"] == 1


# ---------------------------------------------------------------------------
# author pages
# ---------------------------------------------------------------------------

class TestAuthorPages:
    def test_page_removed_when_author_has_no_skins_left(self, tmp_path, monkeypatch):
        import generate_author_pages as gap
        authors = tmp_path / "authors"
        authors.mkdir()
        catalog = tmp_path / "catalog.json"
        two = [{"id": f"{i:016x}", "name": f"S{i}", "author": "bob", "systems": ["gba"],
                "downloadURL": f"https://example.com/{i}.deltaskin", "source": "bob/skins"} for i in range(2)]
        catalog.write_text(json.dumps({"skins": two}))
        (authors / "alice.html").write_text("stale")       # alice was opted out, no skins left
        (authors / "solo.html").write_text("stale")        # fewer than 2 skins now
        monkeypatch.setattr(gap, "CATALOG_PATH", catalog)
        monkeypatch.setattr(gap, "AUTHORS_DIR", authors)
        gap.main()
        names = sorted(p.name for p in authors.iterdir())
        assert names == ["bob.html", "index.html"]
