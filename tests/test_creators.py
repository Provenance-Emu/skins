"""Tests for the creators/<slug>.json schema, policy and PR authorization."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

import pytest
import creator_policy
import validate_creator
from skin_schema import SOCIAL_KEYS, social_url, validate_creator as validate, validate_entry

REPO = Path(__file__).parent.parent
EXAMPLE = REPO / "fixtures" / "creators" / "example.json"


def example():
    return json.loads(EXAMPLE.read_text())


def errors_of(**changes):
    obj = example()
    for k, v in changes.items():
        if v is KeyError:
            obj.pop(k, None)
        else:
            obj[k] = v
    return validate(obj, filename_slug="example")


def has(errors, text):
    return any(text in e for e in errors)


class TestExampleFile:
    def test_hand_written_example_validates(self):
        assert validate(example(), filename_slug="example") == []

    def test_validate_creator_cli_accepts_it(self):
        assert validate_creator.validate_file(EXAMPLE) == []

    def test_minimal_file_validates(self):
        obj = {"slug": "a", "displayName": "A", "aliases": ["A"], "githubLogin": "a"}
        assert validate(obj) == []

    def test_every_documented_social_key_is_in_the_table(self):
        assert set(SOCIAL_KEYS) == {
            "github", "discord", "x", "bluesky", "mastodon", "instagram", "youtube",
            "twitch", "tiktok", "kofi", "patreon", "buymeacoffee", "deltastyles", "reddit",
        }


class TestRequiredAndUnknownFields:
    @pytest.mark.parametrize("field", ["slug", "displayName", "aliases", "githubLogin"])
    def test_required(self, field):
        assert has(errors_of(**{field: KeyError}), f"Missing required field: {field}")

    def test_unknown_top_level_field(self):
        assert has(errors_of(avatar="x"), "Unknown field: avatar")

    def test_not_an_object(self):
        assert validate([]) == ["creator file must be a JSON object"]


class TestSlug:
    @pytest.mark.parametrize("slug", ["Example", "has space", "under_score", "x" * 51, "é"])
    def test_rejects_bad_slugs(self, slug):
        assert has(errors_of(slug=slug), "slug must be lowercase")

    def test_accepts_fifty_chars(self):
        assert validate(dict(example(), slug="x" * 50)) == []

    def test_must_match_file_name(self):
        assert has(validate(example(), filename_slug="other"), "must match the file name")

    def test_slug_regex_agrees_with_author_slug(self):
        for name in ["Hello World", "NostromoCrew01", "a" * 80, "ClearDoom by X!"]:
            assert creator_policy.SLUG_RE.fullmatch(creator_policy.author_slug(name))


class TestAliasesAndNames:
    def test_aliases_must_be_strings(self):
        assert has(errors_of(aliases=["ok", 3]), "aliases must be an array of non-empty strings")

    def test_alias_with_padding(self):
        assert has(errors_of(aliases=[" padded"]), "no leading or trailing spaces")

    def test_duplicate_alias_in_one_file(self):
        assert has(errors_of(aliases=["a", "a"]), "more than once")

    def test_display_name_limit(self):
        assert has(errors_of(displayName="n" * 101), "displayName is 101 characters")

    def test_github_login(self):
        assert has(errors_of(githubLogin="-bad"), "not a valid GitHub login")
        assert has(errors_of(githubLogin="has space"), "not a valid GitHub login")


class TestBio:
    def test_limit_is_500(self):
        assert validate(dict(example(), bio="b" * 500)) == []
        assert has(errors_of(bio="b" * 501), "limit is 500")

    def test_null_bio_ok(self):
        assert errors_of(bio=None) == []

    def test_rejects_html(self):
        assert has(errors_of(bio="hi <script>x</script>"), "plain text")

    def test_allows_comparison_signs(self):
        assert errors_of(bio="GBA < DS, and 2 > 1") == []

    def test_rejects_control_characters(self):
        assert has(errors_of(bio="a\x00b"), "control characters")

    def test_newlines_allowed(self):
        assert errors_of(bio="line one\nline two") == []

    def test_url_in_bio_is_a_review_flag_not_an_error(self):
        obj = dict(example(), bio="see https://example.com")
        assert validate(obj) == []
        assert "bio contains a URL" in creator_policy.review_reasons(obj)

    def test_clean_bio_has_no_review_reasons(self):
        assert creator_policy.review_reasons(example()) == []

    def test_mature_keyword_is_a_review_flag(self):
        import content_policy
        word = (content_policy.default_keywords().words or ["xxx"])[0]
        reasons = creator_policy.review_reasons({"bio": f"all about {word}"})
        assert any("mature keyword" in r for r in reasons)


class TestUrls:
    @pytest.mark.parametrize("url", [
        "http://example.com", "ftp://example.com/x", "javascript:alert(1)",
        "https://bit.ly/abc", "https://sub.tinyurl.com/x", "https://iplogger.org/x",
        "https://user:pw@example.com/", "https://127.0.0.1/x", "https://[::1]/x",
        "https://localhost/x", "https://example.com/a b", "", "//example.com",
    ])
    def test_link_urls_rejected(self, url):
        assert errors_of(links=[{"label": "L", "url": url}]), url

    def test_https_link_ok(self):
        assert errors_of(links=[{"label": "L", "url": "https://example.org/path?q=1"}]) == []

    def test_lookalike_host_is_not_denied(self):
        # `notbit.ly` is not `bit.ly`; only the exact host and its subdomains match.
        assert not creator_policy.host_denied("notbit.ly")
        assert creator_policy.host_denied("www.bit.ly")

    def test_max_links(self):
        links = [{"label": f"L{i}", "url": f"https://example.com/{i}"} for i in range(7)]
        assert has(errors_of(links=links), "limit is 6")
        assert errors_of(links=links[:6]) == []

    def test_label_limit(self):
        assert has(errors_of(links=[{"label": "x" * 31, "url": "https://example.com"}]), "limit is 30")

    def test_link_shape(self):
        assert has(errors_of(links=[{"label": "L"}]), "exactly `label` and `url`")
        assert has(errors_of(links=[{"label": "L", "url": "https://a.com", "x": 1}]), "exactly")
        assert has(errors_of(links=["https://a.com"]), "exactly")

    def test_image_urls_https_only(self):
        assert has(errors_of(avatarURL="http://example.com/a.png"), "avatarURL must be https")
        assert has(errors_of(bannerURL="https://bit.ly/b"), "bannerURL host is not allowed")
        assert errors_of(avatarURL=None, bannerURL="https://example.com/b.png") == []


class TestSocials:
    def test_unknown_key_fails(self):
        assert has(errors_of(socials={"myspace": "tom"}), "Unknown social: 'myspace'")

    @pytest.mark.parametrize("key,handle", [
        ("github", "https://github.com/x"), ("github", "@x"), ("x", "a/b"),
        ("x", "way_too_long_for_x_handle"), ("bluesky", "nodots"), ("mastodon", "nohost"),
        ("kofi", "has space"), ("discord", "a"), ("reddit", "u/name"),
    ])
    def test_bad_handles(self, key, handle):
        assert has(errors_of(socials={key: handle}), f"socials.{key}"), (key, handle)

    def test_handles_not_urls(self):
        assert has(errors_of(socials={"kofi": "https://ko-fi.com/x"}), "handles only")

    def test_urls_built_from_table(self):
        assert social_url("github", "aphaits") == "https://github.com/aphaits"
        assert social_url("bluesky", "aphaits.bsky.social") == "https://bsky.app/profile/aphaits.bsky.social"
        assert social_url("mastodon", "joe@Mastodon.Social") == "https://mastodon.social/@joe"
        assert social_url("kofi", "aphaits") == "https://ko-fi.com/aphaits"

    def test_discord_has_no_url(self):
        assert social_url("discord", "aphaits") is None

    def test_social_url_refuses_invalid(self):
        assert social_url("github", "a/b") is None
        assert social_url("nope", "x") is None

    def test_socials_must_be_object(self):
        assert has(errors_of(socials=["github"]), "socials must be an object")


class TestClaimAndHidden:
    def test_claim_optional(self):
        assert errors_of(claim=None) == []
        assert errors_of(claim=KeyError) == []

    @pytest.mark.parametrize("method", ["source", "file", "manual"])
    def test_methods(self, method):
        assert errors_of(claim={"issue": 1, "method": method, "verifiedAt": "2026-11-10"}) == []

    def test_bad_method(self):
        assert has(errors_of(claim={"issue": 1, "method": "vibes", "verifiedAt": "2026-11-10"}), "claim.method")

    @pytest.mark.parametrize("date", ["2026-13-01", "2026-11-31", "11/10/2026", None, "2026-11-10T00:00:00Z"])
    def test_bad_date(self, date):
        assert has(errors_of(claim={"issue": 1, "method": "file", "verifiedAt": date}), "verifiedAt")

    def test_bad_issue(self):
        for issue in (0, -1, "412", True):
            assert has(errors_of(claim={"issue": issue, "method": "file", "verifiedAt": "2026-11-10"}), "claim.issue")

    def test_unknown_claim_field(self):
        assert has(errors_of(claim={"issue": 1, "method": "file", "verifiedAt": "2026-11-10", "by": "x"}),
                   "Unknown claim field")

    def test_hidden_is_bool(self):
        assert has(errors_of(hidden="yes"), "hidden must be true or false")
        assert errors_of(hidden=True) == []


class TestEntryCreatorKey:
    def entry(self, **kw):
        return dict({"id": "a" * 16, "name": "n", "systems": ["gba"],
                     "downloadURL": "https://e.com/a.deltaskin", "source": "manual"}, **kw)

    def test_valid_override(self):
        assert validate_entry(self.entry(creator="nostromocrew01")) == []

    @pytest.mark.parametrize("bad", ["NostromoCrew01", "a b", "", 3])
    def test_invalid_override(self, bad):
        assert any("creator must be" in e for e in validate_entry(self.entry(creator=bad)))


class TestAuthorSlug:
    def test_matches_author_page_slugify(self):
        import generate_author_pages
        for name in ["Hello World", "alek_witha_k", "  --Odd!!Name-- ", "A" * 70, "名前", "x"]:
            assert creator_policy.author_slug(name) == generate_author_pages.slugify(name)

    def test_matches_for_every_current_author(self):
        import generate_author_pages
        authors = set()
        for p in (REPO / "skins").rglob("*.json"):
            a = json.loads(p.read_text()).get("author")
            if a:
                authors.add(a)
        assert authors
        for a in authors:
            assert creator_policy.author_slug(a) == generate_author_pages.slugify(a)


class TestPRAuthorization:
    owner = {"slug": "aphaits", "displayName": "aphaits", "aliases": ["aphaits"], "githubLogin": "AphaiTS"}
    maint = {"joematt"}

    def check(self, status, head, author, base=None):
        base = self.owner if base is None else base
        return validate_creator.check_change(status, base, head, author, self.maint)

    def test_owner_can_edit_bio(self):
        head = dict(self.owner, bio="new bio")
        assert self.check("M", head, "aphaits") == []

    def test_login_compare_is_case_insensitive(self):
        assert self.check("M", dict(self.owner, bio="x"), "APHAITS") == []

    def test_stranger_rejected(self):
        errs = self.check("M", dict(self.owner, bio="x"), "mallory")
        assert errs and "githubLogin" in errs[0]

    def test_stranger_cannot_delete(self):
        assert self.check("D", None, "mallory")

    def test_owner_can_delete(self):
        assert self.check("D", None, "aphaits") == []

    def test_maintainer_can_do_anything(self):
        head = dict(self.owner, githubLogin="someone-else", hidden=True)
        assert self.check("M", head, "JoeMatt") == []
        assert self.check("A", head, "joematt", base={}) == []

    def test_new_profile_needs_maintainer(self):
        errs = self.check("A", self.owner, "aphaits", base={})
        assert errs and "claim form" in errs[0]

    @pytest.mark.parametrize("field,value", [
        ("githubLogin", "mallory"), ("aliases", ["aphaits", "someone else"]),
        ("claim", {"issue": 1, "method": "manual", "verifiedAt": "2026-11-10"}),
        ("hidden", True), ("slug", "renamed"),
    ])
    def test_owner_cannot_change_protected_fields(self, field, value):
        errs = self.check("M", dict(self.owner, **{field: value}), "aphaits")
        assert errs == [f"{field} can only be changed by a maintainer"]

    def test_owner_cannot_take_over_by_changing_login(self):
        # The base file decides ownership, not the PR's own copy.
        head = dict(self.owner, githubLogin="mallory")
        assert self.check("M", head, "mallory")

    def test_load_maintainers(self, tmp_path):
        co = tmp_path / "CODEOWNERS"
        co.write_text("# comment @nobody\n*  @JoeMatt @org/team\n/scripts/ @Other # trailing\n")
        assert validate_creator.load_maintainers(co) == {"joematt", "other"}

    def test_real_codeowners_names_a_maintainer(self):
        assert "joematt" in validate_creator.load_maintainers()

    def test_load_maintainers_missing_file(self, tmp_path):
        assert validate_creator.load_maintainers(tmp_path / "nope") == set()


class TestChangedFiles:
    def fake(self, monkeypatch, stdout, code=0):
        import subprocess
        monkeypatch.setattr(validate_creator, "_git", lambda *a: subprocess.CompletedProcess(a, code, stdout, "boom"))

    def test_parses_name_status(self, monkeypatch):
        self.fake(monkeypatch, "A\tcreators/new.json\nM\tcreators/old.json\nD\tcreators/gone.json\n"
                               "M\tcreators/README.md\nM\tcreators/sub/x.json\n")
        assert validate_creator.changed_files("origin/main") == [
            ("A", "creators/new.json"), ("M", "creators/old.json"), ("D", "creators/gone.json")]

    def test_git_failure_is_fatal(self, monkeypatch):
        self.fake(monkeypatch, "", code=128)
        with pytest.raises(SystemExit):
            validate_creator.changed_files("origin/nope")
