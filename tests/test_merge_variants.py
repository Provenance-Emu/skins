"""Tests for merge_variants.py: classification and archive building over the
families in fixtures/merge/ (expected.json written by hand in
generate_merge_fixtures.py), the sample split families, the catalog plan
(idempotence, removal, health) and the schema fields. No network access."""

import hashlib
import io
import json
import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

import pytest
import build_catalog as bc
import link_health as lh
import merge_variants as mv
import variants_sidecar as vs
from skin_schema import validate_entry, validate_merged_refs

ROOT = Path(__file__).parent.parent
MERGE_FIXTURES = ROOT / "fixtures" / "merge"
CASES = sorted(p.name for p in MERGE_FIXTURES.iterdir() if (p / "expected.json").exists())


def zip_folder(folder: Path) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for f in sorted(folder.iterdir()):
            z.writestr(f.name, f.read_bytes())
    return buf.getvalue()


def load_case(case: str):
    root = MERGE_FIXTURES / case
    family = json.loads((root / "family.json").read_text())
    expected = json.loads((root / "expected.json").read_text())
    archives = {m["entry"]["downloadURL"]: zip_folder(root / "members" / m["folder"]) for m in family["members"]}
    entries = [m["entry"] for m in family["members"]]
    return family["groupId"], entries, archives, expected


def members_of(case: str):
    _, entries, archives, expected = load_case(case)
    return [mv.read_member(e, archives[e["downloadURL"]]) for e in entries], expected


def healthy(entries) -> dict:
    return {"skins": {e["id"]: {"result": "ok", "url": e["downloadURL"]} for e in entries}}


# ---------------------------------------------------------------------------
# Shared fixtures: classification and the merged archive
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("case", CASES)
def test_fixture_outcome(case):
    members, expected = members_of(case)
    merge = mv.merge_family(members)
    assert merge.kind == expected["outcome"], merge.reason
    if "reason" in expected:
        assert expected["reason"] in merge.reason
    if merge.kind == "split":
        assert merge.info is None
        return
    names = sorted(zipfile.ZipFile(io.BytesIO(merge.archive())).namelist())
    assert names == sorted(["info.json", *expected["files"]])
    assert merge.info["name"] == expected["name"]
    if "identifier" in expected:
        assert merge.info["identifier"] == expected["identifier"]
    if "themes" in expected:
        assert [t["id"] for t in merge.info["themes"]] == expected["themes"]


@pytest.mark.parametrize("case", [c for c in CASES if json.loads(
    (MERGE_FIXTURES / c / "expected.json").read_text())["outcome"] != "split"])
def test_merged_archive_keeps_the_base_and_resolves_every_reference(case):
    members, _ = members_of(case)
    base = members[0]
    merge = mv.merge_family(members)
    data = merge.archive()
    zf = zipfile.ZipFile(io.BytesIO(data))
    info = json.loads(zf.read("info.json"))

    # Delta and Manic read only `representations`: the base's, with its own files, untouched.
    assert info["representations"] == base.info["representations"]
    for name, blob in base.files.items():
        assert zf.read(name) == blob
    assert info["identifier"] == base.info["identifier"] + ".allinone"
    assert info["gameTypeIdentifier"] == base.info["gameTypeIdentifier"]

    # The app's own checks pass, and every variant layout has its artwork.
    assert lh.classify_archive(zf)["result"] == "ok"
    files = zf.namelist()
    for label, assets, strict in lh._variant_layouts(info):
        assert lh._variant_has_artwork(files, assets, strict), label
    assert vs.compute_variants(info)

    # Byte-identical when built again.
    assert mv.merge_family(members_of(case)[0]).archive() == data


def test_themes_carry_each_members_background_bytes():
    members, _ = members_of("themes-three-colours")
    merge = mv.merge_family(members)
    for member, theme in zip(members[1:], merge.info["themes"]):
        assert theme["name"] == member.entry["variantLabel"]
        portrait = theme["assets"]["iphone"]["edgeToEdge"]["portrait"]
        assert merge.files[portrait["resizable"]] == member.files["bg-edge.png"]


def test_alt_rewrites_per_item_art_to_the_renamed_file():
    members, _ = members_of("per-item-art-two")
    merge = mv.merge_family(members)
    item = merge.info["altRepresentations"]["iphone"]["edgeToEdge"]["portrait"]["items"][1]
    assert item["asset"]["normal"] == "alt__btn-a.png"
    assert merge.files["alt__btn-a.png"] == members[1].files["btn-a.png"]
    base_item = merge.info["representations"]["iphone"]["edgeToEdge"]["portrait"]["items"][1]
    assert base_item["asset"]["normal"] == "btn-a.png"


def test_sample_split_families():
    """The published samples: the GBA colourways are themes; the Dreamcast and
    GameCube families differ in thumbstick art, so with three members they stay split."""
    outcomes = {}
    for family in sorted((ROOT / "fixtures" / "variants").glob("sample-split-family*")):
        paths = sorted(family.glob("*.*skin"))
        members = [mv.read_member({"id": f"{i:016x}", "name": p.stem, "downloadURL": str(p),
                                   "variantLabel": p.stem.rsplit("-", 1)[-1]}, p.read_bytes())
                   for i, p in enumerate(paths, 1)]
        outcomes[family.name] = mv.merge_family(members).kind
    assert outcomes == {"sample-split-family": "themes", "sample-split-family-dc": "split",
                        "sample-split-family-gc": "split"}


def test_family_name_matches_browse_js():
    assert mv.family_name({"name": "Pack — Red", "variantLabel": "Red"}) == "Pack"
    assert mv.family_name({"name": "Pack: Red", "variantLabel": "red"}) == "Pack"
    assert mv.family_name({"name": "Red", "variantLabel": "Red"}) == "Red"
    assert mv.family_name({"name": "Solo"}) == "Solo"


def test_theme_ids_are_unique_and_never_alt():
    members = [mv.Member({"id": "x", "variantLabel": label}, {}, {}, ".deltaskin")
               for label in ("Red", "Red", "alt", "")]
    ids = mv._theme_ids(members)
    assert len(set(ids)) == 4 and "alt" not in ids and all(ids)


# ---------------------------------------------------------------------------
# Catalog plan
# ---------------------------------------------------------------------------

class Fetcher:
    def __init__(self, archives):
        self.archives, self.calls = archives, []

    def __call__(self, url):
        self.calls.append(url)
        return self.archives[url]


def plan(case="themes-three-colours", existing=(), health=None, digest=lambda url: f"etag:{url}", entries=None,
         tmp="skins"):
    group, case_entries, archives, _ = load_case(case)
    entries = entries if entries is not None else case_entries
    fetch = Fetcher(archives)
    result = mv.plan_family(group, entries, list(existing), health or healthy(entries), fetch, digest, tmp)
    return result, fetch


def test_plan_builds_the_merged_entry():
    result, _ = plan()
    e = result.entry
    group, entries, _, _ = load_case("themes-three-colours")
    assert result.outcome == "themes"
    assert e["id"] == mv.merged_id(group) == mv.merged_id(group)
    assert e["groupId"] == group and e["groupOrder"] == 0 and e["variantLabel"] == "All variants"
    assert e["mergedFrom"] == [m["id"] for m in entries]
    assert e["downloadURL"] == mv.MIRROR_BASE + e["id"] + ".deltaskin"
    assert e["_file"] == f"skins/gba/merge-test-allinone-{e['id'][:6]}.json"
    assert e["name"] == "Merge Test — All variants"
    clean = {k: v for k, v in e.items() if not k.startswith("_")}
    assert validate_entry(clean) == []
    assert validate_merged_refs([*entries, clean]) == {}


def test_merged_entry_reads_back_as_the_family_name():
    # As the primary (groupOrder 0) it names the family on the site and in the apps.
    result, _ = plan()
    name = result.entry["name"]
    assert mv.family_name(result.entry) == "Merge Test"
    # SkinKit SkinVariantLabel.stripSuffix: everything before the last " — " / " - ".
    assert name.rsplit(" — ", 1)[0] == "Merge Test"


def _blocked_rule(source):
    return [{"match": source, "issue": 1, "verifiedBy": "x", "method": "owner", "date": "2026-11-02"}]


def test_merged_entry_is_hidden_with_an_opted_out_member():
    result, _ = plan()
    group, entries, _, _ = load_case("themes-three-colours")
    merged = {k: v for k, v in result.entry.items() if not k.startswith("_")}
    member = {**entries[2], "source": "alice/skins"}
    catalog = [entries[0], entries[1], member, merged]
    shown, hidden = bc.split_hidden(catalog, {"skins": {}}, opted_out=_blocked_rule("alice/skins"))
    assert {e["id"] for e in hidden} == {member["id"], merged["id"]}
    shown, hidden = bc.split_hidden(catalog, {"skins": {}}, opted_out=[])
    assert hidden == []


def test_merged_entry_is_hidden_with_a_broken_member():
    result, _ = plan()
    group, entries, _, _ = load_case("themes-three-colours")
    merged = {k: v for k, v in result.entry.items() if not k.startswith("_")}
    health = {"skins": {entries[1]["id"]: {"result": "http_404", "url": entries[1]["downloadURL"], "failures": 2}}}
    shown, hidden = bc.split_hidden([*entries, merged], health, opted_out=[])
    assert {e["id"] for e in hidden} == {entries[1]["id"], merged["id"]}


def test_unchanged_hash_skips_without_downloading():
    first, _ = plan()
    existing = {**{k: v for k, v in first.entry.items() if not k.startswith("_")}, "_source_file": first.entry["_file"]}
    second, fetch = plan(existing=[existing])
    assert second.outcome == "unchanged" and fetch.calls == []


def test_changed_archive_rebuilds_in_place():
    first, _ = plan()
    existing = {**{k: v for k, v in first.entry.items() if not k.startswith("_")}, "_source_file": first.entry["_file"]}
    second, fetch = plan(existing=[existing], digest=lambda url: f"etag:new:{url}")
    assert second.outcome == "themes" and second.entry["mergedHash"] != first.entry["mergedHash"]
    assert second.remove == [] and fetch.calls


def test_without_validators_the_bytes_are_hashed_once():
    result, fetch = plan(digest=lambda url: None)
    assert result.outcome == "themes"
    assert len(fetch.calls) == len(set(fetch.calls)) == 3


def test_family_below_two_visible_members_loses_its_merged_entry():
    group, entries, _, _ = load_case("themes-three-colours")
    health = healthy(entries)
    for e in entries[1:]:
        health["skins"][e["id"]] = {"result": "http_404", "url": e["downloadURL"], "failures": 2}
    existing = {"id": mv.merged_id(group), "mergedFrom": [e["id"] for e in entries], "groupId": group,
                "_source_file": "skins/gba/old.json"}
    result, fetch = plan(existing=[existing], health=health)
    assert result.outcome == "removed" and result.remove == ["skins/gba/old.json"] and fetch.calls == []


def test_unhealthy_member_keeps_the_existing_merge():
    group, entries, _, _ = load_case("themes-three-colours")
    health = healthy(entries)
    health["skins"][entries[1]["id"]] = {"result": "network_error", "url": entries[1]["downloadURL"]}
    result, fetch = plan(existing=[{"id": "x", "_source_file": "skins/gba/old.json"}], health=health)
    assert result.outcome == "skipped" and result.remove == [] and fetch.calls == []


def test_family_that_becomes_split_loses_its_merged_entry():
    result, _ = plan("per-item-art-three", existing=[{"id": "x", "_source_file": "skins/gba/old.json"}])
    assert result.outcome == "removed" and "per-item art" in result.reason
    assert result.remove == ["skins/gba/old.json"]


def test_oversized_merge_stays_split(monkeypatch):
    monkeypatch.setattr(mv, "MAX_MERGED_BYTES", 100)
    result, _ = plan(existing=[{"id": "x", "_source_file": "skins/gba/old.json"}])
    assert result.outcome == "removed" and "over" in result.reason and result.entry is None


def test_merged_entries_are_output_never_input():
    group, entries, _, _ = load_case("themes-three-colours")
    merged = {"id": mv.merged_id(group), "groupId": group, "groupOrder": 0, "mergedFrom": [e["id"] for e in entries]}
    originals, merged_by_group = mv.find_families([merged, *reversed(entries)])
    assert originals[group] == entries
    assert merged_by_group[group] == [merged]


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

BASE_ENTRY = {"id": "a" * 16, "name": "X", "systems": ["gba"], "source": "s", "groupId": "g",
              "downloadURL": "https://example.com/x.deltaskin"}


@pytest.mark.parametrize("fields,message", [
    ({"mergedFrom": ["b" * 16, "c" * 16]}, "go together"),
    ({"mergedHash": "0" * 64}, "go together"),
    ({"mergedFrom": ["b" * 16], "mergedHash": "0" * 64}, "at least two"),
    ({"mergedFrom": ["b" * 16, "b" * 16], "mergedHash": "0" * 64}, "at least two"),
    ({"mergedFrom": ["a" * 16, "b" * 16], "mergedHash": "0" * 64}, "itself"),
    ({"mergedFrom": ["nope", "b" * 16], "mergedHash": "0" * 64}, "array of skin ids"),
    ({"mergedFrom": ["b" * 16, "c" * 16], "mergedHash": "abc"}, "64 lowercase hex"),
    ({"mergedFrom": ["b" * 16, "c" * 16], "mergedHash": "0" * 64, "groupId": None}, "requires groupId"),
])
def test_schema_rejects_bad_merge_fields(fields, message):
    errors = validate_entry({**BASE_ENTRY, **fields})
    assert any(message in e for e in errors), errors


def test_merged_refs_must_exist_and_share_the_family():
    merged = {**BASE_ENTRY, "mergedFrom": ["b" * 16, "c" * 16, "d" * 16], "mergedHash": "0" * 64}
    entries = [merged, {"id": "b" * 16, "groupId": "g"}, {"id": "c" * 16, "groupId": "other"}]
    problems = validate_merged_refs(entries)[merged["id"]]
    assert any("another family" in p for p in problems)
    assert any("not in the catalog" in p for p in problems)


def test_check_for_issues_reports_bad_merged_refs(capsys):
    merged = {**BASE_ENTRY, "mergedFrom": ["b" * 16, "c" * 16], "mergedHash": "0" * 64}
    assert bc.check_for_issues([merged]) == 2
    assert "not in the catalog" in capsys.readouterr().out


def test_merged_hash_is_detail_only():
    assert "mergedHash" in bc.BROWSE_INDEX_DETAIL_FIELDS
    assert "mergedFrom" not in bc.BROWSE_INDEX_DETAIL_FIELDS


def test_merged_hash_covers_ids_urls_and_digests():
    a = [{"id": "1", "downloadURL": "u1"}, {"id": "2", "downloadURL": "u2"}]
    h = mv.merged_hash(a, ["d1", "d2"])
    assert h != mv.merged_hash(a, ["d1", "d3"])
    assert h != mv.merged_hash(list(reversed(a)), ["d2", "d1"])
    assert h != mv.merged_hash([a[0], {**a[1], "tags": ["mature"]}], ["d1", "d2"])
    assert h == hashlib.sha256(b"1\x00u1\x00d1\x000\n2\x00u2\x00d2\x000\n").hexdigest()


def test_a_mature_member_makes_the_merged_entry_mature():
    group, entries, _, _ = load_case("themes-three-colours")
    plain, _ = plan()
    assert "mature" not in plain.entry["tags"]
    tagged = [*entries[:2], {**entries[2], "tags": ["mature"]}]
    result, _ = plan(entries=tagged)
    assert result.outcome == "themes" and "mature" in result.entry["tags"]
    # An entry built before the member was tagged is rebuilt, not left "unchanged".
    existing = {**{k: v for k, v in plain.entry.items() if not k.startswith("_")},
                "_source_file": plain.entry["_file"]}
    again, _ = plan(entries=tagged, existing=[existing])
    assert again.outcome == "themes" and "mature" in again.entry["tags"]
