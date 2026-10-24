"""Headless smoke tests of each Streamlit page with streamlit.testing.AppTest."""
from pathlib import Path

from streamlit.testing.v1 import AppTest

from core import repo
from core.seed import fake_clients

ROOT = Path(__file__).resolve().parent.parent


def _page(name: str) -> AppTest:
    at = AppTest.from_file(str(ROOT / "app_pages" / name), default_timeout=30)
    return at


def _by_label(widgets, label_part):
    return next(w for w in widgets if label_part in str(w.label))


def test_new_client_save_flow():
    repo.delete_all()
    at = _page("new_client.py").run()
    assert not at.exception
    _by_label(at.text_input, "First name").input("Rosa")
    _by_label(at.text_input, "Last name").input("Lucero")
    _by_label(at.number_input, "Age").set_value(67)
    _by_label(at.number_input, "NOT including you").set_value(2)
    _by_label(at.number_input, "Seniors").set_value(1)
    _by_label(at.number_input, "Adults").set_value(0)
    _by_label(at.number_input, "Children").set_value(1)
    _by_label(at.text_input, "ZIP").input("87105")
    _by_label(at.text_input, "Phone").input("5055550142")
    at.run()
    _by_label(at.selectbox, "County").set_value("Bernalillo")
    at.checkbox(key="nc_paper").check()
    at.run()
    # radio pre-filled from age
    assert _by_label(at.radio, "Senior").value is True
    _by_label(at.button, "Save New Client").click().run()
    assert not at.exception, at.exception
    assert not at.error, [e.value for e in at.error]
    assert repo.stats()["clients"] == 1
    code = repo.search("Lucero").iloc[0]["member"]
    assert any(code in s.value for s in at.success)


def test_new_client_reports_missing_fields():
    at = _page("new_client.py").run()
    _by_label(at.button, "Save New Client").click().run()
    assert at.error and "Required" in at.error[0].value


def test_returning_client_scan_and_update():
    repo.delete_all()
    ids = repo.bulk_create(fake_clients(5, seed=9), "seed")
    at = _page("returning_client.py").run()
    assert not at.exception
    at.text_input[0].input(f"RGFP-{ids[2]:06d}")
    at.button[0].click().run()
    assert not at.exception, at.exception
    at.text_input(key="rc.1.simc_number").input("SIMC-777")
    at.run()
    _by_label(at.button, "Update Client").click().run()
    assert not at.exception, at.exception
    assert repo.get_client(ids[2]).simc_number == "SIMC-777"


def test_admin_seed():
    repo.delete_all()
    at = _page("admin.py").run()
    assert not at.exception
    at.slider[0].set_value(12)
    _by_label(at.button, "Generate").click().run()
    assert not at.exception, at.exception
    assert repo.stats()["clients"] == 12


# ------------------------------------------------------------- two steps --
def _step(at):
    return at.session_state["nc.step"] if "nc.step" in at.session_state else 1


def _fill_page1(at):
    _by_label(at.text_input, "First name").input("Rosa")
    _by_label(at.text_input, "Last name").input("Lucero")
    _by_label(at.number_input, "Age").set_value(67)
    _by_label(at.number_input, "NOT including you").set_value(1)
    _by_label(at.number_input, "Seniors").set_value(0)
    _by_label(at.number_input, "Adults").set_value(0)
    _by_label(at.number_input, "Children").set_value(1)
    return at.run()


def test_next_validates_page1_only():
    repo.delete_all()
    at = _page("new_client.py").run()
    at.button(key="nc.next").click().run()
    assert _step(at) == 1
    errs = " ".join(e.value for e in at.error)
    assert "Required on page 1" in errs and "First name" in errs
    assert "page 2" not in errs  # page-2 fields aren't complained about yet
    _fill_page1(at)
    at.button(key="nc.next").click().run()
    assert not at.exception and not at.error
    assert at.session_state["nc.step"] == 2
    at.button(key="nc.back").click().run()
    assert at.session_state["nc.step"] == 1
    assert _by_label(at.text_input, "First name").value == "Rosa"  # nothing lost


def test_next_warns_once_on_household_mismatch():
    at = _page("new_client.py").run()
    _fill_page1(at)
    _by_label(at.number_input, "Children").set_value(3)  # 0+0+3 != 1
    at.run()
    at.button(key="nc.next").click().run()
    assert at.warning and "add up" in " ".join(w.value for w in at.warning)
    assert _step(at) == 1
    at.button(key="nc.next").click().run()  # confirmed: go on
    assert at.session_state["nc.step"] == 2


def test_pickup_phone_error_is_caught_on_page1():
    # AppTest can't type into the data editor, so check the page-1 validator directly.
    from ui.client_form import validate_page1
    errors, _ = validate_page1({"first_name": "A", "last_name": "B", "age": 30, "household_others": 0,
                                "others_pickup": True,
                                "pickup_persons": [{"name": "Kim", "phone": "555"}]})
    assert errors and "Pick-up person #1 phone" in errors[0] and "page 1" in errors[0]


# ---------------------------------------------------------------- check-in --
def test_checkin_and_flag_on_returning_client():
    from core import visits
    repo.delete_all()
    cid = repo.bulk_create(fake_clients(1, seed=4), "seed")[0]
    visits.set_remaining(cid, 1)
    at = _page("returning_client.py").run()
    at.text_input[0].input(f"RGFP-{cid:06d}")
    at.button[0].click().run()
    at.button(key="rc_checkin").click().run()
    assert not at.exception, at.exception
    assert any("Checked in" in s.value for s in at.success)
    # second check-in today needs a confirming click, then is flagged (0 left)
    at.button(key="rc_checkin").click().run()
    assert any("already checked in today" in w.value for w in at.warning)
    at.button(key="rc_checkin").click().run()
    assert any("FLAGGED" in e.value for e in at.error)
    assert visits.status(cid).flagged_this_month == 1


def test_admin_set_visits():
    from core import visits
    repo.delete_all()
    cid = repo.bulk_create(fake_clients(1, seed=5), "seed")[0]
    at = _page("admin.py").run()
    at.text_input(key="adm_v_who").input(f"RGFP-{cid:06d}").run()
    at.number_input(key="adm_v_n").set_value(0)
    at.button(key="adm_v_set").click().run()
    assert not at.exception, at.exception
    assert visits.status(cid).remaining == 0


# ------------------------------------------------------------- all clients --
def test_all_clients_page_lists_and_filters():
    from core import visits
    repo.delete_all()
    ids = repo.bulk_create(fake_clients(25, seed=8), "seed")
    visits.set_remaining(ids[0], 0)
    visits.check_in(ids[0])
    at = _page("all_clients.py").run()
    assert not at.exception, at.exception
    assert len(at.dataframe[0].value) == 25
    at.selectbox(key="ac_visits").set_value("Flagged this month").run()
    assert list(at.dataframe[0].value["member"]) == [f"RGFP-{ids[0]:06d}"]
    at.selectbox(key="ac_visits").set_value("All")
    at.text_input(key="ac_text").input(f"rgfp-{ids[3]:06d}").run()
    assert len(at.dataframe[0].value) == 1


def test_all_clients_page_empty_db():
    repo.delete_all()
    at = _page("all_clients.py").run()
    assert not at.exception, at.exception
    assert any("No clients yet" in i.value for i in at.info)


def test_returning_client_opens_record_requested_by_browse_page():
    repo.delete_all()
    cid = repo.bulk_create(fake_clients(3, seed=1), "seed")[1]
    at = _page("returning_client.py")
    at.session_state["rc_open_request"] = cid
    at.run()
    assert not at.exception, at.exception
    assert at.session_state["rc_client_id"] == cid


def test_admin_backups_tab_renders_unconfigured():
    at = _page("admin.py").run()
    assert not at.exception, at.exception
    assert any(m.label == "Daily backups" and m.value == "Off" for m in at.metric)
