#!/usr/bin/env python3
"""
github_ownership.py — GitHub plumbing shared by the issue-driven bots
(`process_optout.py`, `process_claim.py`).

  - `GitHubAPI`: a minimal REST client that answers 204/404 instead of raising.
  - `parse_sections`: issue-form body -> {lowercased heading: text}.
  - `lookup_repo` / `check_account` / `check_file`: "is this issue author in
    control of this repo". `check_account` accepts the owning User or a public
    member of the owning Organization; `check_file` accepts a file in the repo
    root, on the default branch, that contains the issue number (the file name
    differs per bot: `.emuskins-optout`, `.emuskins-creator`).
  - `Issue`: comment on / label / close the triggering issue (prints instead in
    dry-run). `commit_and_push`: commit paths and push to main.

Moved here unchanged from process_optout.py (SkinKit#57); that module re-exports
the names so its callers and tests keep working.
"""

import base64
import json
import re
import subprocess
from dataclasses import dataclass, field
from urllib.parse import quote
from urllib.request import Request, urlopen
from urllib.error import HTTPError

import blocklist

VERIFY_FILE = ".emuskins-optout"  # the opt-out bot's file; other bots pass their own to check_file


# ---------------------------------------------------------------------------
# GitHub REST + gh
# ---------------------------------------------------------------------------

class GitHubAPI:
    """Minimal REST client. `request` returns (status, json-or-None) and does
    not raise on 4xx, because 204/404 are answers here (public_members)."""

    user_agent = "Provenance-SkinCatalog/1.0 (+https://github.com/Provenance-Emu/skins)"

    def __init__(self, token: str, base: str = "https://api.github.com"):
        self.token = token
        self.base = base

    def _open(self, req):
        # Subclasses override this so a bot module's own `urlopen` is the one tests patch.
        return urlopen(req, timeout=20)

    def request(self, method: str, path: str, body=None):
        data = json.dumps(body).encode() if body is not None else None
        req = Request(f"{self.base}/{path.lstrip('/')}", data=data, method=method, headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {self.token}",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": self.user_agent,
            **({"Content-Type": "application/json"} if data else {}),
        })
        try:
            with self._open(req) as r:
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


def check_file(api, v: Verification, issue_number: int, verify_file: str = VERIFY_FILE) -> Verification:
    """`verify_file` on the default branch containing the issue number."""
    if v.status != "unverified":
        return v
    status, data = api.request(
        "GET", f"/repos/{v.full_name}/contents/{verify_file}?ref={quote(v.default_branch, safe='')}")
    if status != 200 or not isinstance(data, dict) or data.get("encoding") != "base64":
        v.notes.append(f"`{verify_file}` not found on `{v.default_branch}`.")
        return v
    try:
        text = base64.b64decode(data.get("content", "")).decode("utf-8", errors="replace")
    except Exception:
        v.notes.append(f"`{verify_file}` could not be read.")
        return v
    if re.search(rf"(?<!\d){issue_number}(?!\d)", text):
        v.status, v.method, v.can_block_all = "verified", "file", False
    else:
        v.notes.append(f"`{verify_file}` exists but doesn't contain the issue number {issue_number}.")
    return v


# ---------------------------------------------------------------------------
# Git
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Issue actions
# ---------------------------------------------------------------------------

class Issue:
    """Comment / label / close on the triggering issue; prints instead in dry-run.
    `ctx` needs `.repo` (owner/name) and `.issue_number`."""

    def __init__(self, api, ctx, dry_run: bool):
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

    def unlabel(self, name: str):
        if self.dry_run:
            print(f"[dry-run] remove label {name!r}")
            return
        self.api.request("DELETE", f"/repos/{self.ctx.repo}/issues/{self.ctx.issue_number}/labels/{quote(name)}")

    def comments(self, max_pages: int = 5) -> list[dict]:
        """The issue's comments, oldest first (read-only, so dry-run reads them too)."""
        out = []
        for page in range(1, max_pages + 1):
            status, data = self.api.request(
                "GET", f"/repos/{self.ctx.repo}/issues/{self.ctx.issue_number}/comments?per_page=100&page={page}")
            if status != 200 or not isinstance(data, list):
                break
            out += data
            if len(data) < 100:
                break
        return out

    def close(self):
        if self.dry_run:
            print(f"[dry-run] close #{self.ctx.issue_number}")
            return
        self.api.request("PATCH", f"/repos/{self.ctx.repo}/issues/{self.ctx.issue_number}",
                         {"state": "closed", "state_reason": "completed"})
