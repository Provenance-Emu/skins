"""Report median Lighthouse scores from three runs of the EmuSkins homepage."""

import argparse
import json
import math
import os
from pathlib import Path
from statistics import median


HOME = "https://emuskins.com/"
RUNS = 3
CATEGORIES = {
    "performance": ("Performance", "performance", 70),
    "accessibility": ("Accessibility", "accessibility", 80),
    "best-practices": ("Best practices", "best_practices", 80),
    "seo": ("SEO", "seo", 90),
}


def homepage_scores(directory):
    scores = {category: [] for category in CATEGORIES}
    for path in sorted(directory.rglob("lhr-*.json")):
        report = json.loads(path.read_text(encoding="utf-8"))
        if report.get("requestedUrl") != HOME:
            continue
        final = report.get("finalDisplayedUrl") or report.get("finalUrl")
        if final != HOME or report.get("runtimeError"):
            raise ValueError(f"{path.name}: homepage audit did not complete at {HOME}")
        for category, values in scores.items():
            value = report.get("categories", {}).get(category, {}).get("score")
            if type(value) not in (int, float) or not 0 <= value <= 1:
                raise ValueError(f"{path.name}: invalid {category} score")
            values.append(value)
    count = len(scores["performance"])
    if count != RUNS:
        raise ValueError(f"Expected {RUNS} homepage reports for {HOME}, found {count}")
    return scores


def percentage(value):
    return math.floor(value * 100 + 0.5)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("reports", type=Path)
    args = parser.parse_args()
    try:
        scores = homepage_scores(args.reports)
    except (OSError, ValueError) as error:
        parser.exit(1, f"{error}\n")
    summary = [
        "## Lighthouse — EmuSkins homepage",
        "",
        "| Category | Runs | Median | Threshold |",
        "|----------|------|--------|-----------|",
    ]
    outputs = []
    for category, (label, key, threshold) in CATEGORIES.items():
        values = scores[category]
        score = percentage(median(values))
        samples = ", ".join(str(percentage(value)) for value in values)
        summary.append(f"| {label} | {samples} | {score} | {threshold} |")
        outputs.append(f"{key}={score}")
    report = "\n".join(summary) + "\n"
    print(report, end="")
    for key, contents in (
        ("GITHUB_STEP_SUMMARY", report),
        ("GITHUB_OUTPUT", "\n".join(outputs) + "\n"),
    ):
        if key in os.environ:
            with open(os.environ[key], "a", encoding="utf-8") as target:
                target.write(contents)


if __name__ == "__main__":
    main()
