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


def registries():
    """The closed lists the reference prints, read from the renderer's source so the page can't drift from it."""
    import re
    source = (FORMAT.parent / "js" / "skin2" / "capabilities.ts").read_text(encoding="utf-8")
    pictures = re.findall(r'"([^"]+)"', re.search(r"PICTURE_SOURCES[^=]*= \[(.*?)\]", source).group(1))
    inputs = re.findall(r'\{ name: "([^"]+)", kind: "([^"]+)", label: "([^"]+)" \}', source)
    return pictures, inputs


def guide():
    """The prose sections above the schema definitions: the rules the schema can't say for panels."""
    pictures, inputs = registries()
    code = lambda text: f"<code>{escape(text)}</code>"
    picture_list = ", ".join(code("picture." + name) for name in pictures)
    rows = "\n".join(
        f"<tr><td>{code(name)}</td><td>{'two-position switch (reserved)' if kind == 'twoPosition' else 'momentary'}</td>"
        f"<td>{escape(label)}</td></tr>" for name, kind, label in inputs)
    return f"""<section id="capabilities"><h2>Capabilities</h2>
<p>A feature is what a reader can draw, and is fixed for a build of the app. A capability is what the app and the running game can supply right now: a memory unit's picture, a wired coin button. It can change during play. The app passes the capabilities it has to the skin, and a condition reads them with {code("has")}: one name or a list, all of which must be present.</p>
<pre><code>{escape('{ "type": "shape", "id": "lamp", "visible": { "has": "picture.vmu.p1" }, ... }')}</code></pre>
<p>The names come from a closed list: {picture_list}, and {code("input.<name>")} for each <a href="#semantic-inputs">semantic input</a>. Any other name is an error. {code("has")} works wherever {code("flag")} does. Using it is the feature {code("capabilities")}.</p>
</section>
<section id="accessory-screens"><h2>Accessory screens</h2>
<p>A {code("screen")} with a {code("source")} other than {code("game")} shows a picture the app supplies instead of the game: {", ".join(code(name) for name in pictures)}. It is never the game's viewport, takes no {code("role")} or {code("placement")}, and is left out of the classic bake. Without an {code("aspect")} it takes its source's (a memory unit is 48:32). {code("sampling")} is {code("nearest")} (the default, hard pixels) or {code("linear")}.</p>
<p>It draws only while the app has {code("picture.<source>")} and has handed over a picture. Otherwise it draws nothing and still takes its place in the layout, so put the housing around it in a <a href="#panels">panel</a> or under {code("visible")} with {code("has")}. Nodes listed after it draw over it: glass, a glare. A skin may have at most four. Each accessory screen and its ancestors may have only one copy. Use separate screen nodes to show the same picture in multiple places. Using one is the feature {code("screens.accessory")}.</p>
</section>
<section id="panels"><h2>Panels</h2>
<p>{code("panel")} on a group makes it a named area that exists only while the app has every capability in {code("needs")}. Without them the whole group is absent: not drawn, not touched, taking no space.</p>
<ul>
<li>A {code("fixed")} panel (the default) is always shown.</li>
<li>A {code("shelf")} opens and closes. Its {code("handle")} names a control inside the group of kind {code("action")} whose input is {code("togglePanel")}. That touch belongs to the skin and never reaches the game. Closed, only the handle remains.</li>
<li>The skin reads the state as the flag {code("panel.<name>.open")}, so its own {code("when")} entries can move or fade the panel. An app may not set flags that start with {code("panel.")}.</li>
<li>A {code("when")} entry may set {code("panel")}: {code('{"presentation": "fixed"}')}, so one panel can be fixed on an iPad and a shelf on a phone.</li>
<li>{code("open")} is the shelf's state the first time the skin is shown. After that the app remembers the player's choice.</li>
</ul>
<p>The validator checks each trait with the capabilities on and off and every combination of open and closed shelves. A shelf's handle must take touches in at least 44 by 44 points, stay inside the safe area, and never overlap another control. Panels do not nest, names are unique, and a skin has at most six. Panels are left out of the classic bake. Using one is the feature {code("panels")}.</p>
</section>
<section id="semantic-inputs"><h2>Semantic inputs</h2>
<p>Controller buttons keep their classic names ({code("a")}, {code("start")}). Things that are not pad buttons have dotted names from this list. A control with one is present only while the app has {code("input.<name>")}, with no condition to write, and sits on a {code("button")} or a {code("trigger")}. Using one is the feature {code("inputs.semantic")}.</p>
<div class="table-scroll"><table class="parts-table"><thead><tr><th>Input</th><th>Kind</th><th>Label</th></tr></thead><tbody>
{rows}
</tbody></table></div>
<p>Two-position switches are reserved for a switch control that is not built yet; the validator rejects them on a button.</p>
</section>
<section id="what-the-skin-provides"><h2>What the skin provides</h2>
<p>An app that has its own floating memory unit or coin button needs to know when the skin is already showing one. The resolved layout reports it: the picture sources the skin shows, the semantic inputs it has controls for, and each panel's open state. It is worked out from the laid-out skin, never from the source alone, so declaring a panel claims nothing.</p>
<ul>
<li>A picture counts when its screen is present, at least 48 by 32 points, inside the canvas and more than 5% opaque.</li>
<li>An input counts when its control is present with a hit frame of at least 44 by 44 points inside the canvas.</li>
<li>A closed shelf still counts for what it holds, as long as its handle can be reached: the player closed it and can open it again.</li>
<li>{code('"duplicate": true')} on a screen or a control marks a second copy that claims nothing.</li>
</ul>
<p>In the renderer this is {code("resolve(document, environment).provided")}. <a href="hosts.html">Hosting a skin with panels</a> shows the app's side.</p>
</section>"""


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
{guide()}
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
