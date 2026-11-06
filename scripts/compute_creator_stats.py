#!/usr/bin/env python3
"""
compute_creator_stats.py — creator stats and badges for docs/creators.json.

Runs in build-catalog.yml right after build_catalog.py. Reads the built catalog
(docs/catalog.json: hidden-download entries are already gone, `creator` and the
sidecar `variants` are already merged in), the directory (docs/creators.json),
badges.json (what each badge is called), disputed.json (entries that count
toward nothing) and badge-dates.json (when each badge was first true), and
rewrites docs/creators.json plus docs/creators/<slug>.json with a `stats` and a
`badges` block on every record. Nothing is stored in the hand-edited
creators/<slug>.json.

    python3 scripts/compute_creator_stats.py              # write
    python3 scripts/compute_creator_stats.py --dry-run    # print the distribution, write nothing

Design: SkinKit docs/specs/2026-11-03-gamification-design.md §1, §2 and §4.

What counts. Per creator, over the entries the catalog lists, minus `sample`
skins, minus ids in disputed.json, minus "All variants" files `merge_variants.py`
builds (`mergedFrom`; they repack members that already count):

    releases           families (`groupId`) plus ungrouped entries
    files              entries
    variantsCompleted  members of families with 2+ members, plus the `variants` a
                       single file carries inside its archive
    systems            distinct system codes, `unofficial` excluded
    dualScreen         entries for a two-screen system (nds, threeDS)
    firstAddedAt       oldest `addedAt` (else `lastUpdated`)
    lastAddedAt        newest effective date (`lastUpdated`, else `addedAt`)
    reachTier          0-3 from the summed thumbnail views, see REACH_TIERS

`downloadCount` is how often a skin's thumbnail was fetched. It is reach, not
installs, so only the coarse tier is published; the sum never is.

Badges. RULES maps each creator badge id in badges.json to a test over the
stats. A badge is earned the first build it tests true; `earnedAt` is that
build's date, kept in badge-dates.json so it does not move on rebuilds (and so a
badge a dispute takes away comes back with its date). Unclaimed creators publish
only the UNCLAIMED_BADGES; their dates are still recorded, so claiming a profile
later does not reset them. Tiered badges (`creator.systems.3/5/10`) are all
published; a consumer shows the highest per stem.

Each published badge is {id, title, description, symbol, tier?, earnedAt}.
"""

import argparse
import json
import os
import re
import sys
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent))
import creator_directory
from added_dates import effective_date
from disputed import DISPUTED_FILE, DisputedError, load_disputed

BADGES_FILE = "badges.json"
BADGE_DATES_FILE = "badge-dates.json"
BADGES_VERSION = 1
BADGE_DATES_VERSION = 1

# Starting points; tune against `--dry-run` on the real catalog (spec "Left to the builder").
SYSTEM_TIERS = (3, 5, 10)
REACH_TIERS = (1_000, 10_000, 100_000)   # summed thumbnail views -> reachTier 1, 2, 3
FAMILY_BUILDER_MIN = 3                    # members in one family
VETERAN_DAYS = 365

# Same set as generate_system_pages.DUAL_SCREEN_SYSTEMS (a test pins them together).
DUAL_SCREEN_SYSTEMS = frozenset({"nds", "threeDS"})
ORIENTATION_TAGS = ("portrait", "landscape")

_BADGE_ID_RE = re.compile(r"^(creator|user)(\.[a-z0-9]+(-[a-z0-9]+)*)+$")
BADGE_AUDIENCES = ("creator", "user")
_PUBLISHED_FIELDS = ("id", "title", "description", "symbol", "tier")


# ---------------------------------------------------------------------------
# What counts
# ---------------------------------------------------------------------------

def countable(entry: dict, disputed=frozenset()) -> bool:
    """True when the entry counts toward its creator's stats."""
    if "sample" in (entry.get("tags") or []):
        return False
    if entry.get("mergedFrom"):
        return False
    return entry.get("id") not in disputed


def _day(value) -> Optional[date]:
    try:
        return date.fromisoformat(value) if isinstance(value, str) else None
    except ValueError:
        return None


def _views(entry: dict) -> int:
    n = entry.get("downloadCount")
    return n if isinstance(n, int) and not isinstance(n, bool) and n > 0 else 0


def reach_tier(views: int) -> int:
    return sum(1 for floor in REACH_TIERS if views >= floor)


def compute_stats(entries: list[dict]) -> tuple[dict, dict]:
    """(stats, facts) for one creator's countable entries. `stats` is published;
    `facts` carries what badge rules need and nothing public (the raw views)."""
    families: dict[str, list[dict]] = defaultdict(list)
    ungrouped = 0
    codes: set[str] = set()
    dual = 0
    variants_in_files = 0
    most_variants_in_file = 0
    views = 0
    first: list[str] = []
    last: list[str] = []

    for e in entries:
        if e.get("groupId"):
            families[e["groupId"]].append(e)
        else:
            ungrouped += 1
        entry_codes = set(e.get("systems") or [])
        codes |= entry_codes
        if entry_codes & DUAL_SCREEN_SYSTEMS:
            dual += 1
        n_variants = len(e.get("variants") or [])
        variants_in_files += n_variants
        most_variants_in_file = max(most_variants_in_file, n_variants)
        views += _views(e)
        if _day(e.get("addedAt") or e.get("lastUpdated")):
            first.append(e.get("addedAt") or e.get("lastUpdated"))
        eff = effective_date(e)
        if _day(eff):
            last.append(eff)

    in_families = sum(len(m) for m in families.values() if len(m) >= 2)
    groups = list(families.values()) + [[e] for e in entries if not e.get("groupId")]
    both_orientations = any(
        all(t in {t for m in g for t in (m.get("tags") or [])} for t in ORIENTATION_TAGS)
        for g in groups)

    stats = {
        "releases": len(families) + ungrouped,
        "files": len(entries),
        "variantsCompleted": in_families + variants_in_files,
        "systems": len(codes - {"unofficial"}),
        "dualScreen": dual,
        "firstAddedAt": min(first) if first else None,
        "lastAddedAt": max(last) if last else None,
        "reachTier": reach_tier(views),
    }
    facts = {
        "largestFamily": max((len(m) for m in families.values()), default=0),
        "bothOrientations": both_orientations,
        "mostVariantsInFile": most_variants_in_file,
        "views": views,
    }
    return stats, facts


# ---------------------------------------------------------------------------
# Badge rules
# ---------------------------------------------------------------------------

def _veteran(stats: dict, today: date) -> bool:
    first = _day(stats.get("firstAddedAt"))
    return bool(stats["files"] >= 1 and first and first <= today - timedelta(days=VETERAN_DAYS))


def _rules() -> dict:
    rules = {
        "creator.first-release": lambda s, f, claimed, today: s["releases"] >= 1,
        "creator.family-builder": lambda s, f, claimed, today: f["largestFamily"] >= FAMILY_BUILDER_MIN,
        # Orientation has no field of its own; the `portrait`/`landscape` tags are the signal.
        "creator.completionist": lambda s, f, claimed, today: (
            f["bothOrientations"] or f["mostVariantsInFile"] >= 2),
        "creator.dual-screen": lambda s, f, claimed, today: s["dualScreen"] >= 1,
        "creator.veteran": lambda s, f, claimed, today: _veteran(s, today),
        "creator.claimed": lambda s, f, claimed, today: bool(claimed),
    }
    for n in SYSTEM_TIERS:
        rules[f"creator.systems.{n}"] = lambda s, f, claimed, today, n=n: s["systems"] >= n
    for tier in range(1, len(REACH_TIERS) + 1):
        rules[f"creator.reach.{tier}"] = lambda s, f, claimed, today, tier=tier: s["reachTier"] >= tier
    return rules


RULES = _rules()

# What an unclaimed creator's page may show (spec §2 "Display"); claiming unlocks the rest.
UNCLAIMED_BADGES = frozenset(
    ["creator.first-release"] + [f"creator.systems.{n}" for n in SYSTEM_TIERS])


def earned_ids(stats: dict, facts: dict, claimed: bool, today: date) -> list[str]:
    """Every badge id whose rule tests true, before the claimed/unclaimed cut."""
    return [bid for bid, rule in RULES.items() if rule(stats, facts, claimed, today)]


def apply_earned_dates(dates: dict, slug: str, earned: list[str], today: str) -> dict:
    """Stamp `today` on each id in `earned` the creator has no date for yet
    (in place in `dates[slug]`). Dates are never moved or removed."""
    own = dates.setdefault(slug, {})
    for bid in earned:
        own.setdefault(bid, today)
    return own


def published_badges(earned: list[str], claimed: bool, defs: dict, own_dates: dict) -> list[dict]:
    """The `badges` block: earned ids in badges.json order, gated by claim status."""
    allowed = set(earned) if claimed else set(earned) & UNCLAIMED_BADGES
    out = []
    for bid, d in defs.items():
        if bid in allowed:
            badge = {k: d[k] for k in _PUBLISHED_FIELDS if k in d}
            badge["earnedAt"] = own_dates[bid]
            out.append(badge)
    return out


# ---------------------------------------------------------------------------
# badges.json
# ---------------------------------------------------------------------------

def validate_badges(doc, rule_ids=None) -> list[str]:
    """Error strings for a parsed badges.json (empty = valid). With `rule_ids`,
    also requires every creator badge to have a rule and every rule a badge, so
    the data and the code cannot drift apart."""
    if not isinstance(doc, dict):
        return ["must be a JSON object"]
    errors = []
    if doc.get("version") != BADGES_VERSION:
        errors.append(f"version must be {BADGES_VERSION}, got {doc.get('version')!r}")
    for key in sorted(set(doc) - {"version", "badges"}):
        errors.append(f"unknown top-level key: {key}")
    badges = doc.get("badges")
    if not isinstance(badges, list) or not badges:
        errors.append('"badges" must be a non-empty array')
        return errors

    seen: dict[str, int] = {}
    tiers: dict[str, set] = defaultdict(set)
    tiered_stems, plain_stems = set(), set()
    creator_ids = set()
    for i, b in enumerate(badges):
        if not isinstance(b, dict):
            errors.append(f"badges[{i}]: must be an object")
            continue
        bid = b.get("id")
        label = f"badges[{i}] ({bid})" if isinstance(bid, str) else f"badges[{i}]"
        if not isinstance(bid, str) or not _BADGE_ID_RE.fullmatch(bid):
            errors.append(f"{label}: id must look like creator.systems.5 (lowercase, dot-separated)")
            continue
        if bid.lower() in seen:
            errors.append(f"{label}: duplicate id")
        seen[bid.lower()] = i
        audience = b.get("for")
        if audience not in BADGE_AUDIENCES:
            errors.append(f"{label}: for must be one of {list(BADGE_AUDIENCES)}")
        elif not bid.startswith(audience + "."):
            errors.append(f"{label}: id must start with {audience + '.'!r} to match for")
        for field in ("title", "description", "symbol"):
            v = b.get(field)
            if not isinstance(v, str) or not v.strip() or v != v.strip():
                errors.append(f"{label}: {field} must be a non-empty string without leading or trailing spaces")
        for field in sorted(set(b) - {"id", "for", "title", "description", "symbol", "tier"}):
            errors.append(f"{label}: unknown field: {field}")
        stem = bid.rsplit(".", 1)[0]
        tier = b.get("tier")
        if "tier" in b:
            if not isinstance(tier, int) or isinstance(tier, bool) or tier < 1:
                errors.append(f"{label}: tier must be a positive integer")
            elif tier in tiers[stem]:
                errors.append(f"{label}: tier {tier} is used twice under {stem}")
            else:
                tiers[stem].add(tier)
            tiered_stems.add(stem)
        else:
            plain_stems.add(stem)
        if audience == "creator":
            creator_ids.add(bid)

    for stem in sorted(tiered_stems & plain_stems):
        errors.append(f"{stem}: some badges under this stem have a tier and some do not")
    if rule_ids is not None:
        for bid in sorted(set(rule_ids) - creator_ids):
            errors.append(f"{bid}: has a rule in compute_creator_stats.py but no entry in badges.json")
        for bid in sorted(creator_ids - set(rule_ids)):
            errors.append(f"{bid}: is in badges.json but compute_creator_stats.py has no rule for it")
    return errors


def load_badges(path: str = BADGES_FILE) -> dict:
    """badges.json as {id: definition} for creator badges, in file order.
    Raises ValueError when the file is missing or invalid."""
    try:
        with open(path, encoding="utf-8") as f:
            doc = json.load(f)
    except (OSError, json.JSONDecodeError, UnicodeDecodeError) as e:
        raise ValueError(f"{path}: {e}") from e
    errors = validate_badges(doc, rule_ids=RULES)
    if errors:
        raise ValueError(f"{path}: " + "; ".join(errors))
    return {b["id"]: b for b in doc["badges"] if b["for"] == "creator"}


def check_badges_file(path: str = BADGES_FILE) -> list[str]:
    """For build_catalog --check-only: error strings, empty when valid."""
    try:
        load_badges(path)
    except ValueError as e:
        return [str(e)]
    return []


# ---------------------------------------------------------------------------
# badge-dates.json
# ---------------------------------------------------------------------------

def load_badge_dates(path: str = BADGE_DATES_FILE) -> dict:
    """{slug: {badge id: YYYY-MM-DD}}; {} when the file is missing or unreadable
    (a lost file restarts the dates, it never breaks a build)."""
    try:
        with open(path, encoding="utf-8") as f:
            doc = json.load(f)
        dates = doc["dates"]
        return {slug: {b: d for b, d in own.items() if _day(d)}
                for slug, own in dates.items() if isinstance(own, dict)}
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return {}


def save_badge_dates(dates: dict, path: str = BADGE_DATES_FILE) -> bool:
    """Write sorted; leave the file alone when nothing changed. True if written."""
    doc = {"version": BADGE_DATES_VERSION,
           "dates": {slug: {b: own[b] for b in sorted(own)} for slug, own in sorted(dates.items()) if own}}
    text = json.dumps(doc, indent=2, ensure_ascii=False) + "\n"
    try:
        with open(path, encoding="utf-8") as f:
            if f.read() == text:
                return False
    except OSError:
        pass
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    return True


# ---------------------------------------------------------------------------
# The pass over the directory
# ---------------------------------------------------------------------------

def compute_all(catalog: dict, directory: dict, defs: dict, disputed, dates: dict,
                today: str) -> dict:
    """Add `stats` and `badges` to every record of `directory` (in place) and
    stamp new badge dates into `dates` (in place). Returns a report dict."""
    today_d = date.fromisoformat(today)
    by_creator: dict[str, list[dict]] = defaultdict(list)
    left_out = Counter()
    for e in catalog.get("skins", []):
        slug = e.get("creator")
        if not slug:
            continue
        if countable(e, disputed):
            by_creator[slug].append(e)
        elif e.get("id") in disputed:
            left_out["disputed"] += 1
        elif e.get("mergedFrom"):
            left_out["merged"] += 1
        else:
            left_out["sample"] += 1

    report = {"creators": 0, "claimed": 0, "stats": [], "earned": Counter(), "published": Counter(),
              "left_out": left_out}
    for record in directory.get("creators", []):
        slug = record["slug"]
        claimed = bool(record.get("claimed"))
        stats, facts = compute_stats(by_creator.get(slug, []))
        earned = earned_ids(stats, facts, claimed, today_d)
        own = apply_earned_dates(dates, slug, earned, today)
        badges = published_badges(earned, claimed, defs, own)
        record["stats"] = stats
        record["badges"] = badges

        report["creators"] += 1
        report["claimed"] += claimed
        report["stats"].append(stats)
        report["earned"].update(earned)
        report["published"].update(b["id"] for b in badges)
    return report


def _bucket(n: int, edges: tuple) -> str:
    for lo, hi in zip(edges, edges[1:] + (None,)):
        if hi is None:
            return f"{lo}+"
        if lo <= n < hi:
            return str(lo) if hi == lo + 1 else f"{lo}-{hi - 1}"
    return str(n)


def format_report(report: dict, defs: dict) -> str:
    """Aggregate distributions only: no creator names and no raw view sums, because
    this lands in public Actions logs and the PR."""
    lines = [f"Creators: {report['creators']} ({report['claimed']} claimed)"]
    lo = report["left_out"]
    if lo:
        lines.append("Left out of every creator's stats: " +
                     ", ".join(f"{n} {why}" for why, n in sorted(lo.items())))
    stats = report["stats"]
    for key, edges in (("releases", (0, 1, 2, 3, 6, 11, 26)), ("files", (0, 1, 2, 6, 11, 26, 51)),
                       ("systems", (0, 1, 2, 3, 4, 5, 10)), ("variantsCompleted", (0, 1, 3, 6, 11, 26)),
                       ("reachTier", (0, 1, 2, 3))):
        counts = Counter(_bucket(s[key], edges) for s in stats)
        order = [_bucket(e, edges) for e in edges]
        lines.append(f"{key:18} " + "  ".join(f"{b}:{counts[b]}" for b in order if counts[b]))
    lines.append("Badges earned (published after the claimed cut):")
    for bid in defs:
        lines.append(f"  {bid:26} {report['earned'][bid]:4} ({report['published'][bid]})")
    return "\n".join(lines)


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Add stats and badges to docs/creators.json")
    p.add_argument("--docs-dir", default="docs", help="Holds catalog.json and creators.json (rewritten)")
    p.add_argument("--badges-file", default=BADGES_FILE)
    p.add_argument("--disputed-file", default=DISPUTED_FILE)
    p.add_argument("--dates-file", default=BADGE_DATES_FILE)
    p.add_argument("--today", help="YYYY-MM-DD; defaults to today (UTC). For reproducible runs and tests")
    p.add_argument("--dry-run", action="store_true",
                   help="Print the distribution; write neither creators.json nor the dates file")
    args = p.parse_args(argv)

    today = args.today or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    if _day(today) is None:
        print(f"--today must be YYYY-MM-DD, got {today!r}", file=sys.stderr)
        return 2
    try:
        defs = load_badges(args.badges_file)
        disputed = load_disputed(args.disputed_file)
        with open(os.path.join(args.docs_dir, "catalog.json"), encoding="utf-8") as f:
            catalog = json.load(f)
        with open(os.path.join(args.docs_dir, "creators.json"), encoding="utf-8") as f:
            directory = json.load(f)
    except (ValueError, DisputedError, OSError) as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1

    dates = load_badge_dates(args.dates_file)
    report = compute_all(catalog, directory, defs, set(disputed), dates, today)
    text = format_report(report, defs)
    print(text)
    if disputed:
        print(f"{len(disputed)} disputed id(s) in {args.disputed_file}.")

    if args.dry_run:
        print("Dry run: nothing written.")
        return 0
    creator_directory.write_directory(directory, args.docs_dir)
    wrote = save_badge_dates(dates, args.dates_file)
    print(f"Wrote stats and badges for {report['creators']} creators under {args.docs_dir}/"
          f"{' and updated ' + args.dates_file if wrote else ''}.")
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as f:
            f.write("## Creator stats\n\n```\n" + text + "\n```\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
