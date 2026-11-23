"""Lines in the catalog build: top-level `lines`, member options, per-line files, --check-only."""

import copy
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

import pytest

import added_dates
import build_catalog as bc
import link_health
import skin_lines
from skin_schema import CATALOG_VERSION, make_id
from .test_skin_lines import RULES, strict_rules


def skin(n, name, label, group, order=0, source="A/b"):
    url = f"https://example.com/{n}.manicskin"
    return {"id": make_id(source, url), "name": name, "variantLabel": label, "groupId": group,
            "groupOrder": order, "source": source, "systems": ["mame"], "author": "A", "downloadURL": url,
            "thumbnailURL": f"https://example.com/{n}.png"}


def line_entries():
    return [skin(1, "Pad Dynamic Island - Red", "Red", "g1"),
            skin(2, "Pad Dynamic Island - Blue", "Blue", "g1", 1),
            skin(3, "Pad D-Pad - Red", "Red", "g2", 2)]


def built():
    entries = line_entries() + [skin(9, "Lone Skin", None, None, source="manual")]
    entries[-1].pop("variantLabel"), entries[-1].pop("groupId")
    lines, _ = skin_lines.assign(entries, [RULES])
    return bc.build_catalog(entries, lines)


def test_catalog_carries_lines_and_member_options():
    catalog = built()
    assert catalog["lines"][0]["id"] == "a-pad" and catalog["version"] == CATALOG_VERSION == 3
    members = [s for s in catalog["skins"] if s["name"].startswith("Pad")]
    assert len(members) == 3 and all(s["lineId"] == "a-pad" and "options" in s for s in members)
    lone = next(s for s in catalog["skins"] if s["name"] == "Lone Skin")
    assert "lineId" not in lone and "options" not in lone
    assert catalog["totalSkins"] == 4


def test_catalog_without_lines_has_no_lines_key():
    assert "lines" not in bc.build_catalog(line_entries())
    assert "lines" not in bc.build_browse_index(bc.build_catalog(line_entries()))


def test_browse_index_keeps_lines_and_options():
    catalog = built()
    index = bc.build_browse_index(catalog)
    assert index["lines"] == catalog["lines"]
    member = next(s for s in index["skins"] if s["name"] == "Pad D-Pad - Red")
    assert member["lineId"] == "a-pad" and member["options"]["stick"] == "dpad"


def test_line_files_written_and_stale_ones_removed(tmp_path):
    (tmp_path / "lines").mkdir()
    (tmp_path / "lines" / "gone.json").write_text("{}")
    paths = bc.write_line_files(built(), str(tmp_path))
    assert [Path(p).name for p in paths] == ["a-pad.json"]
    data = json.loads((tmp_path / "lines" / "a-pad.json").read_text())
    assert data["line"]["id"] == "a-pad"
    assert [m["name"] for m in data["members"]] == [
        "Pad Dynamic Island - Red", "Pad Dynamic Island - Blue", "Pad D-Pad - Red"]
    assert set(data["members"][0]) <= set(bc.LINE_MEMBER_FIELDS)
    assert data["members"][0]["options"]["colour"] == "red" and data["members"][0]["downloadURL"]
    assert not (tmp_path / "lines" / "gone.json").exists()


def test_no_lines_removes_every_line_file_and_creates_nothing(tmp_path):
    assert bc.write_line_files(bc.build_catalog(line_entries()), str(tmp_path)) == []
    assert not (tmp_path / "lines").exists()
    (tmp_path / "lines").mkdir()
    (tmp_path / "lines" / "old.json").write_text("{}")
    bc.write_line_files(bc.build_catalog(line_entries()), str(tmp_path))
    assert list((tmp_path / "lines").iterdir()) == []


# --- main() -----------------------------------------------------------------

@pytest.fixture
def repo(tmp_path, monkeypatch):
    """A scratch repo layout main() can build from, with the network and git stubbed."""
    skins = tmp_path / "skins" / "mame"
    skins.mkdir(parents=True)
    (tmp_path / "lines").mkdir()
    (tmp_path / "creators").mkdir()
    (tmp_path / "docs").mkdir()
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(bc, "fetch_release_download_counts", lambda *a, **k: {})
    monkeypatch.setattr(added_dates, "apply_added_dates",
                        lambda *a, **k: {"dated": 0, "looked_up": 0, "missing": 0, "unavailable": False})
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)

    def write(entries, rules=RULES, health=None):
        for old in skins.glob("*.json"):
            old.unlink()
        for e in entries:
            (skins / f"{e['id']}.json").write_text(json.dumps(e))
        (tmp_path / "lines" / "pad.json").write_text(json.dumps({"lines": [rules]}))
        (tmp_path / "link-health.json").write_text(json.dumps(health or {"skins": {}}))

    def run(*extra):
        root = Path(bc.__file__).parent.parent
        argv = ["build_catalog.py", "--output", "docs/catalog.json",
                "--badges-file", str(root / "badges.json"),
                "--disputed-file", str(tmp_path / "disputed.json"),
                "--variants-file", str(tmp_path / "variants.json"),
                "--health-file", "link-health.json", "--added-dates-file", "added-dates.json",
                "--count-holds-file", "count-holds.json", *extra]
        monkeypatch.setattr(sys, "argv", argv)
        try:
            bc.main()
        except SystemExit as e:
            return e.code or 0
        return 0

    (tmp_path / "disputed.json").write_text(Path(bc.__file__).parent.parent.joinpath("disputed.json").read_text())
    (tmp_path / "variants.json").write_text("{}\n")
    return tmp_path, write, run


def test_main_writes_lines_into_the_catalog_and_line_files(repo):
    tmp, write, run = repo
    write(line_entries())
    assert run() == 0
    catalog = json.loads((tmp / "docs" / "catalog.json").read_text())
    assert [line["id"] for line in catalog["lines"]] == ["a-pad"]
    assert all(s["lineId"] == "a-pad" for s in catalog["skins"])
    assert json.loads((tmp / "docs" / "catalog.min.json").read_text())["lines"][0]["layoutCount"] == 2
    assert (tmp / "docs" / "lines" / "a-pad.json").exists()
    # the skin files themselves are never rewritten with line fields
    assert all("lineId" not in json.loads(p.read_text()) for p in (tmp / "skins" / "mame").glob("*.json"))


def test_hidden_members_leave_the_line_before_it_is_counted(repo):
    tmp, write, run = repo
    entries = line_entries()
    gone = entries[2]                                   # the only member of family g2
    health = {"skins": {gone["id"]: {"url": gone["downloadURL"], "result": sorted(link_health.PERMANENT)[0],
                                     "failures": link_health.HIDE_AFTER}}}
    write(entries, health=health)
    assert run() == 0
    catalog = json.loads((tmp / "docs" / "catalog.json").read_text())
    assert len(catalog["skins"]) == 2
    assert "lines" not in catalog
    assert all("lineId" not in s for s in catalog["skins"])
    assert not (tmp / "docs" / "lines" / "a-pad.json").exists()


def test_line_survives_when_its_default_member_is_hidden(repo):
    tmp, write, run = repo
    entries = line_entries() + [skin(4, "Pad D-Pad - Blue", "Blue", "g2", 3)]
    rules = copy.deepcopy(RULES)
    rules["default"]["colour"] = "red"                  # default member = entries[0]
    write(entries, rules=rules)
    assert run() == 0
    first = json.loads((tmp / "docs" / "catalog.json").read_text())["lines"][0]["default"]
    assert first == {"device": "island", "stick": "joystick", "colour": "red"}
    write(entries[1:], rules=rules)                     # the default member is gone
    assert run() == 0
    line = json.loads((tmp / "docs" / "catalog.json").read_text())["lines"][0]
    assert line["memberCount"] == 3
    assert line["default"] == {"device": "island", "stick": "joystick", "colour": "blue"}


def test_broken_rules_file_does_not_stop_the_build(repo, capsys):
    tmp, write, run = repo
    write(line_entries())
    (tmp / "lines" / "pad.json").write_text("{not json")
    assert run() == 0
    catalog = json.loads((tmp / "docs" / "catalog.json").read_text())
    assert "lines" not in catalog and catalog["totalSkins"] == 3
    assert "Ignoring lines/" in capsys.readouterr().err


def test_check_only_fails_on_a_broken_rules_file(repo, capsys):
    tmp, write, run = repo
    write(line_entries())
    (tmp / "lines" / "pad.json").write_text("{not json")
    assert run("--check-only") == 1
    assert "pad.json" in capsys.readouterr().err


def test_check_only_fails_on_fallout_over_five_percent(repo, capsys):
    tmp, write, run = repo
    entries = [skin(i, f"Pad {'iPad' if i % 2 else 'Dynamic Island'} - C{i}", f"C{i}", f"g{i % 2}", i)
               for i in range(9)]
    entries.append(skin(99, "Pad Watch - Red", "Red", "g9", 99))     # no device value under strict rules
    write(entries, rules=strict_rules())
    assert run("--check-only") == 1
    err = capsys.readouterr().err
    assert "a-pad" in err and "Pad Watch - Red" in err


def test_check_only_passes_with_clean_rules_and_writes_nothing(repo):
    tmp, write, run = repo
    write(line_entries())
    assert run("--check-only") == 0
    assert not (tmp / "docs" / "catalog.json").exists()
