# Deploying to Render

The repo includes a **Blueprint** (`render.yaml`) that creates two things on Render in one go:

| Render resource | What it is |
|---|---|
| `rgfp-intake` | Web service running the Streamlit app |
| `rgfp-db` | Postgres database (holds every client record) |

The app reads the database address from `DATABASE_URL`, which the Blueprint wires up for
you. Locally, with no `DATABASE_URL`, it still uses the SQLite file in `data/`.

> **Why Postgres and not the SQLite file?** On Render, a free web service's disk is wiped
> on every redeploy, restart, and 15-minute idle spin-down. A SQLite file there would lose
> your clients.

---

## 1. Put the code on GitHub (private repository)

Render deploys from a Git repository.

1. On **github.com**, click **New repository**. Name it `rgfp-intake`, choose **Private**,
   and leave every "Initialize" box unticked. Click **Create repository**.
2. In PowerShell, go into the `rgfp` folder. This folder must be the root of the repo,
   because `render.yaml` has to sit at the top. Then run:

   ```powershell
   cd C:\Users\portl\Downloads\FoodBank\rgfp
   git init
   git add .
   git commit -m "RGFP intake app"
   git branch -M main
   git remote add origin https://github.com/<your-github-username>/rgfp-intake.git
   git push -u origin main
   ```

   `.gitignore` keeps your local database (`data/*.db`) out of GitHub.
   GitHub Desktop works too: **File → Add local repository →** pick the `rgfp` folder,
   then **Publish repository**, and keep "private" ticked.

## 2. Create the Blueprint on Render

1. Sign in at **dashboard.render.com**. Signing up with GitHub is easiest.
2. Click **New → Blueprint**.
3. Connect your GitHub account if asked. Give Render access to the `rgfp-intake` repo,
   then select it.
4. Render reads `render.yaml` and lists **rgfp-intake** (web service) and **rgfp-db**
   (Postgres). It asks for two values you choose yourself:
   - **RGFP_STAFF_PASSWORD**: the password volunteers type to use the app.
   - **RGFP_ADMIN_PASSWORD**: a second, different password for the Admin page.
5. Click **Deploy Blueprint** (or **Apply**).

The database comes up first, then the app builds. The first build takes a few minutes.
It's done when the `rgfp-intake` **Logs** tab shows `You can now view your Streamlit app`,
and the service shows **Live**.

## 3. First sign-in and smoke test

1. Open the URL at the top of the `rgfp-intake` page. It looks like
   `https://rgfp-intake.onrender.com`, plus a suffix if that name was taken.
2. Sign in with the staff password.
3. Go to **Admin**, enter the admin password, open **Test data**, and click **Generate**.
4. On **Returning Client**, search `garcia`, open a record, and download a card.
5. When you're satisfied, go to **Admin → Danger zone** and type `DELETE` to clear the test data.

## 4. Set up the tablet

1. In Render, open **rgfp-intake → Environment**. Reveal **RGFP_KIOSK_TOKEN** and copy it.
   The Blueprint generated it randomly.
2. On the tablet, open `https://<your-app-url>/?kiosk=<that token>`.
3. Bookmark the page, or use **Add to Home Screen**.

The tablet gets the New Client form only: no staff login, no lookup, no Admin. When a client
submits, the record appears under **Registered today** on the clerk's Returning Client screen.
To revoke a tablet, change the token value in **Environment** and save. Render redeploys
automatically, and the old link stops working.

## 5. Before real client data goes in: upgrade both plans

The Blueprint starts on Render's **free** plans so you can try it at no cost. They are not
suitable for real records:

- **Free Postgres expires 30 days after creation**, then gets deleted after a grace period.
  It has no backups.
  → Open **rgfp-db**, choose a paid instance type, and turn on backups.
- **The free web service sleeps after 15 minutes idle.** The next visitor waits about a
  minute while it wakes up.
  → Open **rgfp-intake → Settings → Instance Type** and pick a paid type.

Upgrading keeps the same URL and the same data. Check Render's pricing page for current costs.

## 6. Updating the app later

Commit and push to `main`, and Render redeploys automatically:

```powershell
git add .
git commit -m "Describe the change"
git push
```

## 7. Moving data you entered locally

On your PC, go to **Admin → Export → Download** to get a CSV. On Render, go to
**Admin → Import CSV** and upload it. The columns map automatically. The old record number
is kept as `legacy_id`, but **records get new member numbers**. If you've already printed
cards from a local copy, ask before importing; the importer can be changed to keep the
original numbers.

## Troubleshooting

| Symptom | Fix |
|---|---|
| Page says "Staff login isn't configured" | Set `RGFP_STAFF_PASSWORD` under **rgfp-intake → Environment**, then save. |
| "This tablet link isn't valid" | The token in the link doesn't match `RGFP_KIOSK_TOKEN`. Copy it again. |
| First load takes about a minute | You're on the free web service, which wakes from sleep. Upgrade (step 5). |
| Data disappeared after a deploy | `DATABASE_URL` is missing, so the app fell back to SQLite. Check **Environment**. |
| Build fails on a package | Check the **Logs** tab. Python is pinned to 3.13 by `.python-version`. |
| Times are off by an hour | `RGFP_TZ` should be `America/Denver`. Use `America/Phoenix` for fixed MST. |

## Settings reference (Environment variables)

| Variable | Set by | Purpose |
|---|---|---|
| `DATABASE_URL` | Blueprint (from `rgfp-db`) | Postgres connection |
| `RGFP_STAFF_PASSWORD` | You | Staff sign-in. The app refuses to run on Render without it. |
| `RGFP_ADMIN_PASSWORD` | You | Extra lock on Admin |
| `RGFP_KIOSK_TOKEN` | Blueprint (random) | Secret in the tablet link |
| `RGFP_TZ` | Blueprint | Clock time zone (`America/Denver`) |

The shared staff password is a reasonable start. If you later want individual logins
(who changed what), Streamlit supports Google or Microsoft sign-in through OIDC.
