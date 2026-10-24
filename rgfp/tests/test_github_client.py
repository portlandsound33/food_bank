import base64
import json

import pytest

from core.github import GitHubClient, GitHubError, git_blob_sha


class _Resp:
    def __init__(self, status, body=None):
        self.status_code, self._body = status, body
        self.content = b"" if body is None else json.dumps(body).encode()
        self.text = self.content.decode()

    def json(self):
        return self._body


@pytest.fixture
def client(monkeypatch):
    c = GitHubClient("me/rgfp-backups", " github_pat_abc ")
    sent = []
    replies = {}

    def request(method, url, timeout=None, **kw):
        sent.append((method, url, kw))
        return replies.get((method, url.split("/repos/me/rgfp-backups", 1)[1]), _Resp(500, {"message": "?"}))

    monkeypatch.setattr(c.s, "request", request)
    monkeypatch.setattr(c.s, "get", lambda url, timeout=None, **kw: request("GET", url, **kw))
    return c, sent, replies


def test_headers_and_repo(client):
    c, sent, replies = client
    assert c.s.headers["Authorization"] == "Bearer github_pat_abc"
    assert c.s.headers["X-GitHub-Api-Version"] == "2022-11-28"
    replies[("GET", "")] = _Resp(200, {"full_name": "me/rgfp-backups", "private": True,
                                       "default_branch": "main", "html_url": "u"})
    info = c.repo()
    assert info.private and info.default_branch == "main"
    assert sent[0][1] == "https://api.github.com/repos/me/rgfp-backups"


def test_empty_repo_head_is_none(client):
    c, _, replies = client
    replies[("GET", "/git/ref/heads/main")] = _Resp(409, {"message": "Git Repository is empty."})
    assert c.branch_head("main") is None


def test_blob_is_base64_and_errors_explain(client):
    c, sent, replies = client
    replies[("POST", "/git/blobs")] = _Resp(201, {"sha": "abc"})
    assert c.create_blob(b"\x00\x01hi") == "abc"
    assert base64.b64decode(sent[-1][2]["json"]["content"]) == b"\x00\x01hi"
    replies[("POST", "/git/blobs")] = _Resp(403, {"message": "Resource not accessible by personal access token"})
    with pytest.raises(GitHubError, match="Contents: Read and write"):
        c.create_blob(b"x")


def test_tree_supports_deletions(client):
    c, sent, replies = client
    replies[("POST", "/git/trees")] = _Resp(201, {"sha": "t"})
    c.create_tree("base", {"a.txt": "s1", "signatures/old.png": None})
    body = sent[-1][2]["json"]
    assert body["base_tree"] == "base"
    assert {"path": "signatures/old.png", "mode": "100644", "type": "blob", "sha": None} in body["tree"]


def test_git_blob_sha_matches_git():
    # `printf 'hello\n' | git hash-object --stdin`
    assert git_blob_sha(b"hello\n") == "ce013625030ba8dba906f756967f9e9ca394464a"


def test_rejects_bad_repo_name():
    with pytest.raises(ValueError):
        GitHubClient("just-a-name", "t")
