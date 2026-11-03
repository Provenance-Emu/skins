"""Tests for the `mature` tag: schema, keyword matching, submission hook, report link."""

import json
import sys
from pathlib import Path
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

import pytest

from content_policy import (
    KEYWORDS_PATH,
    Keywords,
    apply_mature_tag,
    is_mature,
    mature_matches,
    report_url,
    scan,
    split_mature,
)
from process_submission import save_entries
from skin_schema import MATURE_TAG, normalize_entry, validate_entry


def skin(**over):
    base = {
        "id": "a1b2c3d4e5f60718",
        "name": "Plain Controller",
        "systems": ["gba"],
        "downloadURL": "https://example.com/Plain.deltaskin",
        "source": "manual",
    }
    return {**base, **over}


class TestSchema:
    def test_mature_tag_value(self):
        assert MATURE_TAG == "mature"

    def test_accepts_mature_tag(self):
        assert validate_entry(skin(tags=["portrait", "mature"])) == []

    def test_rejects_non_list_tags(self):
        assert validate_entry(skin(tags="mature"))

    def test_rejects_blank_tag(self):
        assert validate_entry(skin(tags=["ok", " "]))

    def test_rejects_duplicate_mature(self):
        assert validate_entry(skin(tags=["mature", "mature"]))

    def test_null_tags_still_valid(self):
        assert validate_entry(skin(tags=None)) == []


class TestKeywords:
    kw = Keywords(words=["nsfw", "sex", "18 plus", "adults only"], substrings=["hentai"])

    def test_whole_word_match(self):
        assert self.kw.find("Some NSFW Skin") == ["nsfw"]

    def test_word_does_not_match_inside_other_words(self):
        assert self.kw.find("Essex Middlesex Sussex") == []

    def test_punctuation_is_a_word_break(self):
        assert self.kw.find("pack_sex-edition.deltaskin") == ["sex"]

    def test_plus_is_spelled_out(self):
        assert self.kw.find("Skins 18+") == ["18 plus"]

    def test_phrase_match(self):
        assert self.kw.find("For Adults Only") == ["adults only"]

    def test_substring_match_inside_camel_case(self):
        assert self.kw.find("HentaiGBA") == ["hentai"]

    def test_no_match_on_ordinary_name(self):
        assert self.kw.find("Dreamsicle - pastel Dreamcast skin") == []

    def test_empty_text(self):
        assert self.kw.find("") == []


class TestShippedKeywordList:
    def test_file_loads_and_is_not_empty(self):
        kw = Keywords.load(KEYWORDS_PATH)
        assert kw.words and kw.substrings

    def test_every_listed_term_matches_itself(self):
        data = json.loads(Path(KEYWORDS_PATH).read_text())
        kw = Keywords.load(KEYWORDS_PATH)
        for term in data["words"] + data["substrings"]:
            assert kw.find(f"my {term} skin"), term

    @pytest.mark.parametrize("name", [
        "Sussex County GBA", "Analogue Pocket Dark GBC", "Essex Wii", "Sextant Pad",
        "Classic Controller Pro", "Mega Man X Edition", "Scunthorpe Edition",
    ])
    def test_ordinary_names_are_not_flagged(self, name):
        assert mature_matches(skin(name=name)) == []

    @pytest.mark.parametrize("name", ["NSFW Pack", "Hentai Waifu GBA", "xxx edition", "Lewd Pad"])
    def test_flagged_names(self, name):
        assert mature_matches(skin(name=name))


class TestMatchedFields:
    def test_searches_description_author_source_and_urls(self):
        kw = Keywords(words=["nsfw"])
        for field, value in [
            ("description", "this is nsfw"),
            ("author", "nsfw_artist"),
            ("source", "someone/nsfw-skins"),
            ("downloadURL", "https://example.com/nsfw-pad.deltaskin"),
            ("originalURL", "https://example.com/nsfw/pack.zip"),
        ]:
            assert mature_matches(skin(**{field: value}), kw) == [(field, "nsfw")], field

    def test_existing_tags_are_searched(self):
        assert mature_matches(skin(tags=["nsfw"]))

    def test_none_fields_do_not_crash(self):
        assert mature_matches(skin(description=None, author=None, tags=None)) == []


class TestApply:
    def test_adds_tag_on_match(self):
        entry = skin(name="NSFW Pad", tags=["portrait"])
        assert apply_mature_tag(entry) is True
        assert entry["tags"] == ["portrait", MATURE_TAG]

    def test_leaves_clean_entry_alone(self):
        entry = skin(tags=["portrait"])
        assert apply_mature_tag(entry) is False
        assert entry["tags"] == ["portrait"]

    def test_does_not_add_twice(self):
        entry = skin(name="NSFW Pad", tags=[MATURE_TAG])
        assert apply_mature_tag(entry) is False
        assert entry["tags"] == [MATURE_TAG]

    def test_works_on_normalized_entry_with_null_tags(self):
        entry = normalize_entry(skin(name="NSFW Pad"))
        entry["tags"] = None
        assert apply_mature_tag(entry) is True
        assert entry["tags"] == [MATURE_TAG]


class TestSaveEntriesHook:
    def test_submission_path_tags_matching_entry(self, tmp_path):
        entry = normalize_entry(skin(name="Lewd Pad"))
        [written] = save_entries([entry], str(tmp_path))
        assert MATURE_TAG in json.loads(Path(written).read_text())["tags"]

    def test_submission_path_leaves_clean_entry_untagged(self, tmp_path):
        entry = normalize_entry(skin(name="Dreamsicle"))
        [written] = save_entries([entry], str(tmp_path))
        assert MATURE_TAG not in json.loads(Path(written).read_text())["tags"]


class TestSplitAndReport:
    def test_split_mature_keeps_order(self):
        a, b, c = skin(id="a" * 16), skin(id="b" * 16, tags=[MATURE_TAG]), skin(id="c" * 16)
        visible, mature = split_mature([a, b, c])
        assert [s["id"] for s in visible] == ["a" * 16, "c" * 16]
        assert [s["id"] for s in mature] == ["b" * 16]
        assert is_mature(b) and not is_mature(a)

    def test_report_url_prefills_the_issue_form(self):
        url = report_url(skin(name="Weird & Wonderful"))
        parts = urlparse(url)
        q = parse_qs(parts.query)
        assert parts.path == "/Provenance-Emu/skins/issues/new"
        assert q["template"] == ["report-skin.yml"]
        assert q["skin_id"] == ["a1b2c3d4e5f60718"]
        assert q["skin_name"] == ["Weird & Wonderful"]
        assert q["skin_page"] == ["https://emuskins.com/s/a1b2c3d4e5f60718.html"]

    def test_issue_template_label_and_fields(self):
        text = (Path(__file__).parent.parent / ".github" / "ISSUE_TEMPLATE" / "report-skin.yml").read_text()
        assert 'labels: ["content-report"]' in text
        for field in ("skin_id", "skin_name", "skin_page"):
            assert f"id: {field}" in text


class TestScan:
    def test_scan_lists_matches_and_tagged(self, tmp_path):
        d = tmp_path / "gba"
        d.mkdir()
        (d / "a.json").write_text(json.dumps(skin(name="NSFW Pad")))
        (d / "b.json").write_text(json.dumps(skin(id="b" * 16, tags=[MATURE_TAG])))
        (d / "c.json").write_text(json.dumps(skin(id="c" * 16)))
        rows = scan(tmp_path)
        assert sorted(r["id"] for r in rows) == ["a1b2c3d4e5f60718", "b" * 16]
