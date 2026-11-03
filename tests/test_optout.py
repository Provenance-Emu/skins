"""Tests for process_optout.py against a mocked GitHub API and a mocked gh/git runner."""

import base64
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

import pytest
import blocklist as bl
import process_optout as po


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------

class FakeAPI:
    """Routes (method, path) to canned (status, json). Records every call."""

    def __init__(self, routes=None):
        self.routes = routes or {}
        self.calls = []

    def request(self, method, path, body=None):
        self.calls.append((method, path, body))
        for (m, p), resp in self.routes.items():
            if m == method and path == p:
                return resp
        if method == "GET" and "/labels/" in path:
            return 404, None
        return 404, None

    def writes(self):
        return [c for c in self.calls if c[0] != "GET"]

    def comments(self):
        return [c[2]["body"] for c in self.calls if c[0] == "POST" and c[1].endswith("/comments")]


def repo_route(owner, repo, otype, login=None, full=None, default="main"):
    return ("GET", f"/repos/{owner}/{repo}"), (200, {
        "full_name": full or f"{owner}/{repo}",
        "owner": {"login": login or owner, "type": otype},
        "default_branch": default,
    })


def file_route(owner, repo, content, branch="main"):
    return ("GET", f"/repos/{owner}/{repo}/contents/.emuskins-optout?ref={branch}"), (200, {
        "encoding": "base64", "content": base64.b64encode(content.encode()).decode()})


class FakeRun:
    def __init__(self, fail=None, staged=True):
        self.cmds = []
        self.fail = fail or (lambda cmd: None)  # returns stderr string to fail a command
        self.staged = staged

    def __call__(self, cmd):
        self.cmds.append(cmd)
        err = self.fail(cmd)
        if err:
            return subprocess.CompletedProcess(cmd, 1, "", err)
        if cmd[:3] == ["git", "diff", "--cached"]:
            return subprocess.CompletedProcess(cmd, 1 if self.staged else 0, "", "")
        return subprocess.CompletedProcess(cmd, 0, "", "")


def form_body(url, all_repos=False):
    box = "- [X] Block every repo under my account" if all_repos else "- [ ] Block every repo under my account"
    return f"### Repo URL to remove\n\n{url}\n\n### Scope\n\n{box}\n"


def ctx(url="https://github.com/alice/skins", author="alice", number=77, all_repos=False,
        event="issues", comment_body="", comment_author="", state="open", labels=("repo-optout",)):
    return po.Context(repo="Provenance-Emu/skins", event=event, issue_number=number,
                      issue_author=author, issue_body=form_body(url, all_repos), issue_state=state,
                      labels=list(labels), comment_body=comment_body, comment_author=comment_author)


@pytest.fixture
def tree(tmp_path):
    """A skins/ and thumbnails/ tree with skins from several repos."""
    skins, thumbs = tmp_path / "skins", tmp_path / "thumbnails"
    (skins / "gba").mkdir(parents=True)
    (skins / "nds").mkdir(parents=True)
    thumbs.mkdir()

    def add(system, slug, entry):
        (skins / system / f"{slug}.json").write_text(json.dumps(entry))
        for suffix in (".png", "-landscape.png"):
            (thumbs / f"{entry['id']}{suffix}").write_bytes(b"png")

    add("gba", "a1", {"id": "aaaa000000000001", "name": "A1", "source": "alice/skins",
                      "downloadURL": "https://raw.githubusercontent.com/alice/skins/HEAD/a1.deltaskin"})
    # repack: mirror download, origin only in originalURL
    add("gba", "a2", {"id": "aaaa000000000002", "name": "A2", "source": "alice/skins",
                      "downloadURL": "https://github.com/Provenance-Emu/skins/releases/download/mirror/aaaa000000000002.deltaskin",
                      "originalURL": "https://raw.githubusercontent.com/alice/skins/HEAD/pack.zip"})
    # DeltaStyles listing of a GitHub release asset
    add("nds", "a3", {"id": "aaaa000000000003", "name": "A3", "source": "deltastyles.com",
                      "downloadURL": "https://github.com/alice/skins/releases/download/v1/a3.deltaskin"})
    add("gba", "b1", {"id": "bbbb000000000001", "name": "B1", "source": "bob/skins",
                      "downloadURL": "https://raw.githubusercontent.com/bob/skins/HEAD/b1.deltaskin"})
    add("nds", "d1", {"id": "dddd000000000001", "name": "D1", "source": "deltastyles.com",
                      "downloadURL": "https://deltastyles.com/files/skins/1/d1.deltaskin"})
    return tmp_path, skins, thumbs


def run_it(context, api, tree, run=None, dry_run=False, blocklist_path=None):
    tmp, skins, thumbs = tree
    return po.run_optout(context, api, run=run or FakeRun(), dry_run=dry_run,
                         blocklist_path=blocklist_path or bl.BLOCKLIST_PATH,
                         skins_dir=str(skins), thumbnails_dir=str(thumbs), today="2026-11-02")


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------

class TestParsing:
    @pytest.mark.parametrize("text, expected", [
        ("https://github.com/alice/skins", ("alice", "skins")),
        ("https://github.com/alice/skins/", ("alice", "skins")),
        ("https://github.com/alice/skins.git", ("alice", "skins")),
        ("http://www.github.com/Alice/My.Skins_2", ("Alice", "My.Skins_2")),
        ("alice/skins", ("alice", "skins")),
        ("https://github.com/alice/skins\nsecond line ignored", ("alice", "skins")),
    ])
    def test_repo_url_ok(self, text, expected):
        assert po.parse_repo_url(text) == expected

    @pytest.mark.parametrize("text", [
        "", "_No response_", "https://gitlab.com/alice/skins", "https://github.com/alice",
        "https://github.com/alice/skins/tree/main", "https://github.com/alice/skins; rm -rf /",
        "https://github.com/alice/$(whoami)", "https://github.com/alice/skins?x=1", "alice/../x",
        "https://github.com/-alice/skins", "https://github.com/al ice/skins",
    ])
    def test_repo_url_rejected(self, text):
        assert po.parse_repo_url(text) is None

    def test_form(self):
        f = po.parse_form(form_body("https://github.com/alice/skins", all_repos=True))
        assert f == {"repo": ("alice", "skins"), "all_repos": True}
        f = po.parse_form(form_body("https://github.com/alice/skins"))
        assert f["all_repos"] is False

    def test_form_crlf_body(self):
        body = form_body("https://github.com/alice/skins").replace("\n", "\r\n")
        assert po.parse_form(body)["repo"] == ("alice", "skins")


# ---------------------------------------------------------------------------
# Ownership-check branches
# ---------------------------------------------------------------------------

class TestOwnership:
    def test_user_owner_matches_author(self):
        api = FakeAPI(dict([repo_route("alice", "skins", "User")]))
        v = po.check_account(api, po.lookup_repo(api, "alice", "skins"), "Alice")  # login compare is case-insensitive
        assert (v.status, v.method, v.can_block_all) == ("verified", "owner", True)

    def test_user_owner_is_someone_else(self):
        api = FakeAPI(dict([repo_route("alice", "skins", "User")]))
        v = po.check_account(api, po.lookup_repo(api, "alice", "skins"), "mallory")
        assert v.status == "unverified"
        assert not [c for c in api.calls if "public_members" in c[1]]  # no org lookup for a user

    def test_org_public_member_204(self):
        api = FakeAPI(dict([repo_route("acme", "skins", "Organization"),
                            (("GET", "/orgs/acme/public_members/alice"), (204, None))]))
        v = po.check_account(api, po.lookup_repo(api, "acme", "skins"), "alice")
        assert (v.status, v.method, v.can_block_all) == ("verified", "org-member", True)

    def test_org_not_public_member_404(self):
        api = FakeAPI(dict([repo_route("acme", "skins", "Organization"),
                            (("GET", "/orgs/acme/public_members/alice"), (404, None))]))
        v = po.check_account(api, po.lookup_repo(api, "acme", "skins"), "alice")
        assert v.status == "unverified"

    def test_org_member_302_is_not_membership(self):
        """GitHub answers 302 when the requester can't see membership; that isn't a yes."""
        api = FakeAPI(dict([repo_route("acme", "skins", "Organization"),
                            (("GET", "/orgs/acme/public_members/alice"), (302, None))]))
        assert po.check_account(api, po.lookup_repo(api, "acme", "skins"), "alice").status == "unverified"

    def test_repo_not_found(self):
        api = FakeAPI()
        v = po.lookup_repo(api, "alice", "nope")
        assert v.status == "not_found"

    def test_api_error(self):
        api = FakeAPI({("GET", "/repos/alice/skins"): (500, None)})
        assert po.lookup_repo(api, "alice", "skins").status == "error"

    def test_renamed_repo_is_not_verified_under_old_name(self):
        api = FakeAPI(dict([repo_route("alice", "old", "User", full="alice/new")]))
        v = po.lookup_repo(api, "alice", "old")
        assert v.status == "moved" and "alice/new" in v.reason

    def test_owner_is_taken_from_api_not_the_url(self):
        """URL says alice, API says the repo is owned by mallory's org: author alice gets nothing."""
        api = FakeAPI(dict([repo_route("alice", "skins", "Organization", login="alice-org", full="alice/skins")]))
        v = po.lookup_repo(api, "alice", "skins")
        api.routes[("GET", "/orgs/alice-org/public_members/alice")] = (404, None)
        assert po.check_account(api, v, "alice").status == "unverified"

    def test_own_repo_is_refused(self):
        api = FakeAPI(dict([repo_route("Provenance-Emu", "skins", "Organization")]))
        assert po.lookup_repo(api, "Provenance-Emu", "skins").status == "refused"
        api = FakeAPI(dict([repo_route("Provenance-Emu", "other", "Organization")]))
        assert po.lookup_repo(api, "Provenance-Emu", "other").status == "refused"

    def test_file_with_issue_number(self):
        api = FakeAPI(dict([repo_route("alice", "skins", "User"), file_route("alice", "skins", "77\n")]))
        v = po.check_file(api, po.lookup_repo(api, "alice", "skins"), 77)
        assert (v.status, v.method, v.can_block_all) == ("verified", "file", False)

    def test_file_uses_default_branch(self):
        api = FakeAPI(dict([repo_route("alice", "skins", "User", default="trunk"),
                            file_route("alice", "skins", "emuskins opt-out for #77", branch="trunk")]))
        assert po.check_file(api, po.lookup_repo(api, "alice", "skins"), 77).status == "verified"

    @pytest.mark.parametrize("content", ["7", "770", "1770", "", "seventy-seven"])
    def test_file_with_other_number_fails(self, content):
        api = FakeAPI(dict([repo_route("alice", "skins", "User"), file_route("alice", "skins", content)]))
        v = po.check_file(api, po.lookup_repo(api, "alice", "skins"), 77)
        assert v.status == "unverified" and v.notes

    def test_file_issue_4_not_verified_by_34(self):
        api = FakeAPI(dict([repo_route("alice", "skins", "User"), file_route("alice", "skins", "34")]))
        assert po.check_file(api, po.lookup_repo(api, "alice", "skins"), 4).status == "unverified"

    def test_file_missing(self):
        api = FakeAPI(dict([repo_route("alice", "skins", "User")]))
        v = po.check_file(api, po.lookup_repo(api, "alice", "skins"), 77)
        assert v.status == "unverified"


# ---------------------------------------------------------------------------
# Event gating and the flow around it
# ---------------------------------------------------------------------------

class TestFlow:
    def test_non_owner_gets_file_instructions_and_nothing_changes(self, tree):
        api = FakeAPI(dict([repo_route("alice", "skins", "User")]))
        run = FakeRun()
        out = run_it(ctx(author="mallory"), api, tree, run)
        assert out["outcome"] == "unverified"
        [c] = api.comments()
        assert ".emuskins-optout" in c and "77" in c and "/verify" in c
        assert run.cmds == []
        assert bl.load_blocklist() == []
        assert len(list(tree[1].rglob("*.json"))) == 5

    def test_verify_comment_from_non_author_is_ignored(self, tree):
        api = FakeAPI(dict([repo_route("alice", "skins", "User"), file_route("alice", "skins", "77")]))
        out = run_it(ctx(author="mallory", event="issue_comment", comment_body="/verify",
                         comment_author="alice"), api, tree)
        assert out["outcome"] == "ignored"
        assert api.calls == []

    def test_non_verify_comment_is_ignored(self, tree):
        api = FakeAPI()
        out = run_it(ctx(event="issue_comment", comment_body="thanks!", comment_author="alice"), api, tree)
        assert out["outcome"] == "ignored" and api.calls == []

    def test_verify_by_author_with_file_removes_and_blocks_one_repo(self, tree):
        api = FakeAPI(dict([repo_route("alice", "skins", "User"), file_route("alice", "skins", "77")]))
        out = run_it(ctx(author="mallory-is-not-owner", event="issue_comment", comment_body="/verify",
                         comment_author="mallory-is-not-owner"), api, tree)
        assert out["outcome"] == "removed" and out["method"] == "file"
        assert out["match"] == "alice/skins"

    def test_closed_or_removed_issue_ignored(self, tree):
        api = FakeAPI(dict([repo_route("alice", "skins", "User")]))
        assert run_it(ctx(state="closed"), api, tree)["outcome"] == "ignored"
        assert run_it(ctx(labels=("repo-optout", "removed")), api, tree)["outcome"] == "ignored"

    def test_unreadable_url_gets_a_comment(self, tree):
        api = FakeAPI()
        out = run_it(ctx(url="https://example.com/nope"), api, tree)
        assert out["outcome"] == "bad_url" and api.comments()

    def test_missing_repo_reported(self, tree):
        api = FakeAPI()
        out = run_it(ctx(), api, tree)
        assert out["outcome"] == "not_found"

    def test_all_repos_checkbox_with_file_method_blocks_one_repo_and_says_so(self, tree):
        api = FakeAPI(dict([repo_route("alice", "skins", "User"), file_route("alice", "skins", "77")]))
        out = run_it(ctx(author="collab", all_repos=True, event="issue_comment",
                         comment_body="/verify", comment_author="collab"), api, tree)
        assert out["match"] == "alice/skins"  # never alice/*
        assert [e["match"] for e in bl.load_blocklist()] == ["alice/skins"]

    def test_unverified_all_repos_comment_explains_scope(self, tree):
        api = FakeAPI(dict([repo_route("alice", "skins", "User")]))
        run_it(ctx(author="collab", all_repos=True), api, tree)
        assert "only" in api.comments()[0] and "alice/skins" in api.comments()[0]


# ---------------------------------------------------------------------------
# Cleanup
# ---------------------------------------------------------------------------

class TestCleanup:
    def owner_api(self):
        return FakeAPI(dict([repo_route("alice", "skins", "User")]))

    def test_dry_run_changes_nothing_and_runs_nothing(self, tree):
        api, run = self.owner_api(), FakeRun()
        before = sorted(str(p) for p in tree[0].rglob("*") if p.is_file())
        out = run_it(ctx(), api, tree, run, dry_run=True)
        assert out["outcome"] == "removed" and out["removed"] == 3
        assert run.cmds == []                      # no git, no gh
        assert api.writes() == []                  # no comment, label, close
        assert bl.load_blocklist() == []           # blocklist untouched
        assert before == sorted(str(p) for p in tree[0].rglob("*") if p.is_file())

    def test_removes_matching_skins_thumbnails_and_only_those(self, tree):
        out = run_it(ctx(), self.owner_api(), tree)
        _, skins, thumbs = tree
        assert out["removed"] == 3 and out["outcome"] == "removed"
        left = sorted(p.stem for p in skins.rglob("*.json"))
        assert left == ["b1", "d1"]                          # repack (originalURL) and deltastyles-listed release included
        assert sorted(p.name for p in thumbs.iterdir()) == [
            "bbbb000000000001-landscape.png", "bbbb000000000001.png",
            "dddd000000000001-landscape.png", "dddd000000000001.png"]

    def test_blocklist_entry_written(self, tree):
        run_it(ctx(), self.owner_api(), tree)
        assert bl.load_blocklist() == [{"match": "alice/skins", "issue": 77, "verifiedBy": "alice",
                                        "method": "owner", "date": "2026-11-02"}]

    def test_owner_wildcard_removes_every_repo_of_the_account(self, tree):
        _, skins, _ = tree
        (skins / "gba" / "a9.json").write_text(json.dumps({
            "id": "aaaa000000000009", "name": "A9", "source": "alice/other",
            "downloadURL": "https://raw.githubusercontent.com/alice/other/HEAD/a9.deltaskin"}))
        out = run_it(ctx(all_repos=True), self.owner_api(), tree)
        assert out["match"] == "alice/*" and out["removed"] == 4

    def test_git_and_gh_commands(self, tree):
        run = FakeRun()
        run_it(ctx(), self.owner_api(), tree, run)
        cmds = run.cmds
        flat = [" ".join(c) for c in cmds]
        assert any(c.startswith("git add -A --") for c in flat)
        commit = next(c for c in cmds if c[:2] == ["git", "commit"])
        assert "alice/skins" in commit[3] and "#77" in commit[3]
        assert ["git", "push", "origin", "HEAD:main"] in cmds
        # commit and push come before any release asset deletion
        first_delete = next(i for i, c in enumerate(cmds) if c[:3] == ["gh", "release", "delete-asset"])
        assert cmds.index(["git", "push", "origin", "HEAD:main"]) < first_delete
        deleted = {(c[3], c[4]) for c in cmds if c[:3] == ["gh", "release", "delete-asset"]}
        assert ("thumbnails", "aaaa000000000001.png") in deleted
        assert ("thumbnails", "aaaa000000000001-landscape.png") in deleted
        assert ("mirror", "aaaa000000000002.deltaskin") in deleted      # only the mirrored one
        assert not any(t == "mirror" and n.startswith(("aaaa000000000001", "aaaa000000000003")) for t, n in deleted)
        assert not any(n.startswith("bbbb") for _, n in deleted)
        assert all("--yes" in c and c[-2:] == ["--repo", "Provenance-Emu/skins"]
                   for c in cmds if c[:3] == ["gh", "release", "delete-asset"])
        # rebuild dispatched last
        assert cmds[-1][:4] == ["gh", "workflow", "run", "build-catalog.yml"]

    def test_comment_label_close(self, tree):
        api = self.owner_api()
        run_it(ctx(), api, tree)
        [comment] = api.comments()
        assert "Skins removed: 3" in comment and "alice/skins" in comment
        posts = [(c[0], c[1]) for c in api.writes()]
        assert ("POST", "/repos/Provenance-Emu/skins/labels") in posts            # creates `removed` first
        label = next(c for c in api.writes() if c[1].endswith("/issues/77/labels"))
        assert label[2] == {"labels": ["removed"]}
        close = next(c for c in api.writes() if c[0] == "PATCH")
        assert close[2]["state"] == "closed"

    def test_missing_release_asset_is_not_a_failure(self, tree):
        run = FakeRun(fail=lambda c: "release asset not found" if c[:3] == ["gh", "release", "delete-asset"] else None)
        api = self.owner_api()
        out = run_it(ctx(), api, tree, run)
        assert out["outcome"] == "removed" and out["failures"] == []
        assert any(c[0] == "PATCH" for c in api.writes())

    def test_real_asset_failure_leaves_issue_open(self, tree):
        run = FakeRun(fail=lambda c: "HTTP 500" if c[:3] == ["gh", "release", "delete-asset"] else None)
        api = self.owner_api()
        out = run_it(ctx(), api, tree, run)
        assert out["outcome"] == "partial" and out["failures"]
        assert not any(c[0] == "PATCH" for c in api.writes())
        assert "maintainer" in api.comments()[0]

    def test_failed_git_add_deletes_no_release_assets_and_does_not_close(self, tree):
        """If the removal never reaches main, the skin files are still live: touching
        their thumbnails or mirror files would leave them pointing at nothing."""
        run = FakeRun(fail=lambda c: "fatal: pathspec 'thumbnails' did not match" if c[:3] == ["git", "add", "-A"] else None)
        api = self.owner_api()
        with pytest.raises(RuntimeError, match="git add failed"):
            run_it(ctx(), api, tree, run)
        assert not any(c[:3] == ["gh", "release", "delete-asset"] for c in run.cmds)
        assert not any(c[0] == "PATCH" for c in api.writes())

    def test_nothing_staged_with_victims_deletes_no_release_assets(self, tree):
        run = FakeRun(staged=False)
        api = self.owner_api()
        with pytest.raises(RuntimeError, match="not committed"):
            run_it(ctx(), api, tree, run)
        assert not any(c[:3] == ["gh", "release", "delete-asset"] for c in run.cmds)
        assert not any(c[0] == "PATCH" for c in api.writes())

    def test_rebase_conflict_aborts_and_never_counts_as_pushed(self, tree):
        """`git pull --rebase` failing leaves HEAD at origin/main without our commit;
        a push from there is a no-op that succeeds. It must not read as 'pushed'."""
        run = FakeRun(fail=lambda c: "CONFLICT (modify/delete)" if c[:3] == ["git", "pull", "--rebase"] else None)
        api = self.owner_api()
        with pytest.raises(RuntimeError, match="push failed"):
            run_it(ctx(), api, tree, run)
        assert ["git", "rebase", "--abort"] in run.cmds
        assert ["git", "push", "origin", "HEAD:main"] not in run.cmds
        assert not any(c[:3] == ["gh", "release", "delete-asset"] for c in run.cmds)

    def test_rebase_retry_then_push_succeeds(self, tree):
        calls = {"n": 0}

        def fail(c):
            if c[:3] == ["git", "pull", "--rebase"]:
                calls["n"] += 1
                return "CONFLICT" if calls["n"] == 1 else None
        run = FakeRun(fail=fail)
        out = run_it(ctx(), self.owner_api(), tree, run)
        assert out["outcome"] == "removed"
        assert run.cmds.count(["git", "rebase", "--abort"]) == 1

    def test_skin_file_cannot_aim_cleanup_at_other_assets(self, tree):
        """`id`, `downloadURL` and `source` come from the skin file (a JSON-metadata
        submission supplies all three). A file owned by an opted-out repo must not
        be able to delete another skin's thumbnails, mirror file, or any other file."""
        _, skins, thumbs = tree
        (thumbs / "evil.png").write_bytes(b"png")
        (tree[0] / "keep.png").write_bytes(b"png")
        (skins / "gba" / "x1.json").write_text(json.dumps({
            "id": "../keep", "name": "X1", "source": "alice/skins",
            "downloadURL": "https://raw.githubusercontent.com/alice/skins/HEAD/x1.deltaskin"}))
        (skins / "gba" / "x2.json").write_text(json.dumps({
            "id": "dddd000000000001", "name": "X2", "source": "alice/skins",   # D1's id
            "downloadURL": "https://github.com/Provenance-Emu/skins/releases/download/mirror/bbbb000000000001.deltaskin"}))
        (skins / "gba" / "x3.json").write_text(json.dumps({
            "id": "aaaa00000000000f", "name": "X3", "source": "alice/skins",
            "downloadURL": "https://github.com/Provenance-Emu/skins/releases/download/mirror/--repo=evil%2Fx.deltaskin"}))
        run = FakeRun()
        out = run_it(ctx(), self.owner_api(), tree, run)
        assert out["outcome"] == "removed"
        deleted = {(c[3], c[4]) for c in run.cmds if c[:3] == ["gh", "release", "delete-asset"]}
        assert not any(n.startswith(("..", "dddd", "bbbb", "--")) for _, n in deleted)
        assert ("mirror", "aaaa00000000000f.deltaskin") not in deleted
        assert (tree[0] / "keep.png").exists()                       # no traversal out of thumbnails/
        assert (thumbs / "dddd000000000001.png").exists()            # D1 still in the catalog
        assert (thumbs / "dddd000000000001-landscape.png").exists()

    def test_no_matching_skins_still_blocks_and_closes(self, tree):
        api = FakeAPI(dict([repo_route("carol", "skins", "User")]))
        run = FakeRun()
        out = run_it(ctx(url="https://github.com/carol/skins", author="carol"), api, tree, run)
        assert out["removed"] == 0
        assert [e["match"] for e in bl.load_blocklist()] == ["carol/skins"]
        assert not any(c[:3] == ["gh", "workflow", "run"] for c in run.cmds)
        assert any(c[0] == "PATCH" for c in api.writes())

    def test_second_request_does_not_duplicate_entry(self, tree):
        run_it(ctx(), self.owner_api(), tree)
        run_it(ctx(number=78), self.owner_api(), tree)
        assert len(bl.load_blocklist()) == 1

    def test_crawl_does_not_bring_them_back(self, tree):
        """After cleanup the JSON files are gone, so crawl dedup no longer protects them."""
        import process_submission as ps
        run_it(ctx(), self.owner_api(), tree)
        called = []
        import unittest.mock as mock
        with mock.patch.object(ps, "gh_api", side_effect=lambda *a, **k: called.append(a) or {"tree": []}):
            assert ps.process_github_repo("alice/skins") == []
        assert called == []   # the API was never even asked


class TestGitHubAPIClient:
    def test_headers_and_auth(self, monkeypatch):
        seen = {}

        class R:
            status = 204
            def read(self): return b""
            def __enter__(self): return self
            def __exit__(self, *a): return False

        def fake_urlopen(req, timeout=0):
            seen["req"] = req
            return R()

        monkeypatch.setattr(po, "urlopen", fake_urlopen)
        status, data = po.GitHubAPI("tok").request("GET", "/orgs/acme/public_members/alice")
        assert (status, data) == (204, None)
        assert seen["req"].full_url == "https://api.github.com/orgs/acme/public_members/alice"
        assert seen["req"].get_header("Authorization") == "Bearer tok"

    def test_context_from_env(self):
        c = po.Context.from_env({"ISSUE_NUMBER": "5", "ISSUE_AUTHOR": "a", "ISSUE_BODY": "b",
                                 "ISSUE_LABELS": '["repo-optout"]', "EVENT_NAME": "issues"})
        assert c.issue_number == 5 and c.labels == ["repo-optout"]
