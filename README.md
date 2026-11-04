# Administrative Data Operations Center

WHO AFRO GIS Centre. A web app (Shiny for Python, deployed from GitHub to Posit Connect Cloud) that runs the whole
AFRO administrative (SIA) data cycle that `admin.py` runs on the PC: back up the live SharePoint file, build the next
version, check it, store the `check_dp` values, publish the data **and the data dictionary** to SharePoint, and look
into any version (find, compare, inspect), with feedback files per country.

It runs the **same engine** as the PC (`admin.py`, `add_coadmin_columns.py`, `publish_admin_data.py`, the backup tool),
copied into `engine/`. A fix made in `Admin_data_coadministration` reaches the app with `python tools/sync_engine.py`.

```
 browser ──► Shiny app (app.py) ──► job runner ──► engine/admin.py (subprocess, one job at a time)
                │                        │                    │
                │                        ▼                    ▼
                │          SharePoint folder "AdminOps"   SharePoint (live data file + dictionary, Microsoft Graph)
                │          (runs, backups, inputs, state, lock, activity)
                └── users: named keys, operators or viewers
```

The server disk is not permanent, so **everything important lives in a SharePoint folder** (the *store*): the backups of
the live file, every run (manifest, build, dictionary, audit, quality report, feedback workbook, logs), the input files
(lookup, geo reference, district source), the last published state, a lock (one job at a time) and the activity log.
A job copies what the engine needs from the folder, runs the engine, and saves every new or changed file back.

## Tabs

| Tab | What it does | Who |
|---|---|---|
| Overview | live data file and dictionary on SharePoint, last published version, builds, backups, what is next | everybody |
| Cycle | back up, build, check, store values, publish (data + dictionary, ending with the SharePoint clean-up), the whole cycle | operators (backup: everybody) |
| Explore | find records in the live file, any build or any backup; download the result | everybody |
| Quality & compare | inspect a version (quality checks, hygiene, lookup); find duplicates (which record a fix would keep or remove); compare two versions | everybody |
| Files & feedback | download any file of a build; the feedback workbook reduced to one country | everybody |
| Rules | what the system knows and fixes, and the standing decisions | everybody |
| Activity | who ran what, when, with what result | everybody |

## Safety (inherited from the engine)

Publishing stops unless the build was checked, the `check_dp` values are stored, and the live file is still the file the
build started from (nobody's newer edit is overwritten). The previous live file is backed up first, the upload is
verified, SharePoint keeps no version history of the data file or the dictionary, and the previous live dictionary is
kept in the store. Only one job runs at a time (a lock in the SharePoint folder, which also protects against two people
or two servers). Operators can build and publish; viewers can only look and download.

## Storage on SharePoint

* **The lookup is refreshed every time** from the GPEI API (token in `GPEI_API_TOKEN`) as the first step of each build and inspect
  (there is no separate button); the new lookup is saved in the folder and the build records which one it used.
* **Storage is cleaned automatically** (backups, older builds, results, file versions, recycle bin): see DEPLOY.md, section "Storage on SharePoint".
* **Backups of the live file: only the newest 3** are kept in the folder (`OPS_KEEP_BACKUPS`, default 3). Older ones
  are removed after every job. The PC keeps its own complete archive in `SharePoint_version_backup`. The builder uses
  the kept backups as the reference for its repairs, so a build in the app sees 3 backups and a build on the PC sees all of
  them; compare the first app build with a PC build (DEPLOY.md, step 7).
* **The data dictionary is pushed only when its content changed** (compared cell by cell, so a file that was only
  re-saved is not a change). Same for the data file: a file identical to the live one is not uploaded again.
* SharePoint keeps no version history of the data file or the dictionary; overwritten files of 1 MB or more in the app
  folder lose their old versions at once. The 3 most recent earlier dictionaries are kept in the folder.
* Deleted files and versions go to the SharePoint recycle bin first; the space is only freed when the site recycle bin
  is emptied (Site contents > Recycle bin), or by IT.
* Each run adds about 30 MB (build, dictionary, audit, quality report, feedback). Old runs can be removed by hand from
  the `runs` folder once published.

## Resources: read this before choosing a plan

A build reads the whole file and all earlier backups and writes several workbooks. Measured here on the real data
(about 42,000 rows, 164 columns): **about 7 minutes and a peak of 3.6 GB of memory** on 2 CPUs. The app refuses to start a build when
less than 5 GB is free (`OPS_MIN_BUILD_GB`), so the server is never killed half way. Everything except building and
publishing is light. See `DEPLOY.md` for the plan to choose.

## Repository

```
app.py                    the Shiny app (entry point for Posit Connect Cloud)
opscenter/                config (environment variables), auth, store (SharePoint folder), workspace (sync), jobs, pipelines, explore, overview
engine/                   admin.py, add_coadmin_columns.py, publish_admin_data.py, backup_tool/sp_versions.py (copied, not edited here)
tools/seed_store.py       one-time copy of the PC's backups, runs and inputs into the SharePoint folder
tools/make_user.py        makes a user entry (name, role, hashed key)
tools/sync_engine.py      copies the engine (--strip-links for this public repository); --check-public scans for links, paths, secrets
tests/fake_graph.py       fake SharePoint (Graph) for testing
```

The repository is public, so it holds no data, no secret, no SharePoint link and no personal path: all of it comes from
environment variables (see `DEPLOY.md`). Always sync the engine with `python tools/sync_engine.py --strip-links` and
run `python tools/sync_engine.py --check-public` before pushing.

## Run it locally / test

```
pip install -r requirements.txt
python -m shiny run app.py                           # needs the variables of DEPLOY.md
```

`tests/fake_graph.py` is a small fake of Microsoft Graph (the data file, the dictionary, the SharePoint folder with
upload sessions, versions, recycle bin): `python tests/fake_graph.py PORT STORE_DIR ADMIN_FILE DICT_FILE`, then point the
app at it with `PUBLISH_GRAPH_BASE`, `PUBLISH_GRAPH_BETA` and `PUBLISH_TOKEN_URL`. It was used to develop and test every
step (seed, backup, build, check, values, publish, dictionary, inspect, compare, lock, memory guard) without touching
the real SharePoint.

### Duplicates: check and fix

A record entered twice (same Country, Province, District, date, round, vaccine and Response, and the same population and results) is a duplicate. Records with the same names but other figures are different units (most records have no sub-district) and are never treated as duplicates. Exact copies (every value the same) are always removed by the build. For the rest, Quality & compare > Find duplicates lists each group with the record a fix would keep and the one it would remove; it changes nothing. On the Cycle tab, the Duplicates choice decides what Build and the whole cycle do: flag only (default), or remove the extra copy and keep the most complete (or the first) record. Removing asks for a confirmation; the Check step shows the number of duplicates before and after, and the quality report lists every removed row.

### Quick start page and fix list

The first tab, Quick start, is the short guide for new users (about, the five steps, what the build corrects, the fix list, duplicates, tips, support). Its text is `opscenter/guide.py`; the Download PDF button serves `www/WHO_AFRO_Admin_Operations_Center_Quick_Start.pdf`, made with `python tools/make_quick_start_pdf.py --url <address of the app>` (needs `pip install reportlab segno`; rerun and commit the PDF when the guide text changes). Set `OPS_PUBLIC_URL` to the address of the app and the page shows a QR code; `OPS_SUPPORT_EMAILS` (comma-separated) changes the contact addresses. Put the AFRO GIS Centre logo at `www/afro_gis_logo.png` to show it beside the QR code.

Every build also writes `Fix_list_by_country.xlsx`: what the build could not correct safely (missing key fields, report dates, target above total population, coverage above the ceiling, very different targets, coverage that differs, provinces to confirm, combined and separate records, records entered twice), one sheet per problem with the row, the column to correct and the current and suggested values. Files & feedback cuts it per country. New automatic corrections (each has a switch, see the Rules tab): standard country names, province spelling, and a target population that is 10 or 100 times off when the reported coverage and the district's other campaigns agree.
