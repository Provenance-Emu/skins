"""Tests for extract_metadata.py — ZIP streaming and info.json extraction."""

import io
import json
import struct
import sys
import zipfile
from pathlib import Path
from unittest.mock import patch, MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

import pytest
from extract_metadata import (
    stream_extract_info_json,
    _full_download_extract,
    _find_eocd,
    _find_cd_entry,
    _decompress_entry,
)


# ---------------------------------------------------------------------------
# Helpers — build real in-memory ZIPs for testing
# ---------------------------------------------------------------------------

def make_zip_bytes(files: dict[str, bytes]) -> bytes:
    """Create a ZIP archive in memory with the given filename→content mapping."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for name, content in files.items():
            zf.writestr(name, content)
    return buf.getvalue()


def make_skin_zip(info: dict, extra_files: dict = None) -> bytes:
    files = {"info.json": json.dumps(info).encode()}
    if extra_files:
        files.update(extra_files)
    return make_zip_bytes(files)


SAMPLE_INFO = {
    "name": "Dark Mode GBA",
    "identifier": "com.test.delta.gba.darkmode",
    "gameTypeIdentifier": "com.rileytestut.delta.game.gba",
    "debug": False,
}


# ---------------------------------------------------------------------------
# _find_eocd
# ---------------------------------------------------------------------------

class TestFindEocd:
    def test_finds_eocd_in_valid_zip(self):
        data = make_zip_bytes({"test.txt": b"hello"})
        pos = _find_eocd(data)
        assert data[pos:pos+4] == b"PK\x05\x06"

    def test_raises_on_non_zip(self):
        with pytest.raises(ValueError, match="EOCD"):
            _find_eocd(b"this is not a zip file at all")


# ---------------------------------------------------------------------------
# _find_cd_entry
# ---------------------------------------------------------------------------

class TestFindCdEntry:
    def _get_cd(self, zip_bytes: bytes):
        """Extract the central directory bytes from a ZIP."""
        # Parse EOCD
        eocd_pos = zip_bytes.rfind(b"PK\x05\x06")
        eocd = zip_bytes[eocd_pos:eocd_pos+22]
        (_, _, _, _, _, cd_size, cd_offset, _) = struct.unpack("<4sHHHHIIH", eocd)
        return zip_bytes[cd_offset:cd_offset+cd_size]

    def test_finds_info_json(self):
        data = make_skin_zip(SAMPLE_INFO, {"images/bg.png": b"\x89PNG"})
        cd = self._get_cd(data)
        entry = _find_cd_entry(cd, "info.json")
        assert entry is not None
        assert "lh_offset" in entry
        assert "comp_size" in entry

    def test_returns_none_when_not_found(self):
        data = make_zip_bytes({"other.txt": b"nope"})
        cd = self._get_cd(data)
        assert _find_cd_entry(cd, "info.json") is None

    def test_case_insensitive_on_dotslash(self):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("./Info.JSON", json.dumps(SAMPLE_INFO))
        data = buf.getvalue()
        cd = self._get_cd(data)
        entry = _find_cd_entry(cd, "info.json")
        assert entry is not None


# ---------------------------------------------------------------------------
# _decompress_entry
# ---------------------------------------------------------------------------

class TestDecompressEntry:
    def test_stored(self):
        payload = json.dumps({"name": "test"}).encode()
        result = _decompress_entry(payload, method=0, expected_size=len(payload))
        assert result == {"name": "test"}

    def test_deflated(self):
        import zlib
        payload = json.dumps({"name": "test"}).encode()
        compressed = zlib.compress(payload)[2:-4]  # strip zlib header/trailer → raw deflate
        result = _decompress_entry(compressed, method=8, expected_size=len(payload))
        assert result == {"name": "test"}

    def test_invalid_json_returns_none(self):
        result = _decompress_entry(b"not json", method=0, expected_size=8)
        assert result is None

    def test_unknown_compression_returns_none(self):
        result = _decompress_entry(b"data", method=99, expected_size=4)
        assert result is None


# ---------------------------------------------------------------------------
# _full_download_extract
# ---------------------------------------------------------------------------

class TestFullDownloadExtract:
    def test_extracts_info_json(self):
        zip_bytes = make_skin_zip(SAMPLE_INFO)
        with patch("extract_metadata._http_get", return_value=zip_bytes):
            result = _full_download_extract("https://example.com/skin.deltaskin")
        assert result == SAMPLE_INFO

    def test_returns_none_when_no_info_json(self):
        zip_bytes = make_zip_bytes({"other.txt": b"nope"})
        with patch("extract_metadata._http_get", return_value=zip_bytes):
            result = _full_download_extract("https://example.com/skin.deltaskin")
        assert result is None

    def test_returns_none_on_invalid_zip(self):
        with patch("extract_metadata._http_get", return_value=b"not a zip"):
            result = _full_download_extract("https://example.com/skin.deltaskin")
        assert result is None


# ---------------------------------------------------------------------------
# stream_extract_info_json (integration via mocked HTTP)
# ---------------------------------------------------------------------------

class TestStreamExtractInfoJson:
    def _mock_http(self, zip_bytes: bytes):
        """Set up mocks so range requests and HEAD work against zip_bytes."""
        file_size = len(zip_bytes)

        def fake_get_size(url, token=""):
            return file_size

        def fake_range_get(url, start, length, token=""):
            return zip_bytes[start:start+length]

        return fake_get_size, fake_range_get

    def test_extracts_via_range_requests(self):
        zip_bytes = make_skin_zip(SAMPLE_INFO)
        get_size, range_get = self._mock_http(zip_bytes)
        with patch("extract_metadata._get_file_size", get_size), \
             patch("extract_metadata._range_get", range_get):
            result = stream_extract_info_json("https://example.com/skin.deltaskin")
        assert result["name"] == SAMPLE_INFO["name"]
        assert result["gameTypeIdentifier"] == SAMPLE_INFO["gameTypeIdentifier"]

    def test_falls_back_to_full_download_when_no_range(self):
        zip_bytes = make_skin_zip(SAMPLE_INFO)
        with patch("extract_metadata._get_file_size", return_value=None), \
             patch("extract_metadata._http_get", return_value=zip_bytes):
            result = stream_extract_info_json("https://example.com/skin.deltaskin")
        assert result["name"] == SAMPLE_INFO["name"]

    def test_returns_none_when_no_info_json(self):
        zip_bytes = make_zip_bytes({"images/bg.png": b"\x89PNG"})
        get_size, range_get = self._mock_http(zip_bytes)
        with patch("extract_metadata._get_file_size", get_size), \
             patch("extract_metadata._range_get", range_get):
            result = stream_extract_info_json("https://example.com/skin.deltaskin")
        assert result is None

    def test_skin_with_many_files(self):
        """Skin with lots of image assets — CD won't all fit in a tiny tail."""
        extra = {f"images/frame_{i}.png": b"\x89PNG" * 100 for i in range(50)}
        zip_bytes = make_skin_zip(SAMPLE_INFO, extra)
        get_size, range_get = self._mock_http(zip_bytes)
        with patch("extract_metadata._get_file_size", get_size), \
             patch("extract_metadata._range_get", range_get):
            result = stream_extract_info_json("https://example.com/skin.deltaskin")
        assert result is not None
        assert result["name"] == SAMPLE_INFO["name"]
