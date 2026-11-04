# Putting the Operations Center on Posit Connect Cloud

Do these in order. Steps 1-4 are on your PC (Git Bash, in `Gith_repositories`), 5-6 on GitHub and Posit Connect Cloud.

## 0. What you need to decide first

* **Plan / memory.** Measured on the real data (41,735 records, 164 columns): the builder peaks at about **2.7 GB**
  (it was 3.6 GB before the memory work in `add_coadmin_columns.py`: each source row is released as the output sheet is
  filled, and the workbook is freed once it is saved). Inspect peaks at 0.5 GB, Check and Back up are light. The Free plan
  of Posit Connect Cloud (4 GB, 1 CPU) therefore runs the **whole cycle**: tested end to end, 9 minutes, no restart. The default guard
  asks for 5 GB of free memory before a build, which a 4 GB server never has: on the Free plan set `OPS_MIN_BUILD_GB` to
  **3.3** (idle free memory is about 3.8 GB). If the server ever runs out of memory the worker restarts and the
  SharePoint lock stays until it expires (90 minutes) or an operator clicks **Release the lock** in the Overview.
  Credits per hour are CPU x 0.75 + GB x 0.25 (about 1.75 for 1 CPU and 4 GB): check Account Usage on connect.posit.cloud.
  Posit's Free-plan credit limits are enforced from the first usage period that starts on or after 1 November 2026.
  **Pinned versions:** `requirements.txt` pins `pandas==2.2.3` and `openpyxl==3.1.5`, the versions the engine is tested with
  on the PC (the memory change uses an openpyxl internal). With them the app's build and the PC's build were compared on
  the same live file (version 13): every cell identical.
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
The folder will hold the newest 3 backups (about 80 MB with files of 27 MB) plus the big files of the newest builds (about 30 MB each; older builds are cleaned up automatically, see "Storage" below). The app registration that publishes your files
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
| `OPS_MIN_BUILD_GB` | free memory needed to start a build. Default 5 (right for 8 GB or more); **3.3 on the Free plan (4 GB)**, tested |
| `GPEI_API_TOKEN` | the same token as `GPEI_API_TOKEN` in the scope folder's `config/secrets.env` (poliogo.afro.who.int/dashboard/api/apitoken). With it, the lookup is refreshed from the GPEI API at the start of every build and inspect; without it the app uses the lookup that is in the folder and says so in the job log |
| `OPS_KEEP_BACKUPS` (optional) | backups of the live file kept on SharePoint, default 3 |
| `OPS_KEEP_RUNS`, `OPS_KEEP_RESULTS`, `OPS_SWEEP_HOURS` (optional) | builds that keep their big files (2), inspect/compare results kept (3), hours between full version sweeps (24) |

After the first deployment open the content settings and set the compute memory (8 GB or more to build) and, if your
plan allows, who may view the app. Then publish again if asked.

## 7. First use (do this once, on a quiet day)

1. Sign in; the Overview must show the live file, the dictionary, the last published version and the backups.
2. Cycle > **Back up now**: expect "unchanged" (the seed already holds the newest file).
3. Quality & compare > **Inspect** the live file. Its log starts with the lookup refresh: it must say "Lookup is up to date" or "refreshed from the GPEI API" with the number of rounds (475 at the time of writing); if it says NOT refreshed, check `GPEI_API_TOKEN`. It then prints the hygiene checks and the lookup agreement.
4. Run a full cycle from the app **and** `python admin.py build` on the PC from the same live file, then
   `python admin.py compare <PC build> <the app's build file, downloaded from Files>`: the two builds must agree.
   (Done once, on live version 13: identical.)
   **Publish rewrites the live file whenever its content differs from the build**, and it does so even when the data are the
   same: a file that somebody re-saved in Excel has different internals from the one Python writes. The publish step skips the upload only
   when the file on SharePoint already holds the same sheet content. So after someone saves in Excel, the next cycle replaces
   the file with the pipeline's version (same data, a different size) and deletes the old versions of the live file; tell the team
   so nobody is surprised by a "modified by another user" message.

## Storage on SharePoint

What the app keeps on SharePoint, and what it cleans up by itself at the end of every job (nothing needs to be done by hand; Publish
ends with a full clean-up of the whole folder, and every other job does the same at most once a day):

| What | Kept | Variable |
|---|---|---|
| Backups of the live file | newest 3 | `OPS_KEEP_BACKUPS` |
| Earlier live dictionaries | newest 3 | `OPS_KEEP_DICT_COPIES` |
| Builds (`runs/vNN`) | the big files (above 250 KB) of the newest 2 builds and of the last published one; older builds keep only their manifest, logs, check report and small dictionary | `OPS_KEEP_RUNS`, `OPS_RUN_BIG_KB` |
| Inspect and compare results | newest 3 of each | `OPS_KEEP_RESULTS` |
| Version history of every file in the folder | none: a file the app rewrites is replaced (new copy uploaded, old one deleted for good, new one renamed), so no version is created and nothing reaches the recycle bin. History that already exists is removed by a sweep of the whole folder once a day (`OPS_SWEEP_HOURS`, default 24): small files (up to 5 MB) are replaced the same way, bigger ones have their old versions deleted | |
| Recycle bin | deleted files are removed for good (permanent delete); the few versions that still have to be deleted (files above 5 MB, or if SharePoint refuses the permanent delete for the app) pass through the site recycle bin and are emptied from it at the end of the job | |

The PC keeps everything (`SharePoint_version_backup` and `Admin_data_coadministration/workspace/runs`), so nothing is lost for good.
The Overview shows the size of the folder and the result of the last full clean-up. The live data file and dictionary are handled by the
publish step (it deletes their version history and empties the deleted copies from the recycle bin). If SharePoint refuses the permanent delete or the emptying of the
recycle bin for this app, the job log says so; then empty it by hand once in a while
(Site contents > Recycle bin > Second-stage), or ask IT.

## Day to day

* **The lookup refreshes itself.** `lookup.xlsx` changes all the time, so every build and every inspect first reads the campaign rounds
  from the GPEI API (the same data and checks as the scope pipeline, `prepare_the_AFRO_SIA_Dashboard_input.py`) and, when the rounds changed,
  saves the new lookup in the SharePoint folder. The run's manifest records which lookup was used. If the API cannot be read, the build still
  runs with the lookup in the folder and the log says "NOT refreshed". Check does not refresh: it tells you if the lookup changed since the build.
  On the PC: `python admin.py lookup` (add `--dry-run` to only look), and `build` / `inspect` do it first as well.

* The cycle is the same as on the PC: Back up > Build > Check > Store values > Publish, or **Run the whole cycle**.
  A failed job leaves the live data untouched and says why in the job log.
* **A job crashed or the app restarted** and the Overview still says Busy: an operator can click **Release the lock** (the confirmation shows who locked it and since when;
  use it only when that job is really gone, not when someone is running a job from their PC).
* The PC and the app each keep their own backups. Use one of them as the place where you build; if you build on both,
  publishing stops by itself when the live file changed after the build started, so nothing is overwritten.
  Run `tools/seed_store.py` again to bring PC backups and runs into the app's folder.
* A fix to the rules is made in `Admin_data_coadministration`, tested there, committed, then
  `python tools/sync_engine.py` here and commit; Posit redeploys from GitHub.
* Passwords: change a key by making a new `OPS_USERS` entry. To remove someone, delete their entry.

## What was and was not tested

Tested against the real SharePoint folder, on the PC (the app run locally) **and on Posit Connect Cloud, Free plan**: backup,
lookup refresh from the GPEI API, inspect, build, check, store values, publish (the live file was replaced by an identical-data build),
the dictionary (unchanged, not pushed), the storage clean-up (older backups, old builds, versions; permanent delete), the lock.
The app's build and a PC build from the same live file are identical.

Not tested: the Release the lock button against a real crashed job; several operators working at the same time; a build
on a plan with a different memory size (the guard and the variable cover it).
