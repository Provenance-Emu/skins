import json
from pathlib import Path

import pytest

from migrate_release_source import reconcile, group_plans
from generate_skin_pages import migration_redirect_page, migration_redirects


SOURCE = {"repo": "Artist/skins", "attribution": "Artist"}


def test_only_unambiguous_single_skin_matches_keep_old_ids():
    existing = [
        {"id": "old-single", "author": "Artist", "name": "Gamepad",
         "gameTypeIdentifier": "com.rileytestut.delta.game.gba",
         "downloadURL": "https://example.com/Gamepad.deltaskin", "_source_file": "skins/gba/old.json"},
        {"id": "old-pack", "author": "Artist", "name": "Pack",
         "downloadURL": "https://example.com/Pack.zip", "_source_file": "skins/gba/pack.json"},
        {"id": "other", "author": "Someone else", "name": "Unrelated",
         "downloadURL": "https://example.com/Other.zip", "_source_file": "skins/gba/other.json"},
    ]
    plan = {"entry": {"id": "fresh-id", "name": "Gamepad",
                     "gameTypeIdentifier": "com.rileytestut.delta.game.gba"},
            "asset": "fresh-id.deltaskin"}
    old, retained, retired = reconcile(SOURCE, existing, [plan])
    assert retained == ["old-single"]
    assert [entry["id"] for entry in retired] == ["old-pack"]
    assert {entry["id"] for entry in old} == {"old-single", "old-pack"}
    assert plan["entry"]["id"] == "old-single"
    assert plan["destination"] == "skins/gba/old.json"
    assert plan["entry"]["downloadURL"].endswith("/old-single.deltaskin")


def test_ambiguous_old_name_does_not_get_arbitrary_id():
    existing = [{
        "id": str(index), "name": "Gamepad", "author": "Artist",
        "gameTypeIdentifier": "com.rileytestut.delta.game.gba",
        "downloadURL": "https://example.com/Gamepad.deltaskin",
    } for index in range(2)]
    plans = [{"entry": {"name": "Gamepad", "gameTypeIdentifier": "com.rileytestut.delta.game.gba"}}]
    _, retained, retired = reconcile(SOURCE, existing, plans)
    assert retained == []
    assert len(retired) == 2


def test_split_colour_parts_share_a_group():
    plans = [{"entry": {"name": f"Gamepad {index}", "originalURL":
             f"https://github.com/Artist/skins/releases/download/v1/Pad.Zip.-.Part.{index}.zip"}}
             for index in (1, 2, 3)]
    group_plans(SOURCE["repo"], plans)
    assert len({plan["entry"]["groupId"] for plan in plans}) == 1
    assert len({plan["entry"]["groupOrder"] for plan in plans}) == 3


def test_retired_permalink_redirect_is_local(tmp_path):
    path = tmp_path / "redirects.json"
    path.write_text(json.dumps({"0123456789abcdef": "authors/artist.html"}))
    assert migration_redirects(path) == {"0123456789abcdef": "authors/artist.html"}
    page = migration_redirect_page("authors/artist.html")
    assert 'content="0;url=../authors/artist.html"' in page
    assert 'href="https://emuskins.com/authors/artist.html"' in page


@pytest.mark.parametrize("target", ["https://evil.example", "../evil.html", 'authors/a.html"><script>'])
def test_external_or_unsafe_redirect_is_rejected(tmp_path, target):
    path = tmp_path / "redirects.json"
    path.write_text(json.dumps({"0123456789abcdef": target}))
    with pytest.raises(ValueError):
        migration_redirects(path)


def test_canonical_source_prevents_old_site_listings_returning():
    from crawl_sources import prefer_canonical_sources
    source = {**SOURCE, "canonical": True}
    old = {"author": "Artist", "source": "deltastyles.com"}
    canonical = {"author": "Artist", "source": "Artist/skins"}
    other = {"author": "Someone else", "source": "deltastyles.com"}
    assert prefer_canonical_sources([old, canonical, other], {"repos": [source]}) == [canonical, other]


def publication_fixture(tmp_path, monkeypatch):
    import hashlib
    import migrate_release_source as migration
    monkeypatch.chdir(tmp_path)
    (tmp_path / "docs/maintainers").mkdir(parents=True)
    directory = tmp_path / "stage"
    directory.mkdir()
    original = tmp_path / "skins/old.json"
    original.parent.mkdir()
    original.write_text('{"id":"0123456789abcdef"}')
    staged = directory / "skin.deltaskin"
    staged.write_bytes(b"skin")
    destination = tmp_path / "skins/new.json"
    entry = {"id": "fedcba9876543210", "name": "New",
             "downloadURL": "https://github.com/Provenance-Emu/skins/releases/download/mirror-artist-1/new.deltaskin"}
    report = {"source": SOURCE, "tags": ["v1"], "assets": 1, "new_count": 1,
              "original_files": {str(original): hashlib.sha256(original.read_bytes()).hexdigest()},
              "retained_ids": [], "skipped": {},
              "retired": [{"id": "0123456789abcdef", "name": "Old", "path": str(original),
                           "url": "https://example.com/old.zip"}],
              "plans": [{"entry": entry, "asset": "new.deltaskin", "mirrorTag": "mirror-artist-1",
                         "destination": str(destination), "sha256": hashlib.sha256(b"skin").hexdigest(),
                         "skin": {"info": {"name": "New"}, "staged": str(staged)}}]}
    (directory / "plan.json").write_text(json.dumps(report))
    class Archive:
        def __init__(self, path):
            pass
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
    monkeypatch.setattr(migration, "ZipFile", Archive)
    monkeypatch.setattr(migration, "classify_archive", lambda *args, **kwargs: {
        "result": "ok", "deviceSupport": ["iphone", "iphone-portrait"]})
    entry["deviceSupport"] = ["iphone", "iphone-portrait"]
    monkeypatch.setattr(migration, "note_import", lambda *args: None)
    monkeypatch.setattr(migration, "flush_imports", lambda *args: None)
    return migration, directory, original, destination, entry


def test_upload_failure_leaves_old_catalog_intact(tmp_path, monkeypatch):
    migration, directory, original, destination, entry = publication_fixture(tmp_path, monkeypatch)
    def fail(*args):
        raise OSError("Upload failed")
    monkeypatch.setattr(migration, "publish_assets", fail)
    with pytest.raises(OSError):
        migration.publish(directory)
    assert original.exists()
    assert not destination.exists()


def test_migration_keeps_old_links_and_can_be_retried(tmp_path, monkeypatch):
    migration, directory, original, destination, entry = publication_fixture(tmp_path, monkeypatch)
    monkeypatch.setattr(migration, "publish_assets", lambda *args: None)
    migration.publish(directory)
    assert not original.exists()
    assert json.loads(destination.read_text()) == entry
    assert json.loads(Path("skin-redirects.json").read_text()) == {
        "0123456789abcdef": "authors/artist.html"}
    migration.publish(directory)
    assert json.loads(destination.read_text()) == entry


def test_changed_original_stops_migration_before_upload(tmp_path, monkeypatch):
    migration, directory, original, destination, entry = publication_fixture(tmp_path, monkeypatch)
    original.write_text("unexpected edit")
    monkeypatch.setattr(migration, "publish_assets", lambda *args: pytest.fail("Must not upload"))
    with pytest.raises(ValueError, match="Existing catalog file changed"):
        migration.publish(directory)


def test_canonical_author_does_not_trigger_old_host_downloads(monkeypatch):
    import crawl_sources as crawler
    monkeypatch.setattr(crawler, "_ds_fetch", lambda url: "listing")
    monkeypatch.setattr(crawler, "_deltastyles_parse_listing", lambda html: [{
        "author": "Artist", "name": "Pack", "_detail_path": "/skins/123-pack"}])
    monkeypatch.setattr(crawler, "_deltastyles_resolve_variants",
                        lambda *args: pytest.fail("Canonical creator must not download from old host"))
    monkeypatch.setattr(crawler.time, "sleep", lambda *args: None)
    assert crawler.scrape_deltastyles(["arcade"], exclude_authors=["artist"]) == []


def test_verified_duplicate_copies_keep_the_most_used_id():
    existing = [
        {"id": "most-used", "author": "Artist", "name": "Gamepad",
         "gameTypeIdentifier": "com.rileytestut.delta.game.gba", "downloadCount": 20,
         "downloadURL": "https://example.com/a.deltaskin", "_source_file": "skins/gba/a.json"},
        {"id": "duplicate", "author": "Artist", "name": "Gamepad",
         "gameTypeIdentifier": "com.rileytestut.delta.game.gba", "downloadCount": 1,
         "downloadURL": "https://example.com/b.deltaskin", "_source_file": "skins/gba/b.json"},
    ]
    plan = {"entry": {"id": "fresh", "name": "Gamepad",
                     "gameTypeIdentifier": "com.rileytestut.delta.game.gba"},
            "skin": {"fingerprint": "same"}, "asset": "fresh.deltaskin"}
    evidence = {entry["id"]: {"fingerprint": "same"} for entry in existing}
    _, retained, retired = reconcile(SOURCE, existing, [plan], evidence)
    assert retained == ["most-used"]
    assert retired[0]["_replacement_id"] == "most-used"
    assert plan["entry"]["id"] == "most-used"


def test_publisher_stops_queued_uploads_on_rate_limit(tmp_path, monkeypatch):
    import migrate_release_source as migration
    from generate_thumbnails import ReleaseUploadRateLimit
    from types import SimpleNamespace
    monkeypatch.setattr(migration.subprocess, "run", lambda *args, **kwargs: SimpleNamespace(returncode=0))
    monkeypatch.setattr(migration, "http_get_json", lambda *args: {"upload_url": "upload"})
    monkeypatch.setattr(migration, "list_release_assets", lambda *args: [])
    calls = []
    def blocked(*args, **kwargs):
        calls.append(args[1])
        raise ReleaseUploadRateLimit(60, "quota")
    monkeypatch.setattr(migration, "upload_release_asset", blocked)
    (tmp_path / "publish").mkdir()
    plans = []
    for index in range(20):
        name = f"{index}.manicskin"
        (tmp_path / "publish" / name).write_bytes(b"skin")
        plans.append({"mirrorTag": "mirror-test", "asset": name, "sha256": "digest",
                      "entry": {"downloadURL": "unused"}})
    with pytest.raises(ReleaseUploadRateLimit):
        migration.publish_assets(plans, tmp_path)
    assert len(calls) <= 2
