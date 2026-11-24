"""Runs one job at a time in a background thread, with a live log the interface can show.

A job = take the SharePoint lock -> copy what the engine needs from the folder -> run engine commands ->
save every new/changed file back to the folder -> release the lock -> write the activity log."""
import subprocess
import sys
import threading
import time
import datetime as dt
from collections import deque

from . import config


class Job:
    def __init__(self, title, user):
        self.title, self.user = title, user
        self.started = dt.datetime.now()
        self.finished = None
        self.status = "running"          # running | done | failed
        self.message = ""
        self.lines = deque(maxlen=4000)
        self.tick = 0                    # grows with every line, so the interface knows when to redraw

    def emit(self, line):
        for part in str(line).rstrip("\n").split("\n"):
            self.lines.append(part)
        self.tick += 1

    def text(self):
        return "\n".join(self.lines)


class Context:
    def __init__(self, job, ws, store, user):
        self.job, self.ws, self.store, self.user = job, ws, store, user

    def emit(self, line):
        self.job.emit(line)

    def admin(self, *args):
        """Run `python admin.py <args>` in the engine folder, streaming its output into the log. Returns the exit code."""
        cmd = [sys.executable, str(self.ws.engine / "admin.py")] + [str(a) for a in args]
        self.emit("$ python admin.py " + " ".join(str(a) for a in args))
        p = subprocess.Popen(cmd, cwd=str(self.ws.engine), env=self.ws.env(), stdout=subprocess.PIPE,
                             stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace")
        for line in p.stdout:
            self.emit(line)
        p.wait()
        return p.returncode


class StepFailed(Exception):
    pass


class JobManager:
    def __init__(self, store_factory, workspace_factory):
        self._store_factory, self._ws_factory = store_factory, workspace_factory
        self.current = None
        self.last = None
        self._mu = threading.Lock()

    def busy(self):
        return self.current is not None and self.current.status == "running"

    def start(self, title, user, fn, locked=True):
        """fn(ctx) does the work and raises StepFailed("reason") to stop. Returns the Job."""
        with self._mu:
            if self.busy():
                raise RuntimeError("A job is already running: %s" % self.current.title)
            job = Job(title, user["name"] if isinstance(user, dict) else str(user))
            self.current = job
        t = threading.Thread(target=self._run, args=(job, fn, user, locked), daemon=True)
        t.start()
        return job

    def _run(self, job, fn, user, locked):
        store = ws = None
        token = None
        t0 = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        status, message = "failed", "did not finish"
        try:
            store = self._store_factory()
            ws = self._ws_factory(store)
            if locked:
                job.emit("Taking the lock on the SharePoint folder ...")
                token = store.acquire_lock(job.user, job.title)
            ws.prepare()
            ctx = Context(job, ws, store, user)
            fn(ctx)
            status, message = "done", "finished"
        except StepFailed as e:
            status, message = "failed", str(e)
            job.emit("")
            job.emit("STOPPED: %s" % e)
        except Exception as e:   # unexpected: show it, keep the app alive
            status, message = "failed", "%s: %s" % (type(e).__name__, e)
            job.emit("")
            job.emit("STOPPED (unexpected error): %s: %s" % (type(e).__name__, e))
        finally:
            try:
                if ws is not None and token is not None:      # only a job that holds the lock writes to the folder
                    from . import status as _status
                    _status.write(ws, last_job={"title": job.title, "status": status, "message": message,
                                                "at": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")})
                    def _step(label, fn):
                        """one clean-up step; a network blip gets a second try, and a step that still fails is reported by name without stopping the next ones"""
                        for attempt in (1, 2):
                            try:
                                return fn()
                            except Exception as e:
                                if attempt == 1 and "ConnectionError" in type(e).__name__ + str(e):
                                    time.sleep(5)
                                    continue
                                job.emit("WARNING: not done: %s (%s: %s)" % (label, type(e).__name__, e))
                                return None
                    sent = _step("saving the files to SharePoint", lambda: ws.push_changes(job.emit))
                    if sent:
                        job.emit("%d file(s) saved to the SharePoint folder." % len(sent))
                    _step("clean-up of the country feedback files", lambda: ws.prune_feedback(job.emit))
                    _step("clean-up of the old backups", lambda: ws.prune_backups(config.KEEP_BACKUPS, job.emit))
                    _step("clean-up of the dictionary copies", lambda: ws.prune_dir("dictionary_backups", config.KEEP_DICT_COPIES, job.emit, "AFRO_admin_data_dictionary_"))
                    _step("clean-up of the old runs", lambda: ws.prune_runs(config.KEEP_RUNS, job.emit))
                    _step("clean-up of the old inspection results", lambda: ws.prune_by_age("inspect", config.KEEP_RESULTS, job.emit))
                    _step("clean-up of the old comparison results", lambda: ws.prune_by_age("compare", config.KEEP_RESULTS, job.emit))
                    _step("clean-up of the old versions", lambda: ws.sweep_versions(job.emit, force=getattr(job, "force_sweep", False)))
                    res = _step("emptying the recycle bin", lambda: store.empty_recycle_bin(t0))
                    if res:
                        n_bin, info = res
                        if n_bin:
                            job.emit("Storage: recycle bin emptied of what this clean-up removed: %s." % info)
                        elif n_bin is None:
                            job.emit("Storage: the recycle bin was not emptied (%s). Removed versions and files stay in the site recycle bin "
                                     "until it is emptied (Site contents > Recycle bin > Second-stage)." % info)
                    _step("saving the shortened catalog", lambda: ws.push_changes(job.emit))
            except Exception as e:
                job.emit("WARNING: could not save everything to SharePoint (%s: %s)" % (type(e).__name__, e))
            try:
                if store is not None:
                    store.log_activity(job.user, job.title, status, message)
                    if token:
                        store.release_lock(token)
            except Exception:
                pass
            job.finished = dt.datetime.now()
            job.message = message
            job.status = status              # last: the interface treats "running" as busy until everything is saved
            self.last = job
