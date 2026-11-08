"""prune_thumbnails.py: which release assets are orphans, and that nothing is
deleted unless --apply is given (SkinKit#128)."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

import pytest

import prune_thumbnails as pt
import thumbnail_shards as ts

CAT, HIDDEN, REF, GONE, GONE2, KEEP2 = (f"{c}" * 16 for c in "123456")


def asset(name, aid, downloads=0):
    return {"name": name, "id": aid, "download_count": downloads}


@pytest.fixture
def repo(tmp_path):
    """catalog.json with CAT and KEEP2; skins/ with CAT, HIDDEN (not in the
    catalog: link-health hid it) and a skin whose URL points at REF's asset."""
    (tmp_path / "catalog.json").write_text(json.dumps(
        {"skins": [{"id": CAT}, {"id": KEEP2}]}))
    skins = tmp_path / "skins" / "gba"
    skins.mkdir(parents=True)
    (skins / "cat.json").write_text(json.dumps({"id": CAT}))
    (skins / "hidden.json").write_text(json.dumps({"id": HIDDEN, "thumbnailURL": ts.download_url("thumbnails", f"{HIDDEN}.png")}))
    (skins / "ref.json").write_text(json.dumps({
        "id": "9" * 16, "thumbnailURL": ts.download_url("thumbnails-2", f"{REF}.png")}))
    return tmp_path


RELEASES = {
    "thumbnails": [
        asset(f"{CAT}.png", 1), asset(f"{CAT}-landscape.png", 2),
        asset(f"{HIDDEN}.png", 3), asset(f"{GONE}.png", 4, 3987),
        asset(f"{GONE}-landscape.png", 5), asset("README.txt", 6), asset(f"{GONE2}.png", 7),
    ],
    "thumbnails-2": [asset(f"{REF}.png", 8), asset(f"{KEEP2}.png", 9), asset(f"{GONE2}.png", 10)],
}


def plan_for(repo, releases=RELEASES):
    ids = pt.catalog_ids(str(repo / "catalog.json"))
    skin_ids, refs = pt.skin_file_info(str(repo / "skins"))
    return pt.plan_prune(releases, ids, skin_ids, refs), ids, skin_ids


class TestPlan:
    def test_classification(self, repo):
        plan, _, _ = plan_for(repo)
        assert plan.total == 10
        assert plan.current == 3                                    # CAT x2, KEEP2
        assert plan.not_in_catalog == 6
        assert [a["name"] for a in plan.kept_hidden] == [f"{HIDDEN}.png"]
        assert [(a["tag"], a["name"]) for a in plan.kept_referenced] == [("thumbnails-2", f"{REF}.png")]
        assert [a["name"] for a in plan.unrecognized] == ["README.txt"]
        assert {(a["tag"], a["name"]) for a in plan.prune} == {
            ("thumbnails", f"{GONE}.png"), ("thumbnails", f"{GONE}-landscape.png"),
            ("thumbnails", f"{GONE2}.png"), ("thumbnails-2", f"{GONE2}.png")}

    def test_landscape_of_a_current_skin_is_kept(self, repo):
        plan, _, _ = plan_for(repo)
        assert f"{CAT}-landscape.png" not in {a["name"] for a in plan.prune}

    def test_counts_per_release(self, repo):
        plan, _, _ = plan_for(repo)
        assert plan.per_release == {"thumbnails": {"assets": 7, "prune": 3},
                                    "thumbnails-2": {"assets": 3, "prune": 1}}

    def test_referenced_only_by_exact_tag_and_name(self, repo):
        # The skin file points at thumbnails-2/REF; the same name in `thumbnails` is not protected.
        releases = {"thumbnails": [asset(f"{REF}.png", 1)], "thumbnails-2": [asset(f"{REF}.png", 2)]}
        plan, _, _ = plan_for(repo, releases)
        assert [(a["tag"]) for a in plan.prune] == ["thumbnails"]
        assert [(a["tag"]) for a in plan.kept_referenced] == ["thumbnails-2"]


class TestGuards:
    def test_empty_catalog_aborts(self, repo):
        plan, _, skin_ids = plan_for(repo)
        with pytest.raises(pt.PruneError, match="catalog"):
            pt.check_plan(plan, set(), skin_ids)

    def test_empty_skins_aborts(self, repo):
        plan, ids, _ = plan_for(repo)
        with pytest.raises(pt.PruneError, match="skins"):
            pt.check_plan(plan, ids, set())

    def test_too_many_deletions_abort(self, repo):
        plan, ids, skin_ids = plan_for(repo)
        pt.check_plan(plan, ids, skin_ids, max_fraction=0.5)          # 4 of 10
        with pytest.raises(pt.PruneError, match="would be deleted"):
            pt.check_plan(plan, ids, skin_ids, max_fraction=0.3)


class FakeApi:
    def __init__(self, releases):
        self.releases = releases

    def __call__(self, url):
        if "releases?per_page" in url:
            return [{"tag_name": t, "assets_url": f"https://api.example/{t}/assets"} for t in self.releases]
        tag = url.split("/")[3]
        return self.releases[tag]


class TestMain:
    def run(self, repo, *extra, delete=None, releases=RELEASES):
        return pt.main(["--catalog", str(repo / "catalog.json"), "--skins-dir", str(repo / "skins"), *extra],
                       get_json=FakeApi(releases), delete=delete)

    def test_dry_run_is_the_default_and_deletes_nothing(self, repo, capsys):
        calls = []
        assert self.run(repo, delete=calls.append) == 0
        assert calls == []
        out = capsys.readouterr().out
        assert "orphans to delete: 4" in out and "Dry run: nothing was deleted." in out

    def test_explicit_dry_run_deletes_nothing(self, repo):
        calls = []
        assert self.run(repo, "--dry-run", delete=calls.append) == 0 and calls == []

    def test_apply_deletes_only_orphans(self, repo):
        calls = []
        assert self.run(repo, "--apply", delete=calls.append) == 0
        assert sorted(calls) == [4, 5, 7, 10]

    def test_apply_and_dry_run_conflict(self, repo):
        with pytest.raises(SystemExit):
            self.run(repo, "--apply", "--dry-run")

    def test_apply_needs_a_token(self, repo, monkeypatch, capsys):
        monkeypatch.delenv("GITHUB_TOKEN", raising=False)
        assert self.run(repo, "--apply") == 2

    def test_a_failed_delete_is_reported_and_the_rest_go_on(self, repo, capsys):
        calls = []

        def delete(aid):
            calls.append(aid)
            if aid == 5:
                raise OSError("boom")
        assert self.run(repo, "--apply", delete=delete) == 1
        assert sorted(calls) == [4, 5, 7, 10]
        assert "Failed: thumbnails/" + f"{GONE}-landscape.png" in capsys.readouterr().out

    def test_an_asset_already_gone_is_not_a_failure(self, repo):
        class Gone(Exception):
            code = 404

        def delete(aid):
            raise Gone()
        assert self.run(repo, "--apply", delete=delete) == 0

    def test_listing_failure_changes_nothing(self, repo, capsys):
        calls = []

        def broken(url):
            raise OSError("down")
        rc = pt.main(["--apply", "--catalog", str(repo / "catalog.json"),
                      "--skins-dir", str(repo / "skins")], get_json=broken, delete=calls.append)
        assert rc == 1 and calls == []

    def test_empty_catalog_changes_nothing(self, repo):
        (repo / "catalog.json").write_text(json.dumps({"skins": []}))
        calls = []
        assert self.run(repo, "--apply", delete=calls.append) == 1 and calls == []

    def test_report_file(self, repo, tmp_path):
        out = tmp_path / "report.md"
        assert self.run(repo, "--report", str(out)) == 0
        assert "| `thumbnails-2` | 3 | 1 | 2 |" in out.read_text()

    def test_list_names_each_orphan(self, repo, capsys):
        assert self.run(repo, "--list") == 0
        assert f"thumbnails/{GONE}.png  downloads=3987" in capsys.readouterr().out


def test_fetch_releases_pages_every_shard():
    pages = {
        "https://api.github.com/repos/Provenance-Emu/skins/releases?per_page=100&page=1": [
            {"tag_name": "thumbnails-2", "assets_url": "https://api.example/b"},
            {"tag_name": "thumbnails", "assets_url": "https://api.example/a"}],
        "https://api.example/a?per_page=100&page=1": [asset(f"{CAT}.png", 1)],
        "https://api.example/b?per_page=100&page=1": [asset(f"{KEEP2}.png", 2)],
    }
    got = pt.fetch_releases(pages.__getitem__)
    assert list(got) == ["thumbnails", "thumbnails-2"]
