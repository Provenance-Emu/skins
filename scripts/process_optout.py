#!/usr/bin/env python3
"""
process_optout.py — handle a `repo-optout` issue (SkinKit#34).

Run by `.github/workflows/optout.yml` on a new issue from the `remove-repo.yml`
form, and on a `/verify` comment from the issue author. Every value arrives
through the environment, never through the command line or shell
interpolation:

    GITHUB_REPOSITORY   Provenance-Emu/skins
    EVENT_NAME          issues | issue_comment
    ISSUE_NUMBER, ISSUE_AUTHOR (issue.user.login), ISSUE_BODY, ISSUE_STATE
    ISSUE_LABELS        JSON array of label names
    COMMENT_BODY, COMMENT_AUTHOR   (issue_comment only)
    GH_TOKEN / GITHUB_TOKEN        used for the REST API and `gh`

Ownership check (the repo's owner is read from the API, not from the URL):
  - owner is a User and its login equals the issue author  -> method `owner`
  - owner is an Organization and the author is a public member
    (`GET /orgs/{org}/public_members/{login}` -> 204)       -> method `org-member`
  - otherwise the author commits `.emuskins-optout` (containing the issue
    number) to the default branch root and comments `/verify`. Only the issue
    author's `/verify` counts. -> method `file`. This proves one repo, so it
    never grants `owner/*`, even with the box ticked.

A verified request appends to `blocklist.json`, deletes every matching
`skins/**/*.json` and its thumbnails, commits and pushes to main, deletes the
matching release assets, dispatches `build-catalog.yml`, comments, labels the
issue `removed` and closes it.

`--dry-run` still makes read-only API calls for the ownership check, then
prints what it would do without writing files, running git or gh, commenting,
labelling or closing.
"""

import argparse
import base64
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote, unquote, urlsplit
from urllib.request import Request, urlopen
from urllib.error import HTTPError

sys.path.insert(0, str(Path(__file__).parent))
import blocklist

VERIFY_FILE = ".emuskins-optout"
FORM_URL_LABEL = "repo url to remove"
FORM_HEADING = "### Repo URL to remove"
LABEL_REMOVED = "removed"
LABEL_OPTOUT = "repo-optout"

_URL_RE = re.compile(
    rf"^(?:https?://(?:www\.)?github\.com/)?({blocklist._OWNER})/({blocklist._REPO})/?$"
)


# ---------------------------------------------------------------------------
# GitHub REST + gh
# ---------------------------------------------------------------------------

class GitHubAPI:
    """Minimal REST client. `request` returns (status, json-or-None) and does
    not raise on 4xx, because 204/404 are answers here (public_members)."""

    def __init__(self, token: str, base: str = "https://api.github.com"):
        self.token = token
        self.base = base

    def request(self, method: str, path: str, body=None):
        data = json.dumps(body).encode() if body is not None else None
        req = Request(f"{self.base}/{path.lstrip('/')}", data=data, method=method, headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {self.token}",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "Provenance-SkinCatalog-optout/1.0 (+https://github.com/Provenance-Emu/skins)",
            **({"Content-Type": "application/json"} if data else {}),
        })
        try:
            with urlopen(req, timeout=20) as r:
                raw = r.read()
                return r.status, (json.loads(raw) if raw else None)
        except HTTPError as e:
            raw = e.read()
            try:
                return e.code, (json.loads(raw) if raw else None)
            except json.JSONDecodeError:
                return e.code, None


def default_run(cmd: list[str]):
    return subprocess.run(cmd, capture_output=True, text=True)


# ---------------------------------------------------------------------------
# Form parsing
# ---------------------------------------------------------------------------

def parse_sections(body: str) -> dict[str, str]:
    """Issue-form body -> {lowercased heading: text}. Forms render `### Label`
    followed by the answer."""
    sections: dict[str, str] = {}
    current = None
    for line in (body or "").replace("\r\n", "\n").split("\n"):
        m = re.match(r"^###\s+(.*?)\s*$", line)
        if m:
            current = m.group(1).strip().lower()
            sections[current] = ""
        elif current is not None:
            sections[current] += line + "\n"
    return {k: v.strip() for k, v in sections.items()}


def parse_repo_url(text: str) -> tuple[str, str] | None:
    """Strict `owner/repo` from a GitHub repo URL (or bare owner/repo)."""
    text = (text or "").strip()
    first = text.splitlines()[0].strip() if text else ""
    if first.lower().endswith(".git"):
        first = first[:-4]
    m = _URL_RE.match(first)
    if not m or m.group(2) in (".", ".."):
        return None
    return m.group(1), m.group(2)


def parse_form(body: str) -> dict:
    sections = parse_sections(body)
    repo = parse_repo_url(sections.get(FORM_URL_LABEL, ""))
    all_repos = any(
        re.search(r"-\s*\[[xX]\]\s*block every repo", v, re.I) for v in sections.values()
    )
    return {"repo": repo, "all_repos": all_repos}


# ---------------------------------------------------------------------------
# Ownership
# ---------------------------------------------------------------------------

@dataclass
class Verification:
    status: str               # verified | unverified | not_found | moved | refused | error
    method: str | None = None  # owner | org-member | file
    full_name: str = ""
    owner_login: str = ""
    owner_type: str = ""
    default_branch: str = "main"
    reason: str = ""
    can_block_all: bool = False
    notes: list = field(default_factory=list)


def lookup_repo(api, owner: str, repo: str) -> Verification:
    status, data = api.request("GET", f"/repos/{owner}/{repo}")
    if status == 404:
        return Verification("not_found", reason=f"`{owner}/{repo}` doesn't exist or isn't public.")
    if status != 200 or not isinstance(data, dict):
        return Verification("error", reason=f"GitHub returned HTTP {status} for `{owner}/{repo}`.")
    full = data.get("full_name", "")
    v = Verification(
        "unverified",
        full_name=full,
        owner_login=(data.get("owner") or {}).get("login", ""),
        owner_type=(data.get("owner") or {}).get("type", ""),
        default_branch=data.get("default_branch") or "main",
    )
    if full.lower() != f"{owner}/{repo}".lower():
        v.status = "moved"
        v.reason = (f"`{owner}/{repo}` now lives at `{full}`. Open a new request with the "
                    f"current URL, and use the removal-request form for skins listed under the old name.")
    elif full.lower() == blocklist.SELF_REPO or v.owner_login.lower() == blocklist.SELF_REPO.split("/")[0]:
        v.status = "refused"
        v.reason = ("This is EmuSkins' own account. Ask a maintainer in the issue tracker "
                    "or Discord instead.")
    return v


def check_account(api, v: Verification, requester: str) -> Verification:
    """owner / org-member verification. Mutates and returns `v`."""
    if v.status != "unverified":
        return v
    if v.owner_type == "User" and v.owner_login.lower() == requester.lower():
        v.status, v.method, v.can_block_all = "verified", "owner", True
    elif v.owner_type == "Organization":
        status, _ = api.request("GET", f"/orgs/{v.owner_login}/public_members/{requester}")
        if status == 204:
            v.status, v.method, v.can_block_all = "verified", "org-member", True
    return v


def check_file(api, v: Verification, issue_number: int) -> Verification:
    """`.emuskins-optout` on the default branch containing the issue number."""
    if v.status != "unverified":
        return v
    status, data = api.request(
        "GET", f"/repos/{v.full_name}/contents/{VERIFY_FILE}?ref={quote(v.default_branch, safe='')}")
    if status != 200 or not isinstance(data, dict) or data.get("encoding") != "base64":
        v.notes.append(f"`{VERIFY_FILE}` not found on `{v.default_branch}`.")
        return v
    try:
        text = base64.b64decode(data.get("content", "")).decode("utf-8", errors="replace")
    except Exception:
        v.notes.append(f"`{VERIFY_FILE}` could not be read.")
        return v
    if re.search(rf"(?<!\d){issue_number}(?!\d)", text):
        v.status, v.method, v.can_block_all = "verified", "file", False
    else:
        v.notes.append(f"`{VERIFY_FILE}` exists but doesn't contain the issue number {issue_number}.")
    return v


# ---------------------------------------------------------------------------
# Comment text
# ---------------------------------------------------------------------------

def instructions_comment(v: Verification, issue_number: int, all_repos: bool) -> str:
    lines = [
        f"I couldn't confirm that you control `{v.full_name}`. "
        f"The owner is `{v.owner_login}` ({v.owner_type.lower() or 'unknown'}), "
        f"and an owner is verified when it is the account that opened this issue, "
        f"or an org the issue author is a public member of.",
        "",
        "To prove control of this repo:",
        f"1. Commit a file named `{VERIFY_FILE}` to the root of `{v.default_branch}` in `{v.full_name}`. "
        f"It only needs to contain `{issue_number}`.",
        "2. Comment `/verify` here. Only the issue author's `/verify` counts.",
        "",
        "I'll re-read the file from the default branch, then remove the skins and block the repo.",
    ]
    if all_repos:
        lines += ["", "The file proves one repo. Blocking every repo under an account needs the account "
                      "itself (or a public org member), so a file-verified request blocks only "
                      f"`{v.full_name}`."]
    if v.notes:
        lines += ["", *v.notes]
    return "\n".join(lines)


def success_comment(match: str, removed: int, assets: int, v: Verification, failures: list[str]) -> str:
    lines = [
        f"Verified (`{v.method}`). `{match}` is now blocked: the crawler, the submission bot and the "
        f"catalog build skip it.",
        "",
        f"- Skins removed: {removed}",
        f"- Release assets deleted: {assets}" + (f" ({len(failures)} failed)" if failures else ""),
        "",
        "The catalog and site rebuild now; emuskins.com and `catalog.json` update when that run finishes. "
        "To undo, a maintainer deletes the line from `blocklist.json`. Git history isn't rewritten, "
        "so old commits still list the skins.",
    ]
    if failures:
        lines += ["", "These assets couldn't be deleted and need a maintainer:", *[f"- `{f}`" for f in failures]]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Cleanup
# ---------------------------------------------------------------------------

def find_victims(skins_dir: str, rules: list[dict]) -> list[tuple[Path, dict]]:
    """Every skins/**/*.json that `is_blocked` matches against `rules`."""
    out = []
    for path in sorted(Path(skins_dir).rglob("*.json")):
        try:
            entry = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(entry, dict) and blocklist.is_blocked(entry, rules):
            out.append((path, entry))
    return out


_MIRROR_RE = re.compile(
    rf"^https://github\.com/{re.escape(blocklist.SELF_REPO)}/releases/download/mirror/([^/?#]+)$", re.I)
SKIN_ID_RE = re.compile(r"[0-9a-f]{16}")


def valid_skin_id(sid) -> bool:
    """Catalog ids are 16 lowercase hex chars (skin_schema.make_id). Anything else
    in a skin file's `id` is never turned into a file or release-asset name."""
    return isinstance(sid, str) and SKIN_ID_RE.fullmatch(sid) is not None


def release_assets(entry: dict, keep_ids=frozenset()) -> list[tuple[str, str]]:
    """(tag, asset name) pairs to delete for one removed skin.

    Names are built only from an `id` that is 16 hex chars, and the mirror asset
    must be that id's own `{id}.deltaskin|manicskin`: a skin file can't point the
    cleanup at another skin's asset. Ids that a skin staying in the catalog also
    carries (`keep_ids`) are skipped, so a duplicate id can't take its thumbnails."""
    sid = entry.get("id", "")
    if not valid_skin_id(sid) or sid in keep_ids:
        return []
    assets = [("thumbnails", f"{sid}.png"), ("thumbnails", f"{sid}-landscape.png")]
    m = _MIRROR_RE.match(entry.get("downloadURL", "") or "")
    if m and unquote(m.group(1)) in (f"{sid}.deltaskin", f"{sid}.manicskin"):
        assets.append(("mirror", unquote(m.group(1))))
    return assets


def surviving_ids(skins_dir: str, victims) -> set[str]:
    """Ids carried by skin files that are not being removed."""
    gone = {path for path, _ in victims}
    ids = set()
    for path in Path(skins_dir).rglob("*.json"):
        if path in gone:
            continue
        try:
            entry = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(entry, dict) and isinstance(entry.get("id"), str):
            ids.add(entry["id"])
    return ids


def delete_files(victims, thumbnails_dir: str, keep_ids=frozenset()) -> list[Path]:
    removed = []
    for path, entry in victims:
        path.unlink()
        removed.append(path)
        sid = entry.get("id", "")
        if not valid_skin_id(sid) or sid in keep_ids:
            if sid and not valid_skin_id(sid):
                print(f"  ! {path}: id {sid!r} is not 16 hex chars, thumbnails left alone", file=sys.stderr)
            continue
        for name in (f"{sid}.png", f"{sid}-landscape.png"):
            t = Path(thumbnails_dir) / name
            if t.exists():
                t.unlink()
                removed.append(t)
    return removed


def commit_and_push(run, message: str, paths: list[str], attempts: int = 3) -> bool:
    """Commit `paths` and push to main. True once the commit is on origin/main,
    False when there was nothing to commit. Raises if staging, committing or
    pushing fails: the caller deletes release assets only after this returns,
    so a skin file can never stay in the catalog with its assets gone."""
    r = run(["git", "add", "-A", "--", *paths])
    if r.returncode != 0:
        raise RuntimeError(f"git add failed: {r.stderr}")
    if run(["git", "diff", "--cached", "--quiet"]).returncode == 0:
        return False  # nothing staged
    r = run(["git", "commit", "-m", message])
    if r.returncode != 0:
        raise RuntimeError(f"git commit failed: {r.stderr}")
    for _ in range(attempts):
        if run(["git", "pull", "--rebase", "origin", "main"]).returncode != 0:
            # A conflict leaves the rebase half done; HEAD is then origin/main
            # without our commit, and pushing it would "succeed" as a no-op.
            run(["git", "rebase", "--abort"])
            continue
        if run(["git", "push", "origin", "HEAD:main"]).returncode == 0:
            return True
    raise RuntimeError("git push failed after retries")


def delete_release_assets(run, repo: str, victims, dry_run: bool,
                          keep_ids=frozenset()) -> tuple[int, list[str]]:
    """Returns (deleted, failures). A missing asset is not a failure."""
    deleted, failures = 0, []
    seen = set()
    for _, entry in victims:
        for tag, name in release_assets(entry, keep_ids):
            if (tag, name) in seen:
                continue
            seen.add((tag, name))
            cmd = ["gh", "release", "delete-asset", tag, name, "--yes", "--repo", repo]
            if dry_run:
                print("  [dry-run] " + " ".join(cmd))
                continue
            r = run(cmd)
            if r.returncode == 0:
                deleted += 1
            elif "not found" in (r.stderr or "").lower() or "no asset" in (r.stderr or "").lower():
                print(f"  (no such asset {tag}/{name}, skipping)")
            else:
                failures.append(f"{tag}/{name}")
                print(f"  ! could not delete {tag}/{name}: {(r.stderr or '').strip()}", file=sys.stderr)
    return deleted, failures


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


class Issue:
    """Comment / label / close on the triggering issue; prints instead in dry-run."""

    def __init__(self, api, ctx: Context, dry_run: bool):
        self.api, self.ctx, self.dry_run = api, ctx, dry_run

    def comment(self, body: str):
        if self.dry_run:
            print(f"[dry-run] comment on #{self.ctx.issue_number}:\n{body}\n")
            return
        self.api.request("POST", f"/repos/{self.ctx.repo}/issues/{self.ctx.issue_number}/comments",
                         {"body": body})

    def label(self, name: str, color: str = "0e8a16"):
        if self.dry_run:
            print(f"[dry-run] add label {name!r}")
            return
        status, _ = self.api.request("GET", f"/repos/{self.ctx.repo}/labels/{quote(name)}")
        if status == 404:
            self.api.request("POST", f"/repos/{self.ctx.repo}/labels", {"name": name, "color": color})
        self.api.request("POST", f"/repos/{self.ctx.repo}/issues/{self.ctx.issue_number}/labels",
                         {"labels": [name]})

    def close(self):
        if self.dry_run:
            print(f"[dry-run] close #{self.ctx.issue_number}")
            return
        self.api.request("PATCH", f"/repos/{self.ctx.repo}/issues/{self.ctx.issue_number}",
                         {"state": "closed", "state_reason": "completed"})


def should_handle(ctx: Context) -> tuple[bool, str]:
    """Event gating. The workflow `if:` does the same; this is the second check."""
    if ctx.issue_state.lower() == "closed" or LABEL_REMOVED in ctx.labels:
        return False, "issue already handled"
    if ctx.event == "issue_comment":
        if not ctx.comment_author or ctx.comment_author.lower() != ctx.issue_author.lower():
            return False, "comment is not from the issue author"
        if not ctx.comment_body.strip().lower().startswith("/verify"):
            return False, "comment is not /verify"
    elif ctx.event != "issues":
        return False, f"unsupported event {ctx.event}"
    return True, ""


def run_optout(ctx: Context, api, run=default_run, dry_run: bool = False,
               blocklist_path=None, skins_dir: str = "skins",
               thumbnails_dir: str = "thumbnails", today: str | None = None) -> dict:
    """Returns a summary dict; `outcome` says what happened."""
    ok, why = should_handle(ctx)
    if not ok:
        print(f"Ignoring: {why}")
        return {"outcome": "ignored", "reason": why}

    issue = Issue(api, ctx, dry_run)
    form = parse_form(ctx.issue_body)
    if not form["repo"]:
        issue.comment("I couldn't read a GitHub repo URL from this issue. Use the "
                      f"[Remove my repo form](https://github.com/{ctx.repo}/issues/new?template=remove-repo.yml) "
                      "and enter `https://github.com/owner/repo`.")
        return {"outcome": "bad_url"}
    owner, repo = form["repo"]

    v = lookup_repo(api, owner, repo)
    if v.status in ("not_found", "moved", "refused", "error"):
        issue.comment(v.reason)
        return {"outcome": v.status}

    check_account(api, v, ctx.issue_author)
    if v.status == "unverified" and ctx.event == "issue_comment":
        check_file(api, v, ctx.issue_number)
    if v.status != "verified":
        issue.comment(instructions_comment(v, ctx.issue_number, form["all_repos"]))
        return {"outcome": "unverified"}

    # `owner/*` only through an account-level method; a file proves one repo.
    if form["all_repos"] and v.can_block_all:
        match = f"{v.owner_login}/*".lower()
    else:
        match = v.full_name.lower()

    today = today or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    new_entry = {"match": match, "issue": ctx.issue_number, "verifiedBy": ctx.issue_author,
                 "method": v.method, "date": today}
    existing = blocklist.load_blocklist(blocklist_path)
    already = any(blocklist.normalize_match(e["match"]) == match for e in existing)
    entries = existing if already else existing + [new_entry]

    victims = find_victims(skins_dir, [new_entry])
    keep_ids = surviving_ids(skins_dir, victims)
    print(f"Verified via {v.method}: {match}; {len(victims)} skin file(s) match")
    summary = {"outcome": "removed", "match": match, "method": v.method, "removed": len(victims),
               "entry": new_entry, "ids": [e.get("id") for _, e in victims]}

    if dry_run:
        print(f"[dry-run] blocklist.json {'already has' if already else 'would gain'}: {json.dumps(new_entry)}")
        for path, _ in victims:
            print(f"  [dry-run] delete {path}")
        delete_release_assets(run, ctx.repo, victims, dry_run=True, keep_ids=keep_ids)
        print(f"  [dry-run] gh workflow run build-catalog.yml --ref main --repo {ctx.repo}")
        planned = len({a for _, e in victims for a in release_assets(e, keep_ids)})
        issue.comment(success_comment(match, len(victims), planned, v, []))
        issue.label(LABEL_REMOVED)
        issue.close()
        return summary

    if not already:
        blocklist.save_blocklist(entries, blocklist_path)
    delete_files(victims, thumbnails_dir, keep_ids)
    blocklist_rel = str(Path(blocklist_path)) if blocklist_path else "blocklist.json"
    pushed = commit_and_push(
        run,
        f"chore(optout): remove {len(victims)} skin(s) for {match} (#{ctx.issue_number})",
        [blocklist_rel, skins_dir, thumbnails_dir],
    )
    if (victims or not already) and not pushed:
        # Changes were made but none reached main. Deleting release assets now
        # would leave live catalog entries pointing at nothing.
        raise RuntimeError("opt-out changes were not committed; release assets left untouched")
    deleted, failures = delete_release_assets(run, ctx.repo, victims, dry_run=False, keep_ids=keep_ids)
    if victims:
        r = run(["gh", "workflow", "run", "build-catalog.yml", "--ref", "main", "--repo", ctx.repo])
        if r.returncode != 0:
            failures.append("build-catalog.yml dispatch")
    summary.update({"assetsDeleted": deleted, "failures": failures})

    issue.comment(success_comment(match, len(victims), deleted, v, failures))
    if failures:
        summary["outcome"] = "partial"
        return summary  # leave open for a maintainer
    issue.label(LABEL_REMOVED)
    issue.close()
    return summary


def main():
    parser = argparse.ArgumentParser(description="Handle a repo opt-out issue (values come from env)")
    parser.add_argument("--dry-run", action="store_true",
                        help="read-only API calls only; print the plan, change nothing")
    parser.add_argument("--blocklist", default=None)
    parser.add_argument("--skins-dir", default="skins")
    parser.add_argument("--thumbnails-dir", default="thumbnails")
    args = parser.parse_args()

    token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN", "")
    ctx = Context.from_env()
    summary = run_optout(ctx, GitHubAPI(token), dry_run=args.dry_run, blocklist_path=args.blocklist,
                         skins_dir=args.skins_dir, thumbnails_dir=args.thumbnails_dir)
    print(json.dumps({k: v for k, v in summary.items() if k != "ids"}))
    sys.exit(1 if summary["outcome"] == "partial" else 0)


if __name__ == "__main__":
    main()
