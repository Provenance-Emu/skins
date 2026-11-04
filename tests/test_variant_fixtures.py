"""Tests for the sample variant skins in fixtures/variants/ and their generator.

The archives are decoded the way Delta (DeltaCore `ControllerSkin`), the
health check (`link_health.classify_archive`) and the catalog (`skin_schema`)
read them. No network access.
"""

import io
import json
import re
import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

import pytest
import generate_variant_fixtures as gen
import link_health as lh
import variants_sidecar as vs
from skin_schema import GTI_TO_CODE, make_id, system_from_gti, validate_entry

REPO = Path(__file__).parent.parent
FIXTURES = {fx.path: fx for fx in gen.FIXTURES}
ALL = sorted(FIXTURES)
SIZES = ("resizable", "small", "medium", "large")
ORIENTATIONS = {"portrait", "landscape"}
LAYOUT_KEYS = [(d, t, o) for d, t, o, _s in gen.LAYOUTS]


def open_skin(path: str) -> zipfile.ZipFile:
    return zipfile.ZipFile(gen.FIXTURES_DIR / path)


def info_of(path: str) -> dict:
    return lh.parse_info_json(open_skin(path).read("info.json"))


def rep_leaves(tree: dict):
    """(device, display, orientation, representation) for a device -> display -> orientation tree."""
    for device, displays in tree.items():
        for display, orientations in displays.items():
            for orientation, rep in orientations.items():
                yield device, display, orientation, rep


def delta_decodes(rep: dict) -> bool:
    """DeltaCore `ControllerSkin.Representation.init?`: mappingSize, an items array and an
    assets dictionary of strings naming at least one known size are required; items
    need a frame and inputs as a list of strings or a string dictionary."""
    size = rep.get("mappingSize")
    if not (isinstance(size, dict) and all(isinstance(size.get(k), (int, float)) for k in ("width", "height"))):
        return False
    if not isinstance(rep.get("items"), list):
        return False
    assets = rep.get("assets")
    if not (isinstance(assets, dict) and all(isinstance(v, str) for v in assets.values()) and set(assets) & set(SIZES)):
        return False
    for item in rep["items"]:
        frame = item.get("frame", {})
        if not all(isinstance(frame.get(k), (int, float)) for k in ("x", "y", "width", "height")):
            return False
        inputs = item.get("inputs")
        if not (isinstance(inputs, list) and all(isinstance(i, str) for i in inputs)
                or isinstance(inputs, dict) and all(isinstance(v, str) for v in inputs.values())):
            return False
    for screen in rep.get("screens", []):
        if not isinstance(screen.get("outputFrame"), dict):
            return False
    return True


def asset_files(rep: dict) -> set[str]:
    names = {v for v in rep.get("assets", {}).values()}
    names |= {i["thumbstick"]["name"] for i in rep.get("items", []) if "thumbstick" in i}
    return names


# ---------------------------------------------------------------------------
# Every fixture is a valid skin
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("path", ALL)
class TestEverySkin:
    def test_exists_with_the_right_extension(self, path):
        fx = FIXTURES[path]
        assert (gen.FIXTURES_DIR / path).is_file()
        assert path.endswith(".manicskin" if fx.gti.startswith("public.aoshuang") else ".deltaskin")

    def test_health_check_passes_with_no_artwork_gaps(self, path):
        result = lh.classify_archive(open_skin(path))
        assert result["result"] == "ok"
        assert "partialArtwork" not in result  # base and variant artwork all resolve

    def test_required_keys_and_system(self, path):
        info, fx = info_of(path), FIXTURES[path]
        assert all(k in info for k in lh.REQUIRED_INFO_KEYS)
        assert info["debug"] is False  # DeltaCore requires the key
        assert info["gameTypeIdentifier"] == fx.gti
        assert system_from_gti(fx.gti) == fx.system
        assert re.fullmatch(r"com\.provenance-emu\.sample\.[a-z0-9-]+", info["identifier"])

    def test_base_representations_are_complete_and_decode_like_delta(self, path):
        info = info_of(path)
        leaves = list(rep_leaves(info["representations"]))
        assert [(d, t, o) for d, t, o, _r in leaves] == LAYOUT_KEYS
        assert all(delta_decodes(rep) for *_k, rep in leaves)
        # at least one screen and the basic controls on every layout
        for *_k, rep in leaves:
            assert rep["screens"]
            labels = {i for it in rep["items"] if isinstance(it["inputs"], list) for i in it["inputs"]}
            assert {"menu"} <= labels

    def test_every_referenced_file_is_in_the_archive(self, path):
        z = open_skin(path)
        names = set(z.namelist())
        info = info_of(path)
        for *_k, rep in rep_leaves(info["representations"]):
            assert asset_files(rep) <= names
        for name in names - {"info.json"}:
            assert z.getinfo(name).file_size > 0
        # Every artwork file is a PNG with the screens cut out (some alpha).
        from PIL import Image
        for name in names:
            if name.endswith(".png") and name != "thumbstick.png":
                img = Image.open(io.BytesIO(z.read(name)))
                assert img.mode == "RGBA" and img.getextrema()[3][0] == 0, name

    def test_no_variant_key_is_needed_by_the_base(self, path):
        """Variant keys are additive: with them removed the skin is the same base skin."""
        info = info_of(path)
        stripped = {k: v for k, v in info.items() if k not in ("altRepresentations", "themes", "gameOverrides")}
        data = io.BytesIO()
        with zipfile.ZipFile(data, "w") as z:
            for name in open_skin(path).namelist():
                z.writestr(name, json.dumps(stripped) if name == "info.json" else open_skin(path).read(name))
        result = lh.classify_archive(zipfile.ZipFile(io.BytesIO(data.getvalue())))
        assert result["result"] == "ok" and result["variants"] == []


# ---------------------------------------------------------------------------
# Variant formats
# ---------------------------------------------------------------------------

class TestAltDS:
    path = "sample-alt-ds.deltaskin"

    def test_two_complete_layouts_with_swapped_screens(self):
        info = info_of(self.path)
        base, alt = list(rep_leaves(info["representations"])), list(rep_leaves(info["altRepresentations"]))
        assert [k[:3] for k in alt] == LAYOUT_KEYS
        for (_d, _t, _o, b), (*_k, a) in zip(base, alt):
            assert delta_decodes(a) and len(a["screens"]) == len(b["screens"]) == 2
            assert [s["inputFrame"] for s in a["screens"]] == [s["inputFrame"] for s in b["screens"]]
            assert [s["outputFrame"] for s in a["screens"]] == [s["outputFrame"] for s in reversed(b["screens"])]

    def test_toggle_button_in_both_sets(self):
        info = info_of(self.path)
        for tree in (info["representations"], info["altRepresentations"]):
            for *_k, rep in rep_leaves(tree):
                toggles = [i for i in rep["items"] if i["inputs"] == ["toggleAltRepresentations"]]
                assert len(toggles) == 1

    def test_touch_screen_follows_the_bottom_screen(self):
        info = info_of(self.path)
        for tree in (info["representations"], info["altRepresentations"]):
            for *_k, rep in rep_leaves(tree):
                [touch] = [i for i in rep["items"] if i["inputs"] == {"x": "touchScreenX", "y": "touchScreenY"}]
                assert touch["frame"] == rep["screens"][1]["outputFrame"]

    def test_variants(self):
        assert vs.compute_variants(info_of(self.path)) == [vs.compute_variants({"altRepresentations": {"x": 1}})[0]]


class TestThemesGBA:
    path = "sample-themes-gba.deltaskin"

    def test_base_plus_two_themes(self):
        info = info_of(self.path)
        assert [(t["id"], t["name"]) for t in info["themes"]] == [("dark", "Dark"), ("neon", "Neon")]
        assert vs.compute_variants(info) == [{"kind": "theme", "key": "dark", "label": "Dark"},
                                             {"kind": "theme", "key": "neon", "label": "Neon"}]

    def test_themes_swap_artwork_for_every_layout(self):
        info, names = info_of(self.path), set(open_skin(self.path).namelist())
        base_art = {rep["assets"]["large"] for *_k, rep in rep_leaves(info["representations"])}
        for theme in info["themes"]:
            leaves = list(rep_leaves(theme["assets"]))
            assert [k[:3] for k in leaves] == LAYOUT_KEYS
            art = {a["large"] for *_k, a in leaves}
            assert art <= names and not art & base_art and len(art) == len(LAYOUT_KEYS)


class TestGameOverridesJaguar:
    path = "sample-gameoverrides-jaguar.manicskin"

    def test_three_titles_and_one_md5(self):
        keys = list(info_of(self.path)["gameOverrides"])
        assert keys[:3] == ["Doom", "Alien vs Predator", "Wolfenstein 3D"]
        assert len(keys) == 4 and re.fullmatch(r"[0-9a-f]{32}", keys[3])
        assert keys[3] == gen.JAGUAR_MD5

    def test_each_override_is_a_whole_decodable_representation(self):
        info = info_of(self.path)
        names = set(open_skin(self.path).namelist())
        for game, tree in info["gameOverrides"].items():
            leaves = list(rep_leaves(tree))
            assert {k[:3] for k in leaves} == {("iphone", "edgeToEdge", "portrait"), ("iphone", "edgeToEdge", "landscape")}, game
            for *_k, rep in leaves:
                assert delta_decodes(rep) and asset_files(rep) <= names

    def test_overrides_differ_from_the_base_and_each_other(self):
        info = info_of(self.path)
        base = info["representations"]["iphone"]["edgeToEdge"]["portrait"]
        keypads = []
        for tree in info["gameOverrides"].values():
            rep = tree["iphone"]["edgeToEdge"]["portrait"]
            keypads.append(tuple(i["inputs"][0] for i in rep["items"] if isinstance(i["inputs"], list) and i["inputs"][0].startswith("num")))
            assert rep["assets"] != base["assets"]
        assert len(set(keypads)) == 4
        assert len(keypads[0]) < 12  # fewer keys than the base keypad

    def test_base_has_the_full_keypad(self):
        rep = info_of(self.path)["representations"]["iphone"]["edgeToEdge"]["portrait"]
        inputs = {i["inputs"][0] for i in rep["items"] if isinstance(i["inputs"], list)}
        assert {f"num{n}" for n in range(10)} | {"star", "pound", "a", "b", "y", "start", "select"} <= inputs


class TestSplitFamilies:
    @pytest.mark.parametrize("folder, system, gti, ext", [
        ("sample-split-family", "gba", "com.rileytestut.delta.game.gba", ".deltaskin"),
        ("sample-split-family-dc", "dreamcast", "public.aoshuang.game.dc", ".manicskin"),
        ("sample-split-family-gc", "gamecube", "public.aoshuang.game.ngc", ".manicskin"),
    ])
    def test_three_skins_sharing_a_group(self, folder, system, gti, ext):
        members = [fx for p, fx in FIXTURES.items() if p.startswith(folder + "/")]
        assert len(members) == 3
        assert len({fx.group for fx in members}) == 1 and members[0].group.startswith("sample:")
        assert [fx.order for fx in members] == [1, 2, 3]
        assert len({fx.label for fx in members}) == 3
        infos = [info_of(fx.path) for fx in members]
        assert len({i["identifier"] for i in infos}) == 3  # Manic rejects a repeated identifier
        assert {i["gameTypeIdentifier"] for i in infos} == {gti}
        assert all(fx.system == system and fx.path.endswith(ext) for fx in members)
        # split skins carry no single-file variants
        assert all(vs.compute_variants(i) == [] for i in infos)

    def test_dreamcast_and_gamecube_have_thumbsticks(self):
        for path in ("sample-split-family-dc/sample-split-dc-red.manicskin", "sample-split-family-gc/sample-split-gc-red.manicskin"):
            rep = info_of(path)["representations"]["iphone"]["edgeToEdge"]["portrait"]
            sticks = [i for i in rep["items"] if "thumbstick" in i]
            assert sticks and "thumbstick.png" in open_skin(path).namelist()
            assert "leftThumbstickUp" in sticks[0]["inputs"].values()


class TestNES:
    """The plain NES sample iCube's store tests install (SkinKit#90)."""
    path = "sample-nes.deltaskin"

    def test_nes_identity_and_no_variants(self):
        info = info_of(self.path)
        assert info["gameTypeIdentifier"] == "com.rileytestut.delta.game.nes"
        assert system_from_gti(info["gameTypeIdentifier"]) == "nes"
        assert vs.compute_variants(info) == []

    def test_iphone_and_ipad_layouts_with_the_nes_buttons(self):
        reps = info_of(self.path)["representations"]
        assert {"iphone", "ipad"} <= set(reps)
        for _d, _t, _o, rep in rep_leaves(reps):
            inputs = {i for item in rep["items"] for i in (item["inputs"] if isinstance(item["inputs"], list) else item["inputs"].values())}
            assert {"a", "b", "select", "start", "menu", "up", "down", "left", "right"} == inputs
            assert rep["screens"][0]["inputFrame"] == {"x": 0, "y": 0, "width": 256, "height": 240}


# ---------------------------------------------------------------------------
# Catalog entries
# ---------------------------------------------------------------------------

class TestCatalogEntries:
    def entry(self, fx):
        return json.loads(gen.entry_path(fx, REPO / "skins").read_text(encoding="utf-8"))

    @pytest.mark.parametrize("path", ALL)
    def test_entry_is_valid_and_points_at_the_raw_fixture(self, path):
        fx, e = FIXTURES[path], self.entry(FIXTURES[path])
        assert validate_entry(e) == []
        assert e["source"] == "provenance-emu" and e["tags"] == ["sample"]
        assert e["systems"] == [fx.system] and e["gameTypeIdentifier"] == fx.gti
        assert e["downloadURL"] == "https://raw.githubusercontent.com/Provenance-Emu/skins/main/fixtures/variants/" + path
        assert " " not in e["downloadURL"]
        assert e["id"] == make_id("provenance-emu", e["downloadURL"])
        assert e["fileSize"] == (gen.FIXTURES_DIR / path).stat().st_size
        assert e["name"].startswith("Sample ")

    @pytest.mark.parametrize("path", ALL)
    def test_grouping_fields(self, path):
        fx, e = FIXTURES[path], self.entry(FIXTURES[path])
        if fx.group:
            assert (e["groupId"], e["groupOrder"], e["variantLabel"]) == (fx.group, fx.order, fx.label)
            assert e["name"].endswith(" — " + fx.label)
        else:
            assert not e.get("groupId") and not e.get("variantLabel")

    def test_single_file_skins_have_sidecar_records(self):
        store = vs.load_variants(str(REPO / "variants.json"))
        for path in ("sample-alt-ds.deltaskin", "sample-themes-gba.deltaskin", "sample-gameoverrides-jaguar.manicskin"):
            e = self.entry(FIXTURES[path])
            assert store[e["id"]] == {"url": e["downloadURL"], "variants": vs.compute_variants(info_of(path))}
        for fx in FIXTURES.values():
            if fx.group:
                assert self.entry(fx)["id"] not in store

    def test_ids_and_urls_are_unique(self):
        entries = [self.entry(fx) for fx in FIXTURES.values()]
        assert len({e["id"] for e in entries}) == len({e["downloadURL"] for e in entries}) == len(entries) == 13


# ---------------------------------------------------------------------------
# Generator
# ---------------------------------------------------------------------------

class TestGenerator:
    def test_output_is_deterministic(self):
        lay = gen.build_layout(gen.GBA_KIT, (414, 896))
        assert gen.png_bytes(gen.draw_artwork(lay, gen.RED, "t")) == gen.png_bytes(gen.draw_artwork(lay, gen.RED, "t"))
        built = gen.Built({"name": "x"}, {"b.png": b"b", "a.png": b"a"})
        assert gen.zip_skin(built) == gen.zip_skin(built)
        assert zipfile.ZipFile(io.BytesIO(gen.zip_skin(built))).namelist() == ["info.json", "a.png", "b.png"]

    def test_committed_fixtures_match_the_generator(self, monkeypatch):
        """Same info.json and same file set as a fresh run (PNG bytes may differ across Pillow versions)."""
        monkeypatch.setattr(gen, "png_bytes", lambda img: b"png")
        for path in ALL:
            built = FIXTURES[path].build()
            z = open_skin(path)
            assert json.loads(z.read("info.json")) == built.info, path
            assert set(z.namelist()) == {"info.json", *built.files}, path

    def test_archive_layout(self):
        z = open_skin("sample-alt-ds.deltaskin")
        assert z.namelist()[0] == "info.json"
        assert {i.date_time for i in z.infolist()} == {(2026, 1, 1, 0, 0, 0)}

    def test_layout_frames_stay_on_the_canvas(self):
        kits = [gen.DS_KIT, gen.GBA_KIT, gen.JAGUAR_KIT, gen.DC_KIT, gen.GC_KIT, gen.NES_KIT, gen.Kit(**{**gen.DS_KIT.__dict__, "toggle": True})]
        for kit in kits:
            for *_k, size in gen.LAYOUTS:
                lay = gen.build_layout(kit, size)
                frames = [c.frame for c in lay.controls] + [out for _i, out in lay.screens]
                for x, y, w, h in frames:
                    assert x >= 0 and y >= 0 and x + w <= size[0] and y + h <= size[1], (kit, size, (x, y, w, h))

    def test_controls_do_not_cover_each_other(self):
        def overlap(a, b):
            return a[0] < b[0] + b[2] and b[0] < a[0] + a[2] and a[1] < b[1] + b[3] and b[1] < a[1] + a[3]
        for kit in (gen.DS_KIT, gen.GBA_KIT, gen.JAGUAR_KIT, gen.DC_KIT, gen.GC_KIT, gen.NES_KIT):
            for *_k, size in gen.LAYOUTS:
                lay = gen.build_layout(kit, size)
                cs = [c for c in lay.controls if c.shape != "touch"]
                for i, a in enumerate(cs):
                    for b in cs[i + 1:]:
                        assert not overlap(a.frame, b.frame), (size, a.label, b.label)
                    for _inp, out in lay.screens:
                        assert not overlap(a.frame, out), (size, a.label)

    def test_rewriting_entries_keeps_bot_filled_thumbnails(self, tmp_path):
        written = gen.generate(tmp_path / "fx")
        skins = tmp_path / "skins"
        fx = FIXTURES["sample-nes.deltaskin"]
        path = gen.entry_path(fx, skins)
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps({"thumbnailURL": "https://example.invalid/t.png", "screenshotURLs": ["https://example.invalid/s.png"]}))
        variants = tmp_path / "variants.json"
        gen.write_entries(written, skins, variants)
        e = json.loads(path.read_text())
        assert e["thumbnailURL"] == "https://example.invalid/t.png"
        assert e["screenshotURLs"] == ["https://example.invalid/s.png"]
        other = json.loads(gen.entry_path(FIXTURES["sample-themes-gba.deltaskin"], skins).read_text())
        assert other["thumbnailURL"] is None  # fresh entries still start empty
