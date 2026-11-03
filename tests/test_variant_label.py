"""Tests for `variantLabel`: parsing, validation, the backfill, and the scripts that set it.

`derive_variant_label` / `strip_variant_suffix` are a port of the website's
`variantLabel()` / `stripVariantSuffix()` (docs/js/browse.js); the cases below
are the same ones the JS handles. Network access is mocked.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

import pytest
import backfill_variant_labels as bvl
import crawl_sources as cs
import repack_skins as rp
from build_catalog import check_for_issues
from skin_schema import (
    CATALOG_VERSION, MAX_VARIANT_LABEL_LENGTH, derive_variant_label, fit_variant_label,
    strip_variant_suffix, validate_entry,
)
from .test_crawl_deltastyles import _skin, scrape  # noqa: F401  (fixture)
from .test_link_health import PARENT, make_zip, skin_zip


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------

class TestStripVariantSuffix:
    @pytest.mark.parametrize("name, expected", [
        ("Atari Jaguar Paw — Doom", "Atari Jaguar Paw"),
        ("Atari Jaguar Paw - Doom", "Atari Jaguar Paw"),
        ("Atari Jaguar Paw", "Atari Jaguar Paw"),
        ("", ""),
        # An em dash wins over a hyphen, even when the hyphen comes first.
        ("lilPad - Little Sound Dj (LSDj) Skin — lilpad gbc", "lilPad - Little Sound Dj (LSDj) Skin"),
        # A separator at index 0 is not a suffix.
        (" — Leading", " — Leading"),
        ("Hyphen-without-spaces", "Hyphen-without-spaces"),
    ])
    def test_cases(self, name, expected):
        assert strip_variant_suffix(name) == expected


class TestDeriveVariantLabel:
    @pytest.mark.parametrize("name, base, expected", [
        ("Atari Jaguar Paw — Doom", "Atari Jaguar Paw", "Doom"),
        ("Atari Jaguar Paw - Doom", "Atari Jaguar Paw", "Doom"),
        # Only the first separator splits.
        ("A — B — C", "A", "B — C"),
        # Em dash is tried before hyphen.
        ("lilPad - LSDj — lilpad v1-1", "lilPad - LSDj", "lilpad v1-1"),
        # No separator: the base name comes off the front, case-insensitively.
        ("Matte GBA Red", "matte gba", "Red"),
        ("HZN-nds-dark-sceenswap", "HZN-nds", "dark-sceenswap"),
        ("Foo: Bar", "Foo", "Bar"),
        # Nothing derivable: the UI shows the full name.
        ("Cyberdeck", "Cyberdeck", None),
        ("Idle SNES Left", "Cyberdeck", None),
        ("Anything", "", None),
        ("", "Base", None),
        ("Name — ", "Name", None),
    ])
    def test_cases(self, name, base, expected):
        assert derive_variant_label(name, base) == expected

    def test_fit_trims_and_caps(self):
        assert fit_variant_label("  Doom ") == "Doom"
        assert fit_variant_label("   ") is None
        assert fit_variant_label(None) is None
        assert len(fit_variant_label("x" * 500)) == MAX_VARIANT_LABEL_LENGTH


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def entry(**extra):
    return {
        "id": "0123456789abcdef", "name": "Example", "systems": ["gba"],
        "downloadURL": "https://example.com/a.deltaskin", "source": "manual", **extra,
    }


class TestValidateVariantLabel:
    def test_catalog_version_bumped(self):
        assert CATALOG_VERSION >= 3

    def test_unset_and_null_are_valid(self):
        assert validate_entry(entry()) == []
        assert validate_entry(entry(variantLabel=None)) == []

    def test_label_with_group_is_valid(self):
        assert validate_entry(entry(groupId="g", groupOrder=1, variantLabel="Doom")) == []

    @pytest.mark.parametrize("label, fragment", [
        (5, "must be a string"),
        ("", "must not be empty"),
        ("   ", "must not be empty"),
        (" Doom", "whitespace"),
        ("Doom ", "whitespace"),
        ("x" * (MAX_VARIANT_LABEL_LENGTH + 1), "longer than"),
    ])
    def test_bad_labels(self, label, fragment):
        errors = validate_entry(entry(groupId="g", variantLabel=label))
        assert any(fragment in e for e in errors), errors

    def test_label_needs_a_group(self):
        errors = validate_entry(entry(variantLabel="Doom"))
        assert errors == ["variantLabel requires groupId"]

    def test_build_check_reports_it(self, capsys):
        bad = {**entry(variantLabel="Doom"), "_source_file": "skins/gba/x.json"}
        assert check_for_issues([bad]) == 1
        assert "variantLabel requires groupId" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# Backfill
# ---------------------------------------------------------------------------

def write(skins_dir: Path, slug: str, **fields) -> Path:
    data = {"id": slug.ljust(16, "0")[:16], "name": slug, "systems": ["jaguar"],
            "downloadURL": f"https://example.com/{slug}.manicskin", "source": "manual", **fields}
    path = skins_dir / "jaguar" / f"{slug}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return path


def read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


class TestBackfill:
    def test_labels_group_members(self, tmp_path):
        a = write(tmp_path, "a", name="Jaguar Paw — Doom", groupId="g", groupOrder=1)
        b = write(tmp_path, "b", name="Jaguar Paw — Alien vs Predator", groupId="g", groupOrder=2)
        stats = bvl.backfill(tmp_path)
        assert read(a)["variantLabel"] == "Doom"
        assert read(b)["variantLabel"] == "Alien vs Predator"
        assert stats["written"] == 2 and stats["grouped"] == 2 and stats["unlabeled"] == 0

    def test_base_name_comes_from_lowest_group_order(self, tmp_path):
        # File order (b before a) and name order must not matter, only groupOrder.
        a = write(tmp_path, "a", name="Matte GBA", groupId="g", groupOrder=1)
        b = write(tmp_path, "b", name="Matte GBA Emerald", groupId="g", groupOrder=2)
        bvl.backfill(tmp_path)
        assert "variantLabel" not in read(a)
        assert read(b)["variantLabel"] == "Emerald"

    def test_leaves_ungrouped_and_underivable_alone(self, tmp_path):
        solo = write(tmp_path, "solo", name="Solo — Thing")
        odd = write(tmp_path, "odd", name="Unrelated", groupId="g", groupOrder=2)
        first = write(tmp_path, "first", name="Cyberdeck", groupId="g", groupOrder=1)
        before = {p: p.read_text() for p in (solo, odd, first)}
        stats = bvl.backfill(tmp_path)
        assert {p: p.read_text() for p in before} == before
        assert stats["written"] == 0 and stats["unlabeled"] == 2

    def test_keeps_a_hand_set_label_unless_overwriting(self, tmp_path):
        a = write(tmp_path, "a", name="Pack — Doom", groupId="g", groupOrder=1, variantLabel="Doom 1")
        bvl.backfill(tmp_path)
        assert read(a)["variantLabel"] == "Doom 1"
        bvl.backfill(tmp_path, overwrite=True)
        assert read(a)["variantLabel"] == "Doom"

    def test_idempotent(self, tmp_path):
        write(tmp_path, "a", name="Pack — Doom", groupId="g", groupOrder=1)
        assert bvl.backfill(tmp_path)["written"] == 1
        snapshot = {p: p.read_text() for p in tmp_path.rglob("*.json")}
        assert bvl.backfill(tmp_path)["written"] == 0
        assert {p: p.read_text() for p in tmp_path.rglob("*.json")} == snapshot

    def test_dry_run_writes_nothing(self, tmp_path):
        a = write(tmp_path, "a", name="Pack — Doom", groupId="g", groupOrder=1)
        before = a.read_text()
        assert bvl.backfill(tmp_path, dry_run=True)["written"] == 1
        assert a.read_text() == before

    def test_keeps_file_formatting_and_key_order(self, tmp_path):
        path = write(tmp_path, "a", name="Pokédex — Gen 3", groupId="g", groupOrder=1, tags=["x"])
        # Same file saved with raw (non-ASCII) characters, as many catalog files are.
        data = read(path)
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        bvl.backfill(tmp_path)
        text = path.read_text(encoding="utf-8")
        assert "Pokédex" in text and "\\u" not in text
        keys = list(json.loads(text))
        assert keys.index("variantLabel") == keys.index("groupOrder") + 1
        assert text.endswith("}\n")

    def test_backfilled_entries_validate(self, tmp_path):
        paths = [
            write(tmp_path, "a", name="Pack — Doom", groupId="g", groupOrder=1),
            write(tmp_path, "b", name="Pack — Wolf3D", groupId="g", groupOrder=2),
        ]
        bvl.backfill(tmp_path)
        assert all(validate_entry(read(p)) == [] for p in paths)

    def test_catalog_has_no_unlabeled_derivable_entries(self):
        """The committed skins are fully backfilled: re-running changes nothing."""
        assert bvl.plan_labels(bvl.load_entries(bvl.SKINS_DIR)) == {}


# ---------------------------------------------------------------------------
# Scripts that set groupId also set variantLabel
# ---------------------------------------------------------------------------

class TestCrawlerSetsLabel:
    def test_grouped_variants_get_their_label(self, scrape):  # noqa: F811
        path = "/skins/764-turbopocket-16"
        urls = [
            "https://deltastyles.com/files/skins/764/turbopocket16.manicskin",
            "https://deltastyles.com/files/skins/764/pocketengine.manicskin",
        ]
        entries = scrape(
            [_skin(path, "TurboPocket-16")],
            {path: [{"downloadURL": u, "label": u.rsplit("/", 1)[1][:-10]} for u in urls]},
            {u: {"gameTypeIdentifier": "public.aoshuang.game.pce"} for u in urls},
        )
        assert [e["groupId"] for e in entries] == ["deltastyles:764"] * 2
        assert [e["variantLabel"] for e in entries] == ["turbopocket16", "pocketengine"]
        assert all(validate_entry(e) == [] for e in entries)

    def test_single_variant_has_no_label(self, scrape):  # noqa: F811
        path = "/skins/760-gamecube-pocket"
        url = "https://deltastyles.com/files/skins/760/gamecubepocket.manicskin"
        [e] = scrape(
            [_skin(path, "GameCube Pocket")],
            {path: [{"downloadURL": url, "label": "gamecubepocket"}]},
            {url: {"gameTypeIdentifier": "public.aoshuang.game.ngc"}},
        )
        assert not e.get("groupId") and not e.get("variantLabel")


class TestRepackSetsLabel:
    def test_pack_members_get_labels(self):
        data = make_zip({
            "A.deltaskin": skin_zip(identifier="a", name="Big Pack Alpha"),
            "B.deltaskin": skin_zip(identifier="b", name="Beta"),
        })
        entries = rp.plan_entries(PARENT, rp.extract_skins(data))
        assert [e["variantLabel"] for e in entries] == ["Alpha", "Beta"]  # "Big Pack" stripped from the first
        assert all(validate_entry({k: v for k, v in e.items() if not k.startswith("_")}) == [] for e in entries)

    def test_duplicate_names_keep_labels_distinct(self):
        data = make_zip({
            "One/A.deltaskin": skin_zip(identifier="a", name="Same"),
            "Two/B.deltaskin": skin_zip(identifier="b", name="Same"),
        })
        entries = rp.plan_entries(PARENT, rp.extract_skins(data))
        assert len({e["variantLabel"] for e in entries}) == 2

    def test_single_skin_inherits_parent_label(self):
        parent = {**PARENT, "groupId": "g", "groupOrder": 2, "variantLabel": "Kept"}
        [e] = rp.plan_entries(parent, rp.extract_skins(make_zip({"Only.deltaskin": skin_zip()})))
        assert e["variantLabel"] == "Kept" and e["groupId"] == "g"
