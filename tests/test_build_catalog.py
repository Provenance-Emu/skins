"""Tests for build_catalog.py — loading, sorting, deduplication, output."""

import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

import pytest
import build_catalog as bc_module
from build_catalog import load_all_skins, build_catalog, check_for_issues
from skin_schema import CATALOG_VERSION


def write_skin(directory: str, system: str, filename: str, entry: dict):
    system_dir = os.path.join(directory, system)
    os.makedirs(system_dir, exist_ok=True)
    path = os.path.join(system_dir, filename)
    with open(path, "w") as f:
        json.dump(entry, f)
    return path


def valid_skin(id="a1b2c3d4e5f60718", name="Test Skin", system="gba",
               url="https://example.com/Skin.deltaskin"):
    return {
        "id": id,
        "name": name,
        "systems": [system],
        "downloadURL": url,
        "source": "manual",
    }


class TestLoadAllSkins:
    def test_loads_json_files(self):
        with tempfile.TemporaryDirectory() as d:
            write_skin(d, "gba", "skin1.json", valid_skin())
            skins = load_all_skins(d)
            assert len(skins) == 1

    def test_loads_multiple_systems(self):
        with tempfile.TemporaryDirectory() as d:
            write_skin(d, "gba", "s1.json", valid_skin(id="a" * 16, system="gba"))
            write_skin(d, "gbc", "s2.json", valid_skin(id="b" * 16, system="gbc", url="https://example.com/B.deltaskin"))
            skins = load_all_skins(d)
            assert len(skins) == 2

    def test_ignores_non_json(self):
        with tempfile.TemporaryDirectory() as d:
            os.makedirs(os.path.join(d, "gba"))
            with open(os.path.join(d, "gba", "readme.txt"), "w") as f:
                f.write("not json")
            write_skin(d, "gba", "skin.json", valid_skin())
            skins = load_all_skins(d)
            assert len(skins) == 1

    def test_source_file_recorded(self):
        with tempfile.TemporaryDirectory() as d:
            write_skin(d, "gba", "skin.json", valid_skin())
            skins = load_all_skins(d)
            assert "_source_file" in skins[0]

    def test_empty_directory(self):
        with tempfile.TemporaryDirectory() as d:
            skins = load_all_skins(d)
            assert skins == []


class TestBuildCatalog:
    def test_output_structure(self):
        skins = [valid_skin()]
        catalog = build_catalog(skins)
        assert catalog["version"] == CATALOG_VERSION
        assert "lastUpdated" in catalog
        assert catalog["totalSkins"] == 1
        assert len(catalog["skins"]) == 1

    def test_strips_internal_fields(self):
        skin = valid_skin()
        skin["_source_file"] = "/tmp/whatever.json"
        catalog = build_catalog([skin])
        assert "_source_file" not in catalog["skins"][0]

    def test_sorts_by_system_then_name(self):
        skins = [
            valid_skin(id="a" * 16, name="Zebra", system="gba", url="https://example.com/Z.deltaskin"),
            valid_skin(id="b" * 16, name="Alpha", system="gba", url="https://example.com/A.deltaskin"),
            valid_skin(id="c" * 16, name="First", system="gbc", url="https://example.com/F.deltaskin"),
        ]
        catalog = build_catalog(skins)
        names = [s["name"] for s in catalog["skins"]]
        assert names == ["Alpha", "Zebra", "First"]

    def test_zero_skins(self):
        catalog = build_catalog([])
        assert catalog["totalSkins"] == 0
        assert catalog["skins"] == []


class TestCheckForIssues:
    def test_valid_skins_no_errors(self):
        with tempfile.TemporaryDirectory() as d:
            write_skin(d, "gba", "s.json", valid_skin())
            skins = load_all_skins(d)
            errors = check_for_issues(skins)
            assert errors == 0

    def test_duplicate_id_detected(self):
        with tempfile.TemporaryDirectory() as d:
            write_skin(d, "gba", "s1.json", valid_skin(url="https://example.com/A.deltaskin"))
            write_skin(d, "gba", "s2.json", valid_skin(url="https://example.com/B.deltaskin"))
            skins = load_all_skins(d)
            errors = check_for_issues(skins)
            assert errors > 0

    def test_duplicate_url_detected(self):
        with tempfile.TemporaryDirectory() as d:
            write_skin(d, "gba", "s1.json", valid_skin(id="a" * 16))
            write_skin(d, "gba", "s2.json", valid_skin(id="b" * 16))  # same URL as s1
            skins = load_all_skins(d)
            errors = check_for_issues(skins)
            assert errors > 0

    def test_invalid_entry_counted(self):
        with tempfile.TemporaryDirectory() as d:
            bad = {"id": "tooshort", "name": "Bad", "systems": ["gba"],
                   "downloadURL": "https://x.com/s.deltaskin", "source": "manual"}
            write_skin(d, "gba", "bad.json", bad)
            skins = load_all_skins(d)
            errors = check_for_issues(skins)
            assert errors > 0


class TestThumbnailAssetPaging:
    """fetch_release_download_counts pages the release's assets (SkinKit#128)."""

    ASSETS_URL = "https://api.github.com/repos/o/r/releases/1/assets"

    def fake_get(self, total, calls):
        def get_json(url):
            calls.append(url)
            if url == bc_module.GITHUB_THUMBNAILS_API:
                return {"assets_url": self.ASSETS_URL, "assets": [{"name": "first.png", "download_count": 1}]}
            page = int(url.rsplit("page=", 1)[1])
            lo = (page - 1) * 100
            return [{"name": f"{i:016x}.png", "download_count": i} for i in range(lo, min(lo + 100, total))]
        return get_json

    def test_pages_past_the_first_hundred_and_the_thousand(self):
        calls = []
        assets = bc_module.fetch_release_assets(get_json=self.fake_get(2350, calls))
        assert len(assets) == 2350
        assert calls[-1].endswith("per_page=100&page=24")   # 23 full pages, then a short one

    def test_stops_on_an_empty_page_after_a_full_one(self):
        calls = []
        assert len(bc_module.fetch_release_assets(get_json=self.fake_get(200, calls))) == 200
        assert calls[-1].endswith("page=3")

    def test_release_without_assets_url_uses_embedded_assets(self):
        get = lambda url: {"assets": [{"name": "a.png", "download_count": 5}]}
        assert bc_module.fetch_release_assets(get_json=get) == [{"name": "a.png", "download_count": 5}]

    def test_counts_cover_every_page(self, monkeypatch):
        monkeypatch.setattr(bc_module, "_get_json", self.fake_get(1250, []))
        counts = bc_module.fetch_release_download_counts()
        assert len(counts) == 1250 and counts[f"{1249:016x}"] == 1249

    def test_error_gives_no_counts(self, monkeypatch):
        def boom(*a, **k):
            raise OSError("down")
        monkeypatch.setattr(bc_module, "fetch_release_assets", boom)
        assert bc_module.fetch_release_download_counts() == {}
