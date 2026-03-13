"""Tests for process_submission.py — URL type detection and entry building."""

import json
import io
import sys
import zipfile
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

import pytest
from process_submission import detect_url_type, process_skin_file


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_skin_zip(info: dict) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("info.json", json.dumps(info))
    return buf.getvalue()


SAMPLE_INFO = {
    "name": "Dark Mode GBA",
    "gameTypeIdentifier": "com.rileytestut.delta.game.gba",
}


# ---------------------------------------------------------------------------
# detect_url_type
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# process_skin_file (mocked HTTP)
# ---------------------------------------------------------------------------

class TestProcessSkinFile:
    def test_extracts_name_and_system(self):
        zip_bytes = make_skin_zip(SAMPLE_INFO)
        with patch("process_submission.stream_extract_info_json", return_value=SAMPLE_INFO):
            entries = process_skin_file("https://example.com/Skin.deltaskin")
        assert len(entries) == 1
        entry = entries[0]
        assert entry["name"] == "Dark Mode GBA"
        assert entry["systems"] == ["gba"]
        assert entry["gameTypeIdentifier"] == "com.rileytestut.delta.game.gba"

    def test_falls_back_to_filename_when_no_info(self):
        with patch("process_submission.stream_extract_info_json", return_value=None):
            entries = process_skin_file("https://example.com/MyCoolSkin.deltaskin")
        assert entries[0]["name"] == "MyCoolSkin"
        assert entries[0]["systems"] == ["unofficial"]

    def test_unknown_gti_becomes_unofficial(self):
        info = {"name": "x", "gameTypeIdentifier": "com.unknown.xyz"}
        with patch("process_submission.stream_extract_info_json", return_value=info):
            entries = process_skin_file("https://example.com/x.deltaskin")
        assert entries[0]["systems"] == ["unofficial"]

    def test_id_is_16_hex(self):
        with patch("process_submission.stream_extract_info_json", return_value=SAMPLE_INFO):
            entries = process_skin_file("https://example.com/Skin.deltaskin")
        entry = entries[0]
        assert len(entry["id"]) == 16
        assert all(c in "0123456789abcdef" for c in entry["id"])

    def test_download_url_preserved(self):
        url = "https://example.com/Skin.deltaskin"
        with patch("process_submission.stream_extract_info_json", return_value=SAMPLE_INFO):
            entries = process_skin_file(url)
        assert entries[0]["downloadURL"] == url

    def test_submitted_by_included(self):
        with patch("process_submission.stream_extract_info_json", return_value=SAMPLE_INFO):
            entries = process_skin_file(
                "https://example.com/Skin.deltaskin", submitted_by="testuser"
            )
        assert entries[0]["submittedBy"] == "testuser"

    def test_custom_source(self):
        with patch("process_submission.stream_extract_info_json", return_value=SAMPLE_INFO):
            entries = process_skin_file(
                "https://example.com/Skin.deltaskin", source="myrepo/skins"
            )
        assert entries[0]["source"] == "myrepo/skins"
