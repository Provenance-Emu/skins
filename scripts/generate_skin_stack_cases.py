"""Write tests/fixtures/skin-stack/validate-cases.json from link_health.classify_archive.

The file holds synthetic broken skins plus every archive in fixtures/variants/ and every member folder in
fixtures/merge/, each with the verdict link_health.py gives it. tests/test_skin_stack_validate.py checks
link_health.py against the file and tests/js/skin-stack/validate.test.js checks docs/js/skin/validate.js
against it, so the two implementations cannot drift apart unnoticed.

Run after adding a case below, a fixture, or changing link_health.py's rules:
    python3 scripts/generate_skin_stack_cases.py
and review the diff: a changed verdict is a changed rule, and validate.js must follow.
"""
import io, json, sys, zipfile
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import link_health

def layout(asset=None, **extra):
    d = {"mappingSize": {"width": 100, "height": 200}, "items": []}
    if asset is not None:
        d["assets"] = {"resizable": asset} if isinstance(asset, str) else asset
    d.update(extra)
    return d

def info(**kw):
    d = {"identifier": "com.example.t", "name": "T", "gameTypeIdentifier": "com.rileytestut.delta.game.gba", "debug": False,
         "representations": {"iphone": {"edgeToEdge": {"portrait": layout("a.png"), "landscape": layout("b.png")}}}}
    d.update(kw)
    return d

J = lambda o: {"json": o}
cases = []
def case(name, files, note=""):
    cases.append({"name": name, "note": note, "files": files})

case("healthy", {"info.json": J(info()), "a.png": "x", "b.png": "x"})
case("no-info-json", {"a.png": "x", "readme.txt": "x"})
case("empty-archive", {})
case("nested-folder", {"My Skin/info.json": J(info()), "My Skin/a.png": "x", "My Skin/b.png": "x"})
case("pack-of-skins", {"one.deltaskin": "x", "two.manicskin": "x"})
case("pack-of-folders", {"One.deltaskin/info.json": "{}", "One.deltaskin/a.png": "x", "Two.MANICSKIN/info.json": "{}"})
case("junk-only-macosx", {"__MACOSX/._info.json": "x", ".DS_Store": "x", "sub/.DS_Store": "x", "a.png": "x"})
case("junk-beside-root-info", {"info.json": J(info()), "__MACOSX/._a.png": "x", ".DS_Store": "x", "a.png": "x", "b.png": "x"})
case("bad-json", {"info.json": "{ not json", "a.png": "x"})
case("not-an-object", {"info.json": "[1, 2, 3]", "a.png": "x"})
case("missing-keys", {"info.json": J({"name": "T", "representations": {}}), "a.png": "x"})
case("missing-representations", {"info.json": J({"identifier": "i", "name": "T", "gameTypeIdentifier": "g"}), "a.png": "x"})
case("no-artwork-anywhere", {"info.json": J(info())})
case("partial-artwork", {"info.json": J(info()), "a.png": "x"}, "landscape names b.png, which is missing")
case("empty-representations", {"info.json": J(info(representations={}))})
case("layout-without-assets", {"info.json": J(info(representations={"iphone": {"edgeToEdge": {"portrait": layout()}}}))})
case("layout-assets-not-an-object", {"info.json": J(info(representations={"iphone": {"edgeToEdge": {"portrait": layout(items=[], assets="a.png")}}})), "a.png": "x"})
case("lenient-case", {"info.json": J(info()), "Art/A.PNG": "x", "art/B.Png": "x"}, "file name matched anywhere, ignoring case")
case("lenient-case-upper-reference", {"info.json": J(info(representations={"iphone": {"edgeToEdge": {"portrait": layout("Skins/A.PNG"), "landscape": layout("B.Pdf")}}})), "art/a.png": "x", "deep/er/b.png": "x"}, "reference in capitals, files in lowercase elsewhere")
case("lenient-stem", {"info.json": J(info(representations={"iphone": {"edgeToEdge": {"portrait": layout("a.pdf")}}})), "a.png": "x"}, "same stem as .png")
case("lenient-stem-svg", {"info.json": J(info(representations={"iphone": {"edgeToEdge": {"portrait": layout("a.png")}}})), "a.svg": "x"})
case("size-fallback", {"info.json": J(info(representations={"iphone": {"edgeToEdge": {"portrait": layout({"resizable": "gone.pdf", "large": "big.png", "small": ""})}}})), "big.png": "x"})
case("directory-entries", {"info.json": J(info()), "Art/": "", "Art/a.png": "x", "b.png": "x"}, "directory entries are not files")
case("comments-and-trailing-commas", {"info.json": "{\n // a skin\n \"identifier\": \"i\", \"name\": \"T\", \"gameTypeIdentifier\": \"g\", // trailing\n \"representations\": {\"iphone\": {\"edgeToEdge\": {\"portrait\": {\"assets\": {\"resizable\": \"a.png\"},},},},},\n}\n", "a.png": "x"})
case("bom", {"info.json": "﻿" + json.dumps(info()), "a.png": "x", "b.png": "x"})
case("alt-layout-ok", {"info.json": J(info(altRepresentations={"iphone": {"edgeToEdge": {"portrait": layout("alt.png")}}})), "a.png": "x", "b.png": "x", "alt.png": "x"})
case("alt-layout-missing", {"info.json": J(info(altRepresentations={"iphone": {"edgeToEdge": {"portrait": layout("alt.png")}}})), "a.png": "x", "b.png": "x"})
case("alt-layout-names-nothing", {"info.json": J(info(altRepresentations={"iphone": {"edgeToEdge": {"portrait": layout()}}})), "a.png": "x", "b.png": "x"}, "strict: a gap")
case("themes-ok", {"info.json": J(info(themes=[{"id": "dark", "name": "Dark", "assets": {"iphone": {"edgeToEdge": {"portrait": {"resizable": "dark.png"}}}}}])), "a.png": "x", "b.png": "x", "dark.png": "x"})
case("theme-art-missing", {"info.json": J(info(themes=[{"id": "dark", "name": "Dark", "assets": {"iphone": {"edgeToEdge": {"portrait": {"resizable": "dark.png"}}}}}])), "a.png": "x", "b.png": "x"})
case("theme-names-nothing", {"info.json": J(info(themes=[{"id": "dark", "assets": {"iphone": {"edgeToEdge": {"portrait": {}}}}}, {"assets": {"iphone": {"edgeToEdge": {"portrait": {"large": "gone.png"}}}}}, "junk", {"id": "x", "assets": []}])), "a.png": "x", "b.png": "x"}, "not a gap; a theme with no id and a missing file is")
case("game-overrides", {"info.json": J(info(gameOverrides={"Doom": {"iphone": {"edgeToEdge": {"portrait": layout("doom.png")}}}, "Quake": {"iphone": {"edgeToEdge": {"portrait": layout("quake.png")}}}})), "a.png": "x", "b.png": "x", "doom.png": "x"})
case("variants-listed", {"info.json": J(info(altRepresentations={"iphone": {}}, themes=[{"id": " a ", "name": " A "}, {"id": "a"}, {"id": ""}, {"name": "no id"}], gameOverrides={"G": {}})), "a.png": "x", "b.png": "x"})
case("all-base-missing-variants-fine", {"info.json": J(info(altRepresentations={"iphone": {"edgeToEdge": {"portrait": layout("alt.png")}}})), "alt.png": "x"})
case("deep-layout", {"info.json": J(info(representations={"iphone": {"edgeToEdge": {"portrait": layout("a.png")}}, "ipad": {"standard": {"landscape": layout("gone.png")}}, "weird": [layout("a.png")]})), "a.png": "x"})

def build(files):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for path, content in files.items():
            if isinstance(content, dict):
                content = json.dumps(content["json"])
            if path.endswith("/"):
                zf.writestr(zipfile.ZipInfo(path), b"")
            else:
                zf.writestr(path, content.encode("utf-8"))
    buf.seek(0)
    return zipfile.ZipFile(buf)

def run(zf):
    r = link_health.classify_archive(zf)
    r.pop("error", None)
    return r

for c in cases:
    c["expected"] = run(build(c["files"]))

def zip_dir(d):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for p in sorted(d.rglob("*")):
            if p.is_file():
                zf.write(p, p.relative_to(d).as_posix())
    buf.seek(0)
    return zipfile.ZipFile(buf)

fixtures = []
for p in sorted((ROOT / "fixtures" / "variants").rglob("*")):
    if p.suffix in (".deltaskin", ".manicskin"):
        fixtures.append({"path": p.relative_to(ROOT).as_posix(), "expected": run(zipfile.ZipFile(p))})
for p in sorted((ROOT / "fixtures" / "merge").glob("*/members/*")):
    if p.is_dir():
        fixtures.append({"path": p.relative_to(ROOT).as_posix(), "zipDir": True, "expected": run(zip_dir(p))})

out = {"note": "Expected verdicts of link_health.classify_archive (without the free-text `error`). tests/test_skin_stack_validate.py checks the Python against this file, tests/js/skin-stack/validate.test.js checks docs/js/skin/validate.js against it. `files`: a string is the entry's text, {json: ...} is serialized, a name ending in / is a directory entry. Regenerate with scripts/generate_skin_stack_cases.py.",
       "cases": cases, "fixtures": fixtures}
dest = ROOT / "tests/fixtures/skin-stack/validate-cases.json"
dest.write_text(json.dumps(out, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
print(f"wrote {dest.relative_to(ROOT)}: {len(cases)} cases, {len(fixtures)} fixtures")
