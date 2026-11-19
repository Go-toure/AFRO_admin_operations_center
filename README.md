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
| Home | live data file and dictionary on SharePoint, last published version, builds, backups, what is next; the Quick start guide opens at the bottom | everybody |
| Cycle | four small tabs in the order of the work. Run: the Autopilot (the whole cycle with no manual step) or back up, build, check, store values, publish (the whole-cycle button refreshes the scope if it is due, on a machine with R, then inspects the submissions first) (data + dictionary, ending with the SharePoint clean-up). Submissions: inspect the countries' files, accept or reject. Lookup & wiring: scope refresh, lookup fixes, corrections preview, pending rounds. Files & feedback: any file of a build; the feedback workbook and fix list of one country | operators decide (backup, reading and downloads: everybody) |
| Pending admin data | the rounds with nothing received 15 days after their start: one view (country, response, round, start date, end date, delay, not due yet) filtered by country, status, year, month or the last X months, with its own download; the other lists below it, close a round, refresh the list, download | operators close, everybody reads |
| Live data | the live file (newest backup, a build or an older backup) read when the tab is first opened: the Live file (every record in one table to scroll down and sideways, main columns, all columns or the ones you choose, search, download of the whole file or the search result), the Drill-down (country, province, district, records, whole file), and Filters & charts (country, province, district, response, vaccine, round, year, month, last X months; tiles; charts by country, over time, by vaccine / response / round, share of districts reaching 95% or more; the filtered records with their download) | everybody reads |
| Explore & quality | Find records in the live file, any build or any backup; Quality & compare: inspect a version, find duplicates, compare two versions | everybody |
| Rules & activity | Rules: what the system knows and fixes, and the standing decisions. Activity: who ran what, when, with what result | everybody |

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
* **The geo reference** (`geo_reference/` of the SharePoint folder: the AFROGDB names and crosswalks) is copied to the PC when it is missing, and every job tells the
  engine where it is (`AFRO_GEO_REFERENCE_DIR`), so a build adds the `geo_code` / `geo_match` of every record, the new ones included (1.7.0).
* **The ledger of the submissions** is read by the app itself before each job, and every job tells the engine so (`OPS_LEDGER_FROM_APP`). The build and the check
  therefore no longer warn that "the decisions on the submissions were not read"; that warning stays for a build run on a PC without the app (1.7.1).
* **The country workbooks of earlier days are removed** from `submissions/feedback_by_country` at the end of a job (the PC keeps them in `_previous`).
* **A file a job has written but not yet sent is never overwritten** by reading the folder again: the publish writes the published flag
  (`state.json`, the run's `manifest.json`) and the job sends it when it ends (the autopilot sends it right after the publish).
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

## Run it on a PC (Positron) - and in the cloud, the same code

The app reads only this repository and the SharePoint folder. Nothing is read from another repository or folder, so the code that runs on a PC
is the code that runs on Posit Connect Cloud.

```
pip install -r requirements.txt
python tools/make_env.py            # once: writes the git-ignored file .env (the same names as the cloud Variables) from the settings already on the PC
python run_local.py --check         # says which settings are present (never their values)
python run_local.py                 # starts the app on http://127.0.0.1:8765 (in Positron: open app.py, Run Shiny App)
```

Without `OPS_USERS` the person at the keyboard is the operator (no sign-in page). The work files are kept in `ops_work/` (git-ignored).

### Autopilot (tab Cycle)

One button runs the whole cycle with nothing to decide on the way: the scope if it is older than `OPS_SCOPE_MAX_AGE_DAYS` (default 7; only on a machine
with R, skipped otherwise), the inspection of the submissions (the automatic rules accept and fix what is safe), the build (the lookup wired by the
evidence, the decided corrections applied, the accepted files added), the check, the check_dp values, the publish (data file and dictionary), then the
pending list and the country feedback. It asks for one confirmation, stops at the first problem (then nothing is published: the live file is backed up
first and the check must pass), and ends with the list of what is left for a person: files no rule takes, records held back, rounds with nothing
received. Nothing is sent to any country. The duplicates choice of the Cycle tab applies to it.

The check of the whole cycle and of the autopilot is the engine's normal check (the same as `admin.py all` on the PC): it stops on the hard findings
and reports the rest. On top of it the run reports how many records of the base are no longer in the build, reads the live file back after the
publish and compares it with the build (VERIFIED, or a warning), and ends with what it did to the data (rows, records added, cells changed per
column). A stricter check, `admin.py check --strict`, exists on demand on the PC; neither the app nor `all` uses it. 'Prepare only' runs everything up to the check and leaves the publish to a
person, who reads the check report first.

### Scope refresh and lookup wiring (tab Lookup & wiring)

* `scope_pipeline/` holds what the scope refresh runs: the GPEI fetch (`gpei_fetch.py`), the R build with the geo-reference standardization
  (`build_scope_file.R`) and the GPEI round facts (`enrich_scope.py`). The button 'Refresh the scope' runs them, checks the result (rows, geo_code
  columns) and saves `scope_.csv` in `inputs/` of the SharePoint folder, and the GPEI files in `scope/`.
* The geo reference (names and crosswalks) is read from `geo_reference/` of the SharePoint folder. Copy it once, and again when the geo reference
  changes: `python tools/seed_geo.py --geo-repo <the AFRO-Geo-Reference folder>`.
* Needs R (Rscript, with the packages of `build_scope_file.R`) on the machine that runs the app and `GPEI_API_TOKEN` in the settings. The hosting
  service has no R: run the refresh from the PC; everything else (propose, adopt, corrections preview, close pending rounds) runs anywhere.
* 'Propose the lookup fixes' / 'Adopt' run `lookup-fix`; adopted lines go to `inputs/corrections.csv` and `inputs/lookup_overrides.csv` in the
  SharePoint folder and are applied by every build. 'Close this round' marks a pending round as not expected.

## Test

```
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

### Submissions from the countries

The folder `Admin_data_submissions` on SharePoint (link in the variable `OPS_SUBMISSIONS_SHARE_URL`) holds the files the countries
send. The **Submissions** tab runs four things, all with the engine's `submissions.py` (the same command on the PC:
`python admin.py submissions inspect | list | accept FILE | reject FILE | summary | feedback | pending`):

1. **Inspect** reads every `.xlsx` / `.xlsm` / `.csv` of the folder (the folder is only read, never changed). It decides whether the
   file is in the template format (the 164 columns of the live file), or maps the columns when the headers can be recognised with
   certainty (otherwise the file is blocked with the reason). It normalises what has one safe answer (country, province, vaccine, round,
   dates, numbers written as text, percent, Year / SIAMTH, country code and block, an empty Response from the lookup), compares every
   record with the live file (new / already there / same names but other figures / several units) and runs the quality checks.
   The result is `Submissions_report.xlsx`, the prepared records (`prepared/`) and the `ledger.json`, all kept in the `submissions/`
   folder of the AdminOps store.
   The **What is new** box at the top of the tab lists the files that arrived since an inspection you choose (the latest arrival by default), by
   country and file, with the date of the file on SharePoint, a mark for a changed version of a known file, and the new / clean / held-back records
   they bring. Files inside a zip are counted under their zip; a zip whose files were read under another path is not shown as unread.
   The tiles also count the files that are **not admin data** (LQAS, IM / monitoring, AEFI, other: supplies, call-in, summaries): they are read to be
   recognised, add no record and are never in the records held back. The Files table has a column with the kind, and column filters.
   The tiles are written in plain words, and a box **Records held back: why** sorts the held-back records by reason (looks like a record already in the live
   file, no target population, matches several live records, a key variable empty, ...) with the countries concerned.
   Since 1.6.8 the Submissions tab keeps the tiles and the Inspect button on top and puts the rest in sub-tabs (What is new, Held back, Files, Decide,
   Feedback), so the job log stays in view; long tables elsewhere (builds, backups, activity, lookup wiring) scroll inside a box of fixed height or sit in
   collapsed sections.
2. **Accept / Reject**: an operator decides per file; a blocked file cannot be accepted. The decision, who and the note are in the ledger.
   Four automatic rules (setting `submissions_auto`, on by default) take what is safe without a decision: harmless findings only;
   findings the lookup confirms; the same findings as a file a person accepted before; and the clean records of any file that is
   not in the wrong folder or against the lookup's vaccine. A person's decision always wins. Records that fail a check are held
   back with their reason (the "Held back" column), never lost.
3. **Build** adds the records of the accepted files and of the files taken by the rules whose key is not yet in the live file,
   before the rules run. Nothing that is already in the live file is changed by a submission; records with other figures are listed
   in the report for the country. The Check step shows how many records were added.
4. **Feedback and pending data**: every inspection also writes `Submissions_summary.xlsx`, `Pending_admin_data.xlsx` (a lookup
   round with no data in the live file `pending_days` = 15 days after its start, from `pending_since` = 2025-01-01; sheets
   Pending_now, Check_other_name, Date_differs_in_live, Received_not_in_live, Not_yet_due, Resolved, Closed; and Lookup_issues / Lookup_issues_older: live rounds that the lookup cannot place (campaign missing, name or date differs, two campaigns on one date), each with a message for the lookup maintainers; the engine proposes, a person decides) and one workbook per
   country in `feedback_by_country` (a French sheet for the francophone countries). All can be downloaded from the tab; sending them
   to the countries is a person's step. The pending register (`pending_register.json`) of the app is separate from the one on a PC.

An optional `inputs/scope_.csv` in the AdminOps store (the file `scope_.csv` of the scope folder: the districts planned per campaign) adds the scope evidence to the lookup issues: the districts of the live records are compared with the districts planned for each campaign, which separates campaigns the lookup cannot (for example a campaign entered twice). Without it the sheets say "scope not available". The scope file also carries, since 18 Nov 2026, the round facts taken from the GPEI API (end date, mop-up window, ids, planned population, flags): a live round whose date lies inside the GPEI round window is no longer reported as a lookup issue (sheet `Lookup_accepted`).

With `inputs/scope_.csv` in the store the build also wires by itself, before it starts, the lookup cases the evidence lets the engine decide alone (`lookup_fix_auto`, default on in `ops_settings.json`): a live campaign name renamed to the lookup name when the districts of its records are those planned for exactly one lookup campaign and the rename does not change how the engine treats the vaccines, and a campaign the lookup holds twice reduced to one entry. What it decided is listed in the audit like any decided correction (Decided by: engine rule); what would change the vaccines stays a proposal for a person. In the app the lines live for that build only (the store files are not rewritten): to keep them, run `python admin.py lookup-fix` on the PC.

An optional `inputs/lookup_overrides.csv` in the AdminOps store holds changes a person decided to the lookup, which GPEI refreshes at every build (a campaign entered twice removed, a round added, a start date moved); they are applied each time the lookup is read. They are decided on the PC with `python admin.py lookup-fix` (propose / adopt) and the two files `corrections.csv` and `lookup_overrides.csv` are copied to the store's `inputs/`.

An optional `inputs/corrections.csv` in the AdminOps store holds corrections a person decided (columns Country, Province, District,
Response, Round_Add, SIA_date, Column, Found, Restored, Reason, Decided_by, Decided_on); the build applies them and lists every
change in the audit as "Decided correction". A cell changes only while it still holds the value in `Found`.

Files stay where they are in the submissions folder; a changed or replaced file must be inspected again.
