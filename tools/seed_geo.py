#!/usr/bin/env python3
"""Copies the geo reference (names and crosswalks used to standardize the scope) into the SharePoint folder, where the app reads it.

    python tools/seed_geo.py --geo-repo PATH_TO_AFRO-Geo-Reference [--dry-run]

Uploads reference/*.csv (the top-level files, about 5 MB) and R/afrogdb_standardize.R to geo_reference/ in the SharePoint folder of the app.
Run it again after the geo reference changes; files with the same size are skipped. The shapefiles and the other folders are not copied."""
import argparse
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--geo-repo", required=True, help="the AFRO-Geo-Reference folder")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    g = Path(a.geo_repo)
    plan = [("geo_reference/reference/" + p.name, p) for p in sorted((g / "reference").glob("*.csv"))]
    r = g / "R" / "afrogdb_standardize.R"
    if r.is_file():
        plan.append(("geo_reference/R/afrogdb_standardize.R", r))
    if not plan or not (g / "reference" / "afrogdb_geoname_master.csv").is_file():
        sys.exit("%s does not look like the AFRO-Geo-Reference folder (reference/afrogdb_geoname_master.csv is missing)." % g)
    from opscenter.store import Store
    store = Store()
    have = store.walk("geo_reference")
    todo = [(rel, p) for rel, p in plan if have.get(rel[len("geo_reference/"):]) != p.stat().st_size]
    print("%d file(s) to upload, %d already there." % (len(todo), len(plan) - len(todo)))
    for rel, p in todo:
        print("  %s %s  (%.1f MB)" % ("would upload" if a.dry_run else "uploading", rel, p.stat().st_size / 1e6), flush=True)
        if not a.dry_run:
            store.put(rel, p)
    print("Done." if not a.dry_run else "Nothing was written (dry run).")


if __name__ == "__main__":
    main()
