"""Tests for the slim browse index (docs/catalog.min.json) that build_catalog.py writes."""

import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

from build_catalog import (
    BROWSE_INDEX_DETAIL_FIELDS,
    browse_index_entry,
    browse_index_path,
    build_browse_index,
    write_browse_index,
)

FULL_SKIN = {
    "id": "a1b2c3d4e5f60718",
    "name": "Test Skin",
    "author": "someone",
    "systems": ["gba"],
    "source": "manual",
    "downloadURL": "https://example.com/Skin.deltaskin",
    "thumbnailURL": "https://example.com/t.png",
    "downloadCount": 0,
    "tags": ["animated"],
    "version": "1.2",
    "fileSize": 12345,
    "screenshotURLs": ["https://example.com/s1.png"],
    "gameTypeIdentifier": "com.rileytestut.delta.game.gba",
    "rating": None,
    "submittedBy": None,
    "deviceSupport": [],
    "lastUpdated": None,
    "groupId": "g1",
    "groupOrder": 0,
}

CATALOG = {"version": 2, "lastUpdated": "2026-01-01T00:00:00Z", "totalSkins": 1, "skins": [FULL_SKIN]}


class TestBrowseIndexEntry:
    def test_drops_detail_only_fields(self):
        entry = browse_index_entry(FULL_SKIN)
        for field in BROWSE_INDEX_DETAIL_FIELDS:
            assert field not in entry

    def test_keeps_what_the_grid_reads(self):
        entry = browse_index_entry(FULL_SKIN)
        for field in ("id", "name", "author", "systems", "source", "tags",
                      "thumbnailURL", "downloadURL", "downloadCount", "groupId", "groupOrder"):
            assert entry[field] == FULL_SKIN[field]

    def test_drops_empty_values_but_keeps_zero(self):
        entry = browse_index_entry(FULL_SKIN)
        assert "deviceSupport" not in entry
        assert "lastUpdated" not in entry
        assert entry["downloadCount"] == 0
        assert entry["groupOrder"] == 0

    def test_unknown_new_field_passes_through(self):
        entry = browse_index_entry({**FULL_SKIN, "variantLabel": "Dark"})
        assert entry["variantLabel"] == "Dark"

    def test_key_order_is_stable(self):
        keys = list(browse_index_entry(FULL_SKIN))
        assert keys[:3] == ["id", "name", "author"]
        assert keys == list(browse_index_entry(dict(reversed(list(FULL_SKIN.items())))))

    def test_does_not_mutate_input(self):
        before = json.dumps(FULL_SKIN, sort_keys=True)
        browse_index_entry(FULL_SKIN)
        assert json.dumps(FULL_SKIN, sort_keys=True) == before


class TestBrowseIndex:
    def test_keeps_catalog_header_and_every_skin(self):
        index = build_browse_index(CATALOG)
        assert index["version"] == 2
        assert index["totalSkins"] == 1
        assert index["lastUpdated"] == "2026-01-01T00:00:00Z"
        assert [s["id"] for s in index["skins"]] == [FULL_SKIN["id"]]

    def test_catalog_itself_is_untouched(self):
        before = json.dumps(CATALOG, sort_keys=True)
        build_browse_index(CATALOG)
        assert json.dumps(CATALOG, sort_keys=True) == before

    def test_path_sits_next_to_catalog(self):
        assert browse_index_path("docs/catalog.json") == "docs/catalog.min.json"

    def test_write_is_compact_json(self, tmp_path):
        catalog_path = str(tmp_path / "catalog.json")
        out = Path(write_browse_index(CATALOG, catalog_path))
        assert out.name == "catalog.min.json"
        text = out.read_text()
        assert ": " not in text.split('"skins"')[0]
        assert json.loads(text)["skins"][0]["id"] == FULL_SKIN["id"]

    def test_index_only_flag_rewrites_from_existing_catalog(self, tmp_path):
        catalog_path = tmp_path / "catalog.json"
        catalog_path.write_text(json.dumps(CATALOG))
        script = Path(__file__).parent.parent / "scripts" / "build_catalog.py"
        subprocess.run([sys.executable, str(script), "--index-only", "--output", str(catalog_path)],
                       check=True, capture_output=True)
        index = json.loads((tmp_path / "catalog.min.json").read_text())
        assert "version" not in index["skins"][0]
        assert json.loads(catalog_path.read_text()) == CATALOG
