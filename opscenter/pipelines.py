"""The things the buttons do. Each pipeline is a function of a Context (see jobs.py)."""
import csv
import json
import re
from pathlib import Path

from . import config
from .jobs import StepFailed
from .store import Store


# ----------------------------------------------------------------------------------------------- helpers
def available_gb():
    """Memory this container may still use, in GB (cgroup limit if there is one, else the machine)."""
    vals = []
    try:
        for base in ("/sys/fs/cgroup/memory.max", "/sys/fs/cgroup/memory/memory.limit_in_bytes"):
            p = Path(base)
            if p.is_file():
                t = p.read_text().strip()
                if t.isdigit() and int(t) < 1 << 50:
                    cur = Path(str(p).replace("memory.max", "memory.current").replace("limit_in_bytes", "usage_in_bytes"))
                    used = int(cur.read_text().strip()) if cur.is_file() else 0
                    vals.append((int(t) - used) / 1024 ** 3)
                break
    except (OSError, ValueError):
        pass
    try:
        for line in Path("/proc/meminfo").read_text().splitlines():
            if line.startswith("MemAvailable:"):
                vals.append(int(line.split()[1]) / 1024 ** 2)
    except (OSError, ValueError):
        pass
    return min(vals) if vals else None


def local_runs(ws):
    out = []
    rd = ws.workspace / "runs"
    if rd.is_dir():
        for d in rd.iterdir():
            m = re.match(r"^v(\d+)$", d.name)
            if m and (d / "manifest.json").is_file():
                try:
                    out.append((int(m.group(1)), json.loads((d / "manifest.json").read_text(encoding="utf-8"))))
                except ValueError:
                    pass
    return sorted(out)


def catalog(ws):
    p = ws.backup_repo / "catalog" / "versions.csv"
    if not p.is_file():
        return []
    with open(p, newline="", encoding="utf-8") as f:
        rows = [r for r in csv.DictReader(f) if r.get("key") == "admin"]
    return sorted(rows, key=lambda r: int(r["version"]))


def run_state(manifest):
    """One word for the step a run is at."""
    if not manifest.get("build", {}).get("ok"):
        return "build failed"
    if manifest.get("published"):
        return "published"
    if not manifest.get("check", {}).get("ok"):
        return "built - needs check"
    if not manifest.get("excel", {}).get("ok"):
        return "checked - needs check_dp values"
    return "ready to publish"


def operator_only(fn):
    def wrapped(ctx):
        need(ctx, ctx.user["role"] == "operator", "Only operators can do this.")
        return fn(ctx)
    wrapped.__name__ = fn.__name__
    return wrapped


def need(ctx, cond, msg):
    if not cond:
        raise StepFailed(msg)


def admin_ok(ctx, *args):
    rc = ctx.admin(*args)
    if rc:
        raise StepFailed("'admin.py %s' stopped (exit %s). The message above says why." % (args[0], rc))


def ensure_inputs(ctx):
    ctx.emit("Reading the input files from the SharePoint folder ...")
    ctx.ws.pull_inputs()
    for f in ("lookup.xlsx", "geo_reference.csv"):
        need(ctx, (ctx.ws.inputs / f).is_file(), "inputs/%s is missing in the SharePoint folder (run tools/seed_store.py once)." % f)


def ensure_run(ctx, n):
    """The files of run vN and the backup it started from."""
    ctx.emit("Reading run v%d from the SharePoint folder ..." % n)
    ctx.ws.pull_run(n)
    need(ctx, ctx.ws.has_run_data(n), "The big files of v%d were removed from the SharePoint folder to save space (only the newest %d builds "
         "and the last published one keep them). The PC still has them in workspace/runs." % (n, config.KEEP_RUNS))
    m = dict(local_runs(ctx.ws)).get(n, {})
    b = m.get("base", {})
    name = re.split(r"[\\/]", str(b.get("path", "")))[-1]
    names = set()
    if name:
        names.add(name)
    for r in catalog(ctx.ws):
        if b.get("backup_version") and str(r["version"]) == str(b["backup_version"]):
            names.add(Path(r["snapshot"]).name)
    if names:
        ctx.ws.pull_snapshots(names)
    return m


def latest_unpublished(ctx):
    runs = [(n, m) for n, m in local_runs(ctx.ws) if not m.get("published")]
    need(ctx, runs, "There is no build waiting. Run a build first.")
    return runs[-1]


# ----------------------------------------------------------------------------------------------- steps
def step_backup(ctx):
    ctx.ws.pull_light()
    admin_ok(ctx, "backup")


DUP_MODES = {
    "none": "Flag only: list the records entered twice in the quality report, remove nothing (default)",
    "complete": "Fix: remove the extra copy of each record entered twice, keep the most complete one",
    "first": "Fix: remove the extra copy of each record entered twice, keep the first one",
}


def dup_args(dup):
    """The builder option for the duplicates choice ('none' adds nothing: exact copies are always removed, the rest is only flagged)."""
    return ["--", "--resolve-duplicates", dup] if dup in ("complete", "first") else []


def step_build(ctx, dup="none"):
    if not config.SKIP_MEMORY_CHECK:
        gb = available_gb()
        need(ctx, gb is None or gb >= config.MIN_BUILD_GB,
             "This server has about %.1f GB of free memory; a build needs about %.0f GB (it peaks near 4 GB). "
             "Use a Posit plan with more memory, or build on the PC with 'python admin.py build'." % (gb or 0, config.MIN_BUILD_GB))
    ctx.ws.pull_light()
    ensure_inputs(ctx)
    if ctx.ws.pull_submissions():
        ctx.emit("Reading the ledger of the submissions: the accepted files are added to this build.")
    ctx.emit("Reading the backups of the live file (the reference for the repairs) ...")
    ctx.ws.pull_snapshots()
    try:
        if dup in ("complete", "first"):
            ctx.emit("Duplicates: the extra copy of each record entered twice will be removed (%s)." %
                     ("the most complete record is kept" if dup == "complete" else "the first record is kept"))
        admin_ok(ctx, "build", *dup_args(dup))          # refreshes the lookup from the GPEI API first (see engine/refresh_lookup.py)
    finally:
        ctx.ws.push_lookup(ctx.emit)    # a refreshed lookup is kept even when the build stops


def step_check(ctx):
    n, _ = latest_run_any(ctx)
    ensure_run(ctx, n)
    ensure_inputs(ctx)
    admin_ok(ctx, "check")


def step_values(ctx):
    n, _ = latest_unpublished(ctx)
    ensure_run(ctx, n)
    admin_ok(ctx, "excel")


def last_step_cleanup(ctx):
    """The last step of a publish: clean the SharePoint folder (the old versions of every file, the older builds' big files, old
    results, the recycle bin). The clean-up itself runs when the job ends, with the full version sweep forced; it is only asked for
    here, so a publish that failed does not get there. (Every other job runs the same clean-up, with the sweep of the whole folder
    at most once a day.)"""
    ctx.job.force_sweep = True
    ctx.emit("Last step: cleaning the SharePoint folder (old versions, old builds and results, the recycle bin) ...")


def step_publish(ctx):
    n, _ = latest_unpublished(ctx)
    ensure_run(ctx, n)
    need(ctx, ctx.user["role"] == "operator", "Only operators can publish.")
    admin_ok(ctx, "publish")


def latest_run_any(ctx):
    ctx.ws.pull_light()
    runs = local_runs(ctx.ws)
    need(ctx, runs, "There is no build yet.")
    return runs[-1]


# ----------------------------------------------------------------------------------------------- pipelines (what a button runs)
def p_backup(ctx):
    step_backup(ctx)


def make_build(dup="none"):
    @operator_only
    def p(ctx):
        step_build(ctx, dup)
    return p


@operator_only
def p_check(ctx):
    step_check(ctx)


@operator_only
def p_values(ctx):
    ctx.ws.pull_light()
    step_values(ctx)


@operator_only
def p_publish(ctx):
    ctx.ws.pull_light()
    step_publish(ctx)
    last_step_cleanup(ctx)


def make_all(dup="none"):
    @operator_only
    def p(ctx):
        """backup -> build -> check -> values -> publish, all in one go (the run files stay on this server meanwhile)."""
        step_build(ctx, dup)
        ctx.ws.push_changes(ctx.emit)
        admin_ok(ctx, "check")
        ctx.ws.push_changes(ctx.emit)
        admin_ok(ctx, "excel")
        ctx.ws.push_changes(ctx.emit)
        need(ctx, ctx.user["role"] == "operator", "Only operators can publish.")
        admin_ok(ctx, "publish")
        last_step_cleanup(ctx)
    return p


def ensure_source(ctx, spec):
    """Make the file behind 'live' / 'vNN' / 'bN' available locally."""
    spec = (spec or "live").strip()
    if spec == "live":
        step_backup(ctx)
        return
    ctx.ws.pull_light()
    m = re.match(r"^v(\d+)$", spec)
    if m:
        ensure_run(ctx, int(m.group(1)))
        return
    m = re.match(r"^b(\d+)$", spec)
    if m:
        for r in catalog(ctx.ws):
            if r["version"] == m.group(1):
                ctx.ws.pull_snapshots({Path(r["snapshot"]).name})
                return
    raise StepFailed("Unknown source '%s'." % spec)


def make_inspect(source, country):
    def p(ctx):
        ensure_inputs(ctx)
        ensure_source(ctx, source)
        args = ["inspect", "--source", source]
        if country:
            args += ["--country", country]
        try:
            admin_ok(ctx, *args)        # refreshes the lookup from the GPEI API first
        finally:
            ctx.ws.push_lookup(ctx.emit)
    return p


def make_duplicates(source, country):
    def p(ctx):
        ensure_inputs(ctx)
        ensure_source(ctx, source)
        args = ["duplicates", "--source", source]
        if country:
            args += ["--country", country]
        admin_ok(ctx, *args)        # lists the duplicates and what removing them would do; changes nothing
    return p


def sub_ledger(ws):
    """The ledger of the submissions as kept in the local copy (after a pull)."""
    try:
        return json.loads((ws.workspace / "submissions" / "ledger.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"files": {}}


@operator_only
def p_sub_inspect(ctx):
    """Read every file of the submissions folder, say whether it is in the template format, check every record and value, and
    compare with the live file. Changes nothing in the live file and nothing in the folder of the countries."""
    need(ctx, config.SUBMISSIONS_URL, "The variable OPS_SUBMISSIONS_SHARE_URL (share link of the Admin_data_submissions folder) is not set.")
    ensure_inputs(ctx)
    step_backup(ctx)                       # 'live' = the newest backup of the file on SharePoint
    ctx.ws.pull_submissions()              # the ledger: earlier decisions stay
    ctx.emit("Reading the files of the submissions folder ...")
    sub = Store(ctx.store.g, config.SUBMISSIONS_URL)
    n = ctx.ws.pull_submission_files(sub, ctx.emit)
    need(ctx, n > 0, "The submissions folder has no .xlsx / .xlsm / .csv file.")
    try:
        admin_ok(ctx, "submissions", "inspect")
    finally:
        ctx.ws.push_lookup(ctx.emit)
    ctx.ws.prune_prepared(ctx.emit)


def make_sub_decide(action, target, note):
    @operator_only
    def p(ctx):
        ctx.ws.pull_submissions()
        args = ["submissions", action, target, "--by", ctx.user["name"]]
        if note:
            args += ["--note", note]
        admin_ok(ctx, *args)
    return p


def make_compare(a, b):
    def p(ctx):
        ensure_inputs(ctx)
        ensure_source(ctx, a)
        ensure_source(ctx, b)
        admin_ok(ctx, "compare", a, b)
    return p
