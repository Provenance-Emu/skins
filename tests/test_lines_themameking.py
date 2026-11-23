"""lines/themameking-arcade.json against his 3,300 entries as the catalog last listed them
(commit f0c272d3; the set is opted out on main, so the names live in a fixture)."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

import skin_lines

ROOT = Path(__file__).parent.parent
FIXTURE = Path(__file__).parent / "fixtures" / "lines" / "themameking-entries.json"


def load():
    entries = json.loads(FIXTURE.read_text())
    rules, problems = skin_lines.load_rules(str(ROOT / "lines"))
    assert problems == []
    rules = [r for r in rules if skin_lines.catalog_id(r) == "themameking-arcade"]
    lines, report = skin_lines.assign(entries, rules)
    return entries, lines[0], report["themameking-arcade"]


def test_every_entry_joins_the_line():
    entries, line, report = load()
    assert report["candidates"] == 3300 and report["members"] == 3300 and report["fallout"] == []
    assert line["memberCount"] == 3300 and line["layoutCount"] == 150
    assert skin_lines.check({"themameking-arcade": report}) == []


def test_axes_and_value_counts():
    _, line, _ = load()
    assert [a["id"] for a in line["axes"]] == ["device", "game", "controls", "stick", "look", "hand", "colour"]
    sizes = {a["id"]: len(a["values"]) for a in line["axes"]}
    assert sizes == {"device": 3, "game": 2, "controls": 10, "stick": 2, "look": 4, "hand": 2, "colour": 22}


def test_values_are_in_display_order():
    _, line, _ = load()
    axes = {a["id"]: [v["id"] for v in a["values"]] for a in line["axes"]}
    assert axes["device"] == ["island", "notch", "ipad"]
    assert axes["controls"] == ["1-button", "2-button", "3-button", "3-button-wide", "4-button",
                                "5-button", "6-button", "twin-stick", "twin-stick-balanced", "dpad-only"]
    assert axes["hand"] == ["right", "left"]


def test_default_is_six_button_dynamic_island_nightfall():
    _, line, _ = load()
    assert line["default"] == {"device": "island", "game": "horizontal", "controls": "6-button",
                               "stick": "joystick", "look": "normal", "hand": "right",
                               "colour": "nightfall-purple"}


def test_known_names():
    entries, _, _ = load()
    by_name = {e["name"]: e["options"] for e in entries}
    o = by_name["Arcade Tate Twin Stick Balanced Left-Handed - Blackout"]
    assert o == {"device": ["island", "notch"], "game": "tate", "controls": "twin-stick-balanced",
                 "stick": "joystick", "look": "normal", "hand": "left", "colour": "blackout"}
    assert by_name["Arcade 6 Pro - Sakura"]["controls"] == "6-button"
    assert by_name["Arcade iPad Tate 4-Button - Emerald"]["device"] == "ipad"
    assert by_name["Arcade 4-Button Classic D-Pad Full Screen - Whiskey"]["controls"] == "4-button"
    assert by_name["Arcade Tate D-Pad Only - Gunmetal"]["controls"] == "dpad-only"
    assert by_name["Arcade iPad 3-Button Handheld D-Pad - Rose Gold"]["look"] == "handheld"


def test_a_layout_name_the_rules_do_not_know_stays_out_without_breaking_the_line():
    entries = json.loads(FIXTURE.read_text())
    entries.append({"id": "new1", "name": "Arcade 6-Button Dynamic Island - Brand New Colour",
                    "variantLabel": "Brand New Colour", "groupId": entries[0]["groupId"],
                    "groupOrder": 99999, "source": "TheMameKing/manic-emu-arcade-skins", "systems": ["mame"]})
    entries.append({"id": "new2", "name": "Arcade 8-Button Dynamic Island - Blackout",
                    "variantLabel": "Blackout", "groupId": "newgroup", "groupOrder": 99999,
                    "source": "TheMameKing/manic-emu-arcade-skins", "systems": ["mame"]})
    rules, _ = skin_lines.load_rules(str(ROOT / "lines"))
    lines, report = skin_lines.assign(entries, rules)
    r = report["themameking-arcade"]
    # A new colour simply becomes a value; a button count no rule names falls out, alone.
    assert next(e for e in entries if e["id"] == "new1")["options"]["colour"] == "brand-new-colour"
    assert [f["id"] for f in r["fallout"]] == ["new2"] and r["members"] == 3301
    assert skin_lines.check(report) == []
