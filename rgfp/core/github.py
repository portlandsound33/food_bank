"""Minimal GitHub REST client for backups (Git Data API: one commit per backup).

Token: a fine-grained personal access token limited to the backup repository,
with "Contents: Read and write". Nothing else is needed.
"""
from __future__ import annotations

import base64
import hashlib
from dataclasses import dataclass
from typing import Protocol

import requests

API = "https://api.github.com"
TIMEOUT = 30


class GitHubError(RuntimeError):
    def __init__(self, status: int, message: str):
        super().__init__(f"GitHub {status}: {message}")
        self.status = status


def git_blob_sha(data: bytes) -> str:
    """The SHA git gives a file's contents, so unchanged files can be skipped."""
    return hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()


@dataclass
class RepoInfo:
    full_name: str
    private: bool
    default_branch: str
    html_url: str


class GitHubLike(Protocol):  # implemented by GitHubClient and the test fake
    def repo(self) -> RepoInfo: ...
    def branch_head(self, branch: str) -> str | None: ...
    def commit_tree(self, commit_sha: str) -> str: ...
    def tree_files(self, tree_sha: str) -> dict[str, str]: ...
    def create_blob(self, data: bytes) -> str: ...
    def create_tree(self, base_tree: str | None, files: dict[str, str]) -> str: ...
    def create_commit(self, message: str, tree: str, parents: list[str]) -> tuple[str, str]: ...
    def set_branch(self, branch: str, sha: str, create: bool) -> None: ...
    def init_empty_repo(self, branch: str, readme: bytes) -> None: ...
    def read_blob(self, sha: str) -> bytes: ...
    def recent_commits(self, branch: str, path: str, n: int) -> list[dict]: ...


class GitHubClient:
    def __init__(self, repo_full_name: str, token: str):
        if repo_full_name.count("/") != 1:
            raise ValueError("Repository must look like owner/name")
        self.repo_name = repo_full_name.strip()
        self.s = requests.Session()
        self.s.headers.update({
            "Authorization": f"Bearer {token.strip()}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "rgfp-intake-backup",
        })

    # -------------------------------------------------------------- plumbing --
    def _url(self, path: str) -> str:
        return f"{API}/repos/{self.repo_name}{path}"

    def _call(self, method: str, path: str, ok: tuple[int, ...] = (200, 201), **kw) -> dict | list | None:
        r = self.s.request(method, self._url(path), timeout=TIMEOUT, **kw)
        if r.status_code in ok:
            return r.json() if r.content else None
        try:
            msg = r.json().get("message", r.text)
        except ValueError:
            msg = r.text
        hints = {
            401: "the token is wrong or expired",
            403: "the token doesn't have permission (needs Contents: Read and write on this repository)",
            404: "repository not found, or the token can't see it",
        }
        if r.status_code in hints:
            msg = f"{msg} — {hints[r.status_code]}"
        raise GitHubError(r.status_code, msg)

    # ------------------------------------------------------------------- API --
    def repo(self) -> RepoInfo:
        d = self._call("GET", "")
        return RepoInfo(d["full_name"], bool(d["private"]), d.get("default_branch") or "main", d["html_url"])

    def branch_head(self, branch: str) -> str | None:
        """Commit SHA at the tip of ``branch``; None if the branch (or the whole repo) is empty."""
        r = self.s.get(self._url(f"/git/ref/heads/{branch}"), timeout=TIMEOUT)
        if r.status_code in (404, 409):  # 409 = "Git Repository is empty."
            return None
        if r.status_code != 200:
            raise GitHubError(r.status_code, r.text)
        return r.json()["object"]["sha"]

    def commit_tree(self, commit_sha: str) -> str:
        return self._call("GET", f"/git/commits/{commit_sha}")["tree"]["sha"]

    def tree_files(self, tree_sha: str) -> dict[str, str]:
        d = self._call("GET", f"/git/trees/{tree_sha}", params={"recursive": "1"})
        return {e["path"]: e["sha"] for e in d["tree"] if e["type"] == "blob"}

    def create_blob(self, data: bytes) -> str:
        d = self._call("POST", "/git/blobs",
                       json={"content": base64.b64encode(data).decode(), "encoding": "base64"})
        return d["sha"]

    def create_tree(self, base_tree: str | None, files: dict[str, str]) -> str:
        body: dict = {"tree": [{"path": p, "mode": "100644", "type": "blob", "sha": sha}
                               for p, sha in files.items()]}
        if base_tree:
            body["base_tree"] = base_tree
        return self._call("POST", "/git/trees", json=body)["sha"]

    def create_commit(self, message: str, tree: str, parents: list[str]) -> tuple[str, str]:
        d = self._call("POST", "/git/commits", json={"message": message, "tree": tree, "parents": parents})
        return d["sha"], d.get("html_url") or f"https://github.com/{self.repo_name}/commit/{d['sha']}"

    def set_branch(self, branch: str, sha: str, create: bool) -> None:
        if create:
            self._call("POST", "/git/refs", json={"ref": f"refs/heads/{branch}", "sha": sha})
        else:
            self._call("PATCH", f"/git/refs/heads/{branch}", json={"sha": sha, "force": False})

    def init_empty_repo(self, branch: str, readme: bytes) -> None:
        """The Git Data API can't write to a repository with no commits; make a first one."""
        self._call("PUT", "/contents/README.md",
                   json={"message": "Initialize backup repository",
                         "content": base64.b64encode(readme).decode()})  # lands on the default branch

    def read_blob(self, sha: str) -> bytes:
        d = self._call("GET", f"/git/blobs/{sha}")
        return base64.b64decode(d["content"]) if d.get("encoding") == "base64" else d["content"].encode()

    def recent_commits(self, branch: str, path: str, n: int) -> list[dict]:
        d = self._call("GET", "/commits", params={"sha": branch, "path": path, "per_page": n})
        return [{"sha": c["sha"], "message": c["commit"]["message"].splitlines()[0],
                 "date": c["commit"]["committer"]["date"], "url": c["html_url"]} for c in d]
