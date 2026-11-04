"""addedAt: first-commit dates from git history, cached, and degraded gracefully.

These tests build real git repositories in temp dirs (with pinned commit dates)
because the behaviour under test is git's, including the shallow-clone trap.
"""

import json
import os
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

import pytest
import added_dates as ad
import build_catalog
import generate_rss
from skin_schema import validate_entry

GIT_ENV = {
    "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_SYSTEM": os.devnull,
    "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.com",
    "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.com",
}


def git(cwd, *args, date=None):
    env = dict(os.environ, **GIT_ENV)
    if date:
        env["GIT_AUTHOR_DATE"] = env["GIT_COMMITTER_DATE"] = date
    out = subprocess.run(["git", "-c", "commit.gpgsign=false", "-c", "protocol.file.allow=always", *args],
                         cwd=cwd, env=env, capture_output=True, text=True)
    assert out.returncode == 0, out.stderr
    return out.stdout.strip()


def skin(n, **extra):
    return dict({"id": f"{n:016x}", "name": f"Skin {n}", "author": "A", "systems": ["gba"], "source": "manual",
                 "downloadURL": f"https://example.com/{n}.deltaskin"}, **extra)


def write(repo: Path, rel: str, obj) -> Path:
    path = repo / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2))
    return path


def commit(repo: Path, message: str, date: str):
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", message, date=date)


@pytest.fixture
def repo(tmp_path):
    """Three commits: skin 1 on Jan 10, skin 2 on Feb 20, skin 3 on Mar 30 (UTC)."""
    r = tmp_path / "repo"
    r.mkdir()
    git(r, "init", "-q", "-b", "main")
    write(r, "skins/gba/one.json", skin(1))
    commit(r, "one", "2026-01-10T12:00:00+00:00")
    write(r, "skins/gba/two.json", skin(2))
    commit(r, "two", "2026-02-20T12:00:00+00:00")
    write(r, "skins/gbc/three.json", skin(3))
    commit(r, "three", "2026-03-30T12:00:00+00:00")
    return r


def entries_of(repo: Path):
    return build_catalog.load_all_skins(str(repo / "skins"))


def by_name(entries):
    return {Path(e["_source_file"]).name: e for e in entries}


class TestEffectiveDate:
    def test_last_updated_wins(self):
        assert ad.effective_date({"lastUpdated": "2025-09-23", "addedAt": "2026-03-13"}) == "2025-09-23"

    def test_falls_back_to_added_at(self):
        assert ad.effective_date({"lastUpdated": None, "addedAt": "2026-03-13"}) == "2026-03-13"
        assert ad.effective_date({"addedAt": "2026-03-13"}) == "2026-03-13"

    def test_none_when_neither(self):
        assert ad.effective_date({}) is None
        assert ad.effective_date({"lastUpdated": ""}) is None

    def test_sort_recent_orders_by_effective_date_then_name(self):
        a = {"id": "1", "name": "Zed", "addedAt": "2026-03-01"}
        b = {"id": "2", "name": "alpha", "addedAt": "2026-03-01"}
        c = {"id": "3", "name": "Mid", "lastUpdated": "2026-04-01", "addedAt": "2026-01-01"}
        d = {"id": "4", "name": "Undated"}
        e = {"id": "5", "name": "Old", "lastUpdated": "2025-01-01"}
        assert [s["id"] for s in ad.sort_recent([a, b, c, d, e])] == ["3", "2", "1", "5", "4"]

    def test_sort_recent_ignores_input_order(self):
        items = [{"id": str(i), "name": f"n{i % 3}", "addedAt": "2026-03-01"} for i in range(9)]
        assert ad.sort_recent(items) == ad.sort_recent(list(reversed(items)))


class TestBackfill:
    def test_dates_come_from_the_adding_commit(self, repo, tmp_path):
        entries = entries_of(repo)
        cache = tmp_path / "added-dates.json"
        stats = ad.apply_added_dates(entries, str(repo / "skins"), str(cache))
        got = by_name(entries)
        assert got["one.json"]["addedAt"] == "2026-01-10"
        assert got["two.json"]["addedAt"] == "2026-02-20"
        assert got["three.json"]["addedAt"] == "2026-03-30"
        assert stats == {"dated": 3, "looked_up": 3, "missing": 0, "unavailable": False}

    def test_cache_file_shape(self, repo, tmp_path):
        cache = tmp_path / "added-dates.json"
        ad.apply_added_dates(entries_of(repo), str(repo / "skins"), str(cache))
        assert json.loads(cache.read_text()) == {"version": 1, "dates": {
            "skins/gba/one.json": "2026-01-10",
            "skins/gba/two.json": "2026-02-20",
            "skins/gbc/three.json": "2026-03-30",
        }}

    def test_date_is_utc(self, tmp_path):
        r = tmp_path / "r"
        r.mkdir()
        git(r, "init", "-q", "-b", "main")
        write(r, "skins/gba/late.json", skin(1))
        commit(r, "late", "2026-05-01T23:30:00-05:00")  # already May 2 in UTC
        entries = entries_of(r)
        ad.apply_added_dates(entries, str(r / "skins"), str(tmp_path / "c.json"))
        assert entries[0]["addedAt"] == "2026-05-02"

    def test_later_edits_do_not_move_the_date(self, repo, tmp_path):
        write(repo, "skins/gba/one.json", skin(1, version="2"))
        commit(repo, "edit", "2026-06-01T12:00:00+00:00")
        entries = entries_of(repo)
        ad.apply_added_dates(entries, str(repo / "skins"), str(tmp_path / "c.json"))
        assert by_name(entries)["one.json"]["addedAt"] == "2026-01-10"

    def test_rename_keeps_the_original_date(self, repo, tmp_path):
        git(repo, "mv", "skins/gba/one.json", "skins/gba/one-renamed.json")
        commit(repo, "rename", "2026-06-01T12:00:00+00:00")
        entries = entries_of(repo)
        ad.apply_added_dates(entries, str(repo / "skins"), str(tmp_path / "c.json"))
        assert by_name(entries)["one-renamed.json"]["addedAt"] == "2026-01-10"

    def test_split_bundle_members_all_inherit_the_bundle_date(self, tmp_path):
        """A migration that turned one file into several: each member keeps the
        date of the file it came from, which whole-tree rename detection would not give."""
        r = tmp_path / "r"
        r.mkdir()
        git(r, "init", "-q", "-b", "main")
        bundle = skin(1, tags=["bundle"], description="x" * 200)
        write(r, "skins/gba/bundle.json", bundle)
        commit(r, "bundle", "2026-01-10T12:00:00+00:00")
        os.remove(r / "skins/gba/bundle.json")
        for n, name in ((1, "a"), (2, "b"), (3, "c")):
            write(r, f"skins/gba/{name}.json", dict(bundle, id=f"{n:016x}", name=name))
        commit(r, "split", "2026-06-01T12:00:00+00:00")
        entries = entries_of(r)
        ad.apply_added_dates(entries, str(r / "skins"), str(tmp_path / "c.json"))
        assert {e["addedAt"] for e in entries} == {"2026-01-10"}

    def test_hand_set_added_at_is_kept(self, repo, tmp_path):
        write(repo, "skins/gba/one.json", skin(1, addedAt="2020-02-02"))
        commit(repo, "hand", "2026-06-01T12:00:00+00:00")
        entries = entries_of(repo)
        ad.apply_added_dates(entries, str(repo / "skins"), str(tmp_path / "c.json"))
        assert by_name(entries)["one.json"]["addedAt"] == "2020-02-02"

    def test_uncommitted_file_has_no_date_and_is_not_cached(self, repo, tmp_path):
        write(repo, "skins/gba/new.json", skin(9))
        entries = entries_of(repo)
        cache = tmp_path / "c.json"
        stats = ad.apply_added_dates(entries, str(repo / "skins"), str(cache))
        assert "addedAt" not in by_name(entries)["new.json"]
        assert stats["missing"] == 1 and stats["unavailable"] is False
        assert "new.json" not in cache.read_text()


class TestCaching:
    def count_lookups(self, monkeypatch):
        calls = []
        real = ad.Repo.first_added

        def spy(self, rel):
            calls.append(rel)
            return real(self, rel)
        monkeypatch.setattr(ad.Repo, "first_added", spy)
        return calls

    def test_second_run_does_not_touch_history(self, repo, tmp_path, monkeypatch):
        cache = tmp_path / "c.json"
        ad.apply_added_dates(entries_of(repo), str(repo / "skins"), str(cache))
        calls = self.count_lookups(monkeypatch)
        entries = entries_of(repo)
        stats = ad.apply_added_dates(entries, str(repo / "skins"), str(cache))
        assert calls == []
        assert stats["looked_up"] == 0 and stats["dated"] == 3
        assert by_name(entries)["two.json"]["addedAt"] == "2026-02-20"

    def test_only_new_files_are_looked_up(self, repo, tmp_path, monkeypatch):
        cache = tmp_path / "c.json"
        ad.apply_added_dates(entries_of(repo), str(repo / "skins"), str(cache))
        write(repo, "skins/nes/four.json", skin(4))
        commit(repo, "four", "2026-04-15T12:00:00+00:00")
        calls = self.count_lookups(monkeypatch)
        entries = entries_of(repo)
        ad.apply_added_dates(entries, str(repo / "skins"), str(cache))
        assert calls == ["skins/nes/four.json"]
        assert by_name(entries)["four.json"]["addedAt"] == "2026-04-15"
        assert json.loads(cache.read_text())["dates"]["skins/nes/four.json"] == "2026-04-15"

    def test_cached_date_is_trusted_over_history(self, repo, tmp_path):
        cache = tmp_path / "c.json"
        cache.write_text(json.dumps({"version": 1, "dates": {"skins/gba/one.json": "1999-09-09"}}))
        entries = entries_of(repo)
        ad.apply_added_dates(entries, str(repo / "skins"), str(cache))
        assert by_name(entries)["one.json"]["addedAt"] == "1999-09-09"

    @pytest.mark.parametrize("junk", ["not json", "[]", '{"version": 99, "dates": {}}',
                                      '{"version": 1, "dates": []}', ""])
    def test_malformed_cache_is_ignored_and_rebuilt(self, repo, tmp_path, junk):
        cache = tmp_path / "c.json"
        cache.write_text(junk)
        entries = entries_of(repo)
        ad.apply_added_dates(entries, str(repo / "skins"), str(cache))
        assert by_name(entries)["one.json"]["addedAt"] == "2026-01-10"
        assert json.loads(cache.read_text())["version"] == 1

    def test_cache_is_not_rewritten_when_nothing_new(self, repo, tmp_path):
        cache = tmp_path / "c.json"
        ad.apply_added_dates(entries_of(repo), str(repo / "skins"), str(cache))
        cache.write_text(cache.read_text() + "\n")  # marker: a rewrite would remove this blank line
        before = cache.read_text()
        ad.apply_added_dates(entries_of(repo), str(repo / "skins"), str(cache))
        assert cache.read_text() == before


class TestShallowAndNoGit:
    @pytest.fixture
    def shallow(self, repo, tmp_path):
        clone = tmp_path / "clone"
        git(tmp_path, "clone", "-q", "--depth", "1", f"file://{repo}", str(clone))
        assert git(clone, "rev-parse", "--is-shallow-repository") == "true"
        return clone

    def test_the_trap_is_real(self, shallow):
        """Documents why the guard exists: git claims the one grafted commit added everything."""
        out = git(shallow, "log", "--follow", "--diff-filter=A", "--format=%cs", "--", "skins/gba/one.json")
        assert out == "2026-03-30"

    def test_shallow_clone_does_not_crash_or_invent_dates(self, shallow, tmp_path):
        entries = entries_of(shallow)
        cache = tmp_path / "c.json"
        stats = ad.apply_added_dates(entries, str(shallow / "skins"), str(cache))
        assert all("addedAt" not in e for e in entries)
        assert stats == {"dated": 0, "looked_up": 0, "missing": 3, "unavailable": True}
        assert not cache.exists()  # nothing wrong may be cached

    def test_shallow_clone_still_uses_cached_dates(self, shallow, tmp_path):
        cache = tmp_path / "c.json"
        cache.write_text(json.dumps({"version": 1, "dates": {"skins/gba/one.json": "2026-01-10"}}))
        entries = entries_of(shallow)
        stats = ad.apply_added_dates(entries, str(shallow / "skins"), str(cache))
        got = by_name(entries)
        assert got["one.json"]["addedAt"] == "2026-01-10"
        assert "addedAt" not in got["two.json"]
        assert stats["dated"] == 1 and stats["missing"] == 2 and stats["unavailable"] is True
        assert json.loads(cache.read_text())["dates"] == {"skins/gba/one.json": "2026-01-10"}

    def test_not_a_git_repo(self, tmp_path):
        skins = tmp_path / "plain" / "skins"
        write(skins.parent, "skins/gba/x.json", skin(1))
        entries = build_catalog.load_all_skins(str(skins))
        cache = tmp_path / "c.json"
        stats = ad.apply_added_dates(entries, str(skins), str(cache))
        assert "addedAt" not in entries[0]
        assert stats["missing"] == 1 and stats["unavailable"] is True
        assert not cache.exists()

    def test_missing_skins_dir(self, tmp_path):
        assert ad.apply_added_dates([], str(tmp_path / "nope"), str(tmp_path / "c.json"))["missing"] == 0

    def test_git_not_installed(self, repo, tmp_path, monkeypatch):
        monkeypatch.setattr(ad.subprocess, "run", lambda *a, **k: (_ for _ in ()).throw(FileNotFoundError()))
        entries = entries_of(repo)
        stats = ad.apply_added_dates(entries, str(repo / "skins"), str(tmp_path / "c.json"))
        assert stats["dated"] == 0 and stats["missing"] == 3

    def test_build_with_shallow_history_still_publishes(self, shallow, tmp_path, monkeypatch, capsys):
        monkeypatch.setattr(build_catalog, "fetch_release_download_counts", lambda: {})
        cache = tmp_path / "c.json"
        run_build(shallow, tmp_path, cache)
        catalog = json.loads((tmp_path / "out" / "catalog.json").read_text())
        assert catalog["totalSkins"] == 3
        assert all("addedAt" not in s for s in catalog["skins"])
        assert "shallow or unavailable" in capsys.readouterr().err
        assert not cache.exists()


def run_build(repo: Path, tmp_path: Path, cache: Path, *extra):
    argv = ["build_catalog.py", "--skins-dir", str(repo / "skins"),
            "--output", str(tmp_path / "out" / "catalog.json"),
            "--added-dates-file", str(cache),
            "--health-file", str(tmp_path / "health.json"),
            "--variants-file", str(tmp_path / "variants.json"), *extra]
    old, sys.argv = sys.argv, argv
    try:
        build_catalog.main()
    finally:
        sys.argv = old


class TestBuild:
    @pytest.fixture(autouse=True)
    def no_network(self, monkeypatch):
        monkeypatch.setattr(build_catalog, "fetch_release_download_counts", lambda: {})

    def test_every_entry_has_added_at(self, repo, tmp_path):
        run_build(repo, tmp_path, tmp_path / "c.json")
        catalog = json.loads((tmp_path / "out" / "catalog.json").read_text())
        assert {s["name"]: s["addedAt"] for s in catalog["skins"]} == {
            "Skin 1": "2026-01-10", "Skin 2": "2026-02-20", "Skin 3": "2026-03-30"}

    def test_added_at_reaches_browse_index(self, repo, tmp_path):
        run_build(repo, tmp_path, tmp_path / "c.json")
        index = json.loads((tmp_path / "out" / "catalog.min.json").read_text())
        assert all(re.fullmatch(r"\d{4}-\d{2}-\d{2}", s["addedAt"]) for s in index["skins"])

    def test_check_only_does_not_touch_history_or_write_the_cache(self, repo, tmp_path):
        cache = tmp_path / "c.json"
        with pytest.raises(SystemExit) as exc:
            run_build(repo, tmp_path, cache, "--check-only")
        assert exc.value.code == 0
        assert not cache.exists()

    def test_added_at_is_never_written_back_to_skin_files(self, repo, tmp_path):
        before = (repo / "skins/gba/one.json").read_text()
        run_build(repo, tmp_path, tmp_path / "c.json")
        assert (repo / "skins/gba/one.json").read_text() == before


class TestSchema:
    def entry(self, **kw):
        return skin(1, **kw)

    def test_valid(self):
        assert validate_entry(self.entry(addedAt="2026-03-13")) == []
        assert validate_entry(self.entry(addedAt=None)) == []

    @pytest.mark.parametrize("bad", ["2026-13-01", "2026-03-13T00:00:00Z", "March", 20260313, ""])
    def test_invalid(self, bad):
        assert any("addedAt" in e for e in validate_entry(self.entry(addedAt=bad)))


class TestFeed:
    def test_feed_orders_by_effective_date_with_stable_ties(self, tmp_path, monkeypatch):
        skins = [
            {"id": f"{i:016x}", "name": n, "author": "A", "systems": ["gba"], "source": "m",
             "downloadURL": "https://e.com/x.deltaskin", **dates}
            for i, (n, dates) in enumerate([
                ("Bulk B", {"addedAt": "2026-04-02"}),
                ("Bulk A", {"addedAt": "2026-04-02"}),
                ("Fresh", {"addedAt": "2026-11-01"}),
                ("Updated", {"lastUpdated": "2026-12-01", "addedAt": "2026-01-01"}),
                ("Undated", {}),
            ], 1)]
        catalog = tmp_path / "catalog.json"
        catalog.write_text(json.dumps({"version": 3, "skins": skins}))
        monkeypatch.setattr(generate_rss, "CATALOG_PATH", str(catalog))
        monkeypatch.setattr(generate_rss, "OUTPUT_PATH", str(tmp_path / "feed.xml"))
        generate_rss.main()
        xml = (tmp_path / "feed.xml").read_text()
        titles = re.findall(r"<item>\s*<title>(.*?)</title>", xml)
        assert titles == ["Updated", "Fresh", "Bulk A", "Bulk B", "Undated"]
        assert "<pubDate>Sun, 01 Nov 2026" in xml  # pubDate from addedAt, not "now"

    def test_site_script_uses_the_same_effective_date(self):
        js = (Path(__file__).parent.parent / "docs" / "js" / "browse.js").read_text()
        assert "function effectiveDate(skin)" in js
        assert "skin.lastUpdated || skin.addedAt" in js
        assert "effectiveDate(skin)" in js.split("function isNewSkin(skin)")[1].split("}")[0]
        assert "effectiveDate(a)" in js and "effectiveDate(b)" in js
