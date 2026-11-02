"""The things the buttons do. Each pipeline is a function of a Context (see jobs.py)."""
import csv
import json
import re
from pathlib import Path

from . import config
from .jobs import StepFailed


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


def step_build(ctx):
    if not config.SKIP_MEMORY_CHECK:
        gb = available_gb()
        need(ctx, gb is None or gb >= config.MIN_BUILD_GB,
             "This server has about %.1f GB of free memory; a build needs about %.0f GB (it peaks near 4 GB). "
             "Use a Posit plan with more memory, or build on the PC with 'python admin.py build'." % (gb or 0, config.MIN_BUILD_GB))
    ctx.ws.pull_light()
    ensure_inputs(ctx)
    ctx.emit("Reading the backups of the live file (the reference for the repairs) ...")
    ctx.ws.pull_snapshots()
    try:
        admin_ok(ctx, "build")          # refreshes the lookup from the GPEI API first (see engine/refresh_lookup.py)
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


def step_publish(ctx):
    n, _ = latest_unpublished(ctx)
    ensure_run(ctx, n)
    need(ctx, ctx.user["role"] == "operator", "Only operators can publish.")
    admin_ok(ctx, "publish")


def step_dictionary(ctx):
    ctx.ws.pull_light()
    pub = [(n, m) for n, m in local_runs(ctx.ws) if m.get("published")]
    need(ctx, pub, "Nothing has been published from this app or the PC yet.")
    ensure_run(ctx, pub[-1][0])
    admin_ok(ctx, "dictionary")


def latest_run_any(ctx):
    ctx.ws.pull_light()
    runs = local_runs(ctx.ws)
    need(ctx, runs, "There is no build yet.")
    return runs[-1]


# ----------------------------------------------------------------------------------------------- pipelines (what a button runs)
def p_backup(ctx):
    step_backup(ctx)


@operator_only
def p_build(ctx):
    step_build(ctx)


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


@operator_only
def p_dictionary(ctx):
    step_dictionary(ctx)


@operator_only
def p_all(ctx):
    """backup -> build -> check -> values -> publish, all in one go (the run files stay on this server meanwhile)."""
    step_build(ctx)
    ctx.ws.push_changes(ctx.emit)
    admin_ok(ctx, "check")
    ctx.ws.push_changes(ctx.emit)
    admin_ok(ctx, "excel")
    ctx.ws.push_changes(ctx.emit)
    need(ctx, ctx.user["role"] == "operator", "Only operators can publish.")
    admin_ok(ctx, "publish")


@operator_only
def p_lookup(ctx):
    """Refresh the lookup from the GPEI API now (build and inspect do it anyway at their start)."""
    ctx.ws.pull_light()
    ensure_inputs(ctx)
    try:
        admin_ok(ctx, "lookup")
    finally:
        ctx.ws.push_lookup(ctx.emit)


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


def make_compare(a, b):
    def p(ctx):
        ensure_inputs(ctx)
        ensure_source(ctx, a)
        ensure_source(ctx, b)
        admin_ok(ctx, "compare", a, b)
    return p
