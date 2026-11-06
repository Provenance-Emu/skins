"""Stats and badges on author pages and the authors index (SkinKit#68).

The fixture directory is built by the real compute_creator_stats code over a small
catalog, so which badges a claimed and an unclaimed page show comes from #47's
rules and gating, not from hand-written fixture data.
"""

import json
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import compute_creator_stats as stats_mod  # noqa: E402
import creator_directory  # noqa: E402
import creator_pages  # noqa: E402
import creator_profile_html as profile_html  # noqa: E402
import generate_author_pages as authors  # noqa: E402

TODAY = "2026-11-06"


def skin(i, name, author, systems=("snes",), **extra):
    return {
        "id": f"{i:016x}", "name": name, "author": author, "systems": list(systems),
        "source": "manual", "downloadURL": f"https://example.com/{i}.deltaskin",
        "thumbnailURL": f"https://example.com/thumb-{i}.png", "tags": [],
        "downloadCount": 0, "addedAt": "2026-03-01", **extra,
    }


ALICE = {
    "slug": "alice", "displayName": "Alice", "aliases": ["Alice"], "githubLogin": "alice-gh",
    "bio": "Soft hardware skins.", "links": [], "socials": {},
    "claim": {"issue": 7, "method": "manual", "verifiedAt": "2026-11-10"}, "hidden": False,
}

SKINS = [
    # Alice: three systems, a three-member family, one mature skin -> claimed-only badges to show.
    skin(1, "Pad A", "Alice", ("snes",), groupId="fam", groupOrder=0, addedAt="2024-01-01"),
    skin(2, "Pad B", "Alice", ("snes",), groupId="fam", groupOrder=1, addedAt="2024-01-02"),
    skin(3, "Pad C", "Alice", ("snes",), groupId="fam", groupOrder=2, addedAt="2024-01-03"),
    skin(4, "GBA Pad", "Alice", ("gba",), addedAt="2026-01-05"),
    skin(5, "N64 Pad", "Alice", ("n64",), addedAt="2026-01-06"),
    skin(6, "Mature Pad", "Alice", ("nes",), tags=["mature"], addedAt="2026-01-07"),
    # Solo: unclaimed, one skin: only first-release.
    skin(10, "Solo Skin", "Solo", ("snes",), addedAt="2026-09-01"),
    # Duo: unclaimed with three systems, so it earns systems.3, and the claimed-only
    # family-builder badge it must not show.
    skin(20, "D1", "Duo", ("snes",), groupId="duo", groupOrder=0, addedAt="2026-05-01"),
    skin(21, "D2", "Duo", ("gba",), groupId="duo", groupOrder=1, addedAt="2026-05-01"),
    skin(22, "D3", "Duo", ("nes",), groupId="duo", groupOrder=2, addedAt="2026-05-02"),
]


def build_directory(skins, creators):
    """The published directory with stats and badges, made the way the build does."""
    catalog = {"skins": [dict(s) for s in skins]}
    groups = creator_pages.group_by_creator(catalog["skins"], creators)
    directory = creator_directory.build_directory(
        [s for g in groups.values() for s in g], creators, TODAY)
    defs = stats_mod.load_badges(str(ROOT / "badges.json"))
    stats_mod.compute_all(catalog, directory, defs, set(), {}, TODAY)
    return directory


@pytest.fixture
def site(tmp_path, monkeypatch, isolated_creators):
    isolated_creators.mkdir()
    (isolated_creators / "alice.json").write_text(json.dumps(ALICE))
    creators = creator_pages.load_profiles()
    directory = build_directory(SKINS, creators)
    (tmp_path / "creators.json").write_text(json.dumps(directory))
    catalog = tmp_path / "catalog.json"
    catalog.write_text(json.dumps({"version": 2, "skins": SKINS}))
    out = tmp_path / "authors"
    monkeypatch.setattr(authors, "CATALOG_PATH", catalog)
    monkeypatch.setattr(authors, "AUTHORS_DIR", out)
    monkeypatch.setattr(creator_pages, "DIRECTORY_PATH", tmp_path / "creators.json")
    authors.main()

    class Site:
        dir = out
        records = {r["slug"]: r for r in directory["creators"]}

        @staticmethod
        def page(slug):
            return (out / f"{slug}.html").read_text(encoding="utf-8")
    return Site


def badge_titles(html):
    row = re.search(r'<ul class="creator-badges".*?</ul>', html, re.S)
    return re.findall(r'<span>([^<]+)</span></button>', row.group(0)) if row else []


# -- the fixture really exercises the gating ---------------------------------

def test_fixture_directory_has_the_expected_badges(site):
    ids = lambda slug: {b["id"] for b in site.records[slug]["badges"]}  # noqa: E731
    assert {"creator.claimed", "creator.family-builder", "creator.systems.3"} <= ids("alice")
    assert ids("duo") == {"creator.first-release", "creator.systems.3"}  # family-builder is held back
    assert ids("solo") == {"creator.first-release"}


# -- author page -------------------------------------------------------------

def test_claimed_page_shows_stats_and_all_its_badges(site):
    html = site.page("alice")
    assert badge_titles(html) == ["First release", "Three systems", "Family builder", "Veteran", "Claimed profile"]
    # Stats come from the build: the family is one release, the mature skin counts.
    assert '<strong>4</strong><span>Releases</span>' in html
    assert '<strong>6</strong><span>Skins</span>' in html
    assert '<strong>4</strong><span>Systems</span>' in html
    assert '<strong>Jan 2024</strong><span>Active since</span>' in html
    assert "Claim your profile" not in html
    assert "skins across" not in html  # the sentence gives way to the tiles


def test_unclaimed_page_shows_only_the_limited_set_and_the_nudge(site):
    html = site.page("duo")
    assert badge_titles(html) == ["First release", "Three systems"]
    assert "Family builder" not in html and "Claimed profile" not in html
    assert 'Claim your profile</a> to see all badges.' in html
    assert "template=claim-profile.yml" in html.split("badges-nudge")[1]
    assert badge_titles(site.page("solo")) == ["First release"]


def test_badges_carry_their_description_and_an_icon(site):
    html = site.page("alice")
    assert 'title="Published a release with three or more variants."' in html
    assert html.count('<svg class="badge-icon"') == 5
    assert "badge-caption" in html and "data-caption=" in html
    assert "creator-badge').forEach" in html  # the caption script is there


def test_tiered_badges_show_only_the_highest(site):
    badges = [
        {"id": "creator.systems.3", "title": "Three systems", "tier": 1},
        {"id": "creator.systems.10", "title": "Ten systems", "tier": 3},
        {"id": "creator.systems.5", "title": "Five systems", "tier": 2},
        {"id": "creator.claimed", "title": "Claimed profile"},
    ]
    assert [b["title"] for b in profile_html.shown_badges(badges)] == ["Ten systems", "Claimed profile"]


def test_page_without_computed_stats_is_unchanged(tmp_path, site, monkeypatch):
    monkeypatch.setattr(creator_pages, "DIRECTORY_PATH", tmp_path / "missing.json")
    authors.main()
    html = site.page("alice")
    assert "creator-stats" not in html and "creator-badges" not in html and "Claim your profile" not in html
    assert "skins across" in html


def test_held_profile_gets_no_claim_nudge():
    profile = {"slug": "x", "displayName": "X", "claimed": False, "held": True,
               "stats": {"releases": 1}, "badges": [{"id": "creator.first-release", "title": "First release"}]}
    assert "Claim your profile" not in profile_html.badges_html(profile, [])


def test_badge_text_is_escaped_and_unknown_ids_get_the_generic_icon():
    profile = {"slug": "x", "displayName": "X", "claimed": True, "stats": {"releases": 1},
               "badges": [{"id": "creator.brand-new", "title": "<b>Hi</b>", "description": 'say "x" & <y>',
                           "symbol": "../../etc/passwd"}]}
    html = profile_html.badges_html(profile, [])
    assert "<b>" not in html and "&lt;b&gt;Hi&lt;/b&gt;" in html
    assert 'title="say &quot;x&quot; &amp; &lt;y&gt;"' in html
    assert profile_html.badge_icon_html("creator.brand-new") == profile_html.badge_icon_html("generic")
    assert profile_html.badge_icon_html("../../x") == profile_html.badge_icon_html("generic")
    assert profile_html.badge_icon_html("generic").startswith('<svg class="badge-icon"')


def test_malformed_badge_records_are_skipped():
    assert profile_html.shown_badges([None, "x", {"id": 3}, {"id": "a.b", "title": " "},
                                      {"id": "creator.claimed", "title": "Claimed profile"}]) == \
        [{"id": "creator.claimed", "title": "Claimed profile"}]


def test_every_creator_badge_in_badges_json_has_an_icon():
    defs = stats_mod.load_badges(str(ROOT / "badges.json"))
    for bid in defs:
        assert (ROOT / "docs" / "badges" / f"{bid}.svg").is_file(), bid
    assert (ROOT / "docs" / "badges" / "generic.svg").is_file()


# -- the index ---------------------------------------------------------------

def test_index_orders_by_computed_last_added_and_has_an_az_toggle(site):
    html = site.page("index")
    order = re.findall(r'href="([a-z0-9-]+)\.html" class="author-card"', html)
    # lastAddedAt: Solo 2026-09-01, Duo 2026-05-02, Alice 2026-01-07.
    assert order == ["solo", "duo", "alice"]
    assert 'data-sort="az"' in html and 'id="author-sort" role="group"' in html and "hidden>" in html
    assert 'data-name="alice"' in html
    grid = html.split('class="authors-grid"')[1]
    assert not re.search(r">\s*#\s*\d+\b|rank|<ol", grid, re.I)  # no rank numbers


def test_index_follows_stats_last_added_over_added_at(tmp_path, site, monkeypatch):
    # Same skins, but the build says Alice was active most recently (e.g. lastUpdated).
    directory = json.loads((tmp_path / "creators.json").read_text())
    for r in directory["creators"]:
        if r["slug"] == "alice":
            r["stats"]["lastAddedAt"] = "2026-10-30"
    (tmp_path / "creators.json").write_text(json.dumps(directory))
    authors.main()
    order = re.findall(r'href="([a-z0-9-]+)\.html" class="author-card"', site.page("index"))
    assert order == ["alice", "solo", "duo"]


def test_index_cards_show_releases_and_at_most_three_badges(site):
    html = site.page("index")
    alice = html.split('href="alice.html"')[1].split("</a>")[0]
    assert "<span>4</span> releases" in alice
    chips = re.findall(r'class="creator-badge creator-badge-sm"', alice)
    assert len(chips) == 3
    assert [t for t in re.findall(r"<span>([^<0-9][^<]*)</span></span>", alice)] == \
        ["Three systems", "Family builder", "Veteran"]  # the quiet badge gives way when there are others
    assert "<button" not in alice and "<a " not in alice.split("author-card-badges")[1]  # no nested interactives
    solo = html.split('href="solo.html"')[1].split("</a>")[0]
    assert "First release" in solo and "<span>1</span> release<" in solo


def test_card_badges_cap_and_quiet_rule():
    b = lambda i: {"id": f"creator.x{i}", "title": f"T{i}"}  # noqa: E731
    first = {"id": "creator.first-release", "title": "First release"}
    assert [x["title"] for x in profile_html.card_badges([first, b(1), b(2), b(3), b(4)])] == ["T1", "T2", "T3"]
    assert profile_html.card_badges([first]) == [first]


# -- the views label ---------------------------------------------------------

def test_thumbnail_count_is_labelled_views_not_downloads():
    card = authors.build_card(skin(1, "A", "B", downloadCount=1234))
    assert "1,234 views" in card and "⬇ 1,234" not in card
    assert "<span>Views</span>" in authors.MODAL_JS and "<span>Downloads</span>" not in authors.MODAL_JS
    js = (ROOT / "docs" / "js" / "browse.js").read_text(encoding="utf-8")
    assert "toLocaleString()} views</span>" in js
    assert "<span>Views</span><strong>${skin.downloadCount" in js
    assert "<span>Downloads</span>" not in js
