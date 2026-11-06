#!/usr/bin/env python3
"""
process_claim.py — handle a `creator-claim` issue (SkinKit#57, design §3).

Run by `.github/workflows/claim-profile.yml` on a new issue from the
`claim-profile.yml` form, on a `/verify` comment from the issue author, and on
a `/approve` comment from a maintainer (a user named in CODEOWNERS). Every value
arrives through the environment, never through the command line or shell
interpolation:

    GITHUB_REPOSITORY   Provenance-Emu/skins
    EVENT_NAME          issues | issue_comment
    ISSUE_NUMBER, ISSUE_AUTHOR (issue.user.login), ISSUE_BODY, ISSUE_STATE
    ISSUE_LABELS        JSON array of label names
    COMMENT_BODY, COMMENT_AUTHOR   (issue_comment only)
    GH_TOKEN / GITHUB_TOKEN        used for the REST API and `gh`

What it does:

  1. Parses the form and resolves each name to the skins whose `author` is that
     exact string. A name that matches nothing, or an alias that another
     `creators/*.json` already holds, stops the claim with a comment.
  2. Verifies ownership, in this order (github_ownership.py does the GitHub calls):
       source  every matched skin has `source` = `owner/repo`, and the issue
               author is that owner (User) or a public member (Organization)
       file    the author commits `.emuskins-creator` (containing the issue
               number) to the default branch of each repo they don't own by
               login, then comments `/verify`
       manual  some matched skin comes from a host (deltastyles.com,
               delta-skins.github.io): the issue is labelled `needs-maintainer`
               and a maintainer comments `/approve` (optionally
               `/approve aliases: a, b` to change the alias list)
  3. Checks the profile against the schema (skin_schema.validate_creator) and the
     catalog-wide rules the build enforces. A bio with a URL or a mature keyword
     is not rejected: it goes to a maintainer like a manual claim.
  4. On success: mirrors avatar and banner to the `creators` release, writes
     `creators/<slug>.json`, commits to main, dispatches `build-catalog.yml`,
     comments the page URL, labels the issue `claimed` and closes it.

A maintainer's `/approve` counts only for the request the bot last showed them:
the review comment carries a hash of the parsed request, and an issue edited
after that comment gets a fresh review instead of an approval.

Refiling (a second issue from the account in an existing profile's `githubLogin`)
replaces the profile's text, links, socials and images. Names already in that
profile need no new proof; names it doesn't have yet are verified like a claim.
`slug`, `githubLogin` and `hidden` are never changed by a refile.

`--dry-run` still makes read-only calls (GitHub API, image downloads), then
prints what it would do without writing files, running git or gh, commenting,
labelling or closing.
"""

import argparse
import hashlib
import json
import os
import re
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import urlopen

sys.path.insert(0, str(Path(__file__).parent))
import blocklist
import creator_directory
import mirror_creator_images as mirror
from creator_policy import author_slug, review_reasons
from github_ownership import (
    GitHubAPI as _BaseAPI, Issue, check_account, check_file as _check_file,
    commit_and_push, default_run, lookup_repo, parse_sections,
)
from skin_schema import validate_creator
from validate_creator import load_maintainers

VERIFY_FILE = ".emuskins-creator"
LABEL_CLAIM = "creator-claim"
LABEL_CLAIMED = "claimed"
LABEL_MAINTAINER = "needs-maintainer"
BOT_LOGIN = "github-actions[bot]"
SITE = "https://emuskins.com"
MAX_NAMES = 20

# Form field labels, lowercased the way parse_sections() returns them.
F_NAMES = "your name on emuskins"
F_DISPLAY = "display name"
F_BIO = "bio"
F_AVATAR = "avatar url"
F_BANNER = "banner url"
F_LINKS = "links"
F_SOCIALS = "socials"
F_CONFIRM = "confirmation"
FORM_HEADING = "### Your name on EmuSkins"

# Anchored at the end of the comment: review_comment() always ends with it, so text a claimant
# got quoted earlier in the body can never be read as the marker.
_MARKER_RE = re.compile(r"<!-- emuskins-claim:([0-9a-f]{64}) -->\s*\Z")
_AUTHOR_URL_RE = re.compile(r"^https?://\S+?/authors/([a-z0-9-]+)\.html(?:[?#]\S*)?$", re.I)


class GitHubAPI(_BaseAPI):
    user_agent = "Provenance-SkinCatalog-claim/1.0 (+https://github.com/Provenance-Emu/skins)"

    def _open(self, req):
        return urlopen(req, timeout=20)  # resolved here, so tests can patch `process_claim.urlopen`


def check_file(api, v, issue_number: int):
    """`.emuskins-creator` on the default branch containing the issue number."""
    return _check_file(api, v, issue_number, VERIFY_FILE)


# ---------------------------------------------------------------------------
# Text helpers (everything the creator typed is untrusted)
# ---------------------------------------------------------------------------

def code(text) -> str:
    """`text` as an inline code span: no @mentions, links or markup fire inside one,
    and no HTML comment delimiters survive."""
    s = " ".join(str(text).split())
    if len(s) > 200:
        s = s[:197] + "..."
    # An HTML comment inside a code span is still in the comment's source: break up both
    # delimiters so quoted text can't forge (or close) the bot's hidden marker.
    s = re.sub(r"<!", "<\u200b!", s)
    s = re.sub(r"--+>", lambda m: m.group(0)[:-1] + "\u200b>", s)
    ticks = max((len(m) for m in re.findall(r"`+", s)), default=0)
    fence = "`" * (ticks + 1)
    return f"{fence} {s} {fence}" if s.startswith("`") or s.endswith("`") else f"{fence}{s}{fence}"


def bullets(items) -> str:
    return "\n".join(f"- {i}" for i in items)


def clean(text: str) -> str:
    """A form answer; GitHub renders an empty optional field as `_No response_`."""
    text = (text or "").strip()
    return "" if text == "_No response_" else text


# ---------------------------------------------------------------------------
# Form parsing
# ---------------------------------------------------------------------------

@dataclass
class Form:
    names: list = field(default_factory=list)       # raw lines: author strings or author-page URLs
    display_name: str = ""
    bio: str = ""
    avatar: str = ""
    banner: str = ""
    links: list = field(default_factory=list)       # [{label, url}]
    socials: dict = field(default_factory=dict)
    confirmed: bool = False
    errors: list = field(default_factory=list)


def parse_form(body: str) -> Form:
    s = parse_sections(body)
    form = Form()

    seen = set()
    for line in clean(s.get(F_NAMES, "")).splitlines():
        line = line.strip()
        if line and line not in seen:
            seen.add(line)
            form.names.append(line)
    if not form.names:
        form.errors.append("The form has no name. Fill in **Your name on EmuSkins**.")
    elif len(form.names) > MAX_NAMES:
        form.errors.append(f"{len(form.names)} names is more than the {MAX_NAMES} a claim can list.")

    form.display_name = " ".join(clean(s.get(F_DISPLAY, "")).split())
    form.bio = clean(s.get(F_BIO, "")).replace("\r", "")
    form.avatar = clean(s.get(F_AVATAR, ""))
    form.banner = clean(s.get(F_BANNER, ""))

    for line in clean(s.get(F_LINKS, "")).splitlines():
        line = line.strip()
        if not line:
            continue
        label, sep, url = line.partition("|")
        if not sep or not label.strip() or not url.strip():
            form.errors.append(f"Link line {code(line)} isn't `label | url`.")
        else:
            form.links.append({"label": label.strip(), "url": url.strip()})

    for line in clean(s.get(F_SOCIALS, "")).splitlines():
        line = line.strip()
        if not line:
            continue
        key, sep, handle = line.partition(":")
        key, handle = key.strip().lower(), handle.strip()
        if handle.startswith("@"):
            handle = handle[1:]
        if not sep or not key or not handle:
            form.errors.append(f"Social line {code(line)} isn't `key: handle`.")
        elif key in form.socials:
            form.errors.append(f"Social {code(key)} is listed twice.")
        else:
            form.socials[key] = handle  # unknown keys and bad handles are the schema's to report

    form.confirmed = bool(re.search(r"-\s*\[[xX]\]", s.get(F_CONFIRM, "")))
    if not form.confirmed:
        form.errors.append("Tick the box that says you made these skins or are the account that publishes them.")
    return form


# ---------------------------------------------------------------------------
# Catalog
# ---------------------------------------------------------------------------

def load_entries(skins_dir: str) -> list[dict]:
    """Every skins/**/*.json that credits an author (`author`, `source`, `id`, `creator`)."""
    entries = []
    for path in sorted(Path(skins_dir).rglob("*.json")):
        try:
            entry = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(entry, dict) and isinstance(entry.get("author"), str) and entry["author"].strip():
            entries.append({"author": entry["author"], "source": entry.get("source") or "",
                            "id": entry.get("id", ""), "creator": entry.get("creator"),
                            "_source_file": str(path)})
    return entries


def resolve_names(raw_names, entries, creators) -> tuple[list[str], list[str]]:
    """Form names -> (exact catalog `author` strings, problems). A line may be an
    author-page URL (`emuskins.com/authors/<slug>.html`) or the author string."""
    authors = sorted({e["author"] for e in entries})
    by_slug: dict[str, list[str]] = {}
    for a in authors:
        by_slug.setdefault(author_slug(a), []).append(a)
    claimed_by_slug = {c["slug"]: c for c in creators if isinstance(c, dict) and "slug" in c}

    resolved, problems = [], []

    def add(name):
        if name not in resolved:
            resolved.append(name)

    for raw in raw_names:
        m = _AUTHOR_URL_RE.match(raw)
        if m:
            slug = m.group(1).lower()
            if slug in claimed_by_slug:
                for a in claimed_by_slug[slug].get("aliases") or []:
                    add(a)
            elif slug in by_slug and len(by_slug[slug]) == 1:
                add(by_slug[slug][0])
            elif slug in by_slug:
                problems.append(f"{code(raw)} covers several author spellings "
                                f"({', '.join(code(a) for a in by_slug[slug])}). List the exact names instead.")
            else:
                problems.append(f"No author page {code(slug)} in the catalog.")
        elif raw in authors:
            add(raw)
        else:
            near = [a for a in authors if a.strip().lower() == raw.lower()]
            hint = f" Did you mean {code(near[0])}? Names must match the catalog exactly." if near else \
                   " Names must match the author shown on emuskins.com exactly."
            problems.append(f"No skin in the catalog is credited to {code(raw)}.{hint}")
    return resolved, problems


def slug_problems(entries, creators, new_creator) -> list[str]:
    """Errors the catalog build would report once `new_creator` exists, that it
    doesn't report today (so an old, unrelated problem never blocks a claim)."""
    def errors(cs):
        found = creator_directory.validate_creators(cs)
        more, _ = creator_directory.check_resolution(entries, cs)
        return set(found) | set(more)

    slug = new_creator["slug"]
    others = [c for c in creators if c.get("slug") != slug]
    return sorted(errors(others + [new_creator]) - errors(others))


# ---------------------------------------------------------------------------
# Ownership
# ---------------------------------------------------------------------------

@dataclass
class Check:
    status: str                    # verified | needs_file | manual
    method: str | None = None      # source | file | manual (None: nothing needed proving)
    notes: list = field(default_factory=list)
    pending: list = field(default_factory=list)   # Verification objects still waiting for the file


def verify_ownership(api, entries: list[dict], author: str, issue_number: int, check_files: bool) -> Check:
    """Design §3 step 2. `entries` are the skins whose names still need proving."""
    if not entries:
        return Check("verified")
    notes, pending, manual = [], [], False
    by_source: dict[str, int] = {}
    for e in entries:
        by_source[e["source"]] = by_source.get(e["source"], 0) + 1

    used_file = False
    for source in sorted(by_source):
        n = by_source[source]
        m = blocklist.OWNER_REPO_RE.match(source)
        if not m:
            manual = True
            notes.append(f"{n} skin(s) come from {code(source or 'an unknown source')}, which can't be checked automatically.")
            continue
        v = lookup_repo(api, m.group(1), m.group(2))
        if v.status == "error":
            raise RuntimeError(v.reason)
        if v.status != "unverified":
            manual = True
            notes.append(f"{n} skin(s) from {code(source)}: {v.reason}")
            continue
        check_account(api, v, author)
        if v.status != "verified" and check_files:
            check_file(api, v, issue_number)
        if v.status == "verified":
            used_file = used_file or v.method == "file"
            how = {"owner": "owned by the issue author", "org-member": "issue author is a public org member",
                   "file": f"`{VERIFY_FILE}` found"}[v.method]
            notes.append(f"{code(v.full_name)}: verified ({how}).")
        else:
            pending.append(v)
            notes.append(f"{code(v.full_name)}: owned by {code(v.owner_login)} ({v.owner_type.lower() or 'unknown'}), "
                         "not verified yet." + "".join(f" {x}" for x in v.notes))

    if manual:
        return Check("manual", "manual", notes)
    if pending:
        return Check("needs_file", None, notes, pending)
    return Check("verified", "file" if used_file else "source", notes)


# ---------------------------------------------------------------------------
# Profile
# ---------------------------------------------------------------------------

def build_profile(form: Form, aliases: list[str], slug: str, login: str, claim: dict, hidden: bool) -> dict:
    return {
        "slug": slug,
        "displayName": form.display_name or aliases[0],
        "aliases": aliases,
        "githubLogin": login,
        "bio": form.bio or None,
        "avatarURL": form.avatar or f"https://github.com/{login}.png",
        "bannerURL": form.banner or None,
        "links": form.links,
        "socials": form.socials,
        "claim": claim,
        "hidden": hidden,
    }


def request_hash(author: str, aliases: list[str], form: Form) -> str:
    """Identifies what a maintainer reviewed. Anything a creator can edit that
    ends up in the profile or the alias list is in it."""
    payload = {"author": author.lower(), "aliases": sorted(aliases), "display": form.display_name,
               "bio": form.bio, "avatar": form.avatar, "banner": form.banner,
               "links": form.links, "socials": dict(sorted(form.socials.items()))}
    return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def write_profile(profile: dict, creators_dir: str) -> str:
    os.makedirs(creators_dir, exist_ok=True)
    path = os.path.join(creators_dir, f"{profile['slug']}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(profile, f, indent=2, ensure_ascii=False)
        f.write("\n")
    return path


# ---------------------------------------------------------------------------
# Comments
# ---------------------------------------------------------------------------

RETRY = "Edit the issue to fix this, then comment `/verify` and I'll run again."


def problems_comment(problems: list[str]) -> str:
    return "I couldn't process this claim:\n\n" + bullets(problems) + "\n\n" + RETRY


def instructions_comment(check: Check, issue_number: int, review: list[str]) -> str:
    lines = ["I couldn't confirm yet that you control every repo these skins come from.", "", *[f"- {n}" for n in check.notes], ""]
    lines += ["To prove control of a repo above that isn't verified:"]
    for v in check.pending:
        lines.append(f"1. Commit a file named `{VERIFY_FILE}` containing `{issue_number}` to the root of "
                     f"`{v.default_branch}` in `{v.full_name}`.")
    lines += ["", "Then comment `/verify` here. Only the issue author's `/verify` counts, and I re-read each file from the default branch."]
    if review:
        lines += ["", "A maintainer will also review this profile once that's done: " + "; ".join(review) + "."]
    return "\n".join(lines)


def review_comment(ctx, form: Form, aliases: list[str], entries: list[dict], check: Check,
                   review: list[str], maintainers: set[str], digest: str, changed: bool) -> str:
    counts = {a: sum(1 for e in entries if e["author"] == a) for a in aliases}
    lines = []
    if changed:
        lines += ["The request changed since a maintainer last saw it (or nothing had been reviewed yet), "
                  "so this `/approve` didn't count. Here is the current request.", ""]
    lines += [
        f"@{ctx.issue_author} asked to claim a profile for: " + ", ".join(f"{code(a)} ({counts[a]} skins)" for a in aliases) + ".",
        "",
        "Why a maintainer needs to look:",
        *[f"- {r}" for r in review],
        "",
        "What I checked:",
        *[f"- {n}" for n in check.notes],
        "",
        f"Display name {code(form.display_name or aliases[0])}; bio {code(form.bio) if form.bio else 'none'}; "
        f"{len(form.links)} link(s); socials: {', '.join(sorted(form.socials)) or 'none'}.",
        f"Image sources (copied and resized on approval, never linked): avatar "
        f"{code(form.avatar) if form.avatar else 'the GitHub avatar'}, banner {code(form.banner) if form.banner else 'none'}.",
        "",
        "Match the claimant to the creator the way the removal form asks (a profile that links back to this issue, a Discord handle, "
        "a message on the DeltaStyles page). Then comment `/approve`, or `/approve aliases: name one, name two` to change which names "
        "the profile gets. An edit to the issue after this comment needs a new review.",
    ]
    if maintainers:
        lines += ["", "Maintainers: " + " ".join(f"@{m}" for m in sorted(maintainers))]
    lines += ["", f"<!-- emuskins-claim:{digest} -->"]
    return "\n".join(lines)


def success_comment(profile: dict, method: str, updated: bool, failures: list[str], notes=()) -> str:
    slug = profile["slug"]
    lines = [
        ("Updated" if updated else "Claimed") + f" ({method}). Your profile is `creators/{slug}.json` and your page will be "
        f"{SITE}/authors/{slug}.html when the site rebuilds, a few minutes from now.",
        "",
        "- Names on the profile: " + ", ".join(code(a) for a in profile["aliases"]),
        "- To change it later, open a PR that edits `creators/" + slug + ".json` from the " + code(profile["githubLogin"]) +
        " account, or file the claim form again with the same names.",
        "- To remove it, delete that file in a PR. The page goes back to the unclaimed layout.",
    ]
    if notes:
        lines += ["", "Left out of the profile:", *[f"- {n}" for n in notes],
                  "File the claim form again with a working image URL to add it."]
    if failures:
        lines += ["", "These steps failed and need a maintainer:", *[f"- `{f}`" for f in failures]]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------

@dataclass
class Context:
    repo: str                  # Provenance-Emu/skins
    event: str
    issue_number: int
    issue_author: str
    issue_body: str
    issue_state: str = "open"
    labels: list = field(default_factory=list)
    comment_body: str = ""
    comment_author: str = ""

    @classmethod
    def from_env(cls, env=None):
        env = os.environ if env is None else env
        try:
            labels = json.loads(env.get("ISSUE_LABELS") or "[]")
        except json.JSONDecodeError:
            labels = []
        return cls(
            repo=env.get("GITHUB_REPOSITORY", "Provenance-Emu/skins"),
            event=env.get("EVENT_NAME", "issues"),
            issue_number=int(env.get("ISSUE_NUMBER", "0")),
            issue_author=env.get("ISSUE_AUTHOR", ""),
            issue_body=env.get("ISSUE_BODY", ""),
            issue_state=env.get("ISSUE_STATE", "open"),
            labels=labels,
            comment_body=env.get("COMMENT_BODY", ""),
            comment_author=env.get("COMMENT_AUTHOR", ""),
        )


def should_handle(ctx: Context, maintainers: set[str]) -> tuple[str | None, str]:
    """(mode, why not). mode is `open`, `verify` or `approve`. The workflow `if:`
    does the same filtering; this is the second check."""
    if ctx.issue_state.lower() == "closed" or LABEL_CLAIMED in ctx.labels:
        return None, "issue already handled"
    if ctx.event == "issues":
        return "open", ""
    if ctx.event != "issue_comment":
        return None, f"unsupported event {ctx.event}"
    words = ctx.comment_body.strip().lower().split(None, 1)
    command = words[0] if words else ""
    if command == "/verify":
        if ctx.comment_author.lower() != ctx.issue_author.lower() or not ctx.comment_author:
            return None, "/verify is not from the issue author"
        return "verify", ""
    if command == "/approve":
        if ctx.comment_author.lower() not in maintainers:
            return None, "/approve is not from a maintainer"
        return "approve", ""
    return None, "comment is not /verify or /approve"


def parse_alias_override(comment: str) -> list[str] | None:
    """`/approve aliases: a, b` (commas, or one name per line) -> ["a", "b"]."""
    m = re.search(r"(?is)\baliases\s*:\s*(.+)$", comment)
    if not m:
        return None
    text = m.group(1).strip()
    parts = text.splitlines() if "\n" in text else text.split(",")
    return [p.strip() for p in parts if p.strip()]


def last_reviewed_hash(issue: Issue) -> str | None:
    """The hash in the bot's most recent review request on this issue."""
    found = None
    for c in issue.comments():
        if (c.get("user") or {}).get("login") == BOT_LOGIN:
            m = _MARKER_RE.search(c.get("body") or "")
            if m:
                found = m.group(1)
    return found


def run_claim(ctx: Context, api, run=default_run, dry_run: bool = False, *,
              skins_dir: str = "skins", creators_dir: str = "creators",
              maintainers: set[str] | None = None, today: str | None = None,
              prepare_image=mirror.prepare) -> dict:
    """Returns a summary dict; `outcome` says what happened."""
    maintainers = load_maintainers() if maintainers is None else maintainers
    mode, why = should_handle(ctx, maintainers)
    if mode is None:
        print(f"Ignoring: {why}")
        return {"outcome": "ignored", "reason": why}

    issue = Issue(api, ctx, dry_run)
    form = parse_form(ctx.issue_body)
    if form.errors:
        issue.comment(problems_comment(form.errors))
        return {"outcome": "invalid", "errors": form.errors}

    entries = load_entries(skins_dir)
    creators, load_errors = creator_directory.load_creators(creators_dir)
    if load_errors:
        raise RuntimeError("; ".join(load_errors))
    creators = [c for c in creators if isinstance(c, dict)]
    alias_owner = creator_directory.alias_map(creators)
    by_slug = {c.get("slug"): c for c in creators}
    login = ctx.issue_author

    # --- names -> aliases ---------------------------------------------------
    base_aliases, problems = resolve_names(form.names, entries, creators)
    if problems:
        issue.comment(problems_comment(problems))
        return {"outcome": "not_found", "errors": problems}
    digest = request_hash(login, base_aliases, form)

    aliases = base_aliases
    if mode == "approve":
        override = parse_alias_override(ctx.comment_body)
        if override is not None:
            aliases, problems = resolve_names(override, entries, creators)
            if problems or not aliases:
                issue.comment("I couldn't use that alias list:\n\n" + bullets(problems or ["It is empty."]) +
                              "\n\nComment `/approve` again with names that match the catalog exactly.")
                return {"outcome": "not_found", "errors": problems}

    # --- who already holds them --------------------------------------------
    own = None
    for a in aliases:
        slug_held = alias_owner.get(a)
        if slug_held is None:
            continue
        holder = by_slug[slug_held]
        if (holder.get("githubLogin") or "").lower() != login.lower():
            issue.comment(f"{code(a)} already belongs to the profile `{slug_held}`, which another account claimed. "
                          "If that's a mistake, say so here and a maintainer will look.")
            issue.label(LABEL_MAINTAINER, "d93f0b")
            return {"outcome": "conflict", "alias": a}
        if own is not None and own is not holder:
            issue.comment("These names belong to two different profiles of yours. Claim them one profile at a time.")
            return {"outcome": "conflict", "alias": a}
        own = holder
    updated = own is not None

    # --- ownership ----------------------------------------------------------
    proven = set(own.get("aliases") or []) if updated else set()
    to_prove = [e for e in entries if e["author"] in aliases and e["author"] not in proven]
    check = verify_ownership(api, to_prove, login, ctx.issue_number, check_files=ctx.event == "issue_comment")

    # --- profile ------------------------------------------------------------
    today = today or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    if updated:
        slug, hidden, github_login = own["slug"], bool(own.get("hidden")), own["githubLogin"]
        previous = own.get("claim") or {}
    else:
        slug = author_slug(form.display_name) or author_slug(aliases[0])
        hidden, github_login, previous = False, login, {}
    method = check.method or previous.get("method") or "manual"
    claim = {"issue": ctx.issue_number, "method": method, "verifiedAt": today}
    profile = build_profile(form, aliases, slug, github_login, claim, hidden)

    errors = validate_creator(profile, filename_slug=slug)
    if errors:
        issue.comment(problems_comment(errors))
        return {"outcome": "invalid", "errors": errors}
    if not updated and slug.lower() in {str(c.get("slug", "")).lower() for c in creators}:
        # Writing it would replace another creator's file (and, with --clobber, their mirrored images).
        issue.comment(f"A profile with the page name {code(slug)} already exists and isn't yours. "
                      "Pick a different display name, or say so here if you think it's a mistake and a maintainer will look.")
        issue.label(LABEL_MAINTAINER, "d93f0b")
        return {"outcome": "conflict", "errors": [f"slug {slug} exists"]}
    new_creator = {**profile, "_source_file": os.path.join(creators_dir, f"{slug}.json")}
    clashes = slug_problems(entries, creators, new_creator)
    if clashes:
        issue.comment("This profile would collide with another in the catalog, and I can't resolve that myself:\n\n" +
                      bullets(code(c) for c in clashes) + "\n\nA maintainer will look.")
        issue.label(LABEL_MAINTAINER, "d93f0b")
        return {"outcome": "conflict", "errors": clashes}

    # --- who still has to say yes ------------------------------------------
    review = []
    if check.status == "manual":
        review.append("ownership can't be checked automatically")
    review += review_reasons(profile)
    waiting = check.status == "needs_file" or bool(review)

    approved = False
    if mode == "approve" and waiting:
        if last_reviewed_hash(issue) == digest:
            approved = True
        else:
            issue.comment(review_comment(ctx, form, aliases, entries, check, review or ["the proof of ownership is incomplete"],
                                         maintainers, digest, changed=True))
            issue.label(LABEL_MAINTAINER, "d93f0b")
            return {"outcome": "needs_maintainer"}
    if approved and check.status != "verified":
        method = claim["method"] = "manual"

    if not approved:
        if check.status == "needs_file":
            issue.comment(instructions_comment(check, ctx.issue_number, review))
            return {"outcome": "unverified"}
        if review:
            issue.comment(review_comment(ctx, form, aliases, entries, check, review, maintainers, digest, changed=False))
            issue.label(LABEL_MAINTAINER, "d93f0b")
            return {"outcome": "needs_maintainer", "reasons": review}

    # --- done: images, file, commit, build ----------------------------------
    # The published profile points at the mirrored copies and never at the creator's URL
    # (design §1). An image that can't be mirrored is left out, not hotlinked.
    images, notes = {}, []
    for kind, field_name in (("avatar", "avatarURL"), ("banner", "bannerURL")):
        url = profile[field_name]
        profile[field_name] = None
        if not url:
            continue
        try:
            images[kind] = prepare_image(url, kind)
        except mirror.ImageError as e:
            notes.append(f"{kind}: {e}")
            continue
        profile[field_name] = mirror.mirror_url(slug, kind, ctx.repo)
    errors = validate_creator(profile, filename_slug=slug)
    if errors:  # can't happen unless mirror_url() stops being https; never publish it
        raise RuntimeError("; ".join(errors))

    summary = {"outcome": "claimed", "slug": slug, "method": method, "updated": updated, "aliases": aliases}
    path = os.path.join(creators_dir, f"{slug}.json")

    if dry_run:
        print(f"[dry-run] would write {path}:\n{json.dumps(profile, indent=2, ensure_ascii=False)}")
        mirror.upload(run, ctx.repo, slug, images, dry_run=True)
        print(f"  [dry-run] git commit {path}; push to main")
        print(f"  [dry-run] gh workflow run build-catalog.yml --ref main --repo {ctx.repo}")
        issue.comment(success_comment(profile, method, updated, [], notes))
        issue.label(LABEL_CLAIMED)
        issue.close()
        return summary

    # Images first: a profile file on main must never point at a mirror that doesn't exist.
    mirror.upload(run, ctx.repo, slug, images)
    write_profile(profile, creators_dir)
    commit_and_push(run, f"chore(creators): {'update' if updated else 'claim'} {slug} (#{ctx.issue_number})", [path])
    failures = []
    r = run(["gh", "workflow", "run", "build-catalog.yml", "--ref", "main", "--repo", ctx.repo])
    if r.returncode != 0:
        failures.append("build-catalog.yml dispatch")
    summary["failures"] = failures

    issue.comment(success_comment(profile, method, updated, failures, notes))
    if failures:
        summary["outcome"] = "partial"
        return summary  # leave open for a maintainer
    issue.label(LABEL_CLAIMED)
    issue.unlabel(LABEL_MAINTAINER)
    issue.close()
    return summary


def main():
    parser = argparse.ArgumentParser(description="Handle a creator-claim issue (values come from env)")
    parser.add_argument("--dry-run", action="store_true",
                        help="read-only API calls and image downloads only; print the plan, change nothing")
    parser.add_argument("--skins-dir", default="skins")
    parser.add_argument("--creators-dir", default="creators")
    args = parser.parse_args()

    token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN", "")
    ctx = Context.from_env()
    summary = run_claim(ctx, GitHubAPI(token), dry_run=args.dry_run,
                        skins_dir=args.skins_dir, creators_dir=args.creators_dir)
    print(json.dumps({k: v for k, v in summary.items() if k not in ("errors", "aliases")}))
    sys.exit(1 if summary["outcome"] == "partial" else 0)


if __name__ == "__main__":
    main()
