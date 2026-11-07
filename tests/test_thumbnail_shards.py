"""Thumbnail release shards (SkinKit#128): tags and URLs, where an upload goes,
download counts across shards, promoting repo-hosted URLs, opt-out cleanup."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

import pytest

import build_catalog as bc
import generate_skin_pages as skin_pages
import generate_thumbnails as gt
import process_optout as po
import thumbnail_shards as ts

ID1, ID2, ID3 = "aaaa000000000001", "aaaa000000000002", "aaaa000000000003"


def release(tag, n_assets=0):
    return {"id": 100 + ts.shard_number(tag), "tag_name": tag,
            "upload_url": f"https://uploads.example/{tag}/assets{{?name,label}}",
            "assets_url": f"https://api.example/{tag}/assets"}


# ---------------------------------------------------------------------------
# Tags, names, URLs
# ---------------------------------------------------------------------------

class TestTags:
    def test_shard_tags(self):
        for tag in ("thumbnails", "thumbnails-2", "thumbnails-9", "thumbnails-10", "thumbnails-123"):
            assert ts.is_shard_tag(tag), tag
        for tag in ("thumbnails-1", "thumbnails-0", "thumbnails-02", "mirror", "thumbnails-", "thumbnails-x",
                    "thumbnails-2-x", "xthumbnails", "creators", "", None):
            assert not ts.is_shard_tag(tag), tag

    def test_numbers_round_trip(self):
        assert ts.shard_number("thumbnails") == 1
        assert ts.shard_number("thumbnails-12") == 12
        assert ts.tag_for_number(1) == "thumbnails" and ts.tag_for_number(3) == "thumbnails-3"
        with pytest.raises(ValueError):
            ts.shard_number("mirror")

    def test_sort_is_numeric(self):
        assert ts.sort_tags(["thumbnails-10", "thumbnails-2", "mirror", "thumbnails"]) == \
            ["thumbnails", "thumbnails-2", "thumbnails-10"]

    def test_next_tag(self):
        assert ts.next_tag(["thumbnails"]) == "thumbnails-2"
        assert ts.next_tag(["thumbnails", "thumbnails-2", "thumbnails-3"]) == "thumbnails-4"
        assert ts.next_tag([]) == "thumbnails"

    def test_asset_names(self):
        assert ts.parse_asset_name(f"{ID1}.png") == (ID1, False)
        assert ts.parse_asset_name(f"{ID1}-landscape.png") == (ID1, True)
        for bad in (f"{ID1}.jpg", "short.png", f"{ID1.upper()}.png", f"{ID1}-portrait.png", f"{ID1}.png.bak", "", None):
            assert ts.parse_asset_name(bad) is None, bad


class TestUrls:
    def test_release_url_round_trip(self):
        url = ts.download_url("thumbnails-2", f"{ID1}.png")
        assert url == f"https://github.com/Provenance-Emu/skins/releases/download/thumbnails-2/{ID1}.png"
        assert ts.parse_release_url(url) == ("thumbnails-2", f"{ID1}.png")

    def test_other_releases_and_repos_are_not_ours(self):
        mirror = f"https://github.com/Provenance-Emu/skins/releases/download/mirror/{ID1}.deltaskin"
        other = f"https://github.com/someone/else/releases/download/thumbnails/{ID1}.png"
        assert ts.parse_release_url(mirror) is None
        assert ts.parse_release_url(other) is None
        assert not ts.is_own_thumbnail_url(mirror) and not ts.is_own_thumbnail_url(other)

    def test_own_thumbnail_urls(self):
        raw = f"https://raw.githubusercontent.com/Provenance-Emu/skins/main/thumbnails/{ID1}.png"
        assert ts.is_own_thumbnail_url(raw)
        assert ts.is_own_thumbnail_url(ts.download_url("thumbnails", f"{ID1}.png"))
        assert ts.is_own_thumbnail_url(ts.download_url("thumbnails-7", f"{ID1}.png"))
        assert not ts.is_own_thumbnail_url("https://example.com/x.png")
        assert not ts.is_own_thumbnail_url(None)

    def test_raw_url_name(self):
        assert ts.parse_raw_url(f"https://raw.githubusercontent.com/Provenance-Emu/skins/main/thumbnails/{ID1}.png") == f"{ID1}.png"
        assert ts.parse_raw_url("https://raw.githubusercontent.com/Provenance-Emu/skins/main/thumbnails/readme.md") is None
        assert ts.parse_raw_url(ts.download_url("thumbnails", f"{ID1}.png")) is None

    def test_existing_thumbnail_urls_are_unchanged(self):
        # The URL form shipped app builds already use.
        assert ts.download_url("thumbnails", "3957312ad9e7c59e.png") == \
            "https://github.com/Provenance-Emu/skins/releases/download/thumbnails/3957312ad9e7c59e.png"


# ---------------------------------------------------------------------------
# Where an upload goes
# ---------------------------------------------------------------------------

class TestPickTag:
    def test_first_shard_with_room(self):
        assert ts.pick_tag({"thumbnails": 900, "thumbnails-2": 10}) == "thumbnails"
        assert ts.pick_tag({"thumbnails": 950, "thumbnails-2": 10}) == "thumbnails-2"

    def test_soft_cap_is_inclusive_of_the_new_assets(self):
        assert ts.pick_tag({"thumbnails": 949}, need=1) == "thumbnails"
        assert ts.pick_tag({"thumbnails": 949}, need=2) == "thumbnails-2"
        assert ts.SOFT_CAP < ts.HARD_CAP

    def test_all_full_names_the_next_shard(self):
        assert ts.pick_tag({"thumbnails": 950, "thumbnails-2": 960}) == "thumbnails-3"

    def test_no_shards_starts_with_the_original(self):
        assert ts.pick_tag({}) == "thumbnails"


class Recorder:
    """Stands in for the network side of a ShardSet."""
    def __init__(self, fail=()):
        self.created, self.uploads, self.deleted, self.fail = [], [], [], set(fail)

    def create_release(self, tag):
        self.created.append(tag)
        return release(tag)

    def upload(self, rel, name, data):
        if rel["tag_name"] in self.fail:
            return None
        self.uploads.append((rel["tag_name"], name, data))
        return ts.download_url(rel["tag_name"], name)

    def delete(self, asset_id):
        self.deleted.append(asset_id)


def shard_set(rec, sizes, existing=None, soft_cap=ts.SOFT_CAP):
    """ShardSet with `sizes` {tag: n} filler assets and `existing` {name: (tag, id)}."""
    releases = {tag: release(tag) for tag in sizes}
    index = {f"filler-{tag}-{i}": (tag, i) for tag, n in sizes.items() for i in range(n)}
    index.update(existing or {})
    return ts.ShardSet(releases, index, rec.create_release, rec.upload, rec.delete, soft_cap)


class TestShardSet:
    def test_new_asset_goes_to_first_shard_with_room(self):
        rec = Recorder()
        s = shard_set(rec, {"thumbnails": 950, "thumbnails-2": 5})
        url = s.upload(f"{ID1}.png", b"x")
        assert url == ts.download_url("thumbnails-2", f"{ID1}.png")
        assert rec.created == [] and rec.uploads == [("thumbnails-2", f"{ID1}.png", b"x")]

    def test_fills_the_original_shard_while_it_has_room(self):
        rec = Recorder()
        s = shard_set(rec, {"thumbnails": 800, "thumbnails-2": 5})
        assert s.upload(f"{ID1}.png", b"x") == ts.download_url("thumbnails", f"{ID1}.png")

    def test_existing_asset_is_replaced_in_its_own_shard(self):
        rec = Recorder()
        # `thumbnails` is over the soft cap and `thumbnails-2` has room, yet the
        # asset that is already in `thumbnails` keeps its URL.
        s = shard_set(rec, {"thumbnails": 990, "thumbnails-2": 1},
                      existing={f"{ID1}.png": ("thumbnails", 4242)})
        url = s.upload(f"{ID1}.png", b"new")
        assert url == ts.download_url("thumbnails", f"{ID1}.png")
        assert rec.deleted == [4242]
        assert rec.uploads == [("thumbnails", f"{ID1}.png", b"new")]

    def test_creates_the_next_shard_when_all_are_full(self):
        rec = Recorder()
        s = shard_set(rec, {"thumbnails": 950})
        url = s.upload(f"{ID1}.png", b"x")
        assert rec.created == ["thumbnails-2"]
        assert url == ts.download_url("thumbnails-2", f"{ID1}.png")
        # and the one after fills the new shard, not another
        s.upload(f"{ID2}.png", b"y")
        assert rec.created == ["thumbnails-2"]

    def test_empty_set_creates_the_original(self):
        rec = Recorder()
        s = ts.ShardSet({}, {}, rec.create_release, rec.upload, rec.delete)
        s.upload(f"{ID1}.png", b"x")
        assert rec.created == ["thumbnails"]

    def test_a_name_never_lands_in_two_shards(self):
        rec = Recorder()
        s = shard_set(rec, {"thumbnails": 951})
        s.upload(f"{ID1}.png", b"1")
        s.upload(f"{ID1}.png", b"2")
        assert [t for t, n, _ in rec.uploads if n == f"{ID1}.png"] == ["thumbnails-2", "thumbnails-2"]
        assert s.sizes()["thumbnails-2"] == 1

    def test_landscape_follows_the_portrait(self):
        rec = Recorder()
        s = shard_set(rec, {"thumbnails": 949, "thumbnails-2": 0})
        tag = s.tag_for(f"{ID1}.png", need=2)
        assert tag == "thumbnails-2"
        s.upload(f"{ID1}.png", b"p", tag=tag)
        s.upload(f"{ID1}-landscape.png", b"l", tag=tag)
        assert {t for t, _, _ in rec.uploads} == {"thumbnails-2"}

    def test_failed_upload_returns_none_and_is_not_counted(self):
        rec = Recorder(fail={"thumbnails"})
        s = shard_set(rec, {"thumbnails": 10})
        assert s.upload(f"{ID1}.png", b"x") is None
        assert f"{ID1}.png" not in s.index

    def test_failed_shard_creation_returns_none(self):
        s = ts.ShardSet({}, {}, lambda tag: None, lambda *a: "url", lambda i: None)
        assert s.upload(f"{ID1}.png", b"x") is None

    def test_load_reads_every_shard_and_pages_assets(self):
        pages = {
            "https://api.github.com/repos/Provenance-Emu/skins/releases?per_page=100&page=1": [
                {"tag_name": "mirror"}, release("thumbnails-2"), release("thumbnails"), {"tag_name": "thumbnails-x"}],
            "https://api.example/thumbnails/assets?per_page=100&page=1":
                [{"name": f"{ID1}.png", "id": 1}] * 0 + [{"name": f"n{i}.png", "id": i} for i in range(100)],
            "https://api.example/thumbnails/assets?per_page=100&page=2": [{"name": f"{ID1}.png", "id": 7}],
            "https://api.example/thumbnails-2/assets?per_page=100&page=1": [{"name": f"{ID2}.png", "id": 8}],
        }
        rec = Recorder()
        s = ts.ShardSet.load(rec.create_release, rec.upload, rec.delete, get_json=pages.__getitem__)
        assert sorted(s.releases) == ["thumbnails", "thumbnails-2"]
        assert s.index[f"{ID1}.png"] == ("thumbnails", 7)
        assert s.index[f"{ID2}.png"] == ("thumbnails-2", 8)
        assert s.sizes() == {"thumbnails": 101, "thumbnails-2": 1}


# ---------------------------------------------------------------------------
# Download counts (build_catalog)
# ---------------------------------------------------------------------------

LIST_URL = "https://api.github.com/repos/Provenance-Emu/skins/releases?per_page=100&page=1"


def api(shards: dict, broken=()):
    """get_json over fake releases: shards = {tag: [(asset name, downloads)]}."""
    table = {LIST_URL: [release(t) for t in shards]}
    for tag, assets in shards.items():
        table[f"https://api.github.com/repos/Provenance-Emu/skins/releases/tags/{tag}"] = release(tag)
        table[f"https://api.example/{tag}/assets?per_page=100&page=1"] = [
            {"name": n, "download_count": c} for n, c in assets]

    def get_json(url):
        if any(b in url for b in broken):
            raise OSError("boom")
        return table[url]
    return get_json


class TestDownloadCounts:
    def test_counts_every_shard(self):
        got = bc.fetch_release_download_counts(api({
            "thumbnails": [(f"{ID1}.png", 120)],
            "thumbnails-2": [(f"{ID2}.png", 75), (f"{ID2}-landscape.png", 3), ("notes.txt", 9)],
        }))
        assert got == {ID1: 120, ID2: 75, f"{ID2}-landscape": 3}

    def test_a_name_in_two_shards_adds_up(self):
        got = bc.fetch_release_download_counts(api({
            "thumbnails": [(f"{ID1}.png", 100)], "thumbnails-2": [(f"{ID1}.png", 20)]}))
        assert got[ID1] == 120

    def test_one_shard_failing_leaves_its_ids_out(self):
        got = bc.fetch_release_download_counts(api(
            {"thumbnails": [(f"{ID1}.png", 120)], "thumbnails-2": [(f"{ID2}.png", 75)]},
            broken=("releases/tags/thumbnails-2",)))
        assert got == {ID1: 120}

    def test_failed_listing_falls_back_to_the_original_release(self):
        good = api({"thumbnails": [(f"{ID1}.png", 120)]})

        def get_json(url):
            if "releases?per_page" in url:
                raise OSError("boom")
            return good(url)
        assert bc.fetch_release_download_counts(get_json) == {ID1: 120}

    def test_total_failure_is_empty(self):
        def get_json(url):
            raise OSError("down")
        assert bc.fetch_release_download_counts(get_json) == {}

    def test_missing_shard_keeps_its_published_count(self):
        # apply_count_hygiene keeps the previous count for a skin absent from a
        # non-empty fetch, which is what a failed shard looks like.
        entries = [{"id": ID1}, {"id": ID2}]
        fetched = {ID1: 500}
        bc.apply_count_hygiene(entries, fetched, previous={ID1: 400, ID2: 300})
        assert entries[1]["downloadCount"] == 300


# ---------------------------------------------------------------------------
# generate_thumbnails: promote repo-hosted URLs onto the shards
# ---------------------------------------------------------------------------

RAW = "https://raw.githubusercontent.com/Provenance-Emu/skins/main/thumbnails/"


@pytest.fixture
def promote_env(tmp_path, monkeypatch):
    monkeypatch.setattr(gt, "GITHUB_TOKEN", "t")
    monkeypatch.setattr(gt, "_release_rate_limited", False)
    thumbs = tmp_path / "thumbnails"
    thumbs.mkdir()
    return tmp_path, thumbs


def write_skin(tmp, entry):
    path = tmp / f"{entry['id']}.json"
    path.write_text(json.dumps(entry))
    return str(path)


class TestPromote:
    def test_portrait_and_landscape_move_together(self, promote_env):
        tmp, thumbs = promote_env
        (thumbs / f"{ID1}.png").write_bytes(b"p")
        (thumbs / f"{ID1}-landscape.png").write_bytes(b"l")
        path = write_skin(tmp, {"id": ID1, "thumbnailURL": RAW + f"{ID1}.png",
                                "screenshotURLs": [RAW + f"{ID1}-landscape.png"]})
        rec = Recorder()
        s = shard_set(rec, {"thumbnails": 950})
        assert gt.promote_skin(path, s, str(thumbs), dry_run=False) is True
        out = json.loads(Path(path).read_text())
        assert out["thumbnailURL"] == ts.download_url("thumbnails-2", f"{ID1}.png")
        assert out["screenshotURLs"] == [ts.download_url("thumbnails-2", f"{ID1}-landscape.png")]
        assert (thumbs / f"{ID1}.png").exists()          # raw file stays: shipped catalogs use it

    def test_failed_upload_leaves_the_raw_url(self, promote_env):
        tmp, thumbs = promote_env
        (thumbs / f"{ID1}.png").write_bytes(b"p")
        entry = {"id": ID1, "thumbnailURL": RAW + f"{ID1}.png"}
        path = write_skin(tmp, entry)
        s = shard_set(Recorder(fail={"thumbnails"}), {"thumbnails": 5})
        assert gt.promote_skin(path, s, str(thumbs), dry_run=False) is False
        assert json.loads(Path(path).read_text()) == entry

    def test_missing_local_file_is_skipped(self, promote_env):
        tmp, thumbs = promote_env
        entry = {"id": ID1, "thumbnailURL": RAW + f"{ID1}.png"}
        path = write_skin(tmp, entry)
        rec = Recorder()
        assert gt.promote_skin(path, shard_set(rec, {"thumbnails": 5}), str(thumbs), dry_run=False) is False
        assert rec.uploads == []

    def test_only_the_skins_own_names_count(self, promote_env):
        tmp, thumbs = promote_env
        (thumbs / f"{ID2}.png").write_bytes(b"other")
        entry = {"id": ID1, "thumbnailURL": RAW + f"{ID2}.png"}     # another skin's image
        assert gt.raw_thumbnail_names(entry) == []

    def test_release_urls_are_left_alone(self, promote_env):
        tmp, thumbs = promote_env
        (thumbs / f"{ID1}.png").write_bytes(b"p")
        entry = {"id": ID1, "thumbnailURL": ts.download_url("thumbnails", f"{ID1}.png")}
        assert gt.raw_thumbnail_names(entry) == []

    def test_dry_run_uploads_nothing(self, promote_env):
        tmp, thumbs = promote_env
        (thumbs / f"{ID1}.png").write_bytes(b"p")
        entry = {"id": ID1, "thumbnailURL": RAW + f"{ID1}.png"}
        path = write_skin(tmp, entry)
        rec = Recorder()
        assert gt.promote_skin(path, shard_set(rec, {"thumbnails": 5}), str(thumbs), dry_run=True) is True
        assert rec.uploads == [] and json.loads(Path(path).read_text()) == entry

    def test_rate_limit_stops_the_skin_without_rewriting(self, promote_env, monkeypatch):
        tmp, thumbs = promote_env
        monkeypatch.setattr(gt, "_release_rate_limited", True)
        (thumbs / f"{ID1}.png").write_bytes(b"p")
        entry = {"id": ID1, "thumbnailURL": RAW + f"{ID1}.png"}
        path = write_skin(tmp, entry)
        rec = Recorder()
        assert gt.promote_skin(path, shard_set(rec, {"thumbnails": 5}), str(thumbs), dry_run=False) is False
        assert rec.uploads == []


# ---------------------------------------------------------------------------
# Opt-out cleanup and skin pages
# ---------------------------------------------------------------------------

class TestOptoutTags:
    def entry(self, **kw):
        return {"id": ID1, "name": "x", "downloadURL": "https://example.com/x.deltaskin", **kw}

    def test_default_is_the_original_release(self):
        assert po.release_assets(self.entry()) == [
            ("thumbnails", f"{ID1}.png"), ("thumbnails", f"{ID1}-landscape.png")]

    def test_follows_the_skins_own_shard(self):
        e = self.entry(thumbnailURL=ts.download_url("thumbnails-3", f"{ID1}.png"),
                       screenshotURLs=[ts.download_url("thumbnails-3", f"{ID1}-landscape.png")])
        assert po.release_assets(e) == [
            ("thumbnails-3", f"{ID1}.png"), ("thumbnails-3", f"{ID1}-landscape.png")]

    def test_a_url_for_another_release_is_refused(self):
        e = self.entry(thumbnailURL=f"https://github.com/Provenance-Emu/skins/releases/download/mirror/{ID1}.png")
        assert po.release_assets(e)[0] == ("thumbnails", f"{ID1}.png")

    def test_a_url_for_another_skins_asset_is_refused(self):
        e = self.entry(thumbnailURL=ts.download_url("thumbnails-2", f"{ID2}.png"))
        assert po.release_assets(e)[0] == ("thumbnails", f"{ID1}.png")

    def test_a_url_in_another_repo_is_refused(self):
        e = self.entry(thumbnailURL=f"https://github.com/evil/repo/releases/download/thumbnails-2/{ID1}.png")
        assert po.release_assets(e)[0] == ("thumbnails", f"{ID1}.png")


class TestSkinPages:
    def test_shard_urls_count_as_our_thumbnails(self, tmp_path, monkeypatch):
        from PIL import Image
        thumbs = tmp_path / "thumbnails"
        thumbs.mkdir()
        Image.new("RGB", (4, 3)).save(thumbs / f"{ID1}.png")
        monkeypatch.setattr(skin_pages, "THUMBS_DIR", thumbs)
        for tag in ("thumbnails", "thumbnails-2"):
            url = ts.download_url(tag, f"{ID1}.png")
            assert skin_pages.own_thumbnail(url) == (url, (4, 3))
        assert skin_pages.own_thumbnail(f"https://example.com/{ID1}.png") is None
