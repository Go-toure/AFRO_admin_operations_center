# Putting the Operations Center on Posit Connect Cloud

Do these in order. Steps 1-4 are on your PC (Git Bash, in `Gith_repositories`), 5-6 on GitHub and Posit Connect Cloud.

## 0. What you need to decide first

* **Plan / memory.** A build peaks near 4 GB. Posit's published plan table (beta announcement) listed Free 4 GB, Basic 8 GB,
  Enhanced 16 GB per app; check the current numbers on connect.posit.cloud/plans before you subscribe. Use a plan with
  **8 GB or more** if you want to build from the app; on a smaller plan the app still works for everything else and
  refuses a build with a clear message (build on the PC with `python admin.py build` instead).
* **The repository is public** (a free Posit Connect Cloud account can only deploy a public GitHub repository).
  It is safe to be public because it contains **no data, no secret, no SharePoint link and no personal path**: the links
  and the credentials come from the Variables of step 6, and the engine in `engine/` has its links blanked
  (`python tools/sync_engine.py --strip-links`, always use this flag for this repository). Before every push run
  `python tools/sync_engine.py --check-public`: it scans the whole repository and stops you if a SharePoint address, a personal
  path or a secret is found. What stays visible is the logic of the checks and the file names. If you later move to a paid
  plan you can make the repository private on GitHub (Settings > General > Danger Zone) without changing anything else.
* **Who can open the app.** The app has its own login (named users with a key). On top of that, restrict who can open it
  in Posit's content settings if your plan offers private sharing.

## 1. A folder on SharePoint for the app (the "store")

Create an empty folder next to the data, for example `GISWORKSPACE / AdminOps`. Open the folder, **Copy link**, keep it.
The folder will hold the newest 3 backups (about 80 MB with files of 27 MB) plus about 30 MB per run. The app registration that publishes your files
(the same `SHAREPOINT_*` values as in `SharePoint_version_backup/config/secrets.env`) must be able to write in that
folder; it can if it can already replace `AFRO_admin_data.xlsx`, which lives in the same site.

## 2. Get the three links

From `Admin_data_coadministration` on the PC:

```
cd ~/Documents/Gith_repositories/Admin_data_coadministration
python -c "import publish_admin_data as p; print(p.ADMIN_SHARE_URL); print(p.DICT_SHARE_URL)"
```

## 3. Fill the store from the PC (once)

```
cd ~/Documents/Gith_repositories/AFRO_admin_operations_center
pip install -r requirements.txt
python tools/sync_engine.py --strip-links       # public repository: always with --strip-links
python tools/seed_store.py --store-url "<link of the AdminOps folder>" --dry-run
python tools/seed_store.py --store-url "<link of the AdminOps folder>"
```

It copies the lookup, the geo reference and the district source, the newest 3 backups of the live file (`--keep-backups N` to change; they are the reference of
the repairs), the runs (the big files only of the last published build) and the state.
It can be run again; files already there are skipped. It reads the SharePoint credentials from
`SharePoint_version_backup/config/secrets.env` and never prints them.

## 4. Make the users

```
python tools/make_user.py gorgui "Full Name" operator
python tools/make_user.py ahmed "Full Name" viewer
```

You type the key (at least 10 characters, not shown). Each command prints one JSON object. Join them into one:
`{"gorgui": {...}, "ahmed": {...}}`. This is the value of `OPS_USERS`.

## 5. GitHub

Check first: `python tools/sync_engine.py --check-public` must say nothing was found.

Create an empty repository `AFRO_admin_operations_center` on GitHub, then:

```
cd ~/Documents/Gith_repositories/AFRO_admin_operations_center
git init -b main
git add .
git commit -m "Administrative Data Operations Center: Shiny app on the admin data engine"
git remote add origin https://github.com/Go-toure/AFRO_admin_operations_center.git
git push -u origin main
```

## 6. Posit Connect Cloud

Sign in at connect.posit.cloud, **Publish**, choose **Shiny**, pick the repository and the branch `main`, primary file
`app.py`. In the advanced settings add these **Variables** (they are stored as secrets; menu names may differ slightly):

| Variable | Value |
|---|---|
| `SHAREPOINT_TENANT_ID`, `SHAREPOINT_CLIENT_ID`, `SHAREPOINT_CLIENT_SECRET` | the same three values as in the backup tool's `secrets.env` |
| `OPS_STORE_SHARE_URL` | link of the AdminOps folder (step 1) |
| `OPS_ADMIN_SHARE_URL` | link of `AFRO_admin_data.xlsx` (step 2) |
| `OPS_DICT_SHARE_URL` | link of `AFRO_admin_data_dictionary.xlsx` (step 2) |
| `OPS_USERS` | the JSON of step 4 |
| `OPS_MIN_BUILD_GB` (optional) | free memory needed to start a build, default 5 |
| `GPEI_API_TOKEN` | the same token as `GPEI_API_TOKEN` in the scope folder's `config/secrets.env` (poliogo.afro.who.int/dashboard/api/apitoken). With it, the lookup is refreshed from the GPEI API at the start of every build and inspect; without it the app uses the lookup that is in the folder and says so in the job log |
| `OPS_KEEP_BACKUPS` (optional) | backups of the live file kept on SharePoint, default 3 |

After the first deployment open the content settings and set the compute memory (8 GB or more to build) and, if your
plan allows, who may view the app. Then publish again if asked.

## 7. First use (do this once, on a quiet day)

1. Sign in; the Overview must show the live file, the dictionary, the last published version and the backups.
2. Cycle > **Back up now**: expect "unchanged" (the seed already holds the newest file).
3. Cycle > **Refresh the lookup**: the log must say "Lookup is up to date" or "refreshed from the GPEI API" with the number of rounds (474 at the time of writing). If it says NOT refreshed, check `GPEI_API_TOKEN`.
4. Quality & compare > **Inspect** the live file: it prints the hygiene checks and the lookup agreement.
5. Run a full cycle from the app **and** `python admin.py build` on the PC from the same live file, then
   `python admin.py compare v25 <the app's build>`: the two builds must agree (download the app's file from Files).
   Publish from the app only after that.

## Day to day

* **The lookup refreshes itself.** `lookup.xlsx` changes all the time, so every build and every inspect first reads the campaign rounds
  from the GPEI API (the same data and checks as the scope pipeline, `prepare_the_AFRO_SIA_Dashboard_input.py`) and, when the rounds changed,
  saves the new lookup in the SharePoint folder. The run's manifest records which lookup was used. If the API cannot be read, the build still
  runs with the lookup in the folder and the log says "NOT refreshed". Check does not refresh: it tells you if the lookup changed since the build.
  On the PC: `python admin.py lookup` (add `--dry-run` to only look), and `build` / `inspect` do it first as well.

* The cycle is the same as on the PC: Back up > Build > Check > Store values > Publish, or **Run the whole cycle**.
  A failed job leaves the live data untouched and says why in the job log.
* The PC and the app each keep their own backups. Use one of them as the place where you build; if you build on both,
  publishing stops by itself when the live file changed after the build started, so nothing is overwritten.
  Run `tools/seed_store.py` again to bring PC backups and runs into the app's folder.
* A fix to the rules is made in `Admin_data_coadministration`, tested there, committed, then
  `python tools/sync_engine.py` here and commit; Posit redeploys from GitHub.
* Passwords: change a key by making a new `OPS_USERS` entry. To remove someone, delete their entry.

## What was and was not tested

Tested here, against a simulated SharePoint with the real engine: the seed, every pipeline step, publishing of the data
and the dictionary, the lock, the memory guard, the interface (login, all tabs, search, a job with live log).
**Not yet tested against your real SharePoint folder or Posit Connect Cloud**; steps 7.1 to 7.4 are that test.
