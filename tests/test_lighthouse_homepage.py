import json

import pytest

from lighthouse_homepage import CATEGORIES, HOME, homepage_scores


def report(directory, name, url, score, final=None):
    (directory / f"lhr-{name}.json").write_text(json.dumps({
        "requestedUrl": url,
        "finalDisplayedUrl": final or url,
        "categories": {category: {"score": score} for category in CATEGORIES},
    }), encoding="utf-8")


def test_homepage_selection_ignores_systems_reports(tmp_path):
    report(tmp_path, "0", HOME + "systems/index.html", 1)
    for run, score in enumerate((0.64, 0.73, 0.81), 1):
        report(tmp_path, run, HOME, score)
    assert homepage_scores(tmp_path)["performance"] == [0.64, 0.73, 0.81]


def test_missing_homepage_reports_fails(tmp_path):
    report(tmp_path, "systems", HOME + "systems/index.html", 1)
    with pytest.raises(ValueError, match="found 0"):
        homepage_scores(tmp_path)


def test_redirected_homepage_report_fails(tmp_path):
    report(tmp_path, "redirect", HOME, 1, final=HOME + "systems/index.html")
    with pytest.raises(ValueError, match="did not complete"):
        homepage_scores(tmp_path)
