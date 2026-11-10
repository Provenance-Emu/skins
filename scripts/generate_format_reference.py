"""Render the vendored SkinKit schema without dropping any fields or constraints."""

import argparse
from html import escape
import json
from pathlib import Path

FORMAT = Path(__file__).resolve().parents[1] / "docs" / "format"


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
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Skin format 2.0 reference · EmuSkins</title>
<link rel="stylesheet" href="../style.css">
<link rel="stylesheet" href="format.css">
</head>
<body>
<main>
<nav aria-label="Format documentation"><a href="./">Format 2.0</a> · <a href="tutorial.html">GameCube tutorial</a></nav>
<h1>Skin format 2.0 reference</h1>
<p>This reference is generated from the <a href="skin-2.0.schema.json">published JSON Schema</a>. A reference such as <code>#/$defs/layout</code> points to the corresponding definition below. Read the <a href="./">authoring guide</a> for rules the schema cannot express, including hit-frame overlap.</p>
<h2>Rendered examples</h2>
<div class="examples">
<figure data-skin-example="examples/gamecube.json"><figcaption>Controls, anchors and standard parts · <a href="examples/gamecube.json">JSON</a></figcaption></figure>
<figure data-skin-example="examples/shapes.json"><figcaption>Parametric shapes · <a href="examples/shapes.json">JSON</a></figcaption></figure>
<figure data-skin-example="examples/effects.json"><figcaption>Shadows, blur and blend · <a href="examples/effects.json">JSON</a></figcaption></figure>
</div>
<h2>Definitions</h2>
<ul class="definitions">{links}</ul>
{sections}
</main>
<script type="module" src="examples.js"></script>
</body>
</html>
"""


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
