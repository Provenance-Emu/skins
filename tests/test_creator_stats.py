"""Creator stats and badges (compute_creator_stats.py), disputed.json, and the
thumbnail-count hygiene in build_catalog.py. Fixtures only; no network, and no
test reads the real disputed.json, badge-dates.json or creators.json."""

import copy
import json
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

import pytest
import build_catalog
import compute_creator_stats as ccs
import creator_directory as cd
import disputed as dp

REPO = Path(__file__).parent.parent
TODAY = "2026-11-05"
ID = iter(range(1, 100_000))


def skin(creator="ann", **extra):
    n = next(ID)
    return dict({
        "id": f"{n:016x}", "name": f"Skin {n}", "author": creator, "creator": creator,
        "systems": ["gba"], "source": "manual", "downloadURL": f"https://example.com/{n}.deltaskin",
        "tags": [], "downloadCount": None, "addedAt": "2026-10-01", "lastUpdated": None,
    }, **extra)


def family(creator, size, group="g1", **extra):
    return [skin(creator, groupId=group, groupOrder=i, **extra) for i in range(size)]


def record(slug, claimed=False):
    return {"slug": slug, "displayName": slug, "aliases": [slug], "claimed": claimed, "skinIds": []}


def stats_of(entries, **kw):
    return ccs.compute_stats(entries, **kw)[0]


def run(skins, records, disputed=(), dates=None, today=TODAY):
    """compute_all over a fixture catalog. Returns (directory, dates, report)."""
    defs = ccs.load_badges(str(REPO / "badges.json"))
    directory = {"version": 1, "updated": today, "creators": copy.deepcopy(records)}
    dates = {} if dates is None else dates
    report = ccs.compute_all({"skins": skins}, directory, defs, set(disputed), dates, today)
    return directory, dates, report


def badge_ids(directory, slug):
    return [b["id"] for r in directory["creators"] if r["slug"] == slug for b in r["badges"]]


# ---------------------------------------------------------------------------
# Counting rules
# ---------------------------------------------------------------------------

class TestCounting:
    def test_family_is_one_release_and_files_count_each_entry(self):
        entries = family("ann", 7) + [skin("ann")]
        s = stats_of(entries)
        assert (s["releases"], s["files"]) == (2, 8)

    def test_variants_completed_counts_family_members_and_single_file_variants(self):
        packed = skin("ann", variants=[{"kind": "alt", "key": "alt", "label": "Alternate layout"},
                                       {"kind": "theme", "key": "dark", "label": "Dark"}])
        entries = family("ann", 3) + family("ann", 1, group="solo") + [packed, skin("ann")]
        # 3 family members + 2 variants inside one file; the lone "family" of 1 and the plain skin add nothing.
        assert stats_of(entries)["variantsCompleted"] == 5

    def test_a_family_left_with_one_visible_member_completes_nothing(self):
        # build_catalog already dropped the hidden members; what is left is a family of one.
        assert stats_of(family("ann", 1))["variantsCompleted"] == 0
        assert stats_of(family("ann", 1))["releases"] == 1

    def test_systems_are_distinct_and_exclude_unofficial(self):
        entries = [skin("ann", systems=["gba"]), skin("ann", systems=["gba", "nes"]),
                   skin("ann", systems=["unofficial"])]
        assert stats_of(entries)["systems"] == 2

    def test_dual_screen_counts_entries_for_two_screen_systems(self):
        entries = [skin("ann", systems=["nds"]), skin("ann", systems=["threeDS"]), skin("ann")]
        assert stats_of(entries)["dualScreen"] == 2

    def test_dual_screen_set_matches_the_system_pages(self):
        import generate_system_pages
        assert ccs.DUAL_SCREEN_SYSTEMS == generate_system_pages.DUAL_SCREEN_SYSTEMS

    def test_dates(self):
        entries = [skin("ann", addedAt="2026-03-01", lastUpdated="2026-09-09"),
                   skin("ann", addedAt="2026-05-01"), skin("ann", addedAt=None, lastUpdated="2026-04-01")]
        s = stats_of(entries)
        assert s["firstAddedAt"] == "2026-03-01"      # addedAt, else lastUpdated: never a later update
        assert s["lastAddedAt"] == "2026-09-09"       # effective date: lastUpdated wins

    def test_no_dates_is_none(self):
        s = stats_of([skin("ann", addedAt=None)])
        assert s["firstAddedAt"] is None and s["lastAddedAt"] is None

    def test_empty_creator_is_all_zeros(self):
        s = stats_of([])
        assert s == {"releases": 0, "files": 0, "variantsCompleted": 0, "systems": 0, "dualScreen": 0,
                     "firstAddedAt": None, "lastAddedAt": None, "reachTier": 0}


class TestReach:
    @pytest.mark.parametrize("views,tier", [(0, 0), (999, 0), (1000, 1), (9999, 1), (10_000, 2),
                                            (99_999, 2), (100_000, 3), (10**7, 3)])
    def test_tiers(self, views, tier):
        assert ccs.reach_tier(views) == tier

    def test_tier_comes_from_the_sum_over_entries(self):
        entries = [skin("ann", downloadCount=600), skin("ann", downloadCount=600), skin("ann")]
        assert stats_of(entries)["reachTier"] == 1

    def test_the_raw_sum_is_not_published(self):
        entries = [skin("ann", downloadCount=1234)]
        stats, facts = ccs.compute_stats(entries)
        assert "1234" not in json.dumps(stats)
        directory, _, _ = run(entries, [record("ann")])
        assert "1234" not in json.dumps(directory)

    def test_junk_counts_are_ignored(self):
        entries = [skin("ann", downloadCount="5000"), skin("ann", downloadCount=-5), skin("ann", downloadCount=True)]
        assert stats_of(entries)["reachTier"] == 0


class TestWhatIsLeftOut:
    def test_sample_skins_do_not_count(self):
        d, _, report = run([skin("ann"), skin("ann", tags=["sample"])], [record("ann")])
        assert d["creators"][0]["stats"]["files"] == 1
        assert report["left_out"]["sample"] == 1

    def test_merged_all_variants_files_do_not_count(self):
        members = family("ann", 2)
        merged = skin("ann", groupId="g1", groupOrder=0, variantLabel="All variants",
                      mergedFrom=[m["id"] for m in members], mergedHash="x")
        s = stats_of([e for e in members + [merged] if ccs.countable(e)])
        assert (s["files"], s["releases"], s["variantsCompleted"]) == (2, 1, 2)

    def test_disputed_entries_do_not_count(self):
        a, b = skin("ann"), skin("ann", systems=["nes"])
        d, _, report = run([a, b], [record("ann")], disputed={b["id"]})
        s = d["creators"][0]["stats"]
        assert (s["files"], s["systems"]) == (1, 1)
        assert report["left_out"]["disputed"] == 1

    def test_disputing_one_member_can_shrink_a_family_below_two(self):
        fam = family("ann", 2)
        d, _, _ = run(fam, [record("ann")], disputed={fam[0]["id"]})
        assert d["creators"][0]["stats"]["variantsCompleted"] == 0

    def test_override_creator_decides_who_is_counted(self):
        """An entry whose `creator` was overridden counts for that creator only."""
        mine, theirs = skin("starvingartist"), skin("nostromocrew01", author="starvingartist")
        d, _, _ = run([mine, theirs], [record("starvingartist"), record("nostromocrew01")])
        by = {r["slug"]: r["stats"]["files"] for r in d["creators"]}
        assert by == {"starvingartist": 1, "nostromocrew01": 1}

    def test_every_record_gets_stats_and_badges_even_with_no_visible_skins(self):
        d, _, _ = run([], [record("nobody")])
        r = d["creators"][0]
        assert r["stats"]["releases"] == 0 and r["badges"] == []


# ---------------------------------------------------------------------------
# Badges
# ---------------------------------------------------------------------------

class TestBadgeRules:
    def earned(self, entries, claimed=False, today=TODAY):
        stats, facts = ccs.compute_stats(entries)
        return set(ccs.earned_ids(stats, facts, claimed, date.fromisoformat(today)))

    def test_first_release(self):
        assert "creator.first-release" in self.earned([skin("ann")])
        assert "creator.first-release" not in self.earned([])

    @pytest.mark.parametrize("n,expected", [
        (2, set()), (3, {3}), (4, {3}), (5, {3, 5}), (9, {3, 5}), (10, {3, 5, 10})])
    def test_systems_tiers(self, n, expected):
        entries = [skin("ann", systems=[f"sys{i}"]) for i in range(n)]
        got = {int(b.rsplit(".", 1)[1]) for b in self.earned(entries) if b.startswith("creator.systems.")}
        assert got == expected

    def test_family_builder_needs_three_in_one_family(self):
        assert "creator.family-builder" in self.earned(family("ann", 3))
        assert "creator.family-builder" not in self.earned(family("ann", 2) + family("ann", 2, group="g2"))

    def test_completionist_by_orientation_tags_across_a_family(self):
        fam = [skin("ann", groupId="g", tags=["portrait"]), skin("ann", groupId="g", tags=["landscape"])]
        assert "creator.completionist" in self.earned(fam)

    def test_completionist_needs_both_orientations_in_the_same_family(self):
        two = [skin("ann", groupId="a", tags=["portrait"]), skin("ann", groupId="b", tags=["landscape"])]
        assert "creator.completionist" not in self.earned(two)

    def test_completionist_by_two_variants_in_one_file(self):
        v = [{"kind": "alt", "key": "alt", "label": "Alternate layout"},
             {"kind": "theme", "key": "dark", "label": "Dark"}]
        assert "creator.completionist" in self.earned([skin("ann", variants=v)])
        assert "creator.completionist" not in self.earned([skin("ann", variants=v[:1])])

    def test_dual_screen(self):
        assert "creator.dual-screen" in self.earned([skin("ann", systems=["nds"])])
        assert "creator.dual-screen" not in self.earned([skin("ann")])

    def test_veteran_needs_a_year_of_first_added_and_a_visible_entry(self):
        old = [skin("ann", addedAt="2025-11-05")]
        assert "creator.veteran" in self.earned(old)
        assert "creator.veteran" not in self.earned([skin("ann", addedAt="2025-11-06")])
        assert "creator.veteran" not in self.earned([])

    def test_veteran_is_not_reset_by_a_recent_update(self):
        assert "creator.veteran" in self.earned([skin("ann", addedAt="2025-01-01", lastUpdated="2026-11-01")])

    def test_reach_badges_stack(self):
        got = self.earned([skin("ann", downloadCount=12_000)])
        assert {"creator.reach.1", "creator.reach.2"} <= got and "creator.reach.3" not in got

    def test_claimed(self):
        assert "creator.claimed" in self.earned([skin("ann")], claimed=True)
        assert "creator.claimed" not in self.earned([skin("ann")], claimed=False)


class TestPublishedBadges:
    def many(self):
        return [skin("ann", systems=["nds"], downloadCount=2000, addedAt="2024-01-01"),
                *family("ann", 3, systems=["gba"], tags=["portrait", "landscape"])]

    def test_unclaimed_publishes_only_first_release_and_systems(self):
        entries = [skin("ann", systems=[s], downloadCount=2000) for s in ("nds", "gba", "nes")]
        d, _, _ = run(entries, [record("ann", claimed=False)])
        assert badge_ids(d, "ann") == ["creator.first-release", "creator.systems.3"]

    def test_claimed_publishes_everything_earned(self):
        d, _, _ = run(self.many(), [record("ann", claimed=True)])
        got = badge_ids(d, "ann")
        assert {"creator.first-release", "creator.family-builder", "creator.completionist",
                "creator.dual-screen", "creator.veteran", "creator.reach.1", "creator.claimed"} <= set(got)

    def test_badges_carry_their_labels_from_badges_json(self):
        d, _, _ = run([skin("ann")], [record("ann")])
        (b,) = d["creators"][0]["badges"]
        assert b == {"id": "creator.first-release", "title": "First release",
                     "description": "Published a skin on EmuSkins.", "symbol": "sparkles", "earnedAt": TODAY}

    def test_tiered_badges_carry_tier_and_are_all_published(self):
        entries = [skin("ann", systems=[f"s{i}"]) for i in range(5)]
        d, _, _ = run(entries, [record("ann")])
        tiers = {b["id"]: b.get("tier") for b in d["creators"][0]["badges"]}
        assert tiers["creator.systems.3"] == 1 and tiers["creator.systems.5"] == 2

    def test_output_is_in_badges_json_order(self):
        d, _, _ = run(self.many(), [record("ann", claimed=True)])
        order = list(ccs.load_badges(str(REPO / "badges.json")))
        got = badge_ids(d, "ann")
        assert got == sorted(got, key=order.index)


class TestEarnedDates:
    def test_first_true_build_date_sticks_across_rebuilds(self):
        entries = [skin("ann")]
        _, dates, _ = run(entries, [record("ann")], today="2026-11-05")
        d, dates, _ = run(entries, [record("ann")], dates=dates, today="2026-12-25")
        assert d["creators"][0]["badges"][0]["earnedAt"] == "2026-11-05"

    def test_a_newly_earned_badge_gets_the_new_date(self):
        entries = [skin("ann", systems=["gba"]), skin("ann", systems=["nes"])]
        _, dates, _ = run(entries, [record("ann")], today="2026-11-05")
        entries.append(skin("ann", systems=["snes"]))
        d, _, _ = run(entries, [record("ann")], dates=dates, today="2026-12-25")
        got = {b["id"]: b["earnedAt"] for b in d["creators"][0]["badges"]}
        assert got == {"creator.first-release": "2026-11-05", "creator.systems.3": "2026-12-25"}

    def test_dates_are_recorded_for_badges_an_unclaimed_page_does_not_show(self):
        entries = [skin("ann", systems=["nds"])]
        _, dates, _ = run(entries, [record("ann", claimed=False)], today="2026-11-05")
        assert dates["ann"]["creator.dual-screen"] == "2026-11-05"
        d, _, _ = run(entries, [record("ann", claimed=True)], dates=dates, today="2027-01-01")
        by = {b["id"]: b["earnedAt"] for b in d["creators"][0]["badges"]}
        assert by["creator.dual-screen"] == "2026-11-05"         # claiming did not reset it
        assert by["creator.claimed"] == "2027-01-01"

    def test_disputed_badges_disappear_then_return_with_their_original_date(self):
        a, b, c = (skin("ann", systems=[s]) for s in ("gba", "nes", "snes"))
        _, dates, _ = run([a, b, c], [record("ann")], today="2026-11-05")
        d, dates, _ = run([a, b, c], [record("ann")], disputed={c["id"]}, dates=dates, today="2026-11-20")
        assert "creator.systems.3" not in badge_ids(d, "ann")
        assert dates["ann"]["creator.systems.3"] == "2026-11-05"
        d, dates, _ = run([a, b, c], [record("ann")], dates=dates, today="2026-12-01")
        by = {x["id"]: x["earnedAt"] for x in d["creators"][0]["badges"]}
        assert by["creator.systems.3"] == "2026-11-05"

    def test_file_is_sorted_and_written_only_when_changed(self, tmp_path):
        path = str(tmp_path / "badge-dates.json")
        dates = {"zed": {"creator.first-release": "2026-11-05"}, "ann": {"creator.systems.3": "2026-11-06",
                                                                          "creator.first-release": "2026-11-05"}}
        assert ccs.save_badge_dates(dates, path) is True
        text = (tmp_path / "badge-dates.json").read_text()
        assert list(json.loads(text)["dates"]) == ["ann", "zed"]
        assert ccs.save_badge_dates(ccs.load_badge_dates(path), path) is False
        assert (tmp_path / "badge-dates.json").read_text() == text

    def test_creators_with_no_badges_leave_no_empty_entry(self, tmp_path):
        path = str(tmp_path / "d.json")
        ccs.save_badge_dates({"ann": {}}, path)
        assert json.loads((tmp_path / "d.json").read_text())["dates"] == {}

    def test_missing_or_broken_file_means_no_dates(self, tmp_path):
        assert ccs.load_badge_dates(str(tmp_path / "nope.json")) == {}
        (tmp_path / "bad.json").write_text("{not json")
        assert ccs.load_badge_dates(str(tmp_path / "bad.json")) == {}


# ---------------------------------------------------------------------------
# badges.json
# ---------------------------------------------------------------------------

def good_doc():
    return {"version": 1, "badges": [
        {"id": "creator.a", "for": "creator", "title": "A", "description": "a.", "symbol": "star"},
        {"id": "user.b.1", "for": "user", "title": "B", "description": "b.", "symbol": "star", "tier": 1},
        {"id": "user.b.2", "for": "user", "title": "B2", "description": "b2.", "symbol": "star", "tier": 2},
    ]}


class TestBadgesFile:
    def test_the_real_file_is_valid_and_matches_the_rules(self):
        doc = json.loads((REPO / "badges.json").read_text())
        assert ccs.validate_badges(doc, rule_ids=ccs.RULES) == []

    def test_every_rule_id_exists_in_badges_json(self):
        defs = ccs.load_badges(str(REPO / "badges.json"))
        assert set(defs) == set(ccs.RULES)
        assert ccs.UNCLAIMED_BADGES <= set(defs)

    def test_valid(self):
        assert ccs.validate_badges(good_doc()) == []

    @pytest.mark.parametrize("mutate,needle", [
        (lambda d: d.update(version=2), "version"),
        (lambda d: d.update(extra=1), "unknown top-level"),
        (lambda d: d.update(badges=[]), "non-empty"),
        (lambda d: d["badges"][0].update(id="Creator.A"), "id must look like"),
        (lambda d: d["badges"][0].update(id="creator..a"), "id must look like"),
        (lambda d: d["badges"][0].update(**{"for": "user"}), "must start with 'user.'"),
        (lambda d: d["badges"][0].update(**{"for": "robot"}), "for must be one of"),
        (lambda d: d["badges"][0].update(title=" "), "title must be"),
        (lambda d: d["badges"][0].pop("symbol"), "symbol must be"),
        (lambda d: d["badges"][0].update(color="red"), "unknown field"),
        (lambda d: d["badges"].append(dict(d["badges"][0])), "duplicate id"),
        (lambda d: d["badges"][1].update(tier=0), "tier must be"),
        (lambda d: d["badges"][2].update(tier=1), "used twice"),
        (lambda d: d["badges"][2].pop("tier"), "some do not"),
    ])
    def test_errors(self, mutate, needle):
        doc = good_doc()
        mutate(doc)
        assert any(needle in e for e in ccs.validate_badges(doc)), ccs.validate_badges(doc)

    def test_a_creator_badge_without_a_rule_is_an_error(self):
        errs = ccs.validate_badges(good_doc(), rule_ids={"creator.other"})
        assert any("creator.a" in e and "no rule" in e for e in errs)
        assert any("creator.other" in e and "no entry in badges.json" in e for e in errs)

    def test_check_badges_file_reports_a_missing_file(self, tmp_path):
        assert ccs.check_badges_file(str(tmp_path / "badges.json"))


# ---------------------------------------------------------------------------
# disputed.json
# ---------------------------------------------------------------------------

BODY = "### Skin ID\n\n0123456789abcdef\n\n### Skin name\n\nX\n"
KNOWN = {"0123456789abcdef"}


class TestDisputedFile:
    def test_parse_skin_id(self):
        assert dp.parse_skin_id(BODY) == "0123456789abcdef"
        assert dp.parse_skin_id(BODY.replace("\n", "\r\n")) == "0123456789abcdef"
        assert dp.parse_skin_id("### Skin ID\n\n`0123456789ABCDEF`") == "0123456789abcdef"

    @pytest.mark.parametrize("body", [None, "", "no field", "### Skin ID\n\nshort", "### Skin ID\n\n0123456789abcdeg",
                                      "### Skin ID\n\n0123456789abcdef0", "### Skin ID\n\n$(curl x)"])
    def test_parse_rejects_anything_that_is_not_a_16_hex_id(self, body):
        assert dp.parse_skin_id(body) is None

    def test_add_then_remove(self):
        records = {}
        out, _ = dp.apply_label("disputed", ["content-report"], BODY, 12, records, KNOWN, TODAY)
        assert out == "added" and records == {"0123456789abcdef": {"issue": 12, "since": TODAY}}
        out, _ = dp.apply_label("resolved", ["content-report"], BODY, 12, records, KNOWN, TODAY)
        assert out == "removed" and records == {}

    def test_both_are_idempotent_and_keep_the_first_record(self):
        records = {}
        dp.apply_label("disputed", ["content-report"], BODY, 12, records, KNOWN, "2026-11-01")
        out, _ = dp.apply_label("disputed", ["content-report"], BODY, 99, records, KNOWN, TODAY)
        assert out == "unchanged" and records["0123456789abcdef"] == {"issue": 12, "since": "2026-11-01"}
        records.clear()
        out, _ = dp.apply_label("resolved", ["content-report"], BODY, 12, records, KNOWN, TODAY)
        assert out == "ignored"      # never disputed: no comment, no commit

    def test_other_labels_and_other_issues_are_ignored(self):
        assert dp.apply_label("bug", ["content-report"], BODY, 1, {}, KNOWN, TODAY)[0] == "ignored"
        assert dp.apply_label("disputed", ["bug"], BODY, 1, {}, KNOWN, TODAY)[0] == "ignored"

    def test_unreadable_or_unknown_ids_are_errors_and_change_nothing(self):
        records = {}
        assert dp.apply_label("disputed", ["content-report"], "### Skin ID\n\nnope", 1, records, KNOWN, TODAY)[0] == "error"
        # `resolved` on some other kind of report is not our business, even with a bad id.
        assert dp.apply_label("resolved", ["content-report"], "### Skin ID\n\nnope", 1, records, KNOWN, TODAY)[0] == "ignored"
        assert dp.apply_label("disputed", ["content-report"], BODY, 1, records, set(), TODAY)[0] == "error"
        assert records == {}

    def test_file_round_trip_is_sorted(self, tmp_path):
        path = str(tmp_path / "disputed.json")
        dp.save_disputed({"b" * 16: {"issue": 2, "since": TODAY}, "a" * 16: {"issue": 1, "since": TODAY}}, path)
        assert list(json.loads((tmp_path / "disputed.json").read_text())["disputed"]) == ["a" * 16, "b" * 16]
        assert dp.load_disputed(path) == {"a" * 16: {"issue": 1, "since": TODAY}, "b" * 16: {"issue": 2, "since": TODAY}}

    def test_missing_file_is_empty(self, tmp_path):
        assert dp.load_disputed(str(tmp_path / "nope.json")) == {}

    @pytest.mark.parametrize("doc", [
        [], {"version": 2, "disputed": {}}, {"version": 1}, {"version": 1, "disputed": []},
        {"version": 1, "disputed": {"XYZ": {"issue": 1, "since": TODAY}}},
        {"version": 1, "disputed": {"a" * 16: {"issue": "1", "since": TODAY}}},
        {"version": 1, "disputed": {"a" * 16: {"issue": 1, "since": "yesterday"}}},
        {"version": 1, "disputed": {"a" * 16: {"issue": 1, "since": TODAY, "why": "x"}}},
    ])
    def test_invalid_files_raise_instead_of_reading_as_empty(self, tmp_path, doc):
        path = tmp_path / "disputed.json"
        path.write_text(json.dumps(doc))
        with pytest.raises(dp.DisputedError):
            dp.load_disputed(str(path))
        path.write_text("{oops")
        with pytest.raises(dp.DisputedError):
            dp.load_disputed(str(path))

    def test_the_real_file_is_valid(self):
        dp.load_disputed(str(REPO / "disputed.json"))

    def test_cli_apply_writes_the_file_and_reports_the_outcome(self, tmp_path, monkeypatch):
        skins = tmp_path / "skins" / "gba"
        skins.mkdir(parents=True)
        (skins / "x.json").write_text(json.dumps({"id": "0123456789abcdef"}))
        out = tmp_path / "out.txt"
        monkeypatch.chdir(tmp_path)
        for k, v in {"DISPUTED_FILE": str(tmp_path / "disputed.json"), "GITHUB_OUTPUT": str(out),
                     "LABEL_NAME": "disputed", "ISSUE_NUMBER": "7", "ISSUE_BODY": BODY,
                     "ISSUE_LABELS": json.dumps(["content-report", "disputed"])}.items():
            monkeypatch.setenv(k, v)
        assert dp.main(["apply"]) == 0
        assert list(dp.load_disputed(str(tmp_path / "disputed.json"))) == ["0123456789abcdef"]
        assert "outcome=added" in out.read_text()


# ---------------------------------------------------------------------------
# The whole pass, on disk
# ---------------------------------------------------------------------------

class TestMain:
    def setup_docs(self, tmp_path, skins, records):
        docs = tmp_path / "docs"
        docs.mkdir()
        (docs / "catalog.json").write_text(json.dumps({"skins": skins}))
        (docs / "creators.json").write_text(json.dumps({"version": 1, "updated": TODAY, "creators": records}))
        return docs

    def args(self, tmp_path, *extra):
        return ["--docs-dir", str(tmp_path / "docs"), "--badges-file", str(REPO / "badges.json"),
                "--disputed-file", str(tmp_path / "disputed.json"), "--dates-file", str(tmp_path / "dates.json"),
                "--today", TODAY, *extra]

    def test_writes_stats_into_creators_json_and_the_per_creator_file(self, tmp_path):
        docs = self.setup_docs(tmp_path, [skin("ann"), skin("ann", systems=["nds"])], [record("ann"), record("bob")])
        assert ccs.main(self.args(tmp_path)) == 0
        directory = json.loads((docs / "creators.json").read_text())
        by = {r["slug"]: r for r in directory["creators"]}
        assert by["ann"]["stats"]["files"] == 2 and by["bob"]["stats"]["files"] == 0
        assert by["bob"]["badges"] == []
        per = json.loads((docs / "creators" / "ann.json").read_text())
        assert per["stats"] == by["ann"]["stats"] and per["badges"] == by["ann"]["badges"]
        assert (tmp_path / "dates.json").exists()

    def test_running_twice_gives_identical_files(self, tmp_path):
        docs = self.setup_docs(tmp_path, [skin("ann")], [record("ann")])
        ccs.main(self.args(tmp_path))
        first = ((docs / "creators.json").read_text(), (tmp_path / "dates.json").read_text())
        ccs.main(self.args(tmp_path))
        assert ((docs / "creators.json").read_text(), (tmp_path / "dates.json").read_text()) == first

    def test_dry_run_writes_nothing_and_prints_no_creator_names(self, tmp_path, capsys):
        docs = self.setup_docs(tmp_path, [skin("ann-secret-name", downloadCount=1234)], [record("ann-secret-name")])
        before = (docs / "creators.json").read_text()
        assert ccs.main(self.args(tmp_path, "--dry-run")) == 0
        assert (docs / "creators.json").read_text() == before and not (tmp_path / "dates.json").exists()
        out = capsys.readouterr().out
        assert "Creators: 1" in out and "ann-secret-name" not in out and "1234" not in out

    def test_disputed_file_is_applied(self, tmp_path):
        a, b = skin("ann"), skin("ann", systems=["nes"])
        docs = self.setup_docs(tmp_path, [a, b], [record("ann")])
        dp.save_disputed({b["id"]: {"issue": 5, "since": TODAY}}, str(tmp_path / "disputed.json"))
        ccs.main(self.args(tmp_path))
        assert json.loads((docs / "creators.json").read_text())["creators"][0]["stats"]["files"] == 1

    def test_an_invalid_disputed_file_fails_the_run_without_writing(self, tmp_path):
        docs = self.setup_docs(tmp_path, [skin("ann")], [record("ann")])
        (tmp_path / "disputed.json").write_text("{oops")
        before = (docs / "creators.json").read_text()
        assert ccs.main(self.args(tmp_path)) == 1
        assert (docs / "creators.json").read_text() == before


# ---------------------------------------------------------------------------
# Thumbnail-count hygiene
# ---------------------------------------------------------------------------

def counted(ids, **by_id):
    return [{"id": i, "downloadCount": by_id.get(i)} for i in ids]


class TestCountHygiene:
    def apply(self, fetched, previous=None, entries=None, **kw):
        entries = entries if entries is not None else counted(fetched)
        log = build_catalog.apply_count_hygiene(entries, fetched, previous or {}, **kw)
        return {e["id"]: e["downloadCount"] for e in entries}, log

    def test_counts_under_the_floor_are_dropped(self):
        got, log = self.apply({"a": 49, "b": 50, "c": 0})
        assert got == {"a": None, "b": 50, "c": None}
        assert any("dropped 2" in line for line in log)

    def test_a_count_at_ten_times_previous_is_published(self):
        got, _ = self.apply({"a": 1000}, {"a": 100})
        assert got == {"a": 1000}

    def test_a_count_over_ten_times_previous_holds_at_previous(self):
        got, log = self.apply({"a": 1001}, {"a": 100})
        assert got == {"a": 100}
        assert any("held a at 100" in line for line in log)

    def test_a_new_thumbnail_is_never_held_at_zero(self):
        got, _ = self.apply({"a": 5000})
        assert got == {"a": 5000}

    def test_previous_counts_under_the_floor_are_no_baseline(self):
        # The last build published the old unfiltered 12; 800 is a first real count, not a 66x jump.
        got, _ = self.apply({"a": 800}, {"a": 12})
        assert got == {"a": 800}

    def test_accepting_jumps_publishes_them(self):
        got, log = self.apply({"a": 5000}, {"a": 100}, accept_jumps=True)
        assert got == {"a": 5000} and not log

    def test_the_hold_follows_what_was_published_so_it_lasts(self):
        got, _ = self.apply({"a": 5000}, {"a": 100})
        assert got == {"a": 100}
        got, _ = self.apply({"a": 5000}, got)      # next build, same raw count
        assert got == {"a": 100}

    def test_normal_growth_is_untouched(self):
        got, log = self.apply({"a": 900, "b": 60}, {"a": 800, "b": 55})
        assert got == {"a": 900, "b": 60} and not log

    def test_entries_without_a_thumbnail_count_keep_their_value(self):
        entries = counted(["a", "b"], b=7)
        got, _ = self.apply({"a": 100}, entries=entries)
        assert got == {"a": 100, "b": 7}

    def test_a_failed_fetch_keeps_the_previous_counts(self):
        entries = counted(["a", "b"])
        got, log = self.apply({}, {"a": 321}, entries=entries)
        assert got == {"a": 321, "b": None} and any("kept the previous" in line for line in log)

    def test_load_previous_counts(self, tmp_path):
        path = tmp_path / "catalog.json"
        path.write_text(json.dumps({"skins": [{"id": "a", "downloadCount": 5}, {"id": "b", "downloadCount": None},
                                              {"id": "c"}]}))
        assert build_catalog.load_previous_counts(str(path)) == {"a": 5}
        assert build_catalog.load_previous_counts(str(tmp_path / "missing.json")) == {}
        path.write_text("{oops")
        assert build_catalog.load_previous_counts(str(path)) == {}


class TestBuildEndToEnd:
    """build_catalog.main with the fetch mocked: the previous catalog is the baseline."""

    def build(self, root, fetched, monkeypatch, *extra):
        monkeypatch.setattr(build_catalog, "fetch_release_download_counts", lambda: fetched)
        argv = ["build_catalog.py", "--skins-dir", str(root / "skins"),
                "--output", str(root / "docs" / "catalog.json"),
                "--creators-dir", str(root / "creators"),
                "--added-dates-file", str(root / "added.json"),
                "--health-file", str(root / "health.json"),
                "--variants-file", str(root / "variants.json"),
                "--badges-file", str(REPO / "badges.json"),
                "--disputed-file", str(root / "disputed.json"), *extra]
        monkeypatch.setattr(sys, "argv", argv)
        build_catalog.main()
        return {s["id"]: s["downloadCount"]
                for s in json.loads((root / "docs" / "catalog.json").read_text())["skins"]}

    @pytest.fixture
    def root(self, tmp_path):
        s = skin("ann")
        (tmp_path / "skins" / "gba").mkdir(parents=True)
        (tmp_path / "skins" / "gba" / "a.json").write_text(json.dumps(
            {k: v for k, v in s.items() if k not in ("creator", "tags", "downloadCount", "addedAt", "lastUpdated")}))
        (tmp_path / "id.txt").write_text(s["id"])
        return tmp_path

    def test_hold_then_accept(self, root, monkeypatch):
        sid = (root / "id.txt").read_text()
        assert self.build(root, {sid: 200}, monkeypatch) == {sid: 200}
        assert self.build(root, {sid: 5000}, monkeypatch) == {sid: 200}      # >10x: held
        assert self.build(root, {sid: 5000}, monkeypatch, "--accept-count-jumps") == {sid: 5000}
        assert self.build(root, {sid: 5500}, monkeypatch) == {sid: 5500}

    def test_failed_fetch_keeps_published_counts(self, root, monkeypatch):
        sid = (root / "id.txt").read_text()
        self.build(root, {sid: 200}, monkeypatch)
        assert self.build(root, {}, monkeypatch) == {sid: 200}

    def test_check_only_validates_badges_and_disputed(self, root, monkeypatch, capsys):
        (root / "disputed.json").write_text("{oops")
        monkeypatch.setattr(sys, "argv", [
            "build_catalog.py", "--skins-dir", str(root / "skins"), "--creators-dir", str(root / "creators"),
            "--variants-file", str(root / "variants.json"), "--badges-file", str(root / "no-badges.json"),
            "--disputed-file", str(root / "disputed.json"), "--check-only"])
        with pytest.raises(SystemExit) as exc:
            build_catalog.main()
        assert exc.value.code == 1
        err = capsys.readouterr().err
        assert "no-badges.json" in err and "disputed.json" in err
