# Rio Grande Food Project — Intake

Streamlit + SQLAlchemy 2.0 intake app (SQLite locally, Postgres on Render): two-page
new-client registration (RGFP form + NM TEFAP form), QR member cards, scan-to-edit for
returning clients, and an Admin area for test data and CSV import from other systems.

**Deploying to Render → see [DEPLOY_RENDER.md](DEPLOY_RENDER.md).**

```bash
pip install -r requirements.txt -r requirements-dev.txt
streamlit run app.py                 # staff:  http://<host>:8501
                                     # tablet: http://<host>:8501/?kiosk=1
python -m pytest -q                  # 53 tests incl. headless page tests
DATABASE_URL=postgresql://user@host/throwaway_db python -m pytest -q   # same tests on Postgres
```

Settings (env vars, see `core/config.py`): `DATABASE_URL` or `RGFP_DB_URL` (default
`sqlite:///data/rgfp.db`), `RGFP_TZ` (default `America/Denver`), `RGFP_STAFF_PASSWORD`,
`RGFP_ADMIN_PASSWORD`, `RGFP_KIOSK_TOKEN`, `RGFP_MEMBER_PREFIX`, `RGFP_MONTHLY_VISITS` (default 3). With no passwords set the
app is open (local development); on Render it refuses to run without a staff password.
Drop your logo at `assets/logo.png`.

## Layout

```
app.py                     navigation; ?kiosk=1 locks the session to the New Client page
core/                      no Streamlit imports — usable from scripts/tests
  schemas.py               ClientIn (pydantic): the one definition of a valid record
  db.py                    Client (flat `clients` table), engine/session, UTC datetimes
  repo.py                  create/update/search/lookup/duplicates/export/stats
  reference.py             states, NM counties, TEFAP 2026 income table
  qr.py                    QR PNG, CR80 card PNG (300 dpi), member-code parsing
  csv_import.py            auto column mapping + row transform/validation
  seed.py                  realistic fake clients
ui/                        theme/header clock, shared 2-page form, member badge
app_pages/                 new_client.py, returning_client.py, admin.py
samples/legacy_export_sample.csv   messy CSV to try the importer
```

## Key decisions

* **One schema, every entry point.** Form, editor, seeder and CSV importer all build a
  `ClientIn`. Its `before` validators accept messy input (`Y`/`yes`/`1`, `(505) 555 1212`,
  `New Mexico`, Excel-mangled ZIPs) and emit clean values; `warnings()` reports soft
  inconsistencies (age vs. senior answer, household counts that don't add up) without blocking.
* **Primary key = member number.** `client_id` (autoincrement) is shown as `RGFP-000123`,
  encoded in the QR, and stored as `qr_png` on the row. A USB/Bluetooth scanner acts as a
  keyboard: scan into the Returning Client box and Enter opens the record. Typing a name,
  phone fragment or SIMC # searches instead.
* **State/ZIP** is split into `state` (2-letter enum, all states + DC/PR) and `zip`.
  County is a string; for NM it's a pick-list of the 33 counties that still accepts typing.
* **Section 2** stores the *row* (`tefap_household_size`) and *column*
  (`tefap_income_period`) the client picked, plus `tefap_income_limit` — a snapshot of the
  dollar figure at signing, so records stay correct when limits change next year. Picking a
  separate value per column would be redundant: the row determines all three.
  Checking Section 1 hides and clears Section 2, as the paper form instructs.
* **Signature (Section 3)** is a photo (tablet camera) or uploaded image, stored as
  `signature_png`, with `signature_date`. Staff can save without one by ticking
  "Client signed a paper copy".
* **Pick-up people** are a list of `{name, phone}` stored as JSON in the flat row.
* **Clock** uses server time in `America/Denver` (MST in winter, MDT in summer, matching the
  wall clock). Set `RGFP_TZ=America/Phoenix` for fixed MST year-round.
* **Monthly visits:** each client has `visits_remaining` plus the month it belongs to
  (`visits_period`, e.g. `2026-10`). No scheduled job is needed: a count from an earlier month
  reads as the full allowance (`RGFP_MONTHLY_VISITS`, default 3), so it refills on the 1st in
  food-bank time. **Check in** on Returning Client uses one visit; with none left the check-in is
  still recorded but **flagged**. Every check-in is logged in a `checkins` table (`core/visits.py`).
  Admin → Visits sets a client's count (e.g. 0 to test flagging), lists flagged check-ins, and can
  reset everyone. Editing the form never changes the visit count.
* **Backups:** Admin → Backups writes a daily snapshot to a *private* GitHub repo as one commit
  (`core/backup.py`, Git Data API in `core/github.py`): `clients.jsonl`, `checkins.jsonl`,
  `signatures/<member>.png` (only new/changed ones are uploaded), `manifest.json`. A background thread
  checks every 5 minutes and catches up after the app sleeps. Restore loads any past backup into an
  empty database, keeping member numbers. The token is stored Fernet-encrypted with `RGFP_SECRET_KEY`
  and never written into backups. Tests use an in-memory fake GitHub (`tests/fake_github.py`).
* **All Clients** page (`app_pages/all_clients.py`): every record in a sortable table with search and
  filters (visits status, registration date, county); clicking a row opens it on Returning Client.
* **Schema upgrades:** new columns are added to an existing database automatically at startup
  (`core/db.py: _ADDED_COLUMNS`), so deploying a new version keeps all existing records.
* **Two-step form:** page 1 is validated (errors and household-count warnings) before **Next**
  moves to page 2; both pages stay rendered (the inactive one hidden) so nothing typed is lost
  when going back and forth.
* **Tablet flow:** the tablet opens `?kiosk=1` (no sidebar, no staff screens). The client
  submits; the record appears under *Registered today* on the clerk's Returning Client
  screen, where they review it and print the card.

## Admin

* **Test data:** generate 1–100 fake clients (`source = seed`).
* **Import CSV:** auto-maps columns by name/synonym/fuzzy match into an editable mapping
  table. Virtual targets split or derive values: `full_name` → first/M.I./last,
  `state_zip` → state + zip, `date_of_birth` → age, `pickup_name`/`pickup_phone`.
  Options: default area code for 7-digit phones, keep unmapped columns in notes, skip
  people already in the DB (first+last+phone), salvage rows by blanking a bad field (recorded
  in notes). Rejected rows download as CSV with an `_errors` column.
* **Export** (CSV without images) and **Delete all** (type DELETE).

## Next steps worth considering

* Real auth/roles before this holds live PII; HTTPS on the LAN.
* Live mirroring of the clerk's screen to the tablet (would need a shared drafts table).
* Postgres via `RGFP_DB_URL` if more than a few workstations write at once.
