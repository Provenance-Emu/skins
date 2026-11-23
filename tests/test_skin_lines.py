"""Skin lines: rules files, option assignment, fallout and validation."""

import copy
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

import skin_lines


def entry(sid, name, label, group, order=0, source="A/b"):
    return {
        "id": sid, "name": name, "variantLabel": label, "groupId": group, "groupOrder": order,
        "source": source, "systems": ["mame"], "author": "A",
        "downloadURL": f"https://example.com/{sid}.manicskin",
    }


RULES = {
    "id": "pad", "name": "Toy Pad", "creator": "a", "match": {"source": "A/b"},
    "axes": [
        {"id": "device", "label": "Device", "role": "device", "from": "name", "values": [
            {"id": "ipad", "label": "iPad", "tokens": ["iPad"], "device": {"idiom": "ipad"}},
            {"tokens": ["Tate"], "as": ["island", "notch"]},
            {"id": "island", "label": "Dynamic Island", "tokens": ["Dynamic Island"],
             "device": {"idiom": "iphone", "cutout": "island"}},
            {"id": "notch", "label": "Notch", "otherwise": True,
             "device": {"idiom": "iphone", "cutout": "notch"}},
        ]},
        {"id": "stick", "label": "Stick", "role": "choice", "from": "name", "values": [
            {"id": "dpad-only", "label": "D-pad only", "tokens": ["D-Pad Only"]},
            {"id": "dpad", "label": "D-pad", "tokens": ["D-Pad"]},
            {"id": "joystick", "label": "Joystick", "otherwise": True},
        ]},
        {"id": "colour", "label": "Colour", "role": "colour", "from": "variantLabel"},
    ],
    "default": {"device": "island", "stick": "joystick", "colour": "blue"},
}


def strict_rules():
    rules = copy.deepcopy(RULES)
    rules["axes"][0]["values"] = [v for v in rules["axes"][0]["values"]
                                  if not v.get("otherwise") and "as" not in v]
    return rules


def test_assigns_options_from_name_and_label():
    e = [entry("1", "Pad Dynamic Island - Red", "Red", "g1"),
         entry("2", "Pad D-Pad - Red", "Red", "g2")]
    lines, report = skin_lines.assign(e, [RULES])
    assert e[0]["lineId"] == "a-pad"
    assert e[0]["options"] == {"device": "island", "stick": "joystick", "colour": "red"}
    assert e[1]["options"] == {"device": "notch", "stick": "dpad", "colour": "red"}
    assert lines[0]["id"] == "a-pad" and lines[0]["name"] == "Toy Pad"
    assert lines[0]["creator"] == "a" and lines[0]["systems"] == ["mame"]
    assert lines[0]["memberCount"] == 2 and lines[0]["layoutCount"] == 2
    assert report["a-pad"]["candidates"] == 2 and report["a-pad"]["members"] == 2


def test_as_assigns_several_values():
    e = [entry("1", "Pad Tate - Red", "Red", "g1"), entry("2", "Pad iPad - Red", "Red", "g2")]
    skin_lines.assign(e, [RULES])
    assert e[0]["options"]["device"] == ["island", "notch"]


def test_earlier_rule_wins_over_contained_token():
    e = [entry("1", "Pad D-Pad Only - Red", "Red", "g1"), entry("2", "Pad iPad Tate - Red", "Red", "g2")]
    skin_lines.assign(e, [RULES])
    assert e[0]["options"]["stick"] == "dpad-only"
    assert e[1]["options"]["device"] == "ipad"


def test_tokens_match_whole_words_only():
    e = [entry("1", "Pad iPadish - Red", "Red", "g1"), entry("2", "Pad D-Pad - Red", "Red", "g2")]
    skin_lines.assign(e, [RULES])
    assert e[0]["options"]["device"] == "notch"


def test_colliding_entry_stays_out_and_is_reported():
    e = [entry("1", "Pad - Red", "Red", "g1"), entry("2", "Pad D-Pad - Red", "Red", "g2"),
         entry("3", "Pad Classic - Red", "Red", "g3")]
    lines, report = skin_lines.assign(e, [RULES])
    assert "lineId" not in e[2] and "options" not in e[2]
    assert report["a-pad"]["fallout"][0]["id"] == "3"
    assert "same options as 1" in report["a-pad"]["fallout"][0]["reason"]
    assert lines[0]["memberCount"] == 2


def test_axis_without_otherwise_drops_unmatched_entry():
    e = [entry("1", "Pad Dynamic Island - Red", "Red", "g1"), entry("2", "Pad iPad - Red", "Red", "g2"),
         entry("3", "Pad Watch - Red", "Red", "g3")]
    lines, report = skin_lines.assign(e, [strict_rules()])
    assert "lineId" not in e[2]
    assert report["a-pad"]["fallout"][0]["reason"] == "no value for device"


def test_line_with_one_family_is_not_emitted():
    e = [entry("1", "Pad - Red", "Red", "g1"), entry("2", "Pad - Blue", "Blue", "g1", 1)]
    lines, report = skin_lines.assign(e, [RULES])
    assert lines == [] and "lineId" not in e[0] and "options" not in e[1]
    assert report["a-pad"]["members"] == 0


def test_family_split_across_line_boundary_falls_out_whole():
    e = [entry("1", "Pad - Red", "Red", "g1"), entry("2", "Pad D-Pad - Red", "Red", "g2"),
         entry("3", "Pad iPad - Red", "Red", "g3"),
         entry("4", "Pad Classic - Red", "Red", "g3", 1)]      # collides with "1"; shares g3 with "3"
    lines, report = skin_lines.assign(e, [RULES])
    assert "lineId" not in e[2] and "lineId" not in e[3]
    reasons = {f["id"]: f["reason"] for f in report["a-pad"]["fallout"]}
    assert reasons["3"] == "family not wholly in line"
    assert lines[0]["memberCount"] == 2


def test_default_falls_back_when_default_member_is_absent():
    e = [entry("1", "Pad Dynamic Island - Red", "Red", "g1"), entry("2", "Pad D-Pad - Red", "Red", "g2", 1)]
    lines, _ = skin_lines.assign(e, [RULES])                   # RULES default wants colour blue
    assert lines[0]["default"] == {"device": "island", "stick": "joystick", "colour": "red"}


def test_default_kept_when_a_member_fits_it():
    e = [entry("1", "Pad Dynamic Island - Red", "Red", "g1"),
         entry("2", "Pad Dynamic Island - Blue", "Blue", "g1", 1),
         entry("3", "Pad D-Pad - Red", "Red", "g2", 2)]
    lines, _ = skin_lines.assign(e, [RULES])
    assert lines[0]["default"]["colour"] == "blue"


def test_stale_line_fields_are_cleared():
    e = [entry("1", "Other - Red", "Red", "g1", source="X/y")]
    e[0]["lineId"] = "old"
    e[0]["options"] = {"a": "b"}
    skin_lines.assign(e, [RULES])
    assert "lineId" not in e[0] and "options" not in e[0]


def test_record_axes_list_only_used_values_with_their_metadata():
    e = [entry("1", "Pad Dynamic Island - Red", "Red", "g1"), entry("2", "Pad D-Pad - Blue", "Blue", "g2", 1)]
    lines, _ = skin_lines.assign(e, [RULES])
    axes = {a["id"]: a for a in lines[0]["axes"]}
    assert [a["id"] for a in lines[0]["axes"]] == ["device", "stick", "colour"]
    assert [v["id"] for v in axes["device"]["values"]] == ["island", "notch"]
    assert axes["device"]["values"][0]["device"] == {"idiom": "iphone", "cutout": "island"}
    assert axes["device"]["role"] == "device" and "from" not in axes["device"]
    assert "tokens" not in axes["device"]["values"][0]
    assert axes["colour"]["values"] == [{"id": "red", "label": "Red"}, {"id": "blue", "label": "Blue"}]


def test_values_come_out_in_order_not_rule_order():
    rules = copy.deepcopy(RULES)
    stick = rules["axes"][1]["values"]
    stick[0]["order"], stick[1]["order"], stick[2]["order"] = 3, 2, 1
    e = [entry("1", "Pad D-Pad Only - Red", "Red", "g1"), entry("2", "Pad D-Pad - Red", "Red", "g2"),
         entry("3", "Pad - Red", "Red", "g3")]
    lines, _ = skin_lines.assign(e, [rules])
    stick_axis = [a for a in lines[0]["axes"] if a["id"] == "stick"][0]
    assert [v["id"] for v in stick_axis["values"]] == ["joystick", "dpad", "dpad-only"]
    assert "order" not in stick_axis["values"][0]


def test_name_prefix_limits_candidates():
    rules = copy.deepcopy(RULES)
    rules["match"]["namePrefix"] = "Pad"
    e = [entry("1", "Pad - Red", "Red", "g1"), entry("2", "Pad D-Pad - Red", "Red", "g2"),
         entry("3", "Other Thing - Red", "Red", "g3")]
    _, report = skin_lines.assign(e, [rules])
    assert report["a-pad"]["candidates"] == 2 and "lineId" not in e[2]


def test_source_match_ignores_case():
    e = [entry("1", "Pad - Red", "Red", "g1", source="a/B"), entry("2", "Pad D-Pad - Red", "Red", "g2", source="a/B")]
    lines, _ = skin_lines.assign(e, [RULES])
    assert lines and e[0]["lineId"] == "a-pad"


def test_option_values():
    assert skin_lines.option_values("a") == ["a"]
    assert skin_lines.option_values(["a", "b"]) == ["a", "b"]


def test_check_flags_fallout_over_five_percent():
    assert skin_lines.check({"a-pad": {"candidates": 100, "members": 94, "fallout": [{"id": "x", "name": "X", "reason": "r"}] * 6}})
    assert not skin_lines.check({"a-pad": {"candidates": 100, "members": 95, "fallout": [{}] * 5}})
    assert not skin_lines.check({"a-pad": {"candidates": 0, "members": 0, "fallout": []}})


def rules_dir(tmp_path):
    """tmp_path already holds conftest's blocklist.json; rules get their own folder."""
    d = tmp_path / "lines"
    d.mkdir()
    return d


def test_load_rules_reads_every_line(tmp_path):
    tmp_path = rules_dir(tmp_path)
    (tmp_path / "pad.json").write_text(json.dumps({"lines": [RULES]}))
    rules, problems = skin_lines.load_rules(str(tmp_path))
    assert problems == [] and [r["id"] for r in rules] == ["pad"]


def test_load_rules_missing_directory_is_empty(tmp_path):
    assert skin_lines.load_rules(str(tmp_path / "nope")) == ([], [])


def test_load_rules_reports_bad_files(tmp_path):
    tmp_path = rules_dir(tmp_path)
    (tmp_path / "broken.json").write_text("{not json")
    no_axes = {k: v for k, v in RULES.items() if k != "axes"}
    (tmp_path / "noaxes.json").write_text(json.dumps({"lines": [no_axes]}))
    bad_as = copy.deepcopy(RULES)
    bad_as["axes"][0]["values"][1]["as"] = ["island", "watch"]
    (tmp_path / "badas.json").write_text(json.dumps({"lines": [bad_as]}))
    bad_default = copy.deepcopy(RULES)
    bad_default["default"]["stick"] = "wheel"
    (tmp_path / "baddefault.json").write_text(json.dumps({"lines": [bad_default]}))
    rules, problems = skin_lines.load_rules(str(tmp_path))
    assert rules == []
    assert len(problems) == 4
    for name in ("broken.json", "noaxes.json", "badas.json", "baddefault.json"):
        assert any(name in p for p in problems), name


def test_load_rules_reports_duplicate_line_ids(tmp_path):
    tmp_path = rules_dir(tmp_path)
    (tmp_path / "one.json").write_text(json.dumps({"lines": [RULES]}))
    (tmp_path / "two.json").write_text(json.dumps({"lines": [RULES]}))
    rules, problems = skin_lines.load_rules(str(tmp_path))
    assert len(rules) == 1 and any("a-pad" in p for p in problems)
