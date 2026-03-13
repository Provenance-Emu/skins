"""Tests for process_submission.py — URL type detection and entry building."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

import pytest
from process_submission import detect_url_type, build_entry


class TestDetectUrlType:
    def test_deltaskin_direct(self):
        assert detect_url_type("https://example.com/MySkin.deltaskin") == "skin_file"

    def test_manicskin_direct(self):
        assert detect_url_type("https://example.com/MySkin.manicskin") == "skin_file"

    def test_deltaskin_case_insensitive(self):
        assert detect_url_type("https://example.com/MySkin.DELTASKIN") == "skin_file"

    def test_raw_github_skin(self):
        assert detect_url_type(
            "https://raw.githubusercontent.com/user/repo/main/Skin.deltaskin"
        ) == "skin_file"

    def test_github_repo(self):
        assert detect_url_type("https://github.com/user/repo") == "github_repo"
        assert detect_url_type("https://github.com/user/repo/") == "github_repo"

    def test_github_release(self):
        assert detect_url_type("https://github.com/user/repo/releases") == "github_release"
        assert detect_url_type("https://github.com/user/repo/releases/tag/v1.0") == "github_release"

    def test_json_metadata(self):
        assert detect_url_type("https://example.com/skins.json") == "json_metadata"

    def test_unknown(self):
        assert detect_url_type("https://example.com/downloads/") == "unknown"


class TestBuildEntry:
    def _meta(self, url, info=None, type="skin_file"):
        return {"type": type, "url": url, "info": info}

    def test_uses_info_json_name(self):
        info = {"name": "Cool Skin", "gameTypeIdentifier": "com.rileytestut.delta.game.gba"}
        meta = self._meta("https://github.com/user/repo/raw/main/Cool.deltaskin", info)
        entry = build_entry(meta, meta["url"])
        assert entry["name"] == "Cool Skin"

    def test_falls_back_to_filename(self):
        meta = self._meta("https://example.com/MyCoolSkin.deltaskin", info=None)
        entry = build_entry(meta, meta["url"])
        assert entry["name"] == "MyCoolSkin"

    def test_maps_gti_to_system(self):
        info = {"name": "x", "gameTypeIdentifier": "com.rileytestut.delta.game.gba"}
        meta = self._meta("https://example.com/x.deltaskin", info)
        entry = build_entry(meta, meta["url"])
        assert entry["systems"] == ["gba"]

    def test_unknown_gti_becomes_unofficial(self):
        info = {"name": "x", "gameTypeIdentifier": "com.unknown.game.xyz"}
        meta = self._meta("https://example.com/x.deltaskin", info)
        entry = build_entry(meta, meta["url"])
        assert entry["systems"] == ["unofficial"]

    def test_no_info_becomes_unofficial(self):
        meta = self._meta("https://example.com/x.deltaskin", info=None)
        entry = build_entry(meta, meta["url"])
        assert entry["systems"] == ["unofficial"]

    def test_github_source_extracted(self):
        url = "https://raw.githubusercontent.com/myuser/myskins/main/Skin.deltaskin"
        meta = self._meta(url, info={"name": "x"})
        entry = build_entry(meta, url)
        assert entry["source"] == "myuser/myskins"

    def test_non_github_source_is_manual(self):
        url = "https://example.com/Skin.deltaskin"
        meta = self._meta(url, info={"name": "x"})
        entry = build_entry(meta, url)
        assert entry["source"] == "manual"

    def test_id_is_16_hex(self):
        meta = self._meta("https://example.com/S.deltaskin", info={"name": "x"})
        entry = build_entry(meta, meta["url"])
        assert len(entry["id"]) == 16
        assert all(c in "0123456789abcdef" for c in entry["id"])

    def test_download_url_preserved(self):
        url = "https://example.com/Skin.deltaskin"
        meta = self._meta(url, info={"name": "x"})
        entry = build_entry(meta, url)
        assert entry["downloadURL"] == url
