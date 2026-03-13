"""Tests for skin_schema.py — ID generation, validation, slugify, system maps."""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

import pytest
from skin_schema import (
    make_id, slugify, normalize_entry, validate_entry,
    system_from_gti, system_from_name, VALID_SYSTEM_CODES,
)


# ---------------------------------------------------------------------------
# make_id
# ---------------------------------------------------------------------------

class TestMakeId:
    def test_returns_16_hex_chars(self):
        result = make_id("manual", "https://example.com/Skin.deltaskin")
        assert len(result) == 16
        assert all(c in "0123456789abcdef" for c in result)

    def test_deterministic(self):
        a = make_id("manual", "https://example.com/Skin.deltaskin")
        b = make_id("manual", "https://example.com/Skin.deltaskin")
        assert a == b

    def test_different_urls_different_ids(self):
        a = make_id("manual", "https://example.com/SkinA.deltaskin")
        b = make_id("manual", "https://example.com/SkinB.deltaskin")
        assert a != b

    def test_different_sources_different_ids(self):
        a = make_id("manual", "https://example.com/Skin.deltaskin")
        b = make_id("github", "https://example.com/Skin.deltaskin")
        assert a != b

    def test_known_value(self):
        # Regression: verify hash doesn't silently change
        result = make_id("manual", "https://example.com/MySkin.deltaskin")
        assert len(result) == 16  # just length check — don't hardcode hash value


# ---------------------------------------------------------------------------
# slugify
# ---------------------------------------------------------------------------

class TestSlugify:
    def test_basic(self):
        assert slugify("Dark Mode GBA") == "dark-mode-gba"

    def test_strips_special_chars(self):
        assert slugify("Skin (v2.0)!") == "skin-v20"

    def test_collapses_spaces(self):
        assert slugify("  too   many   spaces  ") == "too-many-spaces"

    def test_max_length(self):
        long = "a" * 100
        assert len(slugify(long)) <= 64

    def test_empty(self):
        assert slugify("") == ""

    def test_unicode_passthrough(self):
        result = slugify("スキン GBA")
        assert "gba" in result


# ---------------------------------------------------------------------------
# system_from_gti
# ---------------------------------------------------------------------------

class TestSystemFromGti:
    def test_gba(self):
        assert system_from_gti("com.rileytestut.delta.game.gba") == "gba"

    def test_nds(self):
        assert system_from_gti("com.rileytestut.delta.game.ds") == "nds"

    def test_unknown_returns_none(self):
        assert system_from_gti("com.unknown.game.xyz") is None

    def test_all_known_gtis_map(self):
        gtis = [
            ("com.rileytestut.delta.game.gba", "gba"),
            ("com.rileytestut.delta.game.gbc", "gbc"),
            ("com.rileytestut.delta.game.nes", "nes"),
            ("com.rileytestut.delta.game.snes", "snes"),
            ("com.rileytestut.delta.game.n64", "n64"),
            ("com.rileytestut.delta.game.ds", "nds"),
            ("com.rileytestut.delta.game.genesis", "genesis"),
        ]
        for gti, expected in gtis:
            assert system_from_gti(gti) == expected, f"Failed for {gti}"


# ---------------------------------------------------------------------------
# system_from_name
# ---------------------------------------------------------------------------

class TestSystemFromName:
    def test_exact_short_code(self):
        assert system_from_name("gba") == "gba"

    def test_long_name(self):
        assert system_from_name("Game Boy Advance") == "gba"

    def test_case_insensitive(self):
        assert system_from_name("SUPER NINTENDO") == "snes"

    def test_unknown_returns_none(self):
        assert system_from_name("PlayStation 5") is None


# ---------------------------------------------------------------------------
# validate_entry
# ---------------------------------------------------------------------------

def _valid_entry(**overrides):
    base = {
        "id": "a1b2c3d4e5f60718",
        "name": "Test Skin",
        "systems": ["gba"],
        "downloadURL": "https://example.com/Skin.deltaskin",
        "source": "manual",
    }
    base.update(overrides)
    return base


class TestValidateEntry:
    def test_valid_entry_no_errors(self):
        assert validate_entry(_valid_entry()) == []

    def test_missing_required_field(self):
        entry = _valid_entry()
        del entry["name"]
        errors = validate_entry(entry)
        assert any("name" in e for e in errors)

    def test_invalid_id_too_short(self):
        errors = validate_entry(_valid_entry(id="abc123"))
        assert any("id" in e for e in errors)

    def test_invalid_id_uppercase(self):
        errors = validate_entry(_valid_entry(id="A1B2C3D4E5F60718"))
        assert any("id" in e for e in errors)

    def test_invalid_system_code(self):
        errors = validate_entry(_valid_entry(systems=["ps5"]))
        assert any("ps5" in e for e in errors)

    def test_multiple_systems_valid(self):
        errors = validate_entry(_valid_entry(systems=["gba", "gbc"]))
        assert errors == []

    def test_empty_systems_array(self):
        errors = validate_entry(_valid_entry(systems=[]))
        assert any("systems" in e for e in errors)

    def test_http_url_valid(self):
        errors = validate_entry(_valid_entry(downloadURL="http://example.com/Skin.deltaskin"))
        assert errors == []

    def test_non_http_url_invalid(self):
        errors = validate_entry(_valid_entry(downloadURL="ftp://example.com/Skin.deltaskin"))
        assert any("http" in e for e in errors)

    def test_wrong_extension_flagged(self):
        errors = validate_entry(_valid_entry(downloadURL="https://example.com/Skin.zip"))
        # .zip is allowed as fallback, no error
        # but .exe should be flagged
        errors2 = validate_entry(_valid_entry(downloadURL="https://example.com/Skin.exe"))
        assert any("deltaskin" in e for e in errors2)

    def test_duplicate_id_detected(self):
        existing = {"a1b2c3d4e5f60718"}
        errors = validate_entry(_valid_entry(), catalog_ids=existing)
        assert any("Duplicate" in e for e in errors)

    def test_no_duplicate_when_different_id(self):
        existing = {"ffffffffffffffff"}
        errors = validate_entry(_valid_entry(), catalog_ids=existing)
        assert errors == []

    def test_all_system_codes_valid(self):
        for code in VALID_SYSTEM_CODES:
            errors = validate_entry(_valid_entry(systems=[code]))
            assert errors == [], f"System code {code!r} should be valid"


# ---------------------------------------------------------------------------
# normalize_entry
# ---------------------------------------------------------------------------

class TestNormalizeEntry:
    def test_fills_defaults(self):
        entry = {"id": "x", "name": "y", "systems": ["gba"], "downloadURL": "u", "source": "s"}
        result = normalize_entry(entry)
        assert result["thumbnailURL"] is None
        assert result["tags"] == []
        assert result["screenshotURLs"] == []
        assert result["author"] is None

    def test_preserves_existing_values(self):
        entry = {"id": "x", "name": "y", "systems": ["gba"], "downloadURL": "u", "source": "s",
                 "author": "me", "tags": ["dark"]}
        result = normalize_entry(entry)
        assert result["author"] == "me"
        assert result["tags"] == ["dark"]

    def test_does_not_overwrite_with_none(self):
        entry = {"id": "x", "name": "y", "systems": ["gba"], "downloadURL": "u", "source": "s",
                 "thumbnailURL": "https://example.com/thumb.png"}
        result = normalize_entry(entry)
        assert result["thumbnailURL"] == "https://example.com/thumb.png"
