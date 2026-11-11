"""Render the vendored SkinKit schema without dropping any fields or constraints."""

import argparse
from html import escape
import json
from pathlib import Path

FORMAT = Path(__file__).resolve().parents[1] / "docs" / "format"

# The tabs under the site nav on every docs/format/ page: (href, label).
TABS = [
    ("./", "Overview"),
    ("tutorial.html", "Tutorial"),
    ("examples.html", "Examples"),
    ("playground.html", "Playground"),
    ("reference.html", "Reference"),
]


def page(*, current, file, title, description, heading, lede, body, scripts="", wide=False):
    """A docs/format/ page: the site nav, the format tabs, a heading and `body`.

    `current` is the tab's href (None for a page with no tab), `file` the page's name under format/ ("" for the
    index). `heading`, `lede` and `body` are HTML. The hand-written pages (index, tutorial, examples, playground,
    migration) carry the same chrome, and tests/test_format_pages.py keeps them in step with this.
    """
    tabs = "\n".join(
        f'    <a href="{href}"' + (' aria-current="page"' if href == current else "") + f">{label}</a>"
        for href, label in TABS
    )
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{escape(title)} · EmuSkins</title>
  <meta name="description" content="{escape(description)}">
  <link rel="canonical" href="https://emuskins.com/format/{file}">
  <link rel="stylesheet" href="../style.css">
  <link rel="stylesheet" href="format.css">
  <link rel="icon" href="../logo.svg" type="image/svg+xml">
  <link rel="apple-touch-icon" href="../apple-touch-icon.png">
  <meta name="theme-color" content="#FA3399">
</head>
<body>

<nav>
  <div class="nav-inner">
    <a href="../index.html" class="nav-logo" title="EmuSkins home"><img src="../logo.svg" alt="" width="28" height="28"><b>Emu<span>Skins</span></b></a>
    <div class="nav-links">
      <a href="../index.html">Browse</a>
      <a href="../systems/index.html">Systems</a>
      <a href="../authors/index.html">Authors</a>
      <a href="../submit.html">Submit</a>
      <a href="./" class="active">Create</a>
      <a href="https://wiki.provenance-emu.com/info/skins-guide" target="_blank">Docs</a>
      <a href="https://github.com/Provenance-Emu/skins" target="_blank" class="nav-cta">GitHub</a>
    </div>
  </div>
</nav>

<div class="format-tabs" role="navigation" aria-label="Format 2.0 documentation">
  <div class="format-tabs-inner">
    <span class="format-tabs-label">Format 2.0</span>
{tabs}
  </div>
</div>

<main class="format-main{" is-wide" if wide else ""}">
<header class="format-head">
<h1>{heading}</h1>
<p class="format-lede">{lede}</p>
</header>

{body}
</main>

<footer>
  <p>
    <a href="../index.html">Browse skins</a> ·
    <a href="../submit.html">Submit a Skin</a> ·
    <a href="https://github.com/Provenance-Emu/SkinKit" target="_blank">SkinKit</a> ·
    <a href="https://github.com/Provenance-Emu/skins" target="_blank">GitHub</a> ·
    <a href="https://discord.gg/provenance" target="_blank">Discord</a>
  </p>
</footer>
{scripts}
</body>
</html>
"""


def section(title, anchor, schema):
    content = escape(json.dumps(schema, ensure_ascii=False, indent=2))
    return (f'<section id="{escape(anchor)}"><h2>{escape(title)}</h2>\n'
            f'<details><summary>Show schema</summary><pre><code>{content}</code></pre></details></section>')


def render(schema):
    root = {key: value for key, value in schema.items() if key != "$defs"}
    definitions = schema["$defs"]
    entries = {"document": root, **definitions}
    links = "\n".join(f'<li><a href="#{escape(key)}">{escape(key)}</a></li>' for key in entries)
    sections = "\n".join(section(key, key, value) for key, value in entries.items())
    return page(
        current="reference.html",
        file="reference.html",
        title="Skin format 2.0 reference",
        description="Every node, field and allowed value in skin format 2.0, generated from the published JSON Schema.",
        heading="Schema <span>reference</span>",
        lede=('This page is generated from the <a href="skin-2.0.schema.json">published JSON Schema</a>. '
              'A reference such as <code>#/$defs/layout</code> points to the definition of that name below.'),
        body=f"""<p>The schema can't express every rule. The validator also checks that <code>requires</code> matches the content and that no two hit frames overlap; the <a href="playground.html">playground</a> runs it as you type. For sources to read, see the <a href="examples.html">examples</a>.</p>
<h2>Definitions</h2>
<ul class="definitions">{links}</ul>
{sections}""",
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    schema = json.loads((FORMAT / "skin-2.0.schema.json").read_text(encoding="utf-8"))
    target = FORMAT / "reference.html"
    content = render(schema)
    if args.check:
        if not target.exists() or target.read_text(encoding="utf-8") != content:
            parser.exit(1, "Run python3 scripts/generate_format_reference.py to regenerate the schema reference.\n")
    else:
        target.write_text(content, encoding="utf-8")


if __name__ == "__main__":
    main()
