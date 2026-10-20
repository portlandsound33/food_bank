"""Realistic fake clients for testing (no external deps)."""
from __future__ import annotations

import random
from datetime import date, timedelta

from .reference import NM_COUNTIES
from .schemas import ClientIn, PickupPerson

FIRST = ("Maria Jose Juan Ana Luis Carmen Miguel Rosa Antonio Elena David Sarah Michael Jennifer "
         "James Linda Robert Patricia Daniel Angela Joseph Lucia Carlos Teresa Thomas Grace Ray "
         "Dolores Isaiah Naomi Gabriel Esperanza Marcus Tanya Benjamin Leticia Samuel Irene Diego "
         "Monica Aiyana Hosteen Kai Nizhoni Ernesto Yolanda Frank Gloria").split()
LAST = ("Garcia Martinez Chavez Lucero Baca Romero Sanchez Gonzales Lopez Trujillo Montoya Sandoval "
        "Padilla Archuleta Vigil Gallegos Aragon Armijo Begay Yazzie Tsosie Benally Smith Johnson "
        "Williams Brown Jones Miller Davis Wilson Anderson Taylor Moore Jackson White Harris "
        "Martin Thompson Lee Nguyen Tafoya Maestas Otero Jaramillo Ortiz Apodaca Salazar").split()
ABQ_ZIPS = ["87102", "87104", "87105", "87106", "87107", "87108", "87109", "87110", "87111",
            "87112", "87114", "87120", "87121", "87122", "87123"]


def _phone(rng: random.Random) -> str:
    return f"505-{rng.randint(200, 999)}-{rng.randint(0, 9999):04d}"


def fake_client(rng: random.Random, today: date) -> ClientIn:
    age = rng.choices([rng.randint(18, 59), rng.randint(60, 92)], weights=[0.7, 0.3])[0]
    seniors = rng.choices([0, 1, 2], [0.7, 0.25, 0.05])[0]
    adults = rng.choices([0, 1, 2, 3], [0.35, 0.45, 0.15, 0.05])[0]
    kids = rng.choices([0, 1, 2, 3, 4, 5], [0.4, 0.2, 0.2, 0.1, 0.07, 0.03])[0]
    others = seniors + adults + kids
    pickup = rng.random() < 0.25
    auto = rng.random() < 0.55
    in_abq = rng.random() < 0.8
    intake = today - timedelta(days=rng.randint(0, 700))
    hh = others + 1
    return ClientIn(
        intake_date=intake,
        first_name=rng.choice(FIRST),
        middle_initial=rng.choice([None, *"ABCDEFGJLMRST"]),
        last_name=rng.choice(LAST),
        age=age,
        household_others=others,
        seniors_in_hh=seniors, adults_in_hh=adults, children_in_hh=kids,
        others_pickup=pickup,
        pickup_persons=[PickupPerson(name=f"{rng.choice(FIRST)} {rng.choice(LAST)}", phone=_phone(rng))]
        if pickup else [],
        simc_number=f"SIMC{rng.randint(100000, 999999)}" if rng.random() < 0.4 else None,
        state="NM",
        zip=rng.choice(ABQ_ZIPS) if in_abq else f"87{rng.randint(0, 599):03d}",
        county="Bernalillo" if in_abq else rng.choice(NM_COUNTIES),
        phone=_phone(rng),
        tefap_auto_eligible=auto,
        tefap_household_size=None if auto else hh,
        tefap_income_period=None if auto else rng.choice(["annual", "monthly", "weekly"]),
        tefap_income_at_or_below=None if auto else rng.random() < 0.95,
        signature_date=intake,
        notes="Seeded test record",
    )


def fake_clients(n: int, seed: int | None = None, today: date | None = None) -> list[ClientIn]:
    rng = random.Random(seed)
    today = today or date.today()
    return [fake_client(rng, today) for _ in range(n)]
