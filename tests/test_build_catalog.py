"""Tests for build_catalog.py — loading, sorting, deduplication, output."""

import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

import pytest
from build_catalog import load_all_skins, build_catalog, check_for_issues


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
        assert catalog["version"] == 2
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
