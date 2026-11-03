"""Tests for blocklist.py: URL parsing and entry matching (SkinKit#34)."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

import pytest
import blocklist as bl


def rule(match, **kw):
    return {"match": match, "issue": 1, "verifiedBy": "x", "method": "owner", "date": "2026-11-02", **kw}


# ---------------------------------------------------------------------------
# parse_owner_repo: every URL form in the catalog
# ---------------------------------------------------------------------------

class TestParseOwnerRepo:
    @pytest.mark.parametrize("url, expected", [
        # raw.githubusercontent.com/{o}/{r}/...
        ("https://raw.githubusercontent.com/Polyphian/deltaEmu/HEAD/skins/GBA/DepthsMini.deltaskin",
         "polyphian/deltaemu"),
        ("https://raw.githubusercontent.com/masonkoleh/deltaskins/HEAD/gba/skins/ngptest.deltaskin",
         "masonkoleh/deltaskins"),
        # github.com/{o}/{r}/raw/...
        ("https://github.com/delta-skins/delta-skins.github.io/raw/master/gba/Code002.deltaskin",
         "delta-skins/delta-skins.github.io"),
        # github.com/{o}/{r}/releases/...  (the poketGBA release asset, listed via DeltaStyles)
        ("https://github.com/NobiDevs/poketGBA/releases/download/v1.1/poketGBA_1.1.deltaskin",
         "nobidevs/poketgba"),
        ("https://github.com/NobiDevs/poketGBA/releases/tag/v1.1", "nobidevs/poketgba"),
        ("https://github.com/NobiDevs/poketGBA/releases", "nobidevs/poketgba"),
        # blob / tree / bare repo / .git / trailing slash / www
        ("https://github.com/o/r/blob/main/x.deltaskin", "o/r"),
        ("https://github.com/o/r/tree/main", "o/r"),
        ("https://github.com/o/r", "o/r"),
        ("https://github.com/o/r/", "o/r"),
        ("https://github.com/o/r.git", "o/r"),
        ("https://www.github.com/o/r", "o/r"),
        ("http://github.com/o/r", "o/r"),
        # dots and underscores in repo names, percent-encoded file names after the repo
        ("https://raw.githubusercontent.com/o/my.repo_x/main/a%20b.deltaskin", "o/my.repo_x"),
        # LFS media host
        ("https://media.githubusercontent.com/media/o/r/main/x.deltaskin", "o/r"),
        # case is folded
        ("https://GitHub.com/OWNER/Repo/raw/main/x.deltaskin", "owner/repo"),
    ])
    def test_forms(self, url, expected):
        assert bl.parse_owner_repo(url) == expected

    @pytest.mark.parametrize("url", [
        None, "", "not a url", "ftp://github.com/o/r",
        "https://deltastyles.com/files/skins/760/x.manicskin",
        "https://drive.google.com/uc?id=abc",
        "https://github.com/o",                       # no repo
        "https://github.com/orgs/foo/people",         # not a repo path
        "https://github.com/o/r/issues/1",            # not a file path we store
        "https://raw.githubusercontent.com/o/r",      # no ref
        "https://github.com/-bad/r",                  # invalid owner
        "https://github.com/o/../x/raw/y",
        "https://evilgithub.com/o/r/raw/x",
        "https://github.com.evil.example/o/r/raw/x",
    ])
    def test_rejects(self, url):
        assert bl.parse_owner_repo(url) is None

    def test_source_is_owner_repo_only(self):
        assert bl.parse_source("Polyphian/deltaEmu") == "polyphian/deltaemu"
        assert bl.parse_source("deltastyles.com") is None
        assert bl.parse_source("delta-skins.github.io") is None
        assert bl.parse_source("manual") is None
        assert bl.parse_source(None) is None

    def test_every_catalog_url_parses(self):
        """Every github URL stored in skins/ yields an owner/repo."""
        root = Path(__file__).parent.parent / "skins"
        misses = []
        for p in root.rglob("*.json"):
            d = json.loads(p.read_text())
            for key in ("downloadURL", "originalURL"):
                u = d.get(key) or ""
                if "github" in u and not bl.parse_owner_repo(u):
                    misses.append(u)
        assert misses == []


# ---------------------------------------------------------------------------
# is_blocked
# ---------------------------------------------------------------------------

class TestIsBlocked:
    def test_empty_blocklist_blocks_nothing(self):
        assert not bl.is_blocked({"source": "o/r", "downloadURL": "https://raw.githubusercontent.com/o/r/m/a.deltaskin"}, [])

    def test_matches_source(self):
        assert bl.is_blocked({"source": "Polyphian/deltaEmu", "downloadURL": "https://x.example/a.deltaskin"},
                             [rule("polyphian/deltaemu")])

    def test_matches_raw_download_url(self):
        e = {"source": "manual", "downloadURL": "https://raw.githubusercontent.com/o/r/HEAD/a.deltaskin"}
        assert bl.is_blocked(e, [rule("o/r")])

    def test_matches_github_raw_and_releases_urls(self):
        for url in ("https://github.com/o/r/raw/main/a.deltaskin",
                    "https://github.com/o/r/releases/download/v1/a.deltaskin"):
            assert bl.is_blocked({"source": "deltastyles.com", "downloadURL": url}, [rule("o/r")])

    def test_matches_original_url_for_mirror_rehost(self):
        e = {"source": "masonkoleh/deltaskins",
             "downloadURL": "https://github.com/Provenance-Emu/skins/releases/download/mirror/e8414f7825188181.deltaskin",
             "originalURL": "https://raw.githubusercontent.com/masonkoleh/deltaskins/HEAD/gba/skins/ngptest.deltaskin"}
        assert bl.is_blocked(e, [rule("masonkoleh/deltaskins")])
        # only originalURL carries the origin (source is a site)
        e["source"] = "deltastyles.com"
        assert bl.is_blocked(e, [rule("masonkoleh/deltaskins")])

    def test_aggregator_repo_blocks_only_via_download_url(self):
        e = {"source": "delta-skins.github.io",
             "downloadURL": "https://raw.githubusercontent.com/delta-skins/delta-skins.github.io/master/gba/x.deltaskin"}
        assert bl.is_blocked(e, [rule("delta-skins/delta-skins.github.io")])
        assert not bl.is_blocked(e, [rule("delta-skins/other")])

    def test_case_insensitive_both_ways(self):
        e = {"source": "POLYPHIAN/DELTAEMU", "downloadURL": "https://x.example/a.deltaskin"}
        assert bl.is_blocked(e, [rule("polyphian/deltaEmu")])
        assert bl.is_blocked(e, [rule("Polyphian/DeltaEmu")])

    def test_owner_wildcard(self):
        rules = [rule("someone/*")]
        assert bl.is_blocked({"source": "SomeOne/a", "downloadURL": "https://x.example/a.deltaskin"}, rules)
        assert bl.is_blocked({"source": "deltastyles.com",
                              "downloadURL": "https://github.com/someone/b/releases/download/v/a.deltaskin"}, rules)
        assert not bl.is_blocked({"source": "someone-else/a", "downloadURL": "https://x.example/a.deltaskin"}, rules)
        assert not bl.is_blocked({"source": "someoneelse/a", "downloadURL": "https://x.example/a.deltaskin"}, [rule("someone/*")])

    def test_exact_rule_does_not_match_sibling_or_prefix(self):
        e = {"source": "o/r2", "downloadURL": "https://x.example/a.deltaskin"}
        assert not bl.is_blocked(e, [rule("o/r")])

    def test_unrelated_hosts_never_match(self):
        e = {"source": "deltastyles.com", "downloadURL": "https://deltastyles.com/files/skins/1/a.deltaskin"}
        assert not bl.is_blocked(e, [rule("deltastyles/com"), rule("o/*")])

    def test_mirror_url_alone_never_matches_own_repo(self):
        """Mirror/thumbnail URLs live on Provenance-Emu/skins; they must not carry a block."""
        e = {"source": "deltastyles.com",
             "downloadURL": "https://github.com/Provenance-Emu/skins/releases/download/mirror/abc.deltaskin"}
        assert not bl.is_blocked(e, [rule("provenance-emu/skins")])
        assert not bl.is_blocked(e, [rule("provenance-emu/*")])

    def test_reads_blocklist_json_by_default(self, set_blocklist):
        set_blocklist([rule("o/r")])
        assert bl.is_blocked({"source": "o/r"})
        assert not bl.is_blocked({"source": "o/other"})

    def test_filter_blocked(self):
        entries = [{"source": "o/r"}, {"source": "p/q"}]
        assert bl.filter_blocked(entries, [rule("o/r")]) == [{"source": "p/q"}]

    def test_is_url_blocked(self):
        assert bl.is_url_blocked("https://github.com/O/R", [rule("o/r")])
        assert bl.is_url_blocked("https://github.com/o/r/releases/tag/v1", [rule("o/*")])
        assert not bl.is_url_blocked("https://example.com/a.deltaskin", [rule("o/*")])


# ---------------------------------------------------------------------------
# File handling
# ---------------------------------------------------------------------------

class TestFile:
    def test_one_entry_per_line_and_round_trip(self, tmp_path):
        p = tmp_path / "b.json"
        entries = [rule("a/b"), rule("c/*", method="org-member")]
        bl.save_blocklist(entries, p)
        lines = p.read_text().splitlines()
        assert lines[0] == "[" and lines[-1] == "]" and len(lines) == 4
        assert bl.load_blocklist(p) == entries
        # deleting a line and its comma is a valid undo
        p.write_text("[\n" + lines[1].rstrip(",") + "\n]\n")
        bl.clear_cache()
        assert [e["match"] for e in bl.load_blocklist(p)] == ["a/b"]

    def test_empty_file_is_empty_array(self, tmp_path):
        p = tmp_path / "b.json"
        bl.save_blocklist([], p)
        assert p.read_text() == "[]\n"

    def test_missing_file_is_empty(self, tmp_path):
        assert bl.load_blocklist(tmp_path / "nope.json") == []

    def test_invalid_json_raises_instead_of_allowing_everything(self, tmp_path):
        p = tmp_path / "b.json"
        p.write_text('[\n  {"match": "a/b"},\n]\n')  # trailing comma after a bad undo
        with pytest.raises(ValueError, match="not valid JSON"):
            bl.load_blocklist(p)

    @pytest.mark.parametrize("bad", ["", "owner", "*/*", "o/r/extra", "o/", "-o/r"])
    def test_rejects_bad_match(self, bad, tmp_path):
        p = tmp_path / "b.json"
        p.write_text(json.dumps([{"match": bad}]))
        with pytest.raises(ValueError):
            bl.load_blocklist(p)

    def test_cache_notices_edits(self, tmp_path):
        p = tmp_path / "b.json"
        bl.save_blocklist([rule("a/b")], p)
        assert len(bl.load_blocklist(p)) == 1
        p.write_text(json.dumps([rule("a/b"), rule("c/d")]))
        assert len(bl.load_blocklist(p)) == 2

    def test_shipped_blocklist_is_valid(self):
        root = Path(__file__).parent.parent / "blocklist.json"
        assert isinstance(bl.load_blocklist(root), list)
