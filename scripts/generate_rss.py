#!/usr/bin/env python3
"""Generate RSS 2.0 feed from catalog.json for Provenance Skins site."""

import json
import os
from datetime import datetime, timezone
from email.utils import format_datetime
from xml.sax.saxutils import escape

CATALOG_PATH = os.path.join(os.path.dirname(__file__), "..", "docs", "catalog.json")
OUTPUT_PATH  = os.path.join(os.path.dirname(__file__), "..", "docs", "feed.xml")
SITE_URL     = "https://provenance-emu.github.io/skins/"
FEED_TITLE   = "Provenance Skins"
FEED_DESC    = "Latest community controller skins for Provenance emulator"
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
    return f"{SITE_URL}?skin={skin_id}" if skin_id else SITE_URL


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
    return " | ".join(parts) if parts else "Provenance skin"


def main():
    with open(CATALOG_PATH, encoding="utf-8") as f:
        data = json.load(f)

    skins = data.get("skins", [])

    # Sort by lastUpdated descending, take top MAX_ITEMS
    def sort_key(s):
        lu = s.get("lastUpdated") or ""
        return lu

    skins_sorted = sorted(skins, key=sort_key, reverse=True)[:MAX_ITEMS]

    now_rfc = format_datetime(datetime.now(timezone.utc))

    items_xml = []
    for skin in skins_sorted:
        title   = escape(skin.get("name") or "Unnamed Skin")
        link    = escape(skin_permalink(skin))
        desc    = escape(build_description(skin))
        pub     = rfc2822(skin.get("lastUpdated") or "")
        guid    = escape(skin.get("id") or link)

        enclosure = ""
        thumb = skin.get("thumbnailURL")
        if thumb:
            enclosure = f'        <enclosure url="{escape(thumb)}" type="image/png" length="0"/>'

        items_xml.append(f"""    <item>
        <title>{title}</title>
        <link>{link}</link>
        <description>{desc}</description>
        <pubDate>{pub}</pubDate>
        <guid isPermaLink="true">{link}</guid>
{enclosure}
    </item>""")

    feed = f"""<?xml version="1.0" encoding="UTF-8"?>
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

    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        f.write(feed)

    print(f"Generated RSS feed with {len(skins_sorted)} items → {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
