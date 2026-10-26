"""
Shared <head> tags for every EmuSkins page: title, description, canonical, and
the Open Graph / Twitter card set that Facebook, X, LinkedIn, Discord, Slack,
iMessage, WhatsApp and Telegram read.

Image width/height come from the file itself, so the tags can't disagree with
the card. `tests/test_share_meta.py` checks every generated page against this.
"""

import json
from html import escape
from pathlib import Path

from PIL import Image

SITE_URL = "https://emuskins.com/"
SITE_NAME = "EmuSkins"
DOCS_DIR = Path(__file__).parent.parent / "docs"
HOME_CARD = "cards/home.jpg"
HOME_CARD_ALT = ("EmuSkins logo above the words Free Controller Skins for iPhone & iPad emulators, "
                 "with five skin previews")


def system_card(code):
    """The system's own card if generate_share_cards.py made one, else the home card."""
    rel = f"cards/systems/{code}.jpg"
    return rel if (DOCS_DIR / rel).exists() else HOME_CARD


def image_size(rel):
    with Image.open(DOCS_DIR / rel) as im:
        return im.size


def head_meta(*, title, description, path, image=HOME_CARD, image_alt=HOME_CARD_ALT,
              og_type="website", indent="  ", external_image=None, card="summary_large_image"):
    """Tags for one page. `path` and `image` are relative to the site root
    ("" for the home page, "systems/snes.html", "cards/home.jpg").

    `external_image` is (url, (width, height)) for an image hosted elsewhere,
    such as a skin thumbnail; pair it with card="summary" for a small square
    preview."""
    url = SITE_URL + path
    if external_image:
        image_url, (width, height) = external_image
    else:
        image_url = SITE_URL + image
        width, height = image_size(image)
    image_type = "image/jpeg" if image_url.endswith((".jpg", ".jpeg")) else "image/png"
    t, d, a = escape(title), escape(description), escape(image_alt)
    lines = [
        f"<title>{t}</title>",
        f'<meta name="description" content="{d}">',
        f'<link rel="canonical" href="{url}">',
        f'<meta property="og:type" content="{og_type}">',
        f'<meta property="og:site_name" content="{SITE_NAME}">',
        '<meta property="og:locale" content="en_US">',
        f'<meta property="og:title" content="{t}">',
        f'<meta property="og:description" content="{d}">',
        f'<meta property="og:url" content="{url}">',
        f'<meta property="og:image" content="{image_url}">',
        f'<meta property="og:image:type" content="{image_type}">',
        f'<meta property="og:image:width" content="{width}">',
        f'<meta property="og:image:height" content="{height}">',
        f'<meta property="og:image:alt" content="{a}">',
        f'<meta name="twitter:card" content="{card}">',
        f'<meta name="twitter:title" content="{t}">',
        f'<meta name="twitter:description" content="{d}">',
        f'<meta name="twitter:image" content="{image_url}">',
        f'<meta name="twitter:image:alt" content="{a}">',
    ]
    return "".join(f"{indent}{line}\n" for line in lines)


def breadcrumb_jsonld(crumbs, indent="  "):
    """A BreadcrumbList <script> for `crumbs`, a list of (name, path) from the home page down."""
    data = {
        "@context": "https://schema.org",
        "@type": "BreadcrumbList",
        "itemListElement": [
            {"@type": "ListItem", "position": i + 1, "name": name, "item": SITE_URL + path}
            for i, (name, path) in enumerate(crumbs)
        ],
    }
    body = json.dumps(data, ensure_ascii=False).replace("<", "\\u003c")
    return f'{indent}<script type="application/ld+json">{body}</script>\n'
