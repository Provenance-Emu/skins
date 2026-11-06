"""Creator profiles on the generated author pages, index, skin pages and sitemap.

Each test runs a generator's main() against a small catalog and a few
creators/<slug>.json files in a temp dir (the autouse `isolated_creators`
fixture in conftest.py), so it never reads the committed, CI-generated pages.
"""

import json
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import creator_pages  # noqa: E402
import creator_profile_html as profile_html  # noqa: E402
import generate_author_pages as authors  # noqa: E402
import generate_share_cards as cards  # noqa: E402
import generate_sitemap as sitemap  # noqa: E402
import generate_skin_pages as skin_pages  # noqa: E402
from skin_schema import SOCIAL_KEYS  # noqa: E402


def skin(i, name, author, **extra):
    return {
        "id": f"{i:016x}", "name": name, "author": author, "systems": ["snes"],
        "source": "manual", "downloadURL": f"https://example.com/{i}.deltaskin",
        "thumbnailURL": f"https://example.com/thumb-{i}.png", "tags": [],
        "downloadCount": 1, "addedAt": "2026-03-01", **extra,
    }


ALICE = {
    "slug": "alice", "displayName": "Alice & Co", "aliases": ["Alice", "alice_old"],
    "githubLogin": "alice-gh",
    "bio": "Soft hardware skins.\nRequests on Discord <3 \"quoted\" & escaped.",
    "avatarURL": "https://github.com/alice-gh.png", "bannerURL": "https://example.com/banner.png",
    "links": [{"label": "Website", "url": "https://example.com/alice"}],
    "socials": {"github": "alice-gh", "discord": "alice_skins", "bluesky": "alice.bsky.social"},
    "claim": {"issue": 7, "method": "manual", "verifiedAt": "2026-11-10"},
    "hidden": False,
}

CATALOG_SKINS = [
    skin(1, "Alpha", "Alice", addedAt="2026-01-01"),
    skin(2, "Beta", "alice_old", addedAt="2026-01-02"),
    skin(3, "Gamma", "Bob", addedAt="2026-06-01"),
    skin(4, "Delta", "Bob", addedAt="2026-06-02"),
    skin(5, "Solo Skin", "Solo", addedAt="2026-09-01"),
    # Uploaded by Carol but made by Bob. `author` is an alias of Alice's profile: the override wins.
    skin(6, "Not Alice's", "Alice", creator="bob", addedAt="2026-02-01"),
    skin(7, "A Sample", "Sampler", tags=["sample"]),
    skin(8, "Mature Pad", "Alice", tags=["mature"]),
    skin(9, "Mature Only", "Shady", tags=["mature"]),
]


@pytest.fixture
def site(tmp_path, monkeypatch, isolated_creators):
    """A temp catalog plus a claimed profile for Alice; returns a helper to read generated pages."""
    catalog = tmp_path / "catalog.json"
    catalog.write_text(json.dumps({"version": 2, "skins": CATALOG_SKINS}))
    isolated_creators.mkdir()
    (isolated_creators / "alice.json").write_text(json.dumps(ALICE))
    out = tmp_path / "authors"
    monkeypatch.setattr(authors, "CATALOG_PATH", catalog)
    monkeypatch.setattr(authors, "AUTHORS_DIR", out)
    monkeypatch.setattr(sitemap, "CATALOG_PATH", catalog)
    monkeypatch.setattr(sitemap, "SITEMAP_PATH", tmp_path / "sitemap.xml")
    monkeypatch.setattr(skin_pages, "CATALOG_PATH", catalog)
    monkeypatch.setattr(skin_pages, "SKIN_DIR", tmp_path / "s")
    authors.main()

    class Site:
        dir = out
        creators = isolated_creators
        catalog_path = catalog

        @staticmethod
        def page(slug):
            return (out / f"{slug}.html").read_text(encoding="utf-8")
    return Site


# -- grouping ---------------------------------------------------------------

def test_every_creator_with_a_listed_skin_gets_a_page(site):
    names = {p.name for p in site.dir.glob("*.html")}
    assert {"alice.html", "bob.html", "solo.html", "index.html"} <= names  # Solo has one skin
    assert "sampler.html" not in names  # sample skins are not listed
    assert "shady.html" not in names    # only mature skins: nothing to list


def test_aliases_merge_into_the_creators_page(site):
    html = site.page("alice")
    assert "Alpha" in html and "Beta" in html
    assert "2 skins" in html


def test_creator_override_beats_an_alias(site):
    """`author` is Alice's alias but the entry says `creator: bob`: it is Bob's skin."""
    alice, bob = site.page("alice"), site.page("bob")
    assert "Not Alice&#x27;s" in bob or "Not Alice's" in bob
    assert "Not Alice" not in alice
    assert "3 skins" in bob


def test_mature_skins_are_counted_by_creator_slug(site):
    alice = site.page("alice")
    assert 'data-scope="author" data-key="alice" data-count="1"' in alice
    assert "Mature Pad" not in alice


def test_invalid_creator_file_is_skipped(site, capsys):
    (site.creators / "broken.json").write_text(json.dumps({"slug": "broken", "displayName": "x"}))
    (site.creators / "bad-json.json").write_text("{nope")
    creators = creator_pages.load_profiles()
    assert [c["slug"] for c in creators] == ["alice"]
    assert "skipping creator profile" in capsys.readouterr().out


def test_duplicate_alias_second_file_is_skipped(site):
    other = {**ALICE, "slug": "zed", "displayName": "Zed", "githubLogin": "zed", "aliases": ["Alice"]}
    (site.creators / "zed.json").write_text(json.dumps(other))
    assert [c["slug"] for c in creator_pages.load_profiles()] == ["alice"]


# -- the claimed page -------------------------------------------------------

def test_claimed_page_shows_the_profile(site):
    html = site.page("alice")
    assert "Alice &amp; Co" in html
    assert 'class="claimed-check"' in html
    assert 'class="creator-banner"' in html and "https://example.com/banner.png" in html
    assert "https://github.com/alice-gh.png?size=160" in html  # avatar
    assert "Requests on Discord &lt;3 &quot;quoted&quot; &amp; escaped." in html  # bio, escaped
    assert "Claim this page" not in html


def test_socials_come_from_the_handle_table(site):
    html = site.page("alice")
    assert 'href="https://github.com/alice-gh"' in html
    assert 'href="https://bsky.app/profile/alice.bsky.social"' in html
    # Discord has no profile URL: drawn as text, not a link
    assert re.search(r'<span class="social-chip social-chip-text"[^>]*>.*alice_skins', html)
    assert "discord.com" not in html


def test_links_open_with_untrusted_rel(site):
    html = site.page("alice")
    assert re.search(r'<a class="creator-link" href="https://example.com/alice" target="_blank" '
                     r'rel="nofollow noopener noreferrer ugc">Website', html)


def test_claimed_page_links_the_report_form(site):
    html = site.page("alice")
    assert "template=report-creator.yml" in html
    assert "profile_url=https%3A%2F%2Femuskins.com%2Fauthors%2Falice.html" in html
    assert "Report this profile" in html


def test_claimed_page_json_ld_person_has_same_as(site):
    html = site.page("alice")
    blocks = [json.loads(b) for b in re.findall(r'<script type="application/ld\+json">(.*?)</script>', html, re.S)]
    person = next(b["mainEntity"] for b in blocks if b.get("@type") == "ProfilePage")
    assert person["name"] == "Alice & Co"
    assert person["url"] == "https://emuskins.com/authors/alice.html"
    assert person["image"] == "https://github.com/alice-gh.png"
    assert person["sameAs"] == ["https://github.com/alice-gh", "https://bsky.app/profile/alice.bsky.social",
                                "https://example.com/alice"]


def test_hidden_profile_renders_as_unclaimed(site):
    (site.creators / "alice.json").write_text(json.dumps({**ALICE, "hidden": True}))
    authors.main()
    html = site.page("alice")
    assert "Soft hardware skins" not in html and "creator-banner" not in html
    assert "Claim this page" in html


# -- the unclaimed page -----------------------------------------------------

def test_unclaimed_page_offers_the_claim_form(site):
    html = site.page("solo")
    assert "Claim this page" in html
    assert "template=claim-profile.yml" in html and "names=Solo" in html
    assert "Claim+profile%3A+Solo" in html
    for hero_only in ("claimed-check", "creator-banner", "creator-bio", "Report this profile"):
        assert hero_only not in html.split("</style>")[1]


def test_claim_url_lists_every_alias(site):
    url = profile_html.claim_url({"displayName": "Alice & Co", "aliases": ["Alice", "alice_old"]})
    assert "names=Alice+%26+Co%0AAlice%0Aalice_old" in url


def test_json_ld_cannot_close_the_script_tag(site):
    page = authors.generate_author_page(
        "</script><b>x", "evil", [skin(1, "</script>", "x")], profile=None)
    assert page.count("<script") == page.count("</script>")


def test_unsafe_link_and_image_are_not_drawn():
    profile = {**ALICE, "claimed": True, "bannerURL": "javascript:alert(1)",
               "links": [{"label": "Bad", "url": "http://insecure.example"},
                         {"label": "Short", "url": "https://bit.ly/x"},
                         {"label": "Good", "url": "https://example.com"}]}
    assert profile_html.banner_html(profile) == ""
    html = profile_html.links_html(profile["links"])
    assert "Good" in html and "Bad" not in html and "Short" not in html


def test_every_social_key_has_a_label():
    assert set(profile_html.SOCIAL_LABELS) == set(SOCIAL_KEYS)


# -- alias redirects --------------------------------------------------------

def test_alias_slug_redirects_to_the_creator(site):
    stub = site.page("alice-old")
    assert '<meta http-equiv="refresh" content="0; url=alice.html">' in stub
    assert '<link rel="canonical" href="https://emuskins.com/authors/alice.html">' in stub
    assert 'content="noindex"' in stub


def test_redirects_never_shadow_a_real_page():
    creators = [{"slug": "alice", "aliases": ["Bob", "alice_old"]}]
    # "bob" has its own page, so only the free alias slug redirects
    assert creator_pages.redirect_slugs(creators, {"alice", "bob"}) == {"alice-old": "alice"}
    assert creator_pages.redirect_slugs(creators, {"bob"}) == {}  # creator has no page


def test_pruning_keeps_stubs_and_drops_orphans(site):
    (site.dir / "gone-author.html").write_text("stale")
    authors.main()
    names = {p.name for p in site.dir.glob("*.html")}
    assert "gone-author.html" not in names
    assert "alice-old.html" in names


def test_sitemap_lists_pages_but_not_stubs(site):
    sitemap.main()
    xml = (site.dir.parent / "sitemap.xml").read_text(encoding="utf-8")
    for slug in ("alice", "bob", "solo"):
        assert f"authors/{slug}.html" in xml
    assert "alice-old" not in xml and "sampler" not in xml and "shady" not in xml


# -- the index --------------------------------------------------------------

def test_index_is_most_recent_first_with_claim_marks(site):
    html = site.page("index")
    order = re.findall(r'href="([a-z0-9-]+)\.html" class="author-card"', html)
    # Solo 2026-09, Bob 2026-06, Alice 2026-02 (her newest listed skin is Beta, 01-02; Bob's override skin is 02-01)
    assert order == ["solo", "bob", "alice"]
    alice_card = html.split('href="alice.html"')[1].split("</a>")[0]
    assert "claimed-check" in alice_card and "https://github.com/alice-gh.png?size=96" in alice_card
    assert "claimed-check" not in html.split('href="solo.html"')[1].split("</a>")[0]


def test_sort_for_index_ties_break_by_count_then_name():
    items = [
        {"author": "b", "count": 1, "last_added": "2026-01-01"},
        {"author": "A", "count": 1, "last_added": "2026-01-01"},
        {"author": "c", "count": 5, "last_added": "2026-01-01"},
        {"author": "d", "count": 9, "last_added": None},
        {"author": "e", "count": 1, "last_added": "2026-02-01"},
    ]
    assert [i["author"] for i in authors.sort_for_index(items)] == ["e", "c", "A", "b", "d"]


# -- skin pages -------------------------------------------------------------

def test_skin_page_links_the_creator_it_resolves_to(site):
    pages = {"alice", "bob"}
    override = skin_pages.generate_skin_page({**CATALOG_SKINS[5], "creator": "bob"}, set(), pages)
    assert 'by <a href="../authors/bob.html">Alice</a>' in override  # credit stays the author string
    alias = skin_pages.generate_skin_page({**CATALOG_SKINS[1], "creator": "alice"}, set(), pages)
    assert 'by <a href="../authors/alice.html">alice_old</a>' in alias


def test_skin_page_without_an_author_page_has_no_link(site):
    html = skin_pages.generate_skin_page(CATALOG_SKINS[4], set(), {"alice"})
    assert 'by Solo' in html and "../authors/" not in html.split("<main")[1]


def test_skin_pages_link_single_skin_authors(site):
    skin_pages.main()
    html = (site.dir.parent / "s" / f"{5:016x}.html").read_text(encoding="utf-8")
    assert 'by <a href="../authors/solo.html">Solo</a>' in html
    sample = (site.dir.parent / "s" / f"{7:016x}.html").read_text(encoding="utf-8")
    assert "../authors/sampler.html" not in sample  # sample-only creators have no page


# -- share cards ------------------------------------------------------------

def test_author_card_is_a_valid_share_card():
    img = cards.render_author_card("A Very Long Creator Name That Keeps Going And Going Past The Safe Width", None, [])
    assert img.size == (1200, 630)
    import io
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=86, optimize=True, progressive=True)
    assert buf.tell() <= cards.MAX_BYTES


def test_card_title_fits_one_line_or_is_cut():
    f, line = cards.fit_one_line("Short", "Outfit-Bold.ttf", 60, 34)
    assert line == "Short" and f.getlength(line) <= cards.SAFE_WIDTH
    f, line = cards.fit_one_line("x" * 200, "Outfit-Bold.ttf", 60, 34)
    assert line.endswith("…") and f.getlength(line) <= cards.SAFE_WIDTH


def test_card_avatar_fetch_only_trusts_github(monkeypatch):
    def refuse(*a, **k):
        raise AssertionError("fetched from a host that is not allowed")
    monkeypatch.setattr(cards.urllib.request, "urlopen", refuse)
    for url in ("https://example.com/me.png", "http://github.com/me.png", None, "file:///etc/passwd"):
        assert cards.fetch_avatar(url, "me") is None


def test_author_card_used_only_when_it_exists(monkeypatch, tmp_path):
    import share_meta
    monkeypatch.setattr(share_meta, "DOCS_DIR", tmp_path)
    assert share_meta.author_card("alice") == share_meta.HOME_CARD
    (tmp_path / "cards" / "authors").mkdir(parents=True)
    (tmp_path / "cards" / "authors" / "alice.jpg").write_bytes(b"x")
    assert share_meta.author_card("alice") == "cards/authors/alice.jpg"


# -- browse.js and mature.js ------------------------------------------------

def _js_slugs(path, func, names):
    """Run the page script's own slug fallback in node over `names`."""
    import shutil
    import subprocess
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed")
    src = (ROOT / "docs" / "js" / path).read_text(encoding="utf-8")
    body = re.search(r"function %s\(skin\) \{.*?\n {0,2}\}\n" % func, src, re.S).group(0)
    script = body + "\nconst names=JSON.parse(process.argv[1]);\nconsole.log(JSON.stringify(names.map(n=>%s({author:n}))));" % func
    out = subprocess.run([node, "-e", script, json.dumps(names)], capture_output=True, text=True, check=True)
    return json.loads(out.stdout)


@pytest.mark.parametrize("path,func", [("browse.js", "creatorSlug"), ("mature.js", "creatorOf")])
def test_script_slug_fallback_matches_python(path, func):
    from creator_policy import author_slug
    names = ["aphaits", "felix#6506", "Provenance Emu", "ryan.patrick.creates", "  Spaced  Out ", "ICE",
             "a" * 80, "UPPER_lower-Mixed 9", "日本語"]
    catalog = json.loads((ROOT / "docs" / "catalog.json").read_text(encoding="utf-8"))
    names += sorted({s["author"] for s in catalog["skins"] if s.get("author")})
    assert _js_slugs(path, func, names) == [author_slug(n) for n in names]
