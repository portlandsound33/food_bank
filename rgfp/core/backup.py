"""Daily database backups to a private GitHub repository, and restore from them.

What a backup commit contains (one commit per backup; git history = every past day):
  clients.jsonl          one client per line (everything except images), sorted by member #
  checkins.jsonl         every check-in
  signatures/RGFP-000123.png   signature images, uploaded only when new or changed
  manifest.json          counts + time of the backup
  README.md              what this is and how to restore (written once)

QR codes aren't backed up; they're regenerated from the member number.

Scheduling: a background thread checks every few minutes while the app is running.
If the daily backup time has passed and today's backup hasn't happened, it runs.
On Render's free plan the app sleeps when nobody uses it, so a missed backup runs
as soon as someone opens the app again (data can only change while it's in use).
"""
from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
import threading
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Callable, Iterator

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import Date, func, select, text

from .config import DATA_DIR, MONTHLY_VISITS, ON_RENDER, TZ
from .db import AppSetting, BackupRun, CheckIn, Client, UTCDateTime, format_member_code, session_scope, utcnow
from .github import GitHubClient, GitHubError, GitHubLike, git_blob_sha
from .qr import parse_member_code

log = logging.getLogger("rgfp.backup")

FORMAT_VERSION = 1
MAX_NEW_SIGNATURES_PER_RUN = 400   # GitHub allows ~5,000 API calls/hour; the rest go next run
RETRY_AFTER = timedelta(minutes=30)
CHECK_EVERY_SECONDS = 300
CLIENT_COLUMNS = [c for c in Client.__table__.columns if c.name not in ("qr_png", "signature_png")]
CHECKIN_COLUMNS = list(CheckIn.__table__.columns)

REPO_README = b"""# Rio Grande Food Project - database backups

**This repository contains personal information. Keep it private.**

Written automatically by the RGFP intake app (Admin -> Backups). Every commit is one backup;
the commit history is the list of restore points.

| File | Contents |
|---|---|
| `clients.jsonl` | One client per line (all fields except images) |
| `checkins.jsonl` | Every check-in |
| `signatures/` | Signature images, named by member number |
| `manifest.json` | When the backup was taken, and counts |

To restore: open the app with an empty database, go to Admin -> Backups -> Restore,
choose a backup and press Restore. Member numbers are kept.
"""


# ================================================================ settings ==
def _get(key: str) -> str | None:
    with session_scope() as s:
        row = s.get(AppSetting, key)
        return row.value if row else None


def _set(key: str, value: str | None) -> None:
    with session_scope() as s:
        row = s.get(AppSetting, key)
        if row is None:
            s.add(AppSetting(key=key, value=value))
        else:
            row.value = value


def _secret_key() -> bytes | None:
    """Key for encrypting the GitHub token at rest. Render: RGFP_SECRET_KEY. Locally: a file."""
    k = os.environ.get("RGFP_SECRET_KEY")
    if not k and not ON_RENDER:
        f = DATA_DIR / ".secret_key"
        if not f.exists():
            f.write_text(base64.urlsafe_b64encode(os.urandom(32)).decode())
        k = f.read_text().strip()
    return base64.urlsafe_b64encode(hashlib.sha256(k.encode()).digest()) if k else None


def can_store_token() -> bool:
    return _secret_key() is not None


def save_token(token: str) -> None:
    key = _secret_key()
    if key is None:
        raise RuntimeError("RGFP_SECRET_KEY isn't set on the server, so the token can't be stored safely.")
    _set("backup.token", Fernet(key).encrypt(token.strip().encode()).decode())


def get_token() -> str | None:
    env = os.environ.get("RGFP_GITHUB_TOKEN")
    if env:
        return env.strip()
    enc, key = _get("backup.token"), _secret_key()
    if not enc or key is None:
        return None
    try:
        return Fernet(key).decrypt(enc.encode()).decode()
    except InvalidToken:  # the secret key changed; the token has to be entered again
        return None


@dataclass
class Settings:
    repo: str | None
    enabled: bool
    hour: int                       # local hour of day, 0–23
    token_set: bool
    last_success: datetime | None
    last_attempt: datetime | None


def _dt(v: str | None) -> datetime | None:
    return datetime.fromisoformat(v) if v else None


def load_settings() -> Settings:
    return Settings(
        repo=_get("backup.repo") or None,
        enabled=_get("backup.enabled") == "1",
        hour=int(_get("backup.hour") or 21),
        token_set=get_token() is not None,
        last_success=_dt(_get("backup.last_success")),
        last_attempt=_dt(_get("backup.last_attempt")),
    )


def save_settings(repo: str, enabled: bool, hour: int) -> None:
    repo = repo.strip().removeprefix("https://github.com/").removesuffix(".git").strip("/")
    if repo and repo.count("/") != 1:
        raise ValueError("Repository must look like owner/name, e.g. portlandsound33/rgfp-backups")
    if not 0 <= hour <= 23:
        raise ValueError("hour must be 0–23")
    _set("backup.repo", repo or None)
    _set("backup.enabled", "1" if enabled else "0")
    _set("backup.hour", str(hour))


def make_client(repo: str | None = None, token: str | None = None) -> GitHubLike:
    repo = repo or load_settings().repo
    token = token or get_token()
    if not repo or not token:
        raise RuntimeError("Backup repository and token are not set up yet.")
    return GitHubClient(repo, token)


# Tests swap this for a fake GitHub.
client_factory: Callable[..., GitHubLike] = make_client


# ================================================================ snapshot ==
def _jsonable(v):  # noqa: ANN001, ANN202
    if isinstance(v, (datetime, date)):
        return v.isoformat()
    return v


def _line(d: dict) -> bytes:
    return json.dumps(d, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode() + b"\n"


def _sig_ext(data: bytes) -> str:
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "png"
    if data[:3] == b"\xff\xd8\xff":
        return "jpg"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    return "bin"


def _iter_clients(batch: int = 200) -> Iterator[tuple[dict, bytes | None]]:
    """(row dict, signature bytes) in member-number order, a batch at a time (bounded memory)."""
    last = 0
    while True:
        with session_scope() as s:
            rows = s.execute(
                select(*CLIENT_COLUMNS, Client.signature_png)
                .where(Client.client_id > last).order_by(Client.client_id).limit(batch)
            ).all()
        if not rows:
            return
        for r in rows:
            m = r._mapping
            d = {c.name: _jsonable(m[c.name]) for c in CLIENT_COLUMNS}
            yield d, m["signature_png"]
        last = rows[-1].client_id


def _checkins_jsonl() -> tuple[bytes, int]:
    with session_scope() as s:
        rows = s.execute(select(*CHECKIN_COLUMNS).order_by(CheckIn.checkin_id)).all()
    return b"".join(_line({c.name: _jsonable(r._mapping[c.name]) for c in CHECKIN_COLUMNS}) for r in rows), len(rows)


@dataclass
class BackupResult:
    ok: bool
    message: str
    commit_url: str | None = None
    clients: int = 0
    checkins: int = 0
    signatures_uploaded: int = 0
    signatures_pending: int = 0


_run_lock = threading.Lock()


def is_running() -> bool:
    return _run_lock.locked()


def run_backup(trigger: str = "manual", now: datetime | None = None,
               progress: Callable[[str], None] | None = None) -> BackupResult:
    """Take a backup now. Never raises: failures are returned and logged in backup_runs."""
    if not _run_lock.acquire(blocking=False):
        return BackupResult(False, "A backup is already running.")
    now = now or datetime.now(TZ)
    say = progress or (lambda _m: None)
    with session_scope() as s:
        run = BackupRun(trigger=trigger, started_at=now.astimezone(timezone.utc))
        s.add(run)
        s.flush()
        run_id = run.run_id
    _set("backup.last_attempt", now.isoformat())
    try:
        res = _do_backup(now, say)
    except GitHubError as e:
        res = BackupResult(False, str(e))
    except Exception as e:  # noqa: BLE001
        log.exception("backup failed")
        res = BackupResult(False, f"{type(e).__name__}: {e}")
    finally:
        _run_lock.release()
    with session_scope() as s:
        run = s.get(BackupRun, run_id)
        run.finished_at = utcnow()
        run.ok, run.message, run.commit_url = res.ok, res.message, res.commit_url
        run.clients, run.checkins, run.signatures_uploaded = res.clients, res.checkins, res.signatures_uploaded
    if res.ok:
        _set("backup.last_success", now.isoformat())
    return res


def _do_backup(now: datetime, say: Callable[[str], None]) -> BackupResult:
    gh = client_factory()
    say("Checking the repository…")
    info = gh.repo()
    if not info.private:
        return BackupResult(False, f"{info.full_name} is PUBLIC. Backups contain personal information, so they "
                                   "are only written to a private repository. Make it private, or use another.")
    branch = info.default_branch
    head = gh.branch_head(branch)
    if head is None:
        say("Initializing the empty repository…")
        gh.init_empty_repo(branch, REPO_README)
        head = gh.branch_head(branch)
        if head is None:
            raise RuntimeError("Couldn't initialize the empty repository.")
    base_tree = gh.commit_tree(head)
    remote = gh.tree_files(base_tree)

    changes: dict[str, str | None] = {}

    def put(path: str, data: bytes) -> bool:
        sha = git_blob_sha(data)
        if remote.get(path) == sha:
            return False
        changes[path] = gh.create_blob(data)
        return True

    say("Reading clients…")
    lines: list[bytes] = []
    wanted_sigs: set[str] = set()
    uploaded = pending = n_clients = 0
    for d, sig in _iter_clients():
        n_clients += 1
        path = None
        if sig:
            path = f"signatures/{format_member_code(d['client_id'])}.{_sig_ext(sig)}"
            wanted_sigs.add(path)
            if remote.get(path) != git_blob_sha(sig):
                if uploaded < MAX_NEW_SIGNATURES_PER_RUN:
                    put(path, sig)
                    uploaded += 1
                    if uploaded % 50 == 0:
                        say(f"Uploaded {uploaded} signatures…")
                else:
                    pending += 1
        d["signature_file"] = path
        lines.append(_line(d))
    for path in remote:  # signatures of clients that no longer exist
        if path.startswith("signatures/") and path not in wanted_sigs:
            changes[path] = None

    say("Writing data files…")
    put("clients.jsonl", b"".join(lines))
    checkins, n_checkins = _checkins_jsonl()
    put("checkins.jsonl", checkins)
    if "README.md" not in remote:
        put("README.md", REPO_README)
    stamp = now.astimezone(TZ)
    put("manifest.json", json.dumps({
        "format": FORMAT_VERSION, "app": "rgfp-intake", "backed_up_at": stamp.isoformat(),
        "clients": n_clients, "checkins": n_checkins, "signatures": len(wanted_sigs),
        "signatures_pending": pending, "monthly_visits": MONTHLY_VISITS,
    }, indent=2).encode())

    tree = gh.create_tree(base_tree, changes)
    msg = (f"Backup {stamp:%Y-%m-%d %H:%M %Z} — {n_clients:,} clients, {n_checkins:,} check-ins"
           + (f" ({pending} signatures still to upload)" if pending else ""))
    sha, url = gh.create_commit(msg, tree, [head])
    gh.set_branch(branch, sha, create=False)
    done = f"Backed up {n_clients:,} clients and {n_checkins:,} check-ins"
    if uploaded:
        done += f"; uploaded {uploaded} signature(s)"
    if pending:
        done += f"; {pending} more signature(s) will upload on the next backup"
    return BackupResult(True, done + ".", url, n_clients, n_checkins, uploaded, pending)


def recent_runs(n: int = 15) -> list[BackupRun]:
    with session_scope() as s:
        return list(s.scalars(select(BackupRun).order_by(BackupRun.run_id.desc()).limit(n)))


# =============================================================== schedule ==
def last_scheduled_time(now: datetime, hour: int) -> datetime:
    now = now.astimezone(TZ)
    today_at = now.replace(hour=hour, minute=0, second=0, microsecond=0)
    return today_at if now >= today_at else (today_at - timedelta(days=1))


def is_due(st: Settings, now: datetime) -> bool:
    if not (st.enabled and st.repo and st.token_set):
        return False
    if st.last_attempt and now - st.last_attempt < RETRY_AFTER and (
            st.last_success is None or st.last_attempt > st.last_success):
        return False  # the last try failed recently; don't hammer GitHub
    return st.last_success is None or st.last_success < last_scheduled_time(now, st.hour)


def next_run_time(st: Settings, now: datetime) -> datetime:
    if is_due(st, now):
        return now
    nxt = last_scheduled_time(now, st.hour) + timedelta(days=1)
    return nxt.replace(hour=st.hour)  # keeps wall-clock hour across DST changes


def tick(now: datetime | None = None) -> BackupResult | None:
    """Run a scheduled backup if one is due. Called by the background thread."""
    now = now or datetime.now(TZ)
    if is_due(load_settings(), now):
        return run_backup("scheduled", now=now)
    return None


_thread_lock = threading.Lock()
_thread: threading.Thread | None = None


def start_scheduler() -> None:
    """Start the background checker once per server process."""
    global _thread
    if os.environ.get("RGFP_DISABLE_SCHEDULER"):
        return
    with _thread_lock:
        if _thread is not None and _thread.is_alive():
            return

        def loop() -> None:
            time.sleep(20)  # let the app finish starting
            while True:
                try:
                    tick()
                except Exception:  # noqa: BLE001
                    log.exception("backup scheduler tick failed")
                time.sleep(CHECK_EVERY_SECONDS)

        _thread = threading.Thread(target=loop, name="rgfp-backup-scheduler", daemon=True)
        _thread.start()


# ================================================================ restore ==
def restore_points(n: int = 20) -> list[dict]:
    gh = client_factory()
    return gh.recent_commits(gh.repo().default_branch, "clients.jsonl", n)


def database_is_empty() -> bool:
    with session_scope() as s:
        return not (s.scalar(select(func.count()).select_from(Client))
                    or s.scalar(select(func.count()).select_from(CheckIn)))


def _from_json(col, v):  # noqa: ANN001, ANN202
    if v is None:
        return None
    if isinstance(col.type, UTCDateTime):
        return datetime.fromisoformat(v)
    if isinstance(col.type, Date):
        return date.fromisoformat(v)
    return v


def restore(commit_sha: str | None = None, progress: Callable[[str], None] | None = None) -> dict:
    """Load a backup into an EMPTY database, keeping member numbers."""
    say = progress or (lambda _m: None)
    if not database_is_empty():
        raise RuntimeError("Restore only works on an empty database (Danger zone → delete all first).")
    gh = client_factory()
    info = gh.repo()
    sha = commit_sha or gh.branch_head(info.default_branch)
    if sha is None:
        raise RuntimeError("The backup repository is empty.")
    files = gh.tree_files(gh.commit_tree(sha))
    if "clients.jsonl" not in files:
        raise RuntimeError("That commit doesn't contain a backup (no clients.jsonl).")

    say("Downloading clients…")
    client_cols = {c.name: c for c in CLIENT_COLUMNS}
    checkin_cols = {c.name: c for c in CHECKIN_COLUMNS}
    clients = [json.loads(x) for x in gh.read_blob(files["clients.jsonl"]).splitlines() if x.strip()]
    checkins = ([json.loads(x) for x in gh.read_blob(files["checkins.jsonl"]).splitlines() if x.strip()]
                if "checkins.jsonl" in files else [])
    sig_paths = {p: s for p, s in files.items() if p.startswith("signatures/")}

    say(f"Restoring {len(clients):,} clients…")
    with session_scope() as s:
        for d in clients:
            s.add(Client(**{k: _from_json(client_cols[k], v) for k, v in d.items() if k in client_cols}))
        s.flush()
        for d in checkins:
            s.add(CheckIn(**{k: _from_json(checkin_cols[k], v) for k, v in d.items() if k in checkin_cols}))

    say(f"Restoring {len(sig_paths):,} signatures…")
    n_sig = 0
    for i, (path, blob) in enumerate(sig_paths.items(), 1):
        cid = parse_member_code(path.split("/", 1)[1].rsplit(".", 1)[0])
        if cid is None:
            continue
        data = gh.read_blob(blob)
        with session_scope() as s:
            row = s.get(Client, cid)
            if row is not None:
                row.signature_png = data
                n_sig += 1
        if i % 50 == 0:
            say(f"Restored {i:,} of {len(sig_paths):,} signatures…")

    _reset_sequences()
    return {"clients": len(clients), "checkins": len(checkins), "signatures": n_sig, "commit": sha}


def _reset_sequences() -> None:
    """Postgres keeps a counter for new IDs; move it past the restored ones."""
    with session_scope() as s:
        if s.get_bind().dialect.name != "postgresql":
            return  # SQLite picks max(id)+1 automatically
        for table, col in (("clients", "client_id"), ("checkins", "checkin_id")):
            s.execute(text(
                f"SELECT setval(pg_get_serial_sequence('{table}', '{col}'), "
                f"COALESCE((SELECT MAX({col}) FROM {table}), 1), "
                f"(SELECT MAX({col}) FROM {table}) IS NOT NULL)"))
