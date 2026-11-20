import io
import json
from pathlib import Path
from zipfile import ZipFile

import pytest

import import_release_skins as importer


SOURCE = {"repo": "Artist/skins", "attribution": "Artist"}
FIXTURE = Path(__file__).parent.parent / "fixtures/variants/sample-themes-gba.deltaskin"


def skin(name="Test", identifier="com.test.skin"):
    buffer = io.BytesIO()
    with ZipFile(FIXTURE) as original, ZipFile(buffer, "w") as out:
        for member in original.infolist():
            data = original.read(member.filename)
            if member.filename == "info.json":
                info = importer.parse_info_json(data)
                info.update(name=name, identifier=identifier)
                data = json.dumps(info).encode()
            out.writestr(member.filename, data)
    return buffer.getvalue()


def pack(entries):
    buffer = io.BytesIO()
    with ZipFile(buffer, "w") as out:
        for name, data in entries.items():
            out.writestr(name, data)
    return buffer.getvalue()


def test_nested_release_skins_are_installable():
    data = pack({"Part.zip": pack({"Test.manicskin": skin()})})
    result = importer.unpack_skins(data)
    assert len(result) == 1
    assert result[0]["info"]["name"] == "Test"


def test_existing_pack_and_repeated_release_asset_do_not_duplicate():
    first, new = skin(), skin("New", "com.test.new")
    bodies = {
        "old": pack({"Original.manicskin": first}),
        "release": pack({"Renamed.manicskin": first, "New.manicskin": new}),
        "starter": pack({"Again.manicskin": new}),
    }
    plans, skipped = importer.plan_import(SOURCE,
        [{"id": "original-id", "author": "Artist", "downloadURL": "old"}],
        [{"name": "Release.zip", "browser_download_url": "release"},
         {"name": "Starter.zip", "browser_download_url": "starter"}], bodies.__getitem__)
    assert len(plans) == 1
    assert plans[0]["entry"]["name"] == "New"
    assert skipped["identical"] == 2
    assert plans[0]["entry"]["originalURL"] == "release"


def test_same_identifier_with_changed_data_needs_update_review():
    plans, skipped = importer.plan_import(SOURCE,
        [{"id": "original-id", "author": "Artist", "downloadURL": "old"}],
        [{"name": "Release.zip", "browser_download_url": "release"}],
        {"old": skin(), "release": skin("Renamed") }.__getitem__)
    assert plans == []
    assert skipped["existing_identity"] == 1


def test_unavailable_existing_skin_stops_before_reading_releases():
    calls = []
    def read(url):
        calls.append(url)
        raise OSError("Host blocked")
    with pytest.raises(ValueError, match="Cannot compare existing listing"):
        importer.plan_import(SOURCE,
            [{"id": "old", "author": "Artist", "downloadURL": "old"}],
            [{"name": "Release.zip", "browser_download_url": "release"}], read)
    assert calls == ["old"]


@pytest.mark.parametrize("entries", [
    {"../evil.manicskin": skin()},
    {"deep.zip": pack({"deeper.zip": pack({"again.zip": pack({"too-deep.manicskin": skin()})})})},
])
def test_unsafe_or_over_nested_archive_is_rejected(entries):
    with pytest.raises(ValueError):
        importer.unpack_skins(pack(entries))


def test_expansion_budget_applies_before_reading_members(monkeypatch):
    monkeypatch.setattr(importer, "MAX_EXPANDED", 1)
    with pytest.raises(ValueError, match="expansion limit"):
        importer.unpack_skins(skin())


def test_repeated_import_preserves_existing_listing_id():
    original = skin()
    plans, _ = importer.plan_import(SOURCE, [], [{
        "name": "Test.zip", "browser_download_url": "release"}],
        lambda url: pack({"Test.manicskin": original}))
    entry = plans[0]["entry"]
    again, _ = importer.plan_import(SOURCE, [entry], [{
        "name": "Test.zip", "browser_download_url": "release"}],
        lambda url: original if url == entry["downloadURL"] else pack({"Test.manicskin": original}))
    assert again == []


def test_failed_upload_does_not_write_catalog_entries(tmp_path, monkeypatch):
    monkeypatch.setattr(importer, "release_assets", lambda *args: [
        {"name": "Skin.zip", "browser_download_url": "release"}])
    class Client:
        def get_bytes(self, *args, **kwargs):
            return skin()
    monkeypatch.setattr(importer.polite_http, "get_client", lambda: Client())
    def fail_upload(files):
        raise OSError("Upload interrupted")
    monkeypatch.setattr(importer, "upload", fail_upload)
    with pytest.raises(OSError):
        importer.run_source(SOURCE, [], tmp_path / "skins", True, ["v1"])
    assert not (tmp_path / "skins").exists()


def test_original_baseline_pack_can_replace_unavailable_host(tmp_path):
    original = skin()
    (tmp_path / "original-id.zip").write_bytes(pack({"old.manicskin": original}))
    def read(url):
        assert url == "release"
        return pack({"renamed.manicskin": original})
    plans, skipped = importer.plan_import(SOURCE,
        [{"id": "original-id", "author": "Artist", "downloadURL": "missing"}],
        [{"name": "Release.zip", "browser_download_url": "release"}], read, tmp_path)
    assert plans == []
    assert skipped["identical"] == 1


def test_fingerprint_ignores_zip_order_and_info_formatting():
    original = skin()
    buffer = io.BytesIO()
    with ZipFile(io.BytesIO(original)) as source, ZipFile(buffer, "w") as out:
        for name in reversed(source.namelist()):
            data = source.read(name)
            if name == "info.json":
                data = json.dumps(json.loads(data), indent=4).encode()
            out.writestr(name, data)
    assert importer.unpack_skins(original)[0]["fingerprint"] == importer.unpack_skins(buffer.getvalue())[0]["fingerprint"]


def test_successful_publication_writes_skin_and_variants(tmp_path, monkeypatch):
    monkeypatch.setattr(importer, "release_assets", lambda *args: [
        {"name": "Skin.zip", "browser_download_url": "release"}])
    original = skin()
    class Client:
        def get_bytes(self, *args, **kwargs):
            return original
    monkeypatch.setattr(importer.polite_http, "get_client", lambda: Client())
    uploaded, notes, flushed = [], [], []
    def upload(files):
        uploaded.extend(Path(path).read_bytes() for path in files)
    monkeypatch.setattr(importer, "upload", upload)
    monkeypatch.setattr(importer, "note_import", lambda url, info: notes.append(url))
    monkeypatch.setattr(importer, "flush_imports", lambda entries: flushed.extend(entries))
    importer.run_source(SOURCE, [], tmp_path / "skins", True, ["v1"])
    entries = [json.loads(path.read_text()) for path in (tmp_path / "skins").rglob("*.json")]
    assert len(entries) == 1
    assert entries[0]["author"] == "Artist"
    assert uploaded == [original]
    assert notes == [entries[0]["downloadURL"]]
    assert flushed == entries


def test_release_selection_uses_explicit_tags_and_skips_unrelated_assets(monkeypatch):
    calls = []
    def api(path, token):
        calls.append(path)
        return {"assets": [
            {"name": "Skin.zip", "size": 10, "browser_download_url": "https://github.com/Artist/skins/releases/download/v2/Skin.zip"},
            {"name": "Preview.png", "size": 10, "browser_download_url": "https://example.com/Preview.png"},
        ]}
    monkeypatch.setattr(importer, "gh_api", api)
    assets = importer.release_assets("Artist/skins", ["v2"], "")
    assert calls == ["repos/Artist/skins/releases/tags/v2"]
    assert [asset["name"] for asset in assets] == ["Skin.zip"]


def test_mixed_wrapped_and_archived_skins_are_all_indexed():
    first, second = skin(), skin("Sibling", "com.test.sibling")
    with ZipFile(io.BytesIO(first)) as wrapped:
        members = {"Wrapped/" + name: wrapped.read(name) for name in wrapped.namelist()}
    members["Sibling.manicskin"] = second
    mixed = pack(members)
    assert len(importer.unpack_skins(mixed)) == 2
    plans, skipped = importer.plan_import(SOURCE,
        [{"id": "old", "author": "Artist", "downloadURL": "old"}],
        [{"name": "Release.zip", "browser_download_url": "release"}],
        {"old": mixed, "release": pack({"Copy.manicskin": second})}.__getitem__)
    assert plans == []
    assert skipped["identical"] == 1
