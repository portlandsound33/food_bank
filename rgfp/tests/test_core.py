from datetime import date

import pandas as pd
import pytest
from pydantic import ValidationError

from core import csv_import as ci
from core import repo
from core.qr import parse_member_code
from core.reference import tefap_limit
from core.schemas import ClientIn
from core.seed import fake_clients


def test_coercion_and_derivation():
    c = ClientIn(first_name=" MARIA ", last_name="garcia", middle_initial="j.", age="64",
                 phone="1 (505) 555-1212", state="new mexico", zip="8710",
                 seniors_in_hh=1, adults_in_hh=0, children_in_hh=2,
                 tefap_household_size="4", tefap_income_period="Monthly", others_pickup="N",
                 pickup_persons=[{"name": "x"}])
    assert (c.first_name, c.last_name, c.middle_initial) == ("Maria", "Garcia", "J")
    assert c.phone == "505-555-1212" and c.state == "NM" and c.zip == "08710"
    assert c.is_senior is True and c.is_18_59 is False
    assert c.household_others == 3 and c.household_size == 4
    assert c.tefap_income_limit == 5_088
    assert c.pickup_persons == []  # "No" clears pick-up list


def test_auto_eligible_skips_section2():
    c = ClientIn(first_name="A", last_name="B", tefap_auto_eligible="yes",
                 tefap_household_size=3, tefap_income_period="weekly", tefap_income_at_or_below=True)
    assert c.tefap_household_size is None and c.tefap_income_limit is None and c.tefap_eligible


@pytest.mark.parametrize("field,value", [("phone", "555-12"), ("zip", "ABCDE"), ("state", "Narnia"),
                                         ("age", "200"), ("is_senior", "maybe")])
def test_rejects_bad_values(field, value):
    with pytest.raises(ValidationError):
        ClientIn(first_name="A", last_name="B", **{field: value})


def test_warnings():
    c = ClientIn(first_name="A", last_name="B", age=30, is_senior=True, household_others=4,
                 seniors_in_hh=1, adults_in_hh=1, children_in_hh=1)
    w = " ".join(c.warnings())
    assert "Senior" in w and "= 3" in w


def test_tefap_limits():
    assert tefap_limit(1, "annual") == 29_526
    assert tefap_limit(8, "weekly") == 1_983
    assert tefap_limit(10, "monthly") == 8_591 + 2 * 876


def test_member_code_parse():
    assert parse_member_code("RGFP-000123") == 123
    assert parse_member_code(" rgfp42 ") == 42
    assert parse_member_code("77") == 77
    assert parse_member_code("garcia") is None


def test_repo_roundtrip_and_search():
    repo.delete_all()
    ids = repo.bulk_create(fake_clients(30, seed=3), "seed")
    assert len(ids) == 30
    c = repo.get_client(ids[0])
    assert c.qr_png.startswith(b"\x89PNG")
    data = repo.to_client_in(c)
    data2 = data.model_copy(update={"first_name": "Zelda", "simc_number": "SIMC-XYZ"})
    repo.update_client(c.client_id, data2)
    assert repo.get_client(c.client_id).first_name == "Zelda"
    assert repo.search("zelda").iloc[0]["client_id"] == c.client_id
    assert repo.search("SIMC-XYZ").iloc[0]["client_id"] == c.client_id
    assert repo.lookup(c.member_code).client_id == c.client_id
    assert not repo.possible_duplicates(data2).empty
    assert repo.stats()["clients"] == 30
    assert "member_code" in repo.export_df().columns


def test_csv_mapping_and_transform():
    df = pd.DataFrame({
        "Client Name": ["Garcia, Maria J", "Juan Lopez", ""],
        "DOB": ["3/4/1960", "1990-01-01", ""],
        "Phone #": ["5055551212", "555-1234", ""],
        "St/Zip": ["NM 87102", "New Mexico 87105", ""],
        "SNAP?": ["Y", "N", ""],
        "Household ID": ["A1", "A2", "A3"],
        "Fav color": ["red", "", ""],
    })
    m = ci.suggest_mapping(list(df.columns))
    assert m["Client Name"] == "full_name" and m["DOB"] == "date_of_birth"
    assert m["St/Zip"] == "state_zip" and m["Household ID"] == "legacy_id"
    assert m["Fav color"] == ci.IGNORE
    rs = ci.transform(df, m, unmapped_to_notes=True, today=date(2026, 10, 19))
    a, b, c = rs
    assert (a.client.first_name, a.client.middle_initial, a.client.last_name) == ("Maria", "J", "Garcia")
    assert a.client.age == 66 and a.client.zip == "87102" and "Fav color: red" in a.client.notes
    assert b.client.phone == "505-555-1234"  # default area code
    assert c.client is None  # no name -> rejected


def test_csv_first_last_beats_name():
    m = ci.suggest_mapping(["First Name", "Last Name", "Name", "Zip"])
    assert m["Name"] == ci.IGNORE and m["First Name"] == "first_name" and m["Zip"] == "zip"
