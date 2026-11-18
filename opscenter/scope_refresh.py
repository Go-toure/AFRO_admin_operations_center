"""Refreshing the scope file from the app.

Everything the refresh runs is in this repository (scope_pipeline/: the GPEI fetch, the R build, the enrichment) and everything it reads or
keeps is in the SharePoint folder (geo_reference/ = names and crosswalks, scope/ = the GPEI files, inputs/scope_.csv = the result). No other
folder on the machine is used, so the same code runs on the PC (Positron) and on the hosting service.

What the machine must have: R (Rscript) with the packages of build_scope_file.R, and GPEI_API_TOKEN in the settings. The hosting service
has no R: there the job stops at once and says so; on a PC with R it runs.
"""
import csv
import glob
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

from . import config
from .jobs import StepFailed

PIPE = config.HERE / "scope_pipeline"

# what each choice of the interface runs
MODES = {
    "scope": "Fetch the GPEI data, then build the scope file (about 5 to 15 minutes)",
    "rebuild": "Rebuild the scope file from the GPEI files kept in SharePoint (no GPEI fetch; use when the GPEI site is down)",
}


def find_rscript():
    """Path of Rscript, or None. OPS_RSCRIPT, then PATH, then the usual R install folders on Windows, then R_HOME."""
    if os.environ.get("OPS_RSCRIPT") and Path(os.environ["OPS_RSCRIPT"]).is_file():
        return os.environ["OPS_RSCRIPT"]
    found = shutil.which("Rscript")
    if found:
        return found
    exe = "Rscript.exe" if os.name == "nt" else "Rscript"
    roots = [os.environ.get(k, "") for k in ("ProgramFiles", "ProgramW6432", "ProgramFiles(x86)")]
    roots.append(os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs"))
    cands = []
    for base in filter(None, roots):
        cands += glob.glob(os.path.join(base, "R", "R-*", "bin", "x64", exe))
        cands += glob.glob(os.path.join(base, "R", "R-*", "bin", exe))
    rh = os.environ.get("R_HOME", "").strip()
    if rh:
        cands += [os.path.join(rh, "bin", "x64", exe), os.path.join(rh, "bin", exe)]
    cands = [c for c in cands if os.path.isfile(c)]
    return sorted(cands, reverse=True)[0] if cands else None


def status():
    """What the interface shows before the button: each need and whether it is met."""
    rs = find_rscript()
    items = [
        ("R (Rscript) on this machine", bool(rs),
         "Install R on the PC (or set OPS_RSCRIPT). The hosting service has no R: run the refresh from the PC."),
        ("GPEI token (GPEI_API_TOKEN)", bool(os.environ.get("GPEI_API_TOKEN")), "Add GPEI_API_TOKEN to .env (or to the variables of the content)."),
        ("Scope scripts in the app", (PIPE / "build_scope_file.R").is_file() and (PIPE / "gpei_fetch.py").is_file(), "scope_pipeline/ is missing in the app repository."),
    ]
    return {"items": items, "ready": all(ok for _, ok, _ in items), "rscript": rs}


def _count_rows(path):
    with open(path, newline="", encoding="utf-8-sig") as fh:
        r = csv.reader(fh)
        head = next(r, [])
        return head, sum(1 for _ in r)


def run(ctx, mode="scope"):
    """The pipeline body (the caller wraps it with operator_only): pull the geo reference, fetch (or pull) the GPEI files, run the R build,
    enrich with the round facts, check the result, copy scope_.csv to the inputs of the SharePoint folder."""
    st = status()
    miss = [n + " - " + why for n, ok, why in st["items"] if not ok]
    if miss:
        raise StepFailed("The scope refresh cannot start on this machine:\n  " + "\n  ".join(miss))
    ws = ctx.ws
    data = ws.scope_home / "data"
    data.mkdir(parents=True, exist_ok=True)
    (ws.scope_home / "logs").mkdir(parents=True, exist_ok=True)

    ctx.emit("Reading the geo reference from the SharePoint folder (geo_reference/) ...")
    n = ws.pull_tree("geo_reference")
    if not (ws.geo / "reference" / "afrogdb_geoname_master.csv").is_file() or not (ws.geo / "R" / "afrogdb_standardize.R").is_file():
        raise StepFailed("geo_reference/ is not in the SharePoint folder (or incomplete). Copy it once with: "
                         "python tools/seed_geo.py --geo-repo <the AFRO-Geo-Reference folder>.")
    ctx.emit("   geo reference ready (%d file(s) fetched)." % n)

    if mode == "rebuild":
        ctx.emit("Reading the GPEI files kept in the SharePoint folder (scope/) ...")
        ws.pull_tree("scope")
        for f in ("lookup.xlsx", "gpei_scopes.csv"):
            if not (data / f).is_file():
                raise StepFailed("scope/%s is not in the SharePoint folder: run the full refresh once (it saves these files there)." % f)
    else:
        sys.path.insert(0, str(PIPE))
        try:
            import gpei_fetch
        finally:
            sys.path.remove(str(PIPE))
        from datetime import date
        gpei_fetch.log = ctx.emit                 # the fetch's own messages go to the job log
        ctx.emit("Fetching the campaigns, rounds and scopes from the GPEI API ...")
        lookup_ok, scopes_ok = gpei_fetch.fetch_gpei_data_via_api(ws.scope_home, data, ws.scope_home / "_previous",
                                                                  gpei_fetch.DEFAULT_START_DATE, date.today().isoformat(), None)
        if not (lookup_ok and scopes_ok):
            raise StepFailed("The GPEI fetch did not finish: the lines above say why. Nothing was copied to SharePoint.")

    env = dict(os.environ)
    env.update({"PYTHONIOENCODING": "utf-8", "PYTHONUNBUFFERED": "1", "GPEI_SCOPE_HOME": str(ws.scope_home),
                "AFRO_GEO_REFERENCE_DIR": str(ws.geo)})
    env["PATH"] = str(Path(st["rscript"]).parent) + os.pathsep + env.get("PATH", "")
    before = (data / "scope_.csv").stat().st_mtime if (data / "scope_.csv").is_file() else 0
    ctx.emit("")
    ctx.emit("Building the scope file with R (names standardized with the geo reference) ...")
    ctx.emit("$ Rscript scope_pipeline/build_scope_file.R")
    p = subprocess.Popen([st["rscript"], str(PIPE / "build_scope_file.R")], cwd=str(ws.scope_home), env=env, stdout=subprocess.PIPE,
                         stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace")
    for line in p.stdout:
        ctx.emit(line)
    p.wait()
    f = data / "scope_.csv"
    if p.returncode or not f.is_file() or f.stat().st_mtime <= before:
        raise StepFailed("The R build did not produce scope_.csv (exit %s). The lines above say why (a missing R package is the usual reason: "
                         "install it in R). Nothing was copied to SharePoint." % p.returncode)

    ctx.emit("Adding the GPEI round facts (ids, end date, target population, flags) ...")
    sys.path.insert(0, str(PIPE))
    try:
        from enrich_scope import enrich_scope_with_rounds
    finally:
        sys.path.remove(str(PIPE))
    rounds = data / "gpei_rounds_full.csv"
    if rounds.is_file():
        enrich_scope_with_rounds(f, rounds, log=ctx.emit)
    else:
        ctx.emit("   (no gpei_rounds_full.csv: the round facts are not added)")

    head, n = _count_rows(f)
    if not {"geo_code", "geo_match"} <= set(head):
        raise StepFailed("scope_.csv has %d rows but no geo_code / geo_match columns: the geo reference standardization did not run "
                         "(see the lines above). Nothing was copied to SharePoint." % n)
    if n < 1000:
        raise StepFailed("scope_.csv has only %d rows, far fewer than a normal scope file: nothing was copied to SharePoint." % n)
    ctx.emit("")
    ctx.emit("scope_.csv: %d rows, %d columns." % (n, len(head)))
    ctx.emit("Copying it to the inputs of the SharePoint folder ...")
    ws.push_input("scope_.csv", f, ctx.emit)
    ctx.emit("The GPEI files used (lookup.xlsx, gpei_scopes.csv, gpei_rounds_full.csv) are saved in scope/ of the SharePoint folder when the job ends.")
    ctx.emit("Next: Lookup & wiring > 'Propose the lookup fixes' reads the new scope.")
