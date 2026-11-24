#!/usr/bin/env python3
"""Generate RSS 2.0 feed from catalog.json for the EmuSkins site."""

import json
import os
import sys
from datetime import datetime, timezone
from email.utils import format_datetime
from xml.sax.saxutils import escape

sys.path.insert(0, os.path.dirname(__file__))
from added_dates import effective_date, sort_recent  # noqa: E402
from content_policy import split_mature  # noqa: E402

CATALOG_PATH = os.path.join(os.path.dirname(__file__), "..", "docs", "catalog.json")
OUTPUT_PATH  = os.path.join(os.path.dirname(__file__), "..", "docs", "feed.xml")
SITE_URL     = "https://emuskins.com/"
FEED_TITLE   = "EmuSkins"
FEED_DESC    = "Latest community controller skins for Provenance, iCube, iFly, Delta and Manic EMU"
MAX_ITEMS    = 20


def rfc2822(date_str: str) -> str:
    """Convert ISO date string to RFC 2822 format for pubDate."""
    try:
        dt = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return format_datetime(dt)
    except (ValueError, AttributeError):
        return format_datetime(datetime.now(timezone.utc))


def skin_permalink(skin: dict) -> str:
    skin_id = skin.get("id", "")
    return f"{SITE_URL}s/{skin_id}.html" if skin_id else SITE_URL


def build_description(skin: dict) -> str:
    parts = []
    if skin.get("author"):
        parts.append(f"Author: {skin['author']}")
    systems = skin.get("systems", [])
    if systems:
        parts.append(f"Systems: {', '.join(systems)}")
    tags = skin.get("tags", [])
    if tags:
        parts.append(f"Tags: {', '.join(tags)}")
    return " | ".join(parts) if parts else "Controller skin"


def line_permalink(line_id: str) -> str:
    return f"{SITE_URL}l/{line_id}.html"


def feed_items(skins: list[dict], lines: list[dict], limit: int = MAX_ITEMS) -> list[dict]:
    """The newest `limit` items. A skin outside any line is one item. A line's
    additions on one day are one item ("12 new layouts in <line>"), placed where the
    first of them sorts, so a bulk import takes one place in the feed.

    Each item: title, link, description, date, guid, permalink (whether the guid
    is the link), thumbnail."""
    by_id = {line["id"]: line for line in lines or [] if line.get("id")}
    items, slots = [], {}
    for skin in sort_recent(skins):
        line = by_id.get(skin.get("lineId"))
        date = effective_date(skin) or ""
        if not line:
            link = skin_permalink(skin)
            items.append({"title": skin.get("name") or "Unnamed Skin", "link": link,
                          "description": build_description(skin), "date": date, "guid": link,
                          "permalink": True, "thumbnail": skin.get("thumbnailURL")})
            continue
        key = (line["id"], date[:10])
        if key not in slots:
            slots[key] = {"title": "", "link": line_permalink(line["id"]),
                          "description": build_description(skin), "date": date,
                          "guid": f"line:{line['id']}:{date[:10]}", "permalink": False,
                          "thumbnail": skin.get("thumbnailURL"), "_layouts": set(), "_line": line}
            items.append(slots[key])
        slots[key]["_layouts"].add(skin.get("groupId") or f"skin:{skin.get('id')}")
    items = items[:limit]
    for item in items:
        layouts = item.pop("_layouts", None)
        line = item.pop("_line", None)
        if line:
            n = len(layouts)
            item["title"] = f"{n} new layout{'s' if n != 1 else ''} in {line.get('name') or 'a set'}"
    return items


def render_feed(items: list[dict]) -> str:
    now_rfc = format_datetime(datetime.now(timezone.utc))
    items_xml = []
    for item in items:
        link = escape(item["link"])
        enclosure = ""
        if item.get("thumbnail"):
            enclosure = f'        <enclosure url="{escape(item["thumbnail"])}" type="image/png" length="0"/>'
        guid = (f'<guid isPermaLink="true">{link}</guid>' if item["permalink"]
                else f'<guid isPermaLink="false">{escape(item["guid"])}</guid>')
        items_xml.append(f"""    <item>
        <title>{escape(item["title"])}</title>
        <link>{link}</link>
        <description>{escape(item["description"])}</description>
        <pubDate>{rfc2822(item["date"])}</pubDate>
        {guid}
{enclosure}
    </item>""")

    return f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom">
  <channel>
    <title>{escape(FEED_TITLE)}</title>
    <link>{escape(SITE_URL)}</link>
    <description>{escape(FEED_DESC)}</description>
    <lastBuildDate>{now_rfc}</lastBuildDate>
    <atom:link href="{escape(SITE_URL)}feed.xml" rel="self" type="application/rss+xml"/>
{chr(10).join(items_xml)}
  </channel>
</rss>
"""


def main():
    with open(CATALOG_PATH, encoding="utf-8") as f:
        data = json.load(f)

    skins, _mature = split_mature(data.get("skins", []))  # mature skins stay out of the feed

    # Newest first by lastUpdated, else addedAt (the date the skin file entered the
    # repo); equal dates order by name so the feed is stable.
    items = feed_items(skins, data.get("lines") or [], MAX_ITEMS)

    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        f.write(render_feed(items))

    print(f"Generated RSS feed with {len(items)} items → {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
