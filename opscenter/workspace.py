"""The local scratch copy of what the engine needs, and the sync with the SharePoint folder.

Layout of the SharePoint folder (the store)           local copy (under OPS_WORKDIR)
    state.json                                      -> workspace/state.json
    catalog/versions.csv                            -> backup_repo/catalog/versions.csv
    snapshots/admin/<backups of the live file>      -> backup_repo/snapshots/admin/
    runs/vNN/<manifest, build, dictionary, ...>     -> workspace/runs/vNN/        (not the bulky out/ folder)
    dictionary_backups/                             -> workspace/dictionary_backups/
    inspect/, compare/                              -> workspace/inspect, workspace/compare
    inputs/lookup.xlsx, geo_reference.csv, ...      -> inputs/
    activity.json, lock.json                        (used by the app only)
"""
import csv
import io
import json
import os
import shutil
import sys
from pathlib import Path

from . import config

SKIP_DIRS = {"out", "_backup_cache", "__pycache__"}
SKIP_SUFFIX = (".part", ".pkl", ".tmp")


class Workspace:
    def __init__(self, store):
        self.store = store
        r = config.WORKDIR
        self.root = r
        self.backup_repo = r / "backup_repo"
        self.workspace = r / "workspace"
        self.inputs = r / "inputs"
        self.engine = r / "engine"
        self.logs = r / "logs"
        self.sigfile = r / "sync_state.json"
        try:
            self.sig = {k: tuple(v) for k, v in json.loads(self.sigfile.read_text(encoding="utf-8")).items()}
        except (OSError, ValueError):
            self.sig = {}
        self.maps = [("catalog", self.backup_repo / "catalog"), ("snapshots", self.backup_repo / "snapshots"),
                     ("runs", self.workspace / "runs"), ("dictionary_backups", self.workspace / "dictionary_backups"),
                     ("inspect", self.workspace / "inspect"), ("compare", self.workspace / "compare"),
                     ("inputs", self.inputs)]
        self.single = {"state.json": self.workspace / "state.json"}

    # ------------------------------------------------------------------ engine set-up
    def prepare(self):
        """Copy the engine to a writable place, write its settings, and make the backup tool ready."""
        for d in (self.backup_repo / "catalog", self.backup_repo / "snapshots" / "admin", self.backup_repo / "config",
                  self.workspace / "runs", self.inputs, self.logs):
            d.mkdir(parents=True, exist_ok=True)
        src = config.HERE / "engine"
        self.engine.mkdir(parents=True, exist_ok=True)
        for f in ("admin.py", "add_coadmin_columns.py", "publish_admin_data.py", "refresh_lookup.py"):
            shutil.copy2(src / f, self.engine / f)
        shutil.copy2(src / "backup_tool" / "sp_versions.py", self.backup_repo / "sp_versions.py")
        (self.backup_repo / "config" / "tracked_files.json").write_text(json.dumps({"files": [
            {"key": "admin", "filename": "AFRO_admin_data.xlsx", "share_url": config.ADMIN_URL, "min_bytes": 100000}]}),
            encoding="utf-8")
        self.write_settings()

    def write_settings(self):
        extra = {}
        p = self.inputs / "ops_settings.json"
        if p.is_file():
            try:
                extra = json.loads(p.read_text(encoding="utf-8"))
            except ValueError:
                extra = {}
        ds = extra.get("district_source", "")
        s = {"backup_repo": str(self.backup_repo), "workspace": str(self.workspace),
             "version_floor": int(extra.get("version_floor", 23)), "builder": "add_coadmin_columns.py",
             "publisher": "publish_admin_data.py", "lookup": str(self.inputs / "lookup.xlsx"),
             "refresh_lookup": bool(extra.get("refresh_lookup", True)), "gpei_env_file": "",
             "geo": str(self.inputs / "geo_reference.csv"),
             "district_source": str(self.inputs / ds) if ds else "",
             "build_extra_args": extra.get("build_extra_args", []), "max_row_drop_pct": float(extra.get("max_row_drop_pct", 2.0)),
             "excel_method": "python", "scope_script_dir": "", "scope_data_dir": ""}
        (self.engine / "admin_settings.json").write_text(json.dumps(s, indent=1), encoding="utf-8")

    def env(self):
        e = dict(os.environ)
        e.update({"ADMIN_SETTINGS": str(self.engine / "admin_settings.json"), "ADMIN_LOGDIR": str(self.logs),
                  "OPS_ADMIN_SHARE_URL": config.ADMIN_URL, "OPS_DICT_SHARE_URL": config.DICT_URL,
                  "PYTHONIOENCODING": "utf-8", "PYTHONUNBUFFERED": "1"})
        return e

    # ------------------------------------------------------------------ mapping
    def local_of(self, rel):
        rel = rel.strip("/")
        if rel in self.single:
            return self.single[rel]
        head, _, tail = rel.partition("/")
        for prefix, local in self.maps:
            if head == prefix:
                return local / tail if tail else local
        return None

    def _remember(self, p):
        try:
            st = Path(p).stat()
            self.sig[str(p)] = (st.st_size, st.st_mtime_ns)
        except OSError:
            pass

    def save_sig(self):
        try:
            self.sigfile.parent.mkdir(parents=True, exist_ok=True)
            self.sigfile.write_text(json.dumps(self.sig), encoding="utf-8")
        except OSError:
            pass

    # ------------------------------------------------------------------ pull
    def pull_tree(self, prefix, skip=SKIP_DIRS):
        files = self.store.walk(prefix, skip=skip)
        n = 0
        for rel, size in sorted(files.items()):
            full = prefix.strip("/") + "/" + rel
            dest = self.local_of(full)
            if dest is None or full.endswith(SKIP_SUFFIX):
                continue
            if dest.is_file() and dest.stat().st_size == size and str(dest) in self.sig:
                continue
            self.store.download(full, dest)
            self._remember(dest)
            n += 1
        return n

    def pull_light(self):
        """state, backup catalog, ops_settings and the small files of every run (manifest, check report, logs)."""
        for rel in ("state.json", "catalog/versions.csv", "inputs/ops_settings.json"):
            d = self.local_of(rel)
            try:
                self.store.download(rel, d)
                self._remember(d)
            except Exception:
                if rel == "state.json":
                    pass
        for c in self.store.list("runs"):
            if not c["is_dir"]:
                continue
            for f in self.store.list("runs/" + c["name"]):
                if f["name"] in ("manifest.json", "check_report.md", "publish.log", "dictionary.log", "build.log") and not f["is_dir"]:
                    rel = "runs/%s/%s" % (c["name"], f["name"])
                    d = self.local_of(rel)
                    self.store.download(rel, d)
                    self._remember(d)
        self.write_settings()

    def pull_run(self, n):
        return self.pull_tree("runs/v%d" % n)

    def pull_inputs(self):
        n = self.pull_tree("inputs")
        self.write_settings()
        return n

    def pull_snapshot(self, name):
        rel = "snapshots/admin/" + name
        d = self.local_of(rel)
        if d.is_file() and str(d) in self.sig:
            return d
        self.store.download(rel, d)
        self._remember(d)
        return d

    def pull_snapshots(self, names=None):
        """The backups of the live file. names=None pulls every one (the builder uses them all as its reference)."""
        have = self.store.walk("snapshots/admin")
        n = 0
        for name in sorted(have):
            if names is not None and name not in names:
                continue
            d = self.local_of("snapshots/admin/" + name)
            if d.is_file() and d.stat().st_size == have[name] and str(d) in self.sig:
                continue
            self.store.download("snapshots/admin/" + name, d)
            self._remember(d)
            n += 1
        return n

    # ------------------------------------------------------------------ push
    def _local_files(self):
        for prefix, base in self.maps:
            if prefix == "inputs":
                continue                      # inputs are put there by hand / the seed script, never by a job
            if not base.is_dir():
                continue
            for root, dirs, files in os.walk(base):
                dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
                for f in files:
                    if f.endswith(SKIP_SUFFIX):
                        continue
                    p = Path(root) / f
                    yield prefix + "/" + p.relative_to(base).as_posix(), p
        for rel, p in self.single.items():
            if p.is_file():
                yield rel, p

    def push_lookup(self, emit=None):
        """The refreshed lookup. Inputs are otherwise never pushed by a job; this one file is, when admin.py refreshed it from the
        GPEI API (inputs/lookup.xlsx changed since it was pulled)."""
        p = self.inputs / "lookup.xlsx"
        if not p.is_file():
            return False
        st = p.stat()
        if self.sig.get(str(p)) == (st.st_size, st.st_mtime_ns):
            return False
        self.store.put("inputs/lookup.xlsx", p)
        self._remember(p)
        self.save_sig()
        if emit:
            emit("   saved to SharePoint: inputs/lookup.xlsx (the refreshed lookup)")
        return True

    def push_changes(self, emit=None):
        """Upload every file that is new or changed since it was pulled / last pushed."""
        sent = []
        for rel, p in self._local_files():
            st = p.stat()
            if self.sig.get(str(p)) == (st.st_size, st.st_mtime_ns):
                continue
            self.store.put(rel, p)
            self._remember(p)
            sent.append(rel)
            if emit:
                emit("   saved to SharePoint: %s" % rel)
        self.save_sig()
        return sent

    # ------------------------------------------------------------------ storage management
    def prune_backups(self, keep, emit=None):
        """Keep only the newest `keep` backups of the live file on SharePoint (and here). The catalog in the
        folder is the reference: rows and files beyond the newest `keep` are removed, files that no row points to too.
        The PC keeps its own complete archive (SharePoint_version_backup), so nothing is lost for good.
        Returns the names removed."""
        if keep <= 0:
            return []
        raw = self.store.get("catalog/versions.csv")
        if not raw:
            return []
        rd = csv.DictReader(io.StringIO(raw.decode("utf-8")))
        fields = rd.fieldnames or []
        rows = list(rd)
        admin = sorted([r for r in rows if r.get("key") == "admin"], key=lambda r: int(r["version"]))
        if not admin:
            return []
        kept = admin[-keep:]
        kept_names = {Path(r["snapshot"]).name for r in kept}
        remote = self.store.list("snapshots/admin")
        gone = []
        for f in remote:
            if not f["is_dir"] and f["name"] not in kept_names:
                self.store.delete("snapshots/admin/" + f["name"])
                lp = self.local_of("snapshots/admin/" + f["name"])
                if lp.is_file():
                    lp.unlink()
                self.sig.pop(str(lp), None)
                gone.append(f["name"])
        if len(kept) != len(admin):
            keep_rows = [r for r in rows if r.get("key") != "admin"] + kept
            buf = io.StringIO()
            w = csv.DictWriter(buf, fieldnames=fields)
            w.writeheader()
            for r in keep_rows:
                w.writerow({k: r.get(k, "") for k in fields})
            cat = self.backup_repo / "catalog" / "versions.csv"
            cat.parent.mkdir(parents=True, exist_ok=True)
            cat.write_text(buf.getvalue(), encoding="utf-8", newline="")     # pushed by the next push_changes()
        for local in (self.backup_repo / "snapshots" / "admin").glob("*") if (self.backup_repo / "snapshots" / "admin").is_dir() else []:
            if local.name not in kept_names and local.is_file():
                local.unlink()
                self.sig.pop(str(local), None)
        if emit and gone:
            emit("Storage: %d older backup(s) removed from SharePoint; the newest %d are kept." % (len(gone), keep))
        return gone

    def prune_dir(self, prefix, keep, emit=None, name_prefix=""):
        """Keep the newest `keep` files (by name, which carries the date) of a folder in the store; only files whose
        name starts with name_prefix are counted or removed."""
        if keep <= 0:
            return []
        files = sorted(f["name"] for f in self.store.list(prefix) if not f["is_dir"] and f["name"].startswith(name_prefix))
        gone = files[:-keep] if len(files) > keep else []
        for n in gone:
            self.store.delete(prefix + "/" + n)
            lp = self.local_of(prefix + "/" + n)
            if lp and lp.is_file():
                lp.unlink()
        if emit and gone:
            emit("Storage: %d older file(s) removed from %s." % (len(gone), prefix))
        return gone
