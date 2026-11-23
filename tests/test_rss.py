"""The feed lists a line's additions once per day, not once per file."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

import generate_rss as rss

LINE = {"id": "a-pad", "name": "Toy Pad"}


def skin(sid, name, added, **extra):
    return {"id": sid, "name": name, "addedAt": added, "author": "Ann", "systems": ["mame"], **extra}


def member(sid, group, added, **extra):
    return skin(sid, f"Toy Pad {sid}", added, lineId="a-pad", groupId=group, **extra)


def catalog_skins():
    return [
        member("m1", "g1", "2026-11-20"), member("m2", "g1", "2026-11-20"),
        member("m3", "g2", "2026-11-20"), member("m4", "g3", "2026-11-20"), member("m5", "g3", "2026-11-20"),
        member("m6", "g4", "2026-11-22", thumbnailURL="https://example.com/m6.png"),
        skin("u1", "Unrelated Skin", "2026-11-21"),
    ]


def test_feed_groups_a_lines_additions_by_day():
    items = rss.feed_items(catalog_skins(), [LINE], limit=50)
    assert [i["title"] for i in items] == ["1 new layout in Toy Pad", "Unrelated Skin", "3 new layouts in Toy Pad"]
    assert items[0]["link"] == "https://emuskins.com/l/a-pad.html"
    assert items[0]["guid"] == "line:a-pad:2026-11-22" and items[0]["permalink"] is False
    assert items[0]["thumbnail"] == "https://example.com/m6.png"
    assert items[2]["guid"] == "line:a-pad:2026-11-20" and items[2]["date"] == "2026-11-20"
    assert items[1]["link"] == "https://emuskins.com/s/u1.html" and items[1]["permalink"] is True


def test_limit_counts_items_not_files():
    skins = catalog_skins() + [skin(f"x{i}", f"Extra {i}", "2026-11-19") for i in range(5)]
    items = rss.feed_items(skins, [LINE], limit=4)
    assert [i["title"] for i in items] == ["1 new layout in Toy Pad", "Unrelated Skin", "3 new layouts in Toy Pad", "Extra 0"]


def test_members_of_an_unknown_line_are_ordinary_items():
    items = rss.feed_items(catalog_skins(), [], limit=50)
    assert len(items) == 7 and items[0]["title"] == "Toy Pad m6"


def test_ungrouped_member_counts_as_one_layout():
    skins = [skin("m1", "Toy Pad m1", "2026-11-20", lineId="a-pad"),
             skin("m2", "Toy Pad m2", "2026-11-20", lineId="a-pad")]
    assert rss.feed_items(skins, [LINE], limit=5)[0]["title"] == "2 new layouts in Toy Pad"


def test_render_escapes_and_marks_guid(tmp_path):
    xml = rss.render_feed(rss.feed_items(catalog_skins(), [{"id": "a-pad", "name": "Pad & <Co>"}], limit=50))
    assert "1 new layout in Pad &amp; &lt;Co&gt;" in xml
    assert '<guid isPermaLink="false">line:a-pad:2026-11-22</guid>' in xml
    assert '<guid isPermaLink="true">https://emuskins.com/s/u1.html</guid>' in xml
    assert xml.count("<item>") == 3
