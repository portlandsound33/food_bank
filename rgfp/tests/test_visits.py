from datetime import datetime

import pytest

from core import repo, visits
from core.config import TZ
from core.seed import fake_clients


def _at(y, m, d, h=10):
    return datetime(y, m, d, h, tzinfo=TZ)


@pytest.fixture
def cid():
    repo.delete_all()
    return repo.bulk_create(fake_clients(1, seed=1), "seed", with_qr=False)[0]


def test_new_client_has_full_allowance(cid):
    st = visits.status(cid, now=_at(2026, 10, 5))
    assert st.remaining == 3 and st.used_this_month == 0 and not st.exhausted


def test_three_visits_then_flagged(cid):
    now = _at(2026, 10, 5)
    results = [visits.check_in(cid, now=now) for _ in range(5)]
    assert [r.remaining for r in results] == [2, 1, 0, 0, 0]
    assert [r.flagged for r in results] == [False, False, False, True, True]
    assert [r.visit_number for r in results] == [1, 2, 3, 4, 5]
    st = visits.status(cid, now=now)
    assert st.exhausted and st.used_this_month == 5 and st.flagged_this_month == 2
    assert len(visits.history(flagged_only=True, period="2026-10")) == 2


def test_refills_on_the_first_in_food_bank_time(cid):
    for _ in range(3):
        visits.check_in(cid, now=_at(2026, 10, 31, 20))
    # 11:30 PM Oct 31 in Albuquerque is already Nov 1 in UTC — still October here.
    late = datetime(2026, 10, 31, 23, 30, tzinfo=TZ)
    assert visits.status(cid, now=late).remaining == 0
    assert visits.status(cid, now=_at(2026, 11, 1, 0)).remaining == 3
    r = visits.check_in(cid, now=_at(2026, 11, 1, 9))
    assert not r.flagged and r.remaining == 2 and r.visit_number == 1


def test_admin_set_remaining_enables_flag_testing(cid):
    now = _at(2026, 10, 7)
    visits.set_remaining(cid, 0, now=now)
    assert visits.check_in(cid, now=now).flagged
    visits.set_remaining(cid, 2, now=now)
    r = visits.check_in(cid, now=now)
    assert not r.flagged and r.remaining == 1
    with pytest.raises(ValueError):
        visits.set_remaining(cid, -1)


def test_admin_override_from_last_month_does_not_carry_over(cid):
    visits.set_remaining(cid, 0, now=_at(2026, 9, 20))
    assert visits.status(cid, now=_at(2026, 10, 2)).remaining == 3


def test_reset_all(cid):
    now = _at(2026, 10, 7)
    for _ in range(3):
        visits.check_in(cid, now=now)
    assert visits.reset_all(now=now) == 1
    assert visits.status(cid, now=now).remaining == 3


def test_editing_the_form_does_not_touch_visits(cid):
    now = datetime.now(TZ)
    visits.check_in(cid, now=now)
    data = repo.to_client_in(repo.get_client(cid)).model_copy(update={"simc_number": "X1"})
    repo.update_client(cid, data)
    assert visits.status(cid, now=now).remaining == 2


def test_delete_all_removes_checkins(cid):
    visits.check_in(cid)
    repo.delete_all()
    assert visits.history().empty


def test_migrates_database_from_previous_release(tmp_path):
    import sqlite3

    from sqlalchemy import inspect

    from core.db import get_engine
    db = tmp_path / "old.db"
    con = sqlite3.connect(db)
    con.execute("create table clients (client_id integer primary key, first_name varchar(60) not null, "
                "last_name varchar(60) not null)")
    con.commit()
    con.close()
    insp = inspect(get_engine(f"sqlite:///{db}"))
    assert {"visits_remaining", "visits_period"} <= {c["name"] for c in insp.get_columns("clients")}
    assert "checkins" in insp.get_table_names()
