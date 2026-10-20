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
