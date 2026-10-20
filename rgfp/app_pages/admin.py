"""Admin: overview, test data, CSV import from other systems, export, reset."""
from __future__ import annotations

import hashlib
import hmac

import pandas as pd
import streamlit as st

from core import csv_import as ci
from core import repo, visits
from core.config import ADMIN_PASSWORD, MONTHLY_VISITS
from core.qr import parse_member_code
from core.seed import fake_clients
from ui.theme import header, now_local

ss = st.session_state
header("Admin")

# ------------------------------------------------------------------- gate --
if ADMIN_PASSWORD:
    if not ss.get("admin_ok"):
        with st.form("admin_login"):
            pw = st.text_input("Admin password", type="password")
            if st.form_submit_button("Unlock", type="primary"):
                if hmac.compare_digest(pw.encode(), ADMIN_PASSWORD.encode()):
                    ss["admin_ok"] = True
                    st.rerun()
                st.error("Wrong password.")
        st.stop()
else:
    st.warning("Admin is unlocked because `RGFP_ADMIN_PASSWORD` isn't set. Set it before going live.",
               icon="🔓")

t_over, t_visits, t_seed, t_csv, t_export, t_danger = st.tabs(
    ["📊 Overview", "🗓️ Visits", "🧪 Test data", "📥 Import CSV", "📤 Export", "⚠️ Danger zone"])

# --------------------------------------------------------------- overview --
with t_over:
    s = repo.stats()
    c1, c2, c3 = st.columns(3)
    c1.metric("Client records", f"{s['clients']:,}")
    c2.metric("People served (household totals)", f"{s['people']:,}")
    c3.metric("Auto-eligible (SNAP/WIC/FDPIR/CSFP)", f"{s['auto_eligible']:,}")
    if s["by_source"]:
        st.markdown("**Records by source**")
        st.bar_chart(pd.Series(s["by_source"], name="records"), horizontal=True)

# -------------------------------------------------------------- test data --
with t_seed:
    st.markdown("Add realistic **fake** clients (Albuquerque-area, consistent household counts) to try "
                "the app. They're tagged `source = seed` so you can tell them apart.")
    with st.form("seed"):
        n = st.slider("How many records?", 1, 100, 25)
        seed_val = st.number_input("Random seed (optional, for repeatable data)", value=None, step=1)
        if st.form_submit_button("Generate", type="primary"):
            bar = st.progress(0.0, "Generating…")
            ids = repo.bulk_create(fake_clients(n, seed=seed_val, today=now_local().date()), "seed",
                                   progress=lambda p: bar.progress(p, "Saving + QR codes…"))
            bar.empty()
            st.success(f"Added {len(ids)} records (#{ids[0]}–#{ids[-1]}).")

# ------------------------------------------------------------- csv import --
with t_csv:
    st.markdown(
        "Upload a CSV exported from another system. Columns are matched to our schema automatically — "
        "review the **Maps to** column, fix anything that's wrong, then validate and import.")
    st.download_button("Download blank template CSV", ci.template_csv(), "rgfp_template.csv", "text/csv")
    up = st.file_uploader("CSV file", type=["csv", "txt"], key="csv_up")
    if up is not None:
        raw = up.getvalue()
        fid = hashlib.sha1(raw).hexdigest()[:12]
        try:
            df = ci.read_csv(raw)
        except Exception as e:  # noqa: BLE001
            st.error(f"Couldn't read that file as CSV: {e}")
            st.stop()
        st.caption(f"**{len(df):,} rows**, {len(df.columns)} columns")
        st.dataframe(df.head(5), hide_index=True)

        # --- mapping editor
        if ss.get("csv_fid") != fid:
            ss["csv_fid"] = fid
            ss["csv_map_init"] = ci.suggest_mapping(list(df.columns))
            ss.pop("csv_results", None)
        init = ss["csv_map_init"]
        map_df = pd.DataFrame({
            "Source column": list(df.columns),
            "Sample": [next((v for v in df[c] if str(v).strip()), "") for c in df.columns],
            "Maps to": [init[c] for c in df.columns],
        })
        st.markdown("##### Column mapping")
        edited = st.data_editor(
            map_df, key=f"map_{fid}", hide_index=True, disabled=["Source column", "Sample"],
            column_config={"Maps to": st.column_config.SelectboxColumn(
                options=[ci.IGNORE, *ci.TARGETS], required=True, width="medium")},
        )
        mapping = dict(zip(edited["Source column"], edited["Maps to"]))
        targets = [t for t in mapping.values() if t != ci.IGNORE]
        dupes = sorted({t for t in targets if targets.count(t) > 1})
        has_name = ({"first_name", "last_name"} <= set(targets)) or "full_name" in targets
        with st.expander("What do the special targets do?"):
            st.markdown(
                "- **full_name** — splits “Garcia, Maria J” or “Maria J. Garcia” into first / M.I. / last\n"
                "- **state_zip** — splits “NM 87102” or “New Mexico, 87102”\n"
                "- **date_of_birth** — computes **age** as of the intake date\n"
                "- **pickup_name / pickup_phone** — one authorized pick-up person\n"
                "- Yes/No columns accept Y/N, Yes/No, 1/0, True/False, X; phones accept any 10-digit "
                "format; states accept codes or names; ZIPs repair Excel-dropped leading zeros.")
        if dupes:
            st.error(f"Each target can only be used once: {', '.join(dupes)}")
        if not has_name:
            st.error("Map **first_name + last_name**, or a **full_name** column.")

        c1, c2, c3 = st.columns(3)
        to_notes = c1.checkbox("Keep unmapped columns in notes", value=True)
        skip_dupes = c2.checkbox("Skip people already in the database", value=True,
                                 help="Same first + last name + phone.")
        with_qr = c3.checkbox("Generate QR codes now", value=True,
                              help="Otherwise each QR is created the first time the record is opened.")

        c4, c5, _ = st.columns(3)
        area = c4.text_input("Area code for 7-digit phones", value="505", max_chars=3).strip() or None
        salvage = c5.checkbox("Keep rows with a bad field (blank it, note it)", value=True,
                              help="Otherwise any invalid value rejects the whole row. Names are never blanked.")

        sig = (fid, tuple(sorted(mapping.items())), to_notes, area, salvage)
        if st.button("Validate", type="primary", disabled=bool(dupes) or not has_name):
            with st.spinner("Validating…"):
                ss["csv_results"] = (sig, ci.transform(df, mapping, unmapped_to_notes=to_notes,
                                                       today=now_local().date(),
                                                       default_area_code=area, salvage=salvage))
        if ss.get("csv_results") and ss["csv_results"][0] == sig:
            results = ss["csv_results"][1]
            good = [r for r in results if r.client]
            bad = [r for r in results if not r.client]
            if skip_dupes:
                keys = repo.existing_keys()
                seen: set = set()
                fresh = []
                for r in good:
                    key = (r.client.first_name.lower(), r.client.last_name.lower(), r.client.phone or "")
                    if key not in keys and key not in seen:
                        fresh.append(r)
                        seen.add(key)
                n_dup = len(good) - len(fresh)
                good = fresh
            else:
                n_dup = 0
            warn = [r for r in good if r.warnings]
            m1, m2, m3, m4 = st.columns(4)
            m1.metric("Ready to import", f"{len(good):,}")
            m2.metric("Rejected", f"{len(bad):,}")
            m3.metric("Already in DB / repeated", f"{n_dup:,}")
            m4.metric("Imported with warnings", f"{len(warn):,}")
            if good:
                st.markdown("**Preview of cleaned records**")
                st.dataframe(pd.DataFrame([r.client.model_dump(exclude={"pickup_persons"}) for r in good[:20]]),
                             hide_index=True)
            if bad:
                err_df = pd.DataFrame([{"row": r.row, "errors": "; ".join(r.errors)} for r in bad])
                with st.expander(f"{len(bad)} rejected rows", expanded=len(good) == 0):
                    st.dataframe(err_df, hide_index=True)
                    rej = df.iloc[[r.row - 1 for r in bad]].assign(_errors=err_df["errors"].values)
                    st.download_button("Download rejected rows (CSV)", rej.to_csv(index=False).encode(),
                                       f"rejected_{up.name}", "text/csv")
            if warn:
                with st.expander(f"{len(warn)} rows with warnings (will still import)"):
                    st.dataframe(pd.DataFrame([{"row": r.row, "warnings": " ".join(r.warnings)} for r in warn]),
                                 hide_index=True)
            if good and st.button(f"Import {len(good):,} records", type="primary"):
                bar = st.progress(0.0, "Importing…")
                ids = repo.bulk_create([r.client for r in good], f"csv:{up.name}"[:80], with_qr=with_qr,
                                       progress=lambda p: bar.progress(p, "Importing…"))
                bar.empty()
                ss.pop("csv_results", None)
                st.success(f"Imported {len(ids):,} records (#{ids[0]}–#{ids[-1]}).")
                st.balloons()

# ----------------------------------------------------------------- export --
with t_export:
    st.markdown("All client data (without signature/QR images) as CSV. Contains personal information — "
                "handle accordingly.")
    if st.button("Prepare export"):
        out = repo.export_df()
        st.download_button(f"Download {len(out):,} records", out.to_csv(index=False).encode(),
                           f"rgfp_clients_{now_local():%Y%m%d_%H%M}.csv", "text/csv", type="primary")

# ----------------------------------------------------------------- visits --
with t_visits:
    period = visits.period_of()
    st.markdown(f"Each client gets **{MONTHLY_VISITS} visits per month**. The count refills automatically "
                f"on the 1st (food-bank time). Current month: **{period}**.")

    st.markdown("##### Set a client's visits left this month")
    st.caption("Use this to test flagging (set 0, then check the client in on Returning Client), or to "
               "correct a mistaken check-in.")
    c1, c2, c3 = st.columns([2, 1, 1], vertical_alignment="bottom")
    who = c1.text_input("Member # (or scan the card)", key="adm_v_who", placeholder="RGFP-000123")
    cid = parse_member_code(who) if who else None
    target = repo.get_client(cid) if cid is not None else None
    if who and target is None:
        st.warning("No member with that number.")
    if target is not None:
        cur = visits.status(target.client_id)
        st.caption(f"**{target.full_name}** ({target.member_code}) — currently {cur.remaining} of "
                   f"{cur.allowance} left, {cur.used_this_month} check-in(s) this month.")
        n = c2.number_input("Visits left", 0, 31, value=0, step=1, key="adm_v_n")
        if c3.button("Set", type="primary", width="stretch", key="adm_v_set"):
            visits.set_remaining(target.client_id, int(n))
            st.success(f"{target.full_name} now has {int(n)} visit(s) left this month.")
            st.rerun()

    st.markdown("##### Flagged check-ins this month")
    flagged = visits.history(flagged_only=True, period=period, limit=500)
    if flagged.empty:
        st.caption("None so far.")
    else:
        st.dataframe(flagged.assign(when=flagged["checked_in_at"].dt.strftime("%Y-%m-%d %H:%M"))[
            ["when", "member", "first_name", "last_name", "visit_number"]], hide_index=True,
            column_config={"visit_number": "Visit # (month)"})
    with st.expander("All check-ins this month"):
        allc = visits.history(period=period, limit=2000)
        st.caption(f"{len(allc):,} check-ins")
        if not allc.empty:
            st.dataframe(allc.assign(when=allc["checked_in_at"].dt.strftime("%Y-%m-%d %H:%M"))[
                ["when", "member", "first_name", "last_name", "visit_number", "remaining_after", "flagged"]],
                hide_index=True)

    st.markdown("##### Reset everyone")
    st.caption(f"Gives every client {MONTHLY_VISITS} visits for {period} right now (the check-in history "
               "is kept). Normally unnecessary — the monthly refill is automatic.")
    if st.button(f"Reset all clients to {MONTHLY_VISITS}", key="adm_v_reset"):
        n = visits.reset_all()
        st.success(f"Reset {n:,} clients.")

# ------------------------------------------------------------ danger zone --
with t_danger:
    st.markdown("Permanently delete **every** client record. There is no undo — export first.")
    confirm = st.text_input("Type DELETE to confirm")
    if st.button("Delete all records", disabled=confirm != "DELETE"):
        n = repo.delete_all()
        st.success(f"Deleted {n:,} records.")
