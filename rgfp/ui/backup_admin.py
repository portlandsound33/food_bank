"""Admin → Backups: set up daily GitHub backups, run one now, see history, restore."""
from __future__ import annotations

import os
from datetime import datetime

import pandas as pd
import streamlit as st

from core import backup
from core.config import TZ
from core.github import GitHubError
from ui.theme import fmt_date, fmt_time, now_local


def _hour_label(h: int) -> str:
    return f"{h % 12 or 12}:00 {'AM' if h < 12 else 'PM'}"


def _when(dt: datetime | None) -> str:
    if dt is None:
        return "never"
    d = dt.astimezone(TZ)
    return f"{fmt_date(d, weekday=True)} {fmt_time(d)}"


SETUP_HELP = """
**1. Make a private repository for the backups** (not the app's code repository — that one is public).
On github.com: **New repository** → name it e.g. `rgfp-backups` → choose **Private** →
tick **Add a README file** → **Create repository**.

**2. Make a token that can only write to that repository.**
GitHub → your picture → **Settings → Developer settings → Personal access tokens →
Fine-grained tokens → Generate new token**:
- *Token name*: `RGFP backups` · *Expiration*: up to 1 year (put a renewal reminder in your calendar)
- *Repository access*: **Only select repositories** → pick `rgfp-backups`
- *Permissions → Repository permissions → **Contents**: Read and write* (nothing else)
- **Generate token** and copy it (it's shown once).

**3. Fill in the form below**, press **Save**, then **Test connection** and **Back up now**.
"""


def render() -> None:
    st_ = backup.load_settings()
    env_token = bool(os.environ.get("RGFP_GITHUB_TOKEN"))
    now = now_local()

    # ------------------------------------------------------------ status --
    configured = bool(st_.repo and st_.token_set)
    c1, c2, c3 = st.columns(3)
    c1.metric("Daily backups", "On" if (st_.enabled and configured) else "Off")
    c2.metric("Last successful backup", _when(st_.last_success))
    c3.metric("Next backup", _when(backup.next_run_time(st_, now)) if (st_.enabled and configured) else "—")
    if st_.repo:
        st.caption(f"Repository: [github.com/{st_.repo}](https://github.com/{st_.repo}) · default branch")
    st.caption("While the app is asleep (free Render plan, no visitors) nothing runs — a missed backup "
               "runs as soon as anyone opens the app. Data only changes while the app is in use, so no "
               "changes are missed.")

    with st.expander("How to set up backups (one time, ~5 minutes)", expanded=not configured):
        st.markdown(SETUP_HELP)

    # -------------------------------------------------------------- form --
    if not backup.can_store_token() and not env_token:
        st.error("The server has no **RGFP_SECRET_KEY**, which is used to store the token encrypted. "
                 "In Render, open the FoodBank Blueprint and press **Manual sync** (the latest "
                 "render.yaml creates it), or add `RGFP_SECRET_KEY` with any long random value under "
                 "rgfp-intake → Environment.")
    with st.form("backup_settings"):
        repo_in = st.text_input("Backup repository (owner/name)", value=st_.repo or "",
                                placeholder="portlandsound33/rgfp-backups")
        if env_token:
            st.info("The token comes from the server setting RGFP_GITHUB_TOKEN.")
            token_in = ""
        else:
            token_in = st.text_input(
                "GitHub token", type="password",
                placeholder="•••••••• saved — leave blank to keep" if st_.token_set else "github_pat_…",
                help="Fine-grained token with Contents: Read and write on the backup repository only. "
                     "Stored encrypted; never written into backups.")
        c1, c2 = st.columns(2)
        hour = c1.selectbox("Back up every day at", list(range(24)), index=st_.hour, format_func=_hour_label,
                            help=f"Food-bank time ({now.tzname()}). Pick a time after distribution ends.")
        enabled = c2.toggle("Daily backups on", value=st_.enabled)
        if st.form_submit_button("💾 Save", type="primary"):
            try:
                backup.save_settings(repo_in, enabled, hour)
                if token_in.strip():
                    backup.save_token(token_in)
                st.success("Saved." + (" The first backup runs within a few minutes." if enabled else ""))
                st.rerun()
            except (ValueError, RuntimeError) as e:
                st.error(str(e))

    # ----------------------------------------------------------- actions --
    a1, a2, _ = st.columns([1, 1, 2])
    test = a1.button("🔌 Test connection", disabled=not configured, width="stretch")
    now_btn = a2.button("⬆️ Back up now", disabled=not configured or backup.is_running(), width="stretch")
    if test:
        try:
            gh = backup.make_client()
            info = gh.repo()
            head = gh.branch_head(info.default_branch)
            if not info.private:
                st.error(f"**{info.full_name} is public.** Make it private (Settings → General → Danger Zone → "
                         "Change visibility) — backups contain personal information and won't be written "
                         "to a public repository.")
            else:
                st.success(f"Connected to **{info.full_name}** (private, branch `{info.default_branch}`"
                           + (", empty — will be initialized" if head is None else "") + ").")
        except (GitHubError, RuntimeError, ValueError) as e:
            st.error(f"Couldn't connect: {e}")
    if now_btn:
        with st.status("Backing up…", expanded=True) as box:
            res = backup.run_backup("manual", progress=box.write)
            if res.ok:
                box.update(label=res.message, state="complete")
                if res.commit_url:
                    st.markdown(f"[View this backup on GitHub]({res.commit_url})")
            else:
                box.update(label="Backup failed", state="error")
                st.error(res.message)

    # ----------------------------------------------------------- history --
    runs = backup.recent_runs(15)
    st.markdown("##### Recent backups")
    if not runs:
        st.caption("None yet.")
    else:
        st.dataframe(pd.DataFrame([{
            "when": _when(r.started_at), "how": r.trigger,
            "result": "✅" if r.ok else ("⏳" if r.ok is None else "❌"),
            "details": r.message, "link": r.commit_url,
        } for r in runs]), hide_index=True,
            column_config={"link": st.column_config.LinkColumn("commit", display_text="open")})

    # ----------------------------------------------------------- restore --
    with st.expander("Restore from a backup"):
        st.markdown(
            "Loads a backup into an **empty** database — for example after moving to a new Render database. "
            "Member numbers, check-ins and signatures are restored exactly; QR codes are regenerated.")
        if not configured:
            st.caption("Set up the repository and token above first.")
            return
        if not backup.database_is_empty():
            st.info("The database isn't empty, so restore is disabled. (To replace everything: export first, "
                    "then Danger zone → delete all, then come back here.)")
            return
        if st.button("Find backups"):
            try:
                st.session_state["restore_points"] = backup.restore_points(30)
            except (GitHubError, RuntimeError) as e:
                st.error(str(e))
        points = st.session_state.get("restore_points")
        if points == []:
            st.warning("No backups found in that repository.")
        if points:
            choice = st.selectbox("Backup to restore", points,
                                  format_func=lambda p: f"{p['message']}  ({p['sha'][:7]})")
            ok = st.text_input("Type RESTORE to confirm")
            if st.button("Restore", type="primary", disabled=ok != "RESTORE"):
                with st.status("Restoring…", expanded=True) as box:
                    try:
                        out = backup.restore(choice["sha"], progress=box.write)
                        box.update(label=f"Restored {out['clients']:,} clients, {out['checkins']:,} check-ins "
                                         f"and {out['signatures']:,} signatures.", state="complete")
                        st.session_state.pop("restore_points", None)
                    except (GitHubError, RuntimeError) as e:
                        box.update(label="Restore failed", state="error")
                        st.error(str(e))
