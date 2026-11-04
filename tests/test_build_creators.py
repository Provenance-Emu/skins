"""Creator profiles in the catalog build: resolution order, collisions, outputs."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

import pytest
import build_catalog
import creator_directory as cd

ID = iter(range(1, 10_000))


def skin(author, name=None, source="manual", **extra):
    n = next(ID)
    return dict({
        "id": f"{n:016x}", "name": name or f"Skin {n}", "author": author,
        "systems": ["gba"], "source": source,
        "downloadURL": f"https://example.com/{n}.deltaskin",
    }, **extra)


def creator(slug, aliases, **extra):
    return dict({"slug": slug, "displayName": slug, "aliases": aliases, "githubLogin": slug,
                 "_source_file": f"creators/{slug}.json"}, **extra)


def creator_of(entries, creators):
    cd.assign_creators(entries, creators)
    return [e.get("creator") for e in entries]


class TestResolutionOrder:
    def test_alias_match_wins_over_slugify(self):
        c = creator("aphaits", ["Aphaits Dev"])
        assert creator_of([skin("Aphaits Dev")], [c]) == ["aphaits"]

    def test_slugify_when_unclaimed(self):
        assert creator_of([skin("Some Author!")], []) == ["some-author"]

    def test_alias_match_is_exact(self):
        c = creator("aphaits", ["aphaits"])
        # Different case is a different author string; it falls to slugify, which
        # happens to equal the slug, and check_resolution reports that as a collision.
        e = [skin("Aphaits")]
        assert creator_of(e, [c]) == ["aphaits"]
        errors, _ = cd.check_resolution(e, [c])
        assert any("claimed creator" in x for x in errors)

    def test_override_beats_alias_match(self):
        """The design's precedence fixture: `author` is a claimed alias but the
        entry's own `creator` names someone else (uploader vs artist)."""
        starving = creator("starvingartist", ["starvingartist"])
        clear_doom = skin("starvingartist", name="ClearDoom by NostromoCrew01", creator="nostromocrew01")
        regular = skin("starvingartist")
        other = skin("NostromoCrew01")
        entries = [clear_doom, regular, other]
        assert creator_of(entries, [starving]) == ["nostromocrew01", "starvingartist", "nostromocrew01"]

    def test_override_survives_into_directory_stats(self):
        starving = creator("starvingartist", ["starvingartist"])
        clear_doom = skin("starvingartist", creator="nostromocrew01")
        regular = skin("starvingartist")
        nostromo = skin("NostromoCrew01")
        entries = [clear_doom, regular, nostromo]
        cd.assign_creators(entries, [starving])
        directory = cd.build_directory(entries, [starving], "2026-11-04")
        by = {r["slug"]: r for r in directory["creators"]}
        assert by["starvingartist"]["skinIds"] == [regular["id"]]
        assert by["nostromocrew01"]["skinIds"] == sorted([clear_doom["id"], nostromo["id"]])
        assert check_clean([clear_doom, regular, nostromo], [starving])

    def test_no_author_means_no_creator(self):
        e = skin(None)
        e.pop("author")
        assert creator_of([e], []) == [None]
        assert "creator" not in e

    def test_author_with_no_slug_characters(self):
        assert creator_of([skin("!!!")], []) == [None]


def check_clean(entries, creators):
    errors, _ = cd.check_resolution(entries, creators)
    return errors == []


class TestCollisionRules:
    def test_two_unclaimed_authors_same_slug(self):
        errors, _ = cd.check_resolution([skin("Foo Bar"), skin("foo_bar")], [])
        assert len(errors) == 1 and "'foo-bar'" in errors[0]

    def test_override_resolves_the_collision(self):
        # The error tells the uploader to set `creator` on the entry that differs; doing so must clear it.
        assert check_clean([skin("Foo Bar"), skin("foo_bar", creator="different-artist")], [])

    def test_override_resolves_a_clash_with_a_claimed_slug(self):
        c = creator("foo-bar", ["Foo Bar"])
        assert check_clean([skin("Foo Bar"), skin("foo_bar", creator="someone-else")], [c])

    def test_override_on_one_side_still_reports_a_third_colliding_author(self):
        errors, _ = cd.check_resolution([skin("Foo Bar"), skin("foo_bar", creator="x"), skin("FOO-BAR")], [])
        assert len(errors) == 1 and "'Foo Bar'" in errors[0] and "'FOO-BAR'" in errors[0] and "foo_bar" not in errors[0]

    def test_check_after_assign_still_reports_collisions(self):
        entries = [skin("Foo Bar"), skin("foo_bar")]
        cd.assign_creators(entries, [])   # writes each entry's derived slug into `creator`
        errors, _ = cd.check_resolution(entries, [])
        assert len(errors) == 1 and "'foo-bar'" in errors[0]

    def test_aliasing_both_resolves_the_collision(self):
        c = creator("foo-bar", ["Foo Bar", "foo_bar"])
        assert check_clean([skin("Foo Bar"), skin("foo_bar")], [c])

    def test_same_author_many_skins_is_fine(self):
        assert check_clean([skin("Foo"), skin("Foo")], [])

    def test_override_to_unknown_slug_warns(self):
        errors, warnings = cd.check_resolution([skin("Foo", creator="typo-slug")], [])
        assert errors == [] and any("'typo-slug'" in w for w in warnings)

    def test_override_to_known_author_slug_ok(self):
        assert check_clean([skin("Foo"), skin("Bar", creator="foo")], [])

    def test_override_to_claimed_slug_ok(self):
        c = creator("aphaits", ["aphaits"])
        assert check_clean([skin("aphaits"), skin("Bar", creator="aphaits")], [c])

    def test_stale_claim_is_a_warning_not_an_error(self):
        c = creator("ghost", ["Ghost"])
        errors, warnings = cd.check_resolution([skin("Foo")], [c])
        assert errors == [] and any("stale claim" in w for w in warnings)


class TestCreatorFileRules:
    def test_duplicate_alias_across_files(self):
        a = creator("a", ["Shared"])
        b = creator("b", ["Shared"])
        errors = cd.validate_creators([a, b])
        assert len(errors) == 1 and "creators/b.json" in errors[0] and "creators/a.json" in errors[0]

    def test_slugs_compared_case_insensitively(self):
        a = creator("abc", ["A"])
        b = dict(creator("abc", ["B"]), slug="ABC", _source_file="creators/ABC.json")
        errors = cd.validate_creators([a, b])
        assert any("collides" in e for e in errors)
        assert any("slug must be lowercase" in e for e in errors)  # and the slug itself is invalid

    def test_slug_must_match_file_name(self):
        c = dict(creator("a", ["A"]), _source_file="creators/other.json")
        assert any("must match the file name" in e for e in cd.validate_creators([c]))

    def test_schema_errors_are_prefixed_with_the_file(self):
        c = creator("a", ["A"], bio="x" * 501)
        assert cd.validate_creators([c])[0].startswith("creators/a.json: bio is 501")

    def test_valid_set_passes(self):
        assert cd.validate_creators([creator("a", ["A"]), creator("b", ["B"])]) == []


def write(path: Path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj))


@pytest.fixture
def repo(tmp_path, monkeypatch):
    """A tiny catalog on disk. Never touches the network."""
    monkeypatch.setattr(build_catalog, "fetch_release_download_counts", lambda: {})
    a = skin("aphaits", source="aphaits/skins")
    b = skin("Unclaimed Person", source="deltastyles.com")
    c = skin("starvingartist", name="ClearDoom by NostromoCrew01", creator="nostromocrew01")
    for i, e in enumerate((a, b, c)):
        write(tmp_path / "skins" / "gba" / f"s{i}.json", e)
    write(tmp_path / "creators" / "aphaits.json", {
        "slug": "aphaits", "displayName": "Aphaits", "aliases": ["aphaits"], "githubLogin": "aphaits",
        "bio": "Hi", "avatarURL": "https://github.com/aphaits.png", "bannerURL": None,
        "links": [{"label": "Site", "url": "https://example.com"}],
        "socials": {"github": "aphaits"},
        "claim": {"issue": 1, "method": "source", "verifiedAt": "2026-11-10"}, "hidden": False})
    write(tmp_path / "creators" / "starvingartist.json", {
        "slug": "starvingartist", "displayName": "Starving Artist", "aliases": ["starvingartist"],
        "githubLogin": "starvingartist"})
    return tmp_path, {"a": a, "b": b, "c": c}


def run_build(root: Path, *extra):
    argv = ["build_catalog.py", "--skins-dir", str(root / "skins"),
            "--output", str(root / "docs" / "catalog.json"),
            "--creators-dir", str(root / "creators"),
            "--health-file", str(root / "health.json"),
            "--variants-file", str(root / "variants.json"), *extra]
    old = sys.argv
    sys.argv = argv
    try:
        build_catalog.main()
    finally:
        sys.argv = old


class TestBuild:
    def test_catalog_entries_get_creator(self, repo):
        root, e = repo
        run_build(root)
        catalog = json.loads((root / "docs" / "catalog.json").read_text())
        by_id = {s["id"]: s for s in catalog["skins"]}
        assert by_id[e["a"]["id"]]["creator"] == "aphaits"
        assert by_id[e["b"]["id"]]["creator"] == "unclaimed-person"
        assert by_id[e["c"]["id"]]["creator"] == "nostromocrew01"  # override beats the starvingartist alias

    def test_creator_reaches_the_browse_index(self, repo):
        root, e = repo
        run_build(root)
        index = json.loads((root / "docs" / "catalog.min.json").read_text())
        assert {s["creator"] for s in index["skins"]} == {"aphaits", "unclaimed-person", "nostromocrew01"}

    def test_creators_json_lists_every_author(self, repo):
        root, e = repo
        run_build(root)
        d = json.loads((root / "docs" / "creators.json").read_text())
        assert d["version"] == 1 and d["updated"]
        slugs = [r["slug"] for r in d["creators"]]
        # claimed creators always appear (starvingartist has no skin of its own left), plus every author
        assert slugs == ["aphaits", "nostromocrew01", "starvingartist", "unclaimed-person"]
        by = {r["slug"]: r for r in d["creators"]}

        claimed = by["aphaits"]
        assert claimed["claimed"] is True and claimed["bio"] == "Hi"
        assert claimed["githubLogin"] == "aphaits" and claimed["skinIds"] == [e["a"]["id"]]
        assert "claim" not in claimed and "hidden" not in claimed
        assert claimed["links"] == [{"label": "Site", "url": "https://example.com"}]
        assert claimed["socials"] == {"github": "aphaits"}

        minimal = by["unclaimed-person"]
        assert minimal == {"slug": "unclaimed-person", "displayName": "Unclaimed Person",
                           "aliases": ["Unclaimed Person"], "claimed": False, "avatarURL": None,
                           "skinIds": [e["b"]["id"]]}
        assert by["nostromocrew01"]["skinIds"] == [e["c"]["id"]]
        assert by["starvingartist"]["skinIds"] == []

    def test_unclaimed_github_source_gets_avatar(self, repo):
        root, e = repo
        write(root / "skins" / "gba" / "g.json", skin("Repo Owner", source="someowner/somerepo"))
        run_build(root)
        d = json.loads((root / "docs" / "creators.json").read_text())
        rec = next(r for r in d["creators"] if r["slug"] == "repo-owner")
        assert rec["avatarURL"] == "https://github.com/someowner.png"

    def test_per_creator_files(self, repo):
        root, e = repo
        run_build(root)
        files = sorted(p.name for p in (root / "docs" / "creators").iterdir())
        assert files == ["aphaits.json", "nostromocrew01.json", "starvingartist.json", "unclaimed-person.json"]
        one = json.loads((root / "docs" / "creators" / "aphaits.json").read_text())
        assert one["slug"] == "aphaits" and one["claimed"] is True

    def test_stale_per_creator_files_are_pruned(self, repo):
        root, e = repo
        stale = root / "docs" / "creators" / "gone.json"
        write(stale, {"slug": "gone"})
        run_build(root)
        assert not stale.exists()

    def test_hidden_creator_publishes_nothing_but_keeps_its_skins(self, repo):
        root, e = repo
        path = root / "creators" / "aphaits.json"
        obj = json.loads(path.read_text())
        obj["hidden"] = True
        obj["displayName"] = "Something Offensive"
        write(path, obj)
        run_build(root)
        d = json.loads((root / "docs" / "creators.json").read_text())
        rec = next(r for r in d["creators"] if r["slug"] == "aphaits")
        assert rec["claimed"] is False and rec["displayName"] == "aphaits"
        assert "bio" not in rec and "links" not in rec and "githubLogin" not in rec
        assert rec["skinIds"] == [e["a"]["id"]]
        assert "Offensive" not in (root / "docs" / "creators" / "aphaits.json").read_text()

    def test_no_creators_dir_is_fine(self, repo):
        root, e = repo
        for p in (root / "creators").iterdir():
            p.unlink()
        (root / "creators").rmdir()
        run_build(root)
        catalog = json.loads((root / "docs" / "catalog.json").read_text())
        assert all("creator" in s for s in catalog["skins"])

    def test_hand_set_creator_is_not_lost_on_unclaimed_entries(self, repo):
        root, e = repo
        run_build(root)
        catalog = json.loads((root / "docs" / "catalog.json").read_text())
        assert next(s for s in catalog["skins"] if s["id"] == e["c"]["id"])["creator"] == "nostromocrew01"

    def test_broken_creator_file_does_not_publish_profiles(self, repo, capsys):
        root, e = repo
        write(root / "creators" / "bad.json", {"slug": "bad"})
        run_build(root)  # build continues like it does for invalid skins
        assert "Ignoring creators/" in capsys.readouterr().err
        d = json.loads((root / "docs" / "creators.json").read_text())
        assert all(r["claimed"] is False for r in d["creators"])


class TestCheckOnly:
    def test_clean_repo_passes(self, repo, capsys):
        root, _ = repo
        with pytest.raises(SystemExit) as exc:
            run_build(root, "--check-only")
        assert exc.value.code == 0
        assert not (root / "docs").exists()  # check-only writes nothing

    def test_duplicate_alias_fails(self, repo, capsys):
        root, _ = repo
        write(root / "creators" / "dupe.json", {
            "slug": "dupe", "displayName": "Dupe", "aliases": ["aphaits"], "githubLogin": "dupe"})
        with pytest.raises(SystemExit) as exc:
            run_build(root, "--check-only")
        assert exc.value.code == 1
        assert "already claimed by" in capsys.readouterr().out

    def test_case_colliding_slugs_fail(self, repo, capsys):
        root, _ = repo
        # Two files that differ only by case. On a case-insensitive file system the
        # second write replaces the first, so give the second a distinct stem to stay portable.
        write(root / "creators" / "upper.json", {
            "slug": "Aphaits", "displayName": "X", "aliases": ["X"], "githubLogin": "x"})
        with pytest.raises(SystemExit) as exc:
            run_build(root, "--check-only")
        assert exc.value.code == 1
        out = capsys.readouterr().out
        assert "collides" in out and "slug must be lowercase" in out

    def test_unclaimed_author_slug_collision_fails(self, repo, capsys):
        root, _ = repo
        write(root / "skins" / "gba" / "x1.json", skin("Foo Bar"))
        write(root / "skins" / "gba" / "x2.json", skin("foo_bar"))
        with pytest.raises(SystemExit) as exc:
            run_build(root, "--check-only")
        assert exc.value.code == 1
        assert "all become creator slug 'foo-bar'" in capsys.readouterr().out

    def test_malformed_override_fails(self, repo, capsys):
        root, _ = repo
        write(root / "skins" / "gba" / "x1.json", skin("Foo", creator="Not A Slug"))
        with pytest.raises(SystemExit) as exc:
            run_build(root, "--check-only")
        assert exc.value.code == 1
        assert "creator must be a creator slug" in capsys.readouterr().out

    def test_override_to_unknown_slug_only_warns(self, repo, capsys):
        root, _ = repo
        write(root / "skins" / "gba" / "x1.json", skin("Foo", creator="nobody-here"))
        with pytest.raises(SystemExit) as exc:
            run_build(root, "--check-only")
        assert exc.value.code == 0
        assert "'nobody-here'" in capsys.readouterr().err

    def test_stale_claim_only_warns(self, repo, capsys):
        root, _ = repo
        write(root / "creators" / "ghost.json", {
            "slug": "ghost", "displayName": "Ghost", "aliases": ["Ghost"], "githubLogin": "ghost"})
        with pytest.raises(SystemExit) as exc:
            run_build(root, "--check-only")
        assert exc.value.code == 0
        assert "stale claim" in capsys.readouterr().err


class TestRealRepo:
    """The repo's own skins and creators/ must pass the same checks CI runs."""

    def test_current_catalog_has_no_collisions(self):
        repo_root = Path(__file__).parent.parent
        entries = build_catalog.load_all_skins(str(repo_root / "skins"))
        creators, errors = cd.load_creators(str(repo_root / "creators"))
        assert errors == [] and cd.validate_creators(creators) == []
        errs, _ = cd.check_resolution(entries, creators)
        assert errs == []
