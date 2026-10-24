"""In-memory stand-in for the GitHub API, behaving like git (content-addressed blobs, commits)."""
from __future__ import annotations

import hashlib

from core.github import GitHubError, RepoInfo, git_blob_sha


class FakeGitHub:
    def __init__(self, private: bool = True, empty: bool = True, name: str = "me/rgfp-backups"):
        self.info = RepoInfo(name, private, "main", f"https://github.com/{name}")
        self.blobs: dict[str, bytes] = {}
        self.trees: dict[str, dict[str, str]] = {}
        self.commits: dict[str, dict] = {}
        self.refs: dict[str, str] = {}
        self.calls: list[str] = []
        if not empty:
            self.init_empty_repo("main", b"# hello\n")

    def _log(self, name: str) -> None:
        self.calls.append(name)

    # --- GitHubLike
    def repo(self) -> RepoInfo:
        self._log("repo")
        return self.info

    def branch_head(self, branch: str) -> str | None:
        self._log("branch_head")
        return self.refs.get(branch)

    def commit_tree(self, commit_sha: str) -> str:
        return self.commits[commit_sha]["tree"]

    def tree_files(self, tree_sha: str) -> dict[str, str]:
        return dict(self.trees[tree_sha])

    def create_blob(self, data: bytes) -> str:
        if not self.refs:
            raise GitHubError(409, "Git Repository is empty.")
        self._log("create_blob")
        sha = git_blob_sha(data)
        self.blobs[sha] = data
        return sha

    def create_tree(self, base_tree: str | None, files: dict[str, str | None]) -> str:
        t = dict(self.trees[base_tree]) if base_tree else {}
        for p, sha in files.items():
            if sha is None:
                t.pop(p, None)
            else:
                assert sha in self.blobs, f"unknown blob for {p}"
                t[p] = sha
        sha = hashlib.sha1(repr(sorted(t.items())).encode()).hexdigest()
        self.trees[sha] = t
        return sha

    def create_commit(self, message: str, tree: str, parents: list[str]) -> tuple[str, str]:
        sha = hashlib.sha1(f"{message}{tree}{parents}{len(self.commits)}".encode()).hexdigest()
        self.commits[sha] = {"message": message, "tree": tree, "parents": parents}
        return sha, f"https://github.com/{self.info.full_name}/commit/{sha}"

    def set_branch(self, branch: str, sha: str, create: bool) -> None:
        if not create and branch not in self.refs:
            raise GitHubError(422, "Reference does not exist")
        self.refs[branch] = sha

    def init_empty_repo(self, branch: str, readme: bytes) -> None:
        sha = git_blob_sha(readme)
        self.blobs[sha] = readme
        tree = self.create_tree(None, {"README.md": sha})
        c, _ = self.create_commit("init", tree, [])
        self.refs[branch] = c

    def read_blob(self, sha: str) -> bytes:
        return self.blobs[sha]

    def recent_commits(self, branch: str, path: str, n: int) -> list[dict]:
        out, sha = [], self.refs.get(branch)
        while sha and len(out) < n:
            c = self.commits[sha]
            if path in self.trees[c["tree"]]:
                out.append({"sha": sha, "message": c["message"], "date": "", "url": ""})
            sha = c["parents"][0] if c["parents"] else None
        return out

    # --- helpers for assertions
    def files_at_head(self) -> dict[str, bytes]:
        t = self.trees[self.commits[self.refs["main"]]["tree"]]
        return {p: self.blobs[s] for p, s in t.items()}
