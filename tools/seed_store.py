#!/usr/bin/env python3
"""One-time (and safely repeatable) copy of what already exists on the PC into the SharePoint folder the app uses.

    python tools/seed_store.py --store-url "<share link of the SharePoint folder>" [--dry-run]

Run it on the PC, in this repository, after you created an EMPTY folder on SharePoint (for example
AdminOps) and copied its share link ("Copy link", people with the link can edit is NOT needed:
the app signs in with its own registration; any link that opens the folder works).

It uploads
    inputs/       lookup.xlsx, geo_reference.csv and the district source file from Admin_data_coadministration
    catalog/      the backup catalog (admin rows only) of SharePoint_version_backup
    snapshots/    the newest 3 backups of the live file (--keep-backups N; the build uses them as its reference)
    runs/         every run (manifest, check report, logs); the big files only for the newest published run
    state.json    the last published version
Files already in the folder with the same size are skipped, so the script can be run again. Secrets are read from
the environment or from SharePoint_version_backup/config/secrets.env and are never printed."""
import argparse
import csv
import json
import os
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))

BIG = 1_000_000


def load_env(path):
    if path.is_file():
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--store-url", default=os.environ.get("OPS_STORE_SHARE_URL", ""))
    ap.add_argument("--admin-repo", default=str(HERE.parent / "Admin_data_coadministration"))
    ap.add_argument("--backup-repo", default=str(HERE.parent / "SharePoint_version_backup"))
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--no-snapshots", action="store_true", help="skip the (large) backups")
    ap.add_argument("--keep-backups", type=int, default=3,
                    help="how many of the newest backups of the live file go to SharePoint (default 3; the app keeps only that many)")
    a = ap.parse_args()
    ar, br = Path(a.admin_repo), Path(a.backup_repo)
    load_env(br / "config" / "secrets.env")
    if not a.store_url:
        sys.exit("Give the share link of the SharePoint folder with --store-url.")
    os.environ["OPS_STORE_SHARE_URL"] = a.store_url
    # config reads the environment when it is imported, so import after setting it
    from opscenter import config
    from opscenter.store import Store
    store = Store()
    print("SharePoint folder: %s" % store.name)
    have = store.walk("")
    plan = []        # (store path, local path)

    def add(rel, p):
        plan.append((rel, Path(p)))

    for f in ("lookup.xlsx", "geo_reference.csv"):
        if (ar / f).is_file():
            add("inputs/" + f, ar / f)
    ds = None
    if (ar / "inputs").is_dir():
        for p in sorted((ar / "inputs").iterdir()):
            if p.is_file() and p.suffix.lower() in (".xlsx", ".csv"):
                add("inputs/" + p.name, p)
                if "FIVE_REGIONS" in p.name.upper():
                    ds = p.name
    sett = {"version_floor": 23, "district_source": ds or ""}
    # catalog (admin rows only) and the snapshots they point to
    cat = br / "catalog" / "versions.csv"
    rows = []
    if cat.is_file():
        with open(cat, newline="", encoding="utf-8") as f:
            rd = csv.DictReader(f)
            fields = rd.fieldnames
            rows = [r for r in rd if r.get("key") == "admin"]
    rows = sorted(rows, key=lambda r: int(r["version"]))[-a.keep_backups:] if a.keep_backups > 0 else rows
    if not a.no_snapshots:
        for r in rows:
            p = br / r["snapshot"]
            if p.is_file():
                add("snapshots/admin/" + p.name, p)
            else:
                print("   (snapshot missing on the PC: %s)" % r["snapshot"])
    # runs
    runs_dir = ar / "workspace" / "runs"
    runs = sorted([d for d in runs_dir.iterdir() if re.match(r"^v\d+$", d.name)], key=lambda d: int(d.name[1:])) if runs_dir.is_dir() else []
    pub = [d for d in runs if (json.loads((d / "manifest.json").read_text(encoding="utf-8")).get("published") if (d / "manifest.json").is_file() else False)]
    big_for = pub[-1].name if pub else (runs[-1].name if runs else None)
    for d in runs:
        for p in sorted(d.iterdir()):
            if p.is_dir() or p.suffix == ".part":
                continue
            if p.stat().st_size > BIG and d.name != big_for:
                continue
            add("runs/%s/%s" % (d.name, p.name), p)
    if (ar / "workspace" / "state.json").is_file():
        add("state.json", ar / "workspace" / "state.json")
    for p in sorted((ar / "workspace" / "dictionary_backups").glob("*.xlsx")) if (ar / "workspace" / "dictionary_backups").is_dir() else []:
        add("dictionary_backups/" + p.name, p)

    todo = [(rel, p) for rel, p in plan if have.get(rel) != p.stat().st_size]
    total = sum(p.stat().st_size for _, p in todo)
    print("%d file(s) to upload (%.0f MB), %d already there." % (len(todo), total / 1e6, len(plan) - len(todo)))
    if a.dry_run:
        for rel, p in todo:
            print("   would upload %s  (%.1f MB)" % (rel, p.stat().st_size / 1e6))
        return
    for i, (rel, p) in enumerate(todo, 1):
        print("[%d/%d] %s  (%.1f MB)" % (i, len(todo), rel, p.stat().st_size / 1e6), flush=True)
        store.put(rel, p)
    # catalog, rewritten with snapshot paths that exist in the folder
    if rows:
        import io
        buf = io.StringIO()
        w = csv.DictWriter(buf, fieldnames=fields)
        w.writeheader()
        for r in rows:
            r = dict(r)
            r["snapshot"] = "snapshots/admin/" + Path(r["snapshot"]).name
            w.writerow(r)
        store.put("catalog/versions.csv", buf.getvalue().encode("utf-8"))
        print("catalog/versions.csv written (%d versions)" % len(rows))
    if not store.exists("inputs/ops_settings.json"):
        store.put_json("inputs/ops_settings.json", sett)
        print("inputs/ops_settings.json written")
    print("\nDone. The app can now read everything it needs from the folder.")


if __name__ == "__main__":
    main()
