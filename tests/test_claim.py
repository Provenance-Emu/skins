"""Tests for process_claim.py, mirror_creator_images.py and github_ownership.py
against a mocked GitHub API, a mocked gh/git runner and mocked image fetches."""

import base64
import io
import json
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

import pytest
import creator_directory
import github_ownership as go
import mirror_creator_images as mirror
import polite_http
import process_claim as pc
import process_optout as po
from skin_schema import validate_creator

REPO = "Provenance-Emu/skins"
ROOT = Path(__file__).parent.parent
MAINTAINERS = {"joematt"}


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
        return 404, None

    def writes(self):
        return [c for c in self.calls if c[0] != "GET"]

    def comments(self):
        return [c[2]["body"] for c in self.calls if c[0] == "POST" and c[1].endswith("/comments")]

    def labels(self):
        return [c[2]["labels"][0] for c in self.calls if c[0] == "POST" and c[1].endswith("/labels") and "labels" in (c[2] or {})]

    def closed(self):
        return any(c[0] == "PATCH" and (c[2] or {}).get("state") == "closed" for c in self.calls)


def repo_route(owner, repo, otype="User", default="main"):
    return ("GET", f"/repos/{owner}/{repo}"), (200, {
        "full_name": f"{owner}/{repo}", "owner": {"login": owner, "type": otype}, "default_branch": default})


def member_route(org, login):
    return ("GET", f"/orgs/{org}/public_members/{login}"), (204, None)


def file_route(owner, repo, content, branch="main"):
    return ("GET", f"/repos/{owner}/{repo}/contents/.emuskins-creator?ref={branch}"), (200, {
        "encoding": "base64", "content": base64.b64encode(content.encode()).decode()})


def comments_route(number, bodies):
    return ("GET", f"/repos/{REPO}/issues/{number}/comments?per_page=100&page=1"), (200, [
        {"user": {"login": "github-actions[bot]"}, "body": b} for b in bodies])


class FakeRun:
    """Records git/gh commands. `release_exists` answers `gh release view`."""

    def __init__(self, fail=None, release_exists=True):
        self.cmds = []
        self.fail = fail or (lambda cmd: None)
        self.release_exists = release_exists

    def __call__(self, cmd):
        self.cmds.append(cmd)
        err = self.fail(cmd)
        if err:
            return subprocess.CompletedProcess(cmd, 1, "", err)
        if cmd[:3] == ["git", "diff", "--cached"]:
            return subprocess.CompletedProcess(cmd, 1, "", "")
        if cmd[:3] == ["gh", "release", "view"] and not self.release_exists:
            return subprocess.CompletedProcess(cmd, 1, "", "release not found")
        return subprocess.CompletedProcess(cmd, 0, "", "")

    def starting(self, *prefix):
        return [c for c in self.cmds if c[:len(prefix)] == list(prefix)]


def fake_prepare(url, kind):
    if "bad" in url:
        raise mirror.ImageError(f"{kind} isn't an image I can read")
    return f"png:{kind}".encode()


def form_body(names="Alice", display="", bio="", avatar="", banner="", links="", socials="", confirmed=True):
    def field(label, value):
        return f"### {label}\n\n{value if value else '_No response_'}\n\n"
    box = "- [X] I made these skins, or I am the account that publishes them." if confirmed else \
          "- [ ] I made these skins, or I am the account that publishes them."
    return (field("Your name on EmuSkins", names) + field("Display name", display) + field("Bio", bio) +
            field("Avatar URL", avatar) + field("Banner URL", banner) + field("Links", links) +
            field("Socials", socials) + f"### Confirmation\n\n{box}\n")


def ctx(body=None, author="alice", number=88, event="issues", comment_body="", comment_author="",
        state="open", labels=("creator-claim",)):
    return pc.Context(repo=REPO, event=event, issue_number=number, issue_author=author,
                      issue_body=body if body is not None else form_body(), issue_state=state,
                      labels=list(labels), comment_body=comment_body, comment_author=comment_author)


@pytest.fixture
def tree(tmp_path):
    skins = tmp_path / "skins"
    (skins / "gba").mkdir(parents=True)
    (tmp_path / "creators").mkdir()
    n = [0]

    def add(author, source):
        n[0] += 1
        (skins / "gba" / f"s{n[0]}.json").write_text(json.dumps(
            {"id": f"{n[0]:016x}", "name": f"S{n[0]}", "author": author, "source": source}))

    add("Alice", "alice/skins")
    add("Alice", "alice/skins")
    add("alice_old", "alice/skins")
    add("AcmeCrew", "acme/skins")
    add("DeltaDan", "deltastyles.com")
    add("DeltaDan", "deltastyles.com")
    add("Mixed", "alice/skins")
    add("Mixed", "deltastyles.com")
    add("Bob", "carol/skins")
    add("Foo Bar", "deltastyles.com")
    add("Foo-Bar", "deltastyles.com")
    add("Dana", "deltastyles.com")
    return tmp_path


def claim(tree, context, api, run=None, dry_run=False, prepare=fake_prepare, maintainers=MAINTAINERS):
    return pc.run_claim(context, api, run=run or FakeRun(), dry_run=dry_run,
                        skins_dir=str(tree / "skins"), creators_dir=str(tree / "creators"),
                        maintainers=maintainers, today="2026-11-10", prepare_image=prepare)


def written(tree, slug):
    return json.loads((tree / "creators" / f"{slug}.json").read_text())


def alice_api(*extra):
    """alice owns alice/skins; `extra` are more (key, response) route pairs."""
    return FakeAPI(dict([repo_route("alice", "skins"), *extra]))


# ---------------------------------------------------------------------------
# Form parsing and name resolution
# ---------------------------------------------------------------------------

class TestParseForm:
    def test_full_form(self):
        f = pc.parse_form(form_body(
            names="Alice\nalice_old\nAlice", display="Alice D", bio="Soft skins.\nSecond line.",
            avatar="https://example.com/a.png", banner="https://example.com/b.png",
            links="Website | https://example.com\nShop | https://shop.example.com/x | y",
            socials="GitHub: @alice\nbluesky: alice.bsky.social"))
        assert f.errors == []
        assert f.names == ["Alice", "alice_old"]
        assert f.display_name == "Alice D"
        assert f.bio == "Soft skins.\nSecond line."
        assert f.links[1] == {"label": "Shop", "url": "https://shop.example.com/x | y"}
        assert f.socials == {"github": "alice", "bluesky": "alice.bsky.social"}
        assert f.confirmed

    def test_no_response_is_empty(self):
        f = pc.parse_form(form_body())
        assert (f.display_name, f.bio, f.avatar, f.banner, f.links, f.socials) == ("", "", "", "", [], {})

    def test_bad_lines_and_unticked_box(self):
        f = pc.parse_form(form_body(links="no pipe here", socials="justakey\nx: a\nx: b", confirmed=False))
        assert len(f.errors) == 4
        assert any("isn't `label | url`" in e for e in f.errors)
        assert any("isn't `key: handle`" in e for e in f.errors)
        assert any("listed twice" in e for e in f.errors)
        assert any("Tick the box" in e for e in f.errors)

    def test_missing_names(self):
        assert any("no name" in e for e in pc.parse_form(form_body(names="")).errors)

    def test_too_many_names(self):
        names = "\n".join(f"n{i}" for i in range(pc.MAX_NAMES + 1))
        assert any("more than" in e for e in pc.parse_form(form_body(names=names)).errors)


class TestResolveNames:
    def test_exact_url_and_hint(self, tree):
        entries = pc.load_entries(str(tree / "skins"))
        assert pc.resolve_names(["Alice"], entries, []) == (["Alice"], [])
        assert pc.resolve_names(["https://emuskins.com/authors/deltadan.html"], entries, [])[0] == ["DeltaDan"]
        _, problems = pc.resolve_names(["alice"], entries, [])
        assert "Did you mean ` Alice `" not in problems[0] and "Did you mean `Alice`" in problems[0]
        _, problems = pc.resolve_names(["Nobody"], entries, [])
        assert "exactly" in problems[0]

    def test_url_covering_two_spellings_is_refused(self, tree):
        entries = pc.load_entries(str(tree / "skins"))
        names, problems = pc.resolve_names(["https://emuskins.com/authors/foo-bar.html"], entries, [])
        assert names == [] and "several author spellings" in problems[0]

    def test_url_of_claimed_page_gives_its_aliases(self, tree):
        entries = pc.load_entries(str(tree / "skins"))
        creators = [{"slug": "alice", "aliases": ["Alice", "alice_old"]}]
        names, _ = pc.resolve_names(["https://emuskins.com/authors/alice.html"], entries, creators)
        assert names == ["Alice", "alice_old"]


def test_code_span_neutralises_mentions_and_ticks():
    assert pc.code("@everyone") == "`@everyone`"
    assert pc.code("a`b") == "``a`b``"
    assert "\n" not in pc.code("a\nb")
    assert pc.code("`x`").startswith("`` `x`")


# ---------------------------------------------------------------------------
# Event gating
# ---------------------------------------------------------------------------

class TestShouldHandle:
    @pytest.mark.parametrize("kw,mode", [
        (dict(), "open"),
        (dict(event="issue_comment", comment_body="/verify", comment_author="Alice"), "verify"),
        (dict(event="issue_comment", comment_body="/approve aliases: x", comment_author="JoeMatt"), "approve"),
    ])
    def test_handled(self, kw, mode):
        assert pc.should_handle(ctx(**kw), MAINTAINERS)[0] == mode

    @pytest.mark.parametrize("kw", [
        dict(state="closed"),
        dict(labels=("creator-claim", "claimed")),
        dict(event="issue_comment", comment_body="/verify", comment_author="mallory"),
        dict(event="issue_comment", comment_body="/approve", comment_author="alice"),
        dict(event="issue_comment", comment_body="looks good", comment_author="alice"),
        dict(event="issue_comment", comment_body="/verify", comment_author=""),
        dict(event="pull_request"),
    ])
    def test_ignored(self, kw):
        assert pc.should_handle(ctx(**kw), MAINTAINERS)[0] is None

    def test_ignored_does_nothing(self, tree):
        api = FakeAPI()
        assert claim(tree, ctx(state="closed"), api)["outcome"] == "ignored"
        assert api.calls == []

    def test_alias_override_parsing(self):
        assert pc.parse_alias_override("/approve") is None
        assert pc.parse_alias_override("/approve aliases: a, b ,c") == ["a", "b", "c"]
        assert pc.parse_alias_override("/approve aliases:\nSmith, John\nJ Smith") == ["Smith, John", "J Smith"]


# ---------------------------------------------------------------------------
# Verification paths
# ---------------------------------------------------------------------------

class TestSourceVerification:
    def test_repo_owner_completes_with_no_human(self, tree):
        api, run = alice_api(), FakeRun()
        out = claim(tree, ctx(form_body(bio="Soft skins.", socials="github: alice",
                                        links="Site | https://example.com")), api, run)
        assert out["outcome"] == "claimed" and out["method"] == "source"
        profile = written(tree, "alice")
        assert profile["githubLogin"] == "alice" and profile["aliases"] == ["Alice"]
        assert profile["avatarURL"] == "https://github.com/alice.png"
        assert profile["claim"] == {"issue": 88, "method": "source", "verifiedAt": "2026-11-10"}
        assert profile["hidden"] is False
        assert validate_creator(profile, filename_slug="alice") == []
        creators, errs = creator_directory.load_creators(str(tree / "creators"))
        assert errs == [] and creator_directory.validate_creators(creators) == []

        # images uploaded before the commit, build dispatched after it
        order = [c[:3] for c in run.cmds]
        upload = order.index(["gh", "release", "upload"])
        commit = order.index(["git", "commit", "-m"])
        dispatch = order.index(["gh", "workflow", "run"])
        assert upload < commit < dispatch
        assert run.starting("git", "add")[0][-1].endswith("alice.json")
        assert "claim alice (#88)" in run.starting("git", "commit")[0][3]

        assert "needs-maintainer" not in api.labels() and "claimed" in api.labels() and api.closed()
        assert "https://emuskins.com/authors/alice.html" in api.comments()[-1]

    def test_org_public_member(self, tree):
        api = FakeAPI(dict([repo_route("acme", "skins", "Organization"), member_route("acme", "alice")]))
        out = claim(tree, ctx(form_body(names="AcmeCrew")), api)
        assert out["outcome"] == "claimed" and out["method"] == "source"

    def test_non_member_of_org_gets_file_instructions(self, tree):
        api = FakeAPI(dict([repo_route("acme", "skins", "Organization")]))
        out = claim(tree, ctx(form_body(names="AcmeCrew")), api)
        assert out["outcome"] == "unverified"
        assert ".emuskins-creator" in api.comments()[0] and "`acme/skins`" in api.comments()[0]
        assert list((tree / "creators").iterdir()) == []

    def test_every_repo_must_verify(self, tree):
        # Alice's skins are all in alice/skins; Bob's are in carol/skins. Claiming both needs both.
        api = alice_api(repo_route("carol", "skins"))
        out = claim(tree, ctx(form_body(names="Alice\nBob")), api)
        assert out["outcome"] == "unverified"
        assert "`carol/skins`" in api.comments()[0] and "alice/skins`: verified" in api.comments()[0]


class TestFileVerification:
    def test_instructions_then_verify(self, tree):
        api = FakeAPI(dict([repo_route("carol", "skins")]))
        out = claim(tree, ctx(form_body(names="Bob"), author="bob"), api)
        assert out["outcome"] == "unverified" and list((tree / "creators").iterdir()) == []
        assert "contain" in api.comments()[0] and "`88`" in api.comments()[0]

        api = FakeAPI(dict([repo_route("carol", "skins"), file_route("carol", "skins", "claim 88\n")]))
        out = claim(tree, ctx(form_body(names="Bob"), author="bob", event="issue_comment",
                              comment_body="/verify", comment_author="bob"), api)
        assert out["outcome"] == "claimed" and out["method"] == "file"
        assert written(tree, "bob")["claim"]["method"] == "file"

    def test_file_with_wrong_number_is_refused(self, tree):
        api = FakeAPI(dict([repo_route("carol", "skins"), file_route("carol", "skins", "claim 880\n")]))
        out = claim(tree, ctx(form_body(names="Bob"), author="bob", event="issue_comment",
                              comment_body="/verify", comment_author="bob"), api)
        assert out["outcome"] == "unverified"
        assert "doesn't contain the issue number 88" in api.comments()[0]

    def test_file_is_not_read_when_the_issue_opens(self, tree):
        api = FakeAPI(dict([repo_route("carol", "skins"), file_route("carol", "skins", "88")]))
        out = claim(tree, ctx(form_body(names="Bob"), author="bob"), api)
        assert out["outcome"] == "unverified"
        assert not any("contents" in c[1] for c in api.calls)


class TestManualVerification:
    def review_hash(self, api):
        return re.search(r"emuskins-claim:([0-9a-f]{64})", api.comments()[0]).group(1)

    def test_deltastyles_waits_for_a_maintainer(self, tree):
        api = FakeAPI()
        out = claim(tree, ctx(form_body(names="DeltaDan"), author="dan"), api)
        assert out["outcome"] == "needs_maintainer"
        assert "needs-maintainer" in api.labels() and not api.closed()
        assert list((tree / "creators").iterdir()) == []
        text = api.comments()[0]
        assert "`deltastyles.com`" in text and "/approve" in text and "@joematt" in text
        assert "claimed" not in api.labels()

    def test_approve_with_the_reviewed_hash_completes(self, tree):
        first = FakeAPI()
        body = form_body(names="DeltaDan", bio="Hi")
        claim(tree, ctx(body, author="dan"), first)
        digest = self.review_hash(first)

        api = FakeAPI(dict([comments_route(88, ["unrelated", f"x\n<!-- emuskins-claim:{digest} -->"])]))
        out = claim(tree, ctx(body, author="dan", event="issue_comment", comment_body="/approve",
                              comment_author="JoeMatt"), api)
        assert out["outcome"] == "claimed" and out["method"] == "manual"
        profile = written(tree, "deltadan")
        assert profile["claim"]["method"] == "manual" and profile["githubLogin"] == "dan"
        assert "claimed" in api.labels() and api.closed()

    def test_approve_after_an_edit_asks_again(self, tree):
        first = FakeAPI()
        claim(tree, ctx(form_body(names="DeltaDan", bio="Hi"), author="dan"), first)
        digest = self.review_hash(first)

        edited = form_body(names="DeltaDan", bio="Hi, and now different")
        api = FakeAPI(dict([comments_route(88, [f"<!-- emuskins-claim:{digest} -->"])]))
        out = claim(tree, ctx(edited, author="dan", event="issue_comment", comment_body="/approve",
                              comment_author="joematt"), api)
        assert out["outcome"] == "needs_maintainer"
        assert list((tree / "creators").iterdir()) == []
        assert "didn't count" in api.comments()[0]
        assert self.review_hash(api) != digest

    def test_a_forged_marker_from_a_user_does_not_count(self, tree):
        first = FakeAPI()
        body = form_body(names="DeltaDan")
        claim(tree, ctx(body, author="dan"), first)
        digest = self.review_hash(first)
        api = FakeAPI({("GET", f"/repos/{REPO}/issues/88/comments?per_page=100&page=1"):
                       (200, [{"user": {"login": "dan"}, "body": f"<!-- emuskins-claim:{digest} -->"}])})
        out = claim(tree, ctx(body, author="dan", event="issue_comment", comment_body="/approve",
                              comment_author="joematt"), api)
        assert out["outcome"] == "needs_maintainer"

    def test_approve_without_a_prior_review_does_not_publish(self, tree):
        api = FakeAPI()
        out = claim(tree, ctx(form_body(names="DeltaDan"), author="dan", event="issue_comment",
                              comment_body="/approve", comment_author="joematt"), api)
        assert out["outcome"] == "needs_maintainer"
        assert list((tree / "creators").iterdir()) == []

    def test_approve_from_a_non_maintainer_is_ignored(self, tree):
        api = FakeAPI()
        out = claim(tree, ctx(form_body(names="DeltaDan"), author="dan", event="issue_comment",
                              comment_body="/approve", comment_author="dan"), api)
        assert out["outcome"] == "ignored" and api.calls == []

    def test_approve_can_adjust_the_alias_list(self, tree):
        first = FakeAPI()
        body = form_body(names="DeltaDan", display="Dan")
        claim(tree, ctx(body, author="dan"), first)
        digest = self.review_hash(first)

        api = FakeAPI(dict([comments_route(88, [f"<!-- emuskins-claim:{digest} -->"])]))
        out = claim(tree, ctx(body, author="dan", event="issue_comment",
                              comment_body="/approve aliases: DeltaDan, Dana", comment_author="joematt"), api)
        assert out["outcome"] == "claimed"
        assert written(tree, "dan")["aliases"] == ["DeltaDan", "Dana"]

    def test_alias_override_must_match_the_catalog(self, tree):
        first = FakeAPI()
        body = form_body(names="DeltaDan")
        claim(tree, ctx(body, author="dan"), first)
        api = FakeAPI(dict([comments_route(88, [f"<!-- emuskins-claim:{self.review_hash(first)} -->"])]))
        out = claim(tree, ctx(body, author="dan", event="issue_comment",
                              comment_body="/approve aliases: Nobody", comment_author="joematt"), api)
        assert out["outcome"] == "not_found" and list((tree / "creators").iterdir()) == []

    def test_mixed_sources_go_manual_and_report_what_was_checked(self, tree):
        api = alice_api()
        out = claim(tree, ctx(form_body(names="Mixed")), api)
        assert out["outcome"] == "needs_maintainer"
        text = api.comments()[0]
        assert "`alice/skins`: verified" in text and "`deltastyles.com`" in text

    def test_repo_that_moved_goes_manual(self, tree):
        api = FakeAPI({("GET", "/repos/alice/skins"): (200, {
            "full_name": "alice2/skins", "owner": {"login": "alice2", "type": "User"}, "default_branch": "main"})})
        out = claim(tree, ctx(), api)
        assert out["outcome"] == "needs_maintainer" and "now lives at" in api.comments()[0]

    def test_github_error_is_raised(self, tree):
        api = FakeAPI({("GET", "/repos/alice/skins"): (500, None)})
        with pytest.raises(RuntimeError, match="HTTP 500"):
            claim(tree, ctx(), api)


class TestPolicyReview:
    def test_url_in_bio_routes_a_verified_claim_to_a_maintainer(self, tree):
        body = form_body(bio="Find me at https://example.com")
        api = alice_api()
        out = claim(tree, ctx(body), api)
        assert out["outcome"] == "needs_maintainer"
        assert "bio contains a URL" in api.comments()[0]
        assert list((tree / "creators").iterdir()) == []
        digest = re.search(r"emuskins-claim:([0-9a-f]{64})", api.comments()[0]).group(1)

        api = alice_api(comments_route(88, [f"<!-- emuskins-claim:{digest} -->"]))
        out = claim(tree, ctx(body, event="issue_comment", comment_body="/approve", comment_author="joematt"), api)
        assert out["outcome"] == "claimed" and out["method"] == "source"

    def test_mature_keyword_in_bio(self, tree):
        out = claim(tree, ctx(form_body(bio="Hentai themed skins")), alice_api())
        assert out["outcome"] == "needs_maintainer"


# ---------------------------------------------------------------------------
# Validation and conflicts
# ---------------------------------------------------------------------------

class TestInvalid:
    @pytest.mark.parametrize("kw,needle", [
        (dict(bio="x" * 501), "bio is 501"),
        (dict(socials="mastodon: nothandle"), "mastodon"),
        (dict(socials="myspace: tom"), "Unknown social"),
        (dict(links="Short | https://bit.ly/abc"), "not allowed"),
        (dict(links="Plain | http://example.com"), "must be https"),
        (dict(avatar="http://example.com/a.png"), "avatarURL must be https"),
        (dict(links="\n".join(f"L{i} | https://example.com/{i}" for i in range(7))), "limit is 6"),
    ])
    def test_schema_errors_are_listed(self, tree, kw, needle):
        api, run = alice_api(), FakeRun()
        out = claim(tree, ctx(form_body(**kw)), api, run)
        assert out["outcome"] == "invalid" and needle in api.comments()[0]
        assert "/verify" in api.comments()[0]
        assert list((tree / "creators").iterdir()) == [] and run.cmds == []

    def test_form_errors(self, tree):
        api = FakeAPI()
        assert claim(tree, ctx(form_body(confirmed=False)), api)["outcome"] == "invalid"
        assert api.calls[0][0] == "POST" and "Tick the box" in api.comments()[0]

    def test_unknown_name(self, tree):
        api = FakeAPI()
        out = claim(tree, ctx(form_body(names="alice")), api)
        assert out["outcome"] == "not_found" and "Did you mean" in api.comments()[0]
        assert not any(c[1].startswith("/repos/alice") for c in api.calls)

    def test_image_that_cannot_be_mirrored_stops_before_anything_is_published(self, tree):
        api, run = alice_api(), FakeRun()
        out = claim(tree, ctx(form_body(avatar="https://example.com/bad.png")), api, run)
        assert out["outcome"] == "invalid" and "avatar isn't an image" in api.comments()[0]
        assert list((tree / "creators").iterdir()) == [] and run.cmds == []


class TestConflicts:
    def put_creator(self, tree, slug="alice", login="someone-else", aliases=("Alice",), **extra):
        profile = {"slug": slug, "displayName": slug.title(), "aliases": list(aliases), "githubLogin": login,
                   "bio": "Old bio", "avatarURL": None, "bannerURL": None, "links": [], "socials": {},
                   "claim": {"issue": 3, "method": "source", "verifiedAt": "2026-10-01"}, "hidden": False, **extra}
        (tree / "creators" / f"{slug}.json").write_text(json.dumps(profile))

    def test_alias_held_by_another_account(self, tree):
        self.put_creator(tree)
        api = alice_api()
        out = claim(tree, ctx(), api)
        assert out["outcome"] == "conflict" and "already belongs to the profile `alice`" in api.comments()[0]
        assert "needs-maintainer" in api.labels()
        assert written(tree, "alice")["githubLogin"] == "someone-else"

    def test_refiling_updates_without_new_proof_and_keeps_protected_fields(self, tree):
        self.put_creator(tree, login="alice", hidden=True)
        api = FakeAPI()  # any GitHub call would 404 and fail the claim
        out = claim(tree, ctx(form_body(bio="New bio")), api)
        assert out["outcome"] == "claimed" and out["updated"] is True
        assert not any(c[1].startswith("/repos/alice") for c in api.calls)
        profile = written(tree, "alice")
        assert profile["bio"] == "New bio" and profile["hidden"] is True and profile["slug"] == "alice"
        assert profile["claim"]["method"] == "source" and profile["claim"]["issue"] == 88
        assert "Updated" in api.comments()[-1]

    def test_refile_adding_a_name_verifies_only_the_new_one(self, tree):
        self.put_creator(tree, login="alice")
        api = alice_api()
        out = claim(tree, ctx(form_body(names="Alice\nalice_old")), api)
        assert out["outcome"] == "claimed"
        assert written(tree, "alice")["aliases"] == ["Alice", "alice_old"]
        assert any(c[1] == "/repos/alice/skins" for c in api.calls)

        # a new name from somewhere the claimant doesn't control is not waved through
        self.put_creator(tree, slug="zed", login="alice", aliases=("Foo Bar",))
        out = claim(tree, ctx(form_body(names="Foo Bar\nDeltaDan")), alice_api())
        assert out["outcome"] == "needs_maintainer"

    def test_slug_that_belongs_to_another_author_is_a_conflict(self, tree):
        # "Foo Bar" and "Foo-Bar" both slug to foo-bar; claiming one leaves the other colliding.
        api = FakeAPI()
        out = claim(tree, ctx(form_body(names="Foo Bar"), author="foo"), api)
        assert out["outcome"] == "conflict"
        assert "foo-bar" in api.comments()[0] and "needs-maintainer" in api.labels()

    def test_display_name_slug_colliding_with_an_unclaimed_author(self, tree):
        api = alice_api()
        out = claim(tree, ctx(form_body(display="Dana")), api)
        assert out["outcome"] == "conflict"
        assert "dana" in api.comments()[0] and "needs-maintainer" in api.labels()
        assert list((tree / "creators").iterdir()) == []


# ---------------------------------------------------------------------------
# Dry run, partial failure
# ---------------------------------------------------------------------------

class TestRuns:
    def test_dry_run_writes_nothing(self, tree, capsys):
        api, run = alice_api(), FakeRun()
        out = claim(tree, ctx(form_body(bio="Soft skins.")), api, run, dry_run=True)
        assert out["outcome"] == "claimed"
        assert list((tree / "creators").iterdir()) == []
        assert run.cmds == []
        assert api.writes() == []
        printed = capsys.readouterr().out
        assert "[dry-run] would write" in printed and "gh workflow run build-catalog.yml" in printed
        assert "alice-avatar.png" in printed

    def test_dispatch_failure_leaves_the_issue_open(self, tree):
        api = alice_api()
        run = FakeRun(fail=lambda c: "boom" if c[:3] == ["gh", "workflow", "run"] else None)
        out = claim(tree, ctx(), api, run)
        assert out["outcome"] == "partial" and not api.closed()
        assert "build-catalog.yml dispatch" in api.comments()[-1]

    def test_push_failure_raises_before_anything_is_closed(self, tree):
        api = alice_api()
        run = FakeRun(fail=lambda c: "rejected" if c[:2] == ["git", "push"] else None)
        with pytest.raises(RuntimeError, match="push failed"):
            claim(tree, ctx(), api, run)
        assert not api.closed()

    def test_upload_failure_raises_before_the_commit(self, tree):
        run = FakeRun(fail=lambda c: "nope" if c[:3] == ["gh", "release", "upload"] else None)
        with pytest.raises(RuntimeError, match="could not upload"):
            claim(tree, ctx(), alice_api(), run)
        assert run.starting("git", "commit") == []

    def test_banner_is_mirrored_when_given(self, tree):
        run = FakeRun()
        claim(tree, ctx(form_body(banner="https://example.com/banner.png")), alice_api(), run)
        uploaded = [Path(c[4]).name for c in run.starting("gh", "release", "upload")]
        assert sorted(uploaded) == ["alice-avatar.png", "alice-banner.png"]


def test_context_from_env():
    c = pc.Context.from_env({"ISSUE_NUMBER": "5", "ISSUE_AUTHOR": "a", "ISSUE_BODY": "b",
                             "ISSUE_LABELS": '["creator-claim"]', "EVENT_NAME": "issue_comment",
                             "COMMENT_BODY": "/verify", "COMMENT_AUTHOR": "a"})
    assert c.issue_number == 5 and c.labels == ["creator-claim"] and c.comment_body == "/verify"


# ---------------------------------------------------------------------------
# Files that ship with the bot
# ---------------------------------------------------------------------------

class TestShippedFiles:
    def test_issue_template_labels_match_the_parser(self):
        text = (ROOT / ".github/ISSUE_TEMPLATE/claim-profile.yml").read_text()
        labels = {m.group(1).strip().lower() for m in re.finditer(r"^\s+label:\s*(.+)$", text, re.M)
                  if not m.group(1).strip().startswith("I made")}
        assert labels == {pc.F_NAMES, pc.F_DISPLAY, pc.F_BIO, pc.F_AVATAR, pc.F_BANNER,
                          pc.F_LINKS, pc.F_SOCIALS, pc.F_CONFIRM}
        assert 'labels: ["creator-claim"]' in text and 'title: "Claim profile: "' in text
        assert f"### {pc.F_NAMES.title()}".lower() in pc.FORM_HEADING.lower()

    def test_workflow_passes_issue_text_only_through_env(self):
        text = (ROOT / ".github/workflows/claim-profile.yml").read_text()
        for line in text.splitlines():
            if "${{" in line and not line.lstrip().startswith("#"):
                assert re.match(r"^\s+[A-Z_]+: .*\$\{\{ [^}]+ \}\}", line), f"expression outside env: {line!r}"
        run_blocks = re.findall(r"^\s+run: (.+)$", text, re.M)
        assert all("${{" not in r for r in run_blocks)
        assert "python3 scripts/process_claim.py" in text and "concurrency:" in text
        # the issue-body heading in the `if:` is the form's first heading
        assert pc.FORM_HEADING in text


# ---------------------------------------------------------------------------
# github_ownership.py
# ---------------------------------------------------------------------------

class TestGitHubOwnership:
    def test_optout_re_exports_the_shared_code(self):
        assert po.lookup_repo is go.lookup_repo and po.check_account is go.check_account
        assert po.Verification is go.Verification and po.parse_sections is go.parse_sections
        assert po.commit_and_push is go.commit_and_push and po.Issue is go.Issue
        assert issubclass(po.GitHubAPI, go.GitHubAPI) and issubclass(pc.GitHubAPI, go.GitHubAPI)

    def test_user_agents(self):
        assert "optout" in po.GitHubAPI.user_agent and "claim" in pc.GitHubAPI.user_agent

    def test_check_file_takes_the_file_name(self):
        v = go.Verification("unverified", full_name="carol/skins", default_branch="main")
        api = FakeAPI(dict([file_route("carol", "skins", "n: 7")]))
        go.check_file(api, v, 7, ".emuskins-creator")
        assert v.status == "verified" and v.method == "file"
        v2 = go.Verification("unverified", full_name="carol/skins", default_branch="main")
        go.check_file(FakeAPI(), v2, 7, ".emuskins-creator")
        assert v2.status == "unverified" and ".emuskins-creator" in v2.notes[0]

    def test_issue_comments_pages(self):
        page1 = [{"body": str(i)} for i in range(100)]
        api = FakeAPI({
            ("GET", f"/repos/{REPO}/issues/9/comments?per_page=100&page=1"): (200, page1),
            ("GET", f"/repos/{REPO}/issues/9/comments?per_page=100&page=2"): (200, [{"body": "last"}]),
        })
        got = go.Issue(api, ctx(number=9), dry_run=True).comments()
        assert len(got) == 101 and got[-1]["body"] == "last"


# ---------------------------------------------------------------------------
# mirror_creator_images.py
# ---------------------------------------------------------------------------

def png(size=(10, 10), color=(200, 30, 30, 255), fmt="PNG", mode="RGBA"):
    from PIL import Image
    buf = io.BytesIO()
    Image.new(mode, size, color if mode == "RGBA" else color[:3]).save(buf, fmt)
    return buf.getvalue()


class FakeClient:
    """Stands in for polite_http.PoliteClient: maps url -> Response."""

    def __init__(self, responses):
        self.responses = responses
        self.requested = []

    def request(self, url, **kw):
        self.requested.append((url, kw))
        r = self.responses[url]
        if isinstance(r, Exception):
            raise r
        return r


def resp(body=b"", status=200, location=None):
    headers = {"location": location} if location else {}
    return polite_http.Response(status, headers, body, "")


PUBLIC = lambda host: None  # noqa: E731


class TestMirror:
    def test_resize_sizes_and_format(self):
        from PIL import Image
        a = Image.open(io.BytesIO(mirror.resize_image(png((600, 300)), "avatar")))
        b = Image.open(io.BytesIO(mirror.resize_image(png((300, 300), fmt="JPEG", mode="RGB"), "banner")))
        assert a.size == (256, 256) and a.format == "PNG"
        assert b.size == (1200, 400) and b.format == "PNG"

    def test_not_an_image(self):
        with pytest.raises(mirror.ImageError, match="avatar isn't an image"):
            mirror.resize_image(b"<svg xmlns='http://www.w3.org/2000/svg'/>", "avatar")

    def test_unsupported_format(self):
        from PIL import Image
        buf = io.BytesIO()
        Image.new("RGB", (4, 4)).save(buf, "BMP")
        with pytest.raises(mirror.ImageError, match="PNG, JPEG, GIF or WebP"):
            mirror.resize_image(buf.getvalue(), "avatar")

    def test_too_many_pixels(self, monkeypatch):
        monkeypatch.setattr(mirror, "MAX_PIXELS", 50)
        with pytest.raises(mirror.ImageError, match="megapixels"):
            mirror.resize_image(png((10, 10)), "avatar")

    def test_too_many_bytes(self):
        with pytest.raises(mirror.ImageError, match="larger than 2 MB"):
            mirror.resize_image(b"x" * (mirror.MAX_BYTES + 1), "avatar")

    def test_fetch_follows_checked_redirects(self):
        client = FakeClient({
            "https://github.com/a.png": resp(status=302, location="https://avatars.githubusercontent.com/u/1"),
            "https://avatars.githubusercontent.com/u/1": resp(b"BODY"),
        })
        assert mirror.fetch_image_bytes("https://github.com/a.png", client=client, resolve=PUBLIC) == b"BODY"
        assert all(kw["follow_redirects"] is False and kw["max_bytes"] == mirror.MAX_BYTES + 1
                   for _, kw in client.requested)

    @pytest.mark.parametrize("location,needle", [
        ("http://example.com/a.png", "must be https"),
        ("https://bit.ly/x", "not allowed"),
        ("https://127.0.0.1/a.png", "IP address"),
    ])
    def test_redirect_to_a_bad_target(self, location, needle):
        client = FakeClient({"https://example.com/a.png": resp(status=301, location=location)})
        with pytest.raises(mirror.ImageError, match=needle):
            mirror.fetch_image_bytes("https://example.com/a.png", client=client, resolve=PUBLIC)

    def test_redirect_loop(self):
        client = FakeClient({"https://example.com/a.png": resp(status=302, location="https://example.com/a.png")})
        with pytest.raises(mirror.ImageError, match="too many redirects"):
            mirror.fetch_image_bytes("https://example.com/a.png", client=client, resolve=PUBLIC)

    def test_oversize_body(self):
        client = FakeClient({"https://example.com/a.png": resp(b"x" * (mirror.MAX_BYTES + 1))})
        with pytest.raises(mirror.ImageError, match="larger than 2 MB"):
            mirror.fetch_image_bytes("https://example.com/a.png", client=client, resolve=PUBLIC)

    def test_http_error_and_blocked_host(self):
        import urllib.error
        err = urllib.error.HTTPError("https://example.com/a.png", 404, "nf", {}, None)
        client = FakeClient({"https://example.com/a.png": err})
        with pytest.raises(mirror.ImageError, match="HTTP 404"):
            mirror.fetch_image_bytes("https://example.com/a.png", client=client, resolve=PUBLIC)
        client = FakeClient({"https://deltastyles.com/a.png": polite_http.HostBlocked("deltastyles.com", 403)})
        with pytest.raises(mirror.ImageError, match="refusing requests"):
            mirror.fetch_image_bytes("https://deltastyles.com/a.png", client=client, resolve=PUBLIC)

    def test_private_host_is_refused_without_a_request(self):
        client = FakeClient({})
        with pytest.raises(mirror.ImageError, match="private address"):
            mirror.fetch_image_bytes("https://internal.example.com/a.png", client=client,
                                     resolve=lambda h: f"{h} resolves to a private address")
        assert client.requested == []

    def test_resolver(self, monkeypatch):
        import socket

        def infos(ip):
            return lambda host, port, **kw: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, port))]

        monkeypatch.setattr(socket, "getaddrinfo", infos("10.0.0.5"))
        assert "private" in mirror._resolve_public("x.example.com")
        monkeypatch.setattr(socket, "getaddrinfo", infos("169.254.169.254"))
        assert "private" in mirror._resolve_public("x.example.com")
        monkeypatch.setattr(socket, "getaddrinfo", infos("140.82.112.3"))
        assert mirror._resolve_public("github.com") is None

        def boom(*a, **k):
            raise OSError("nxdomain")
        monkeypatch.setattr(socket, "getaddrinfo", boom)
        assert "doesn't resolve" in mirror._resolve_public("nope.example.com")

    def test_prepare_end_to_end(self):
        client = FakeClient({"https://example.com/a.png": resp(png((40, 20)))})
        out = mirror.prepare("https://example.com/a.png", "avatar", client=client, resolve=PUBLIC)
        from PIL import Image
        assert Image.open(io.BytesIO(out)).size == (256, 256)
        with pytest.raises(mirror.ImageError, match="avatar"):
            mirror.prepare("http://example.com/a.png", "avatar", client=client, resolve=PUBLIC)

    def test_asset_names_and_url(self):
        assert mirror.asset_name("alice", "banner") == "alice-banner.png"
        assert mirror.mirror_url("alice", "avatar") == f"https://github.com/{REPO}/releases/download/creators/alice-avatar.png"

    def test_upload_creates_the_release_once_and_clobbers(self):
        run = FakeRun(release_exists=False)
        names = mirror.upload(run, REPO, "alice", {"avatar": b"a", "banner": b"b"})
        assert names == ["alice-avatar.png", "alice-banner.png"]
        assert len(run.starting("gh", "release", "create")) == 1
        ups = run.starting("gh", "release", "upload")
        assert len(ups) == 2 and all("--clobber" in c for c in ups)

    def test_upload_to_an_existing_release(self):
        run = FakeRun()
        mirror.upload(run, REPO, "alice", {"avatar": b"a"})
        assert run.starting("gh", "release", "create") == []

    def test_upload_dry_run_and_empty(self, capsys):
        run = FakeRun()
        assert mirror.upload(run, REPO, "alice", {"avatar": b"a"}, dry_run=True) == ["alice-avatar.png"]
        assert mirror.upload(run, REPO, "alice", {}) == []
        assert run.cmds == [] and "dry-run" in capsys.readouterr().out

    def test_release_create_failure(self):
        run = FakeRun(release_exists=False, fail=lambda c: "denied" if c[:3] == ["gh", "release", "create"] else None)
        with pytest.raises(RuntimeError, match="could not create"):
            mirror.upload(run, REPO, "alice", {"avatar": b"a"})
