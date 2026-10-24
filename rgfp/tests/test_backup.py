import json
from datetime import datetime, timedelta

import pytest

from core import backup, repo, visits
from core.config import TZ
from core.seed import fake_clients
from tests.fake_github import FakeGitHub

PNG = b"\x89PNG\r\n\x1a\n" + b"fake-signature-"
JPG = b"\xff\xd8\xff" + b"jpeg-signature"


@pytest.fixture
def gh(monkeypatch):
    fake = FakeGitHub()
    monkeypatch.setattr(backup, "client_factory", lambda *a, **k: fake)
    repo.delete_all()
    with backup.session_scope() as s:  # clean settings/runs between tests
        s.query(backup.AppSetting).delete()
        s.query(backup.BackupRun).delete()
    return fake


def _seed(n=5, sigs=2):
    ids = repo.bulk_create(fake_clients(n, seed=11), "seed")
    for i, cid in enumerate(ids[:sigs]):
        data = repo.to_client_in(repo.get_client(cid))
        repo.update_client(cid, data, PNG + bytes([i]))
    return ids


def test_backup_writes_one_commit_with_all_files(gh):
    ids = _seed()
    visits.check_in(ids[0])
    res = backup.run_backup("manual")
    assert res.ok, res.message
    files = gh.files_at_head()
    assert {"clients.jsonl", "checkins.jsonl", "manifest.json", "README.md"} <= set(files)
    assert sum(p.startswith("signatures/") for p in files) == 2
    rows = [json.loads(x) for x in files["clients.jsonl"].splitlines()]
    assert [r["client_id"] for r in rows] == ids
    assert "qr_png" not in rows[0] and "signature_png" not in rows[0]
    assert rows[0]["signature_file"] == f"signatures/RGFP-{ids[0]:06d}.png"
    assert json.loads(files["manifest.json"])["clients"] == 5
    assert len(files["checkins.jsonl"].splitlines()) == 1
    # empty repo was initialised, then exactly one backup commit on top
    head = gh.commits[gh.refs["main"]]
    assert head["message"].startswith("Backup ") and len(head["parents"]) == 1
    assert backup.recent_runs()[0].ok


def test_second_backup_only_uploads_changes(gh):
    ids = _seed()
    assert backup.run_backup().ok
    gh.calls.clear()
    assert backup.run_backup().ok
    # nothing changed: only manifest (new timestamp) is a new blob; signatures untouched
    assert gh.calls.count("create_blob") == 1
    repo.update_client(ids[3], repo.to_client_in(repo.get_client(ids[3])), JPG)
    gh.calls.clear()
    res = backup.run_backup()
    assert res.signatures_uploaded == 1
    assert f"signatures/RGFP-{ids[3]:06d}.jpg" in gh.files_at_head()


def test_deleted_clients_signatures_are_removed(gh):
    _seed()
    backup.run_backup()
    repo.delete_all()
    backup.run_backup()
    files = gh.files_at_head()
    assert not any(p.startswith("signatures/") for p in files)
    assert files["clients.jsonl"] == b""


def test_refuses_public_repository(gh):
    gh.info.private = False
    _seed()
    res = backup.run_backup()
    assert not res.ok and "PUBLIC" in res.message
    assert gh.refs == {}  # nothing written
    assert backup.recent_runs()[0].ok is False


def test_signature_upload_cap_continues_next_run(gh, monkeypatch):
    monkeypatch.setattr(backup, "MAX_NEW_SIGNATURES_PER_RUN", 2)
    _seed(n=5, sigs=5)
    r1 = backup.run_backup()
    assert r1.ok and r1.signatures_uploaded == 2 and r1.signatures_pending == 3
    r2 = backup.run_backup()
    r3 = backup.run_backup()
    assert r3.signatures_pending == 0
    assert sum(p.startswith("signatures/") for p in gh.files_at_head()) == 5


def test_restore_round_trip_keeps_member_numbers(gh):
    ids = _seed(n=6, sigs=3)
    repo.delete_all()
    ids = _seed(n=6, sigs=3)  # ids no longer start at 1
    visits.check_in(ids[1])
    visits.check_in(ids[1])
    before = repo.export_df()
    backup.run_backup()
    repo.delete_all()
    assert backup.database_is_empty()
    out = backup.restore()
    assert out == {"clients": 6, "checkins": 2, "signatures": 3, "commit": gh.refs["main"]}
    after = repo.export_df()
    assert list(after["client_id"]) == ids
    cols = ["first_name", "last_name", "phone", "zip", "county", "pickup_persons", "tefap_income_limit",
            "visits_remaining"]
    assert after[cols].equals(before[cols])
    assert repo.get_client(ids[0]).signature_png == PNG + bytes([0])
    assert visits.status(ids[1]).used_this_month == 2
    # new registrations continue after the highest restored member number
    new = repo.create_client(repo.to_client_in(repo.get_client(ids[0])))
    assert new.client_id == max(ids) + 1


def test_restore_refuses_non_empty_database(gh):
    _seed()
    backup.run_backup()
    with pytest.raises(RuntimeError, match="empty database"):
        backup.restore()


def test_restore_older_point(gh):
    _seed(n=2, sigs=0)
    backup.run_backup()
    first = gh.refs["main"]
    repo.bulk_create(fake_clients(3, seed=2), "seed")
    backup.run_backup()
    points = backup.restore_points()
    assert len(points) == 2 and points[1]["sha"] == first
    repo.delete_all()
    assert backup.restore(first)["clients"] == 2


def test_schedule_logic():
    hour = 21
    st = backup.Settings("me/x", True, hour, True, None, None)
    now = datetime(2026, 10, 24, 9, tzinfo=TZ)
    assert backup.is_due(st, now)  # never backed up -> right away
    st.last_success = datetime(2026, 10, 23, 21, 5, tzinfo=TZ)
    assert not backup.is_due(st, now)  # last night's done
    assert backup.next_run_time(st, now) == datetime(2026, 10, 24, 21, tzinfo=TZ)
    assert backup.is_due(st, datetime(2026, 10, 24, 21, 1, tzinfo=TZ))
    # app slept through 9 PM; first wake-up the next morning catches up
    assert backup.is_due(st, datetime(2026, 10, 25, 7, tzinfo=TZ))
    # a recent failure waits 30 minutes before retrying
    st.last_attempt = datetime(2026, 10, 24, 21, 1, tzinfo=TZ)
    assert not backup.is_due(st, datetime(2026, 10, 24, 21, 20, tzinfo=TZ))
    assert backup.is_due(st, datetime(2026, 10, 24, 21, 40, tzinfo=TZ))
    # disabled / not configured
    assert not backup.is_due(backup.Settings("me/x", False, hour, True, None, None), now)
    assert not backup.is_due(backup.Settings(None, True, hour, True, None, None), now)
    # DST: Nov 1 2026 — still 9 PM wall-clock
    st2 = backup.Settings("me/x", True, hour, True, datetime(2026, 10, 31, 21, tzinfo=TZ), None)
    assert backup.next_run_time(st2, datetime(2026, 11, 1, 10, tzinfo=TZ)).hour == 21


def test_tick_runs_only_when_due(gh):
    _seed(n=1, sigs=0)
    backup.save_settings("me/rgfp-backups", enabled=True, hour=21)
    backup.save_token("github_pat_test")
    now = datetime.now(TZ)
    assert backup.tick(now) is not None  # first time: runs
    assert backup.tick(now + timedelta(minutes=5)) is None


def test_token_is_encrypted_and_never_backed_up(gh):
    backup.save_token("github_pat_SECRET123")
    assert backup.get_token() == "github_pat_SECRET123"
    with backup.session_scope() as s:
        stored = s.get(backup.AppSetting, "backup.token").value
    assert "SECRET123" not in stored
    _seed(n=1, sigs=0)
    backup.run_backup()
    assert not any(b"SECRET123" in v for v in gh.files_at_head().values())


def test_settings_validation(gh):
    backup.save_settings("https://github.com/me/rgfp-backups.git", True, 6)
    st = backup.load_settings()
    assert st.repo == "me/rgfp-backups" and st.hour == 6 and st.enabled
    with pytest.raises(ValueError):
        backup.save_settings("not-a-repo", True, 6)
