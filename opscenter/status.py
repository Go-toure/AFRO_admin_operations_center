"""The state of the Operations Center in one place, in plain words: what is live, what is waiting, and the next things to do.

Two readers use it: the Home tab (a card "What to do next") and the status file written after every job (workspace/status.json, kept in the SharePoint
folder), which a person, a dashboard or an AI agent can read without parsing a job log.

Nothing here changes any data. It only reads the small files the app already keeps."""
import datetime as dt
import json

from . import __version__
from . import followup, submissions_view
from .pipelines import catalog, local_runs, run_state

# where each action is done (the names of the tabs of the app)
GO = {"cycle": "Cycle > Run", "subs": "Cycle > Submissions", "wiring": "Cycle > Lookup & wiring", "pending": "Pending admin data",
      "live": "Live data", "home": "Home"}


def _read_json(path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def snapshot(ws, subs=None, live=None, lock=None, last_job=None):
    """Everything worth knowing about the state, as plain data. `subs` is what submissions_view returns (read from this machine when not given);
    `live` is the SharePoint information of the live file when the caller has it; `last_job` is {'title', 'status', 'message', 'at'}."""
    state = _read_json(ws.workspace / "state.json", {})
    pub = state.get("published") or {}
    cat = catalog(ws)
    newest = cat[-1] if cat else {}
    runs = local_runs(ws)
    unpub = [(n, m) for n, m in runs if not m.get("published")]
    waiting = None
    if unpub:
        n, m = unpub[-1]
        waiting = {"version": n, "state": run_state(m), "built": (m.get("created") or "")[:16]}
    if subs is None:
        try:
            subs = submissions_view.load_local(ws)
        except Exception:
            subs = {"configured": False}
    sub = {"configured": bool(subs.get("configured"))}
    if sub["configured"]:
        pend = subs.get("pending")
        sub.update({
            "files_in_folder": subs.get("in_folder"), "not_inspected": len(subs.get("not_inspected", [])), "changed_since_inspected": len(subs.get("changed", [])),
            "last_inspected": subs.get("last_inspected", ""), "waiting_files": subs.get("waiting"), "waiting_distinct_files": subs.get("waiting_distinct"),
            "taken_by_rules": subs.get("by_rules"), "accepted_by_a_person": subs.get("accepted"), "clean_new_records_waiting_for_a_build": subs.get("clean_new"),
            "already_added_files": subs.get("added"), "already_added_records": subs.get("added_records"),
            "records_held_back": subs.get("held_back"),
            "held_back_by_reason": {h["Reason"]: h["Records"] for h in subs.get("held_reasons", [])},
            "files_not_admin_data": subs.get("not_admin"), "not_admin_by_kind": subs.get("not_admin_kinds"),
            "admin_files_that_cannot_be_read": subs.get("blocked_admin"),
            "files_already_in_the_live_file": subs.get("nothing_new"),
            "pending_rounds_nothing_received": pend[0] if pend else None, "pending_rounds_to_check": pend[1] if pend else None})
    fu = {}
    try:
        for r in followup.table(ws):
            k = r["Follow-up"].split(":")[0].split(" for ")[0]
            fu[k] = fu.get(k, 0) + 1
    except Exception:
        fu = {}
    snap = {
        "followup_countries": fu,
        "generated_at": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "app_version": __version__,
        "live_file": ({"modified_utc": live.get("modified"), "modified_by": live.get("by"), "size": live.get("size")} if live and live.get("ok") else None),
        "last_published": {"version": pub.get("version"), "at": pub.get("at"), "backup_version": pub.get("backup_version")} if pub else None,
        "newest_backup": {"version": newest.get("version"), "saved_utc": (newest.get("sharepoint_modified_utc") or "")[:16].replace("T", " "),
                          "rows": newest.get("rows")} if newest else None,
        "build_waiting_to_be_published": waiting,
        "submissions": sub,
        "last_job": last_job,
        "lock": lock,
    }
    snap["next_actions"] = next_actions(snap)
    return snap


def next_actions(snap):
    """The things to do now, most important first: [{'level': 'wait'|'do'|'look'|'ok', 'text': plain words, 'go': where in the app}]."""
    out = []

    def add(level, text, go):
        out.append({"level": level, "text": text, "go": GO[go]})
    lock = snap.get("lock")
    if lock:
        add("wait", "%s is running '%s' (since %s). Wait for it to end before starting another job." % (lock.get("who"), lock.get("what"), (lock.get("since") or "")[:16]), "home")
    live, nb = snap.get("live_file"), snap.get("newest_backup")
    if live and nb and live.get("modified_utc") and nb.get("saved_utc") and str(live["modified_utc"])[:16] > str(nb["saved_utc"])[:16]:
        add("do", "The live file on SharePoint was changed on %s by %s, after the last backup. Back it up (or run the Autopilot) so the next build starts from it." %
            (str(live["modified_utc"])[:16], live.get("modified_by") or "someone"), "cycle")
    sub = snap.get("submissions") or {}
    if sub.get("configured"):
        if sub.get("not_inspected"):
            add("do", "%d file(s) in the submissions folder were not read yet. Run 'Inspect the submissions'." % sub["not_inspected"], "subs")
        if sub.get("changed_since_inspected"):
            add("do", "%d file(s) were replaced after they were read. Inspect again to read the new version." % sub["changed_since_inspected"], "subs")
    bw = snap.get("build_waiting_to_be_published")
    if bw:
        add("do", "Build v%s is %s. Finish the cycle (check, check_dp values, publish) or run the Autopilot." % (bw["version"], bw["state"]), "cycle")
    if sub.get("configured"):
        if sub.get("clean_new_records_waiting_for_a_build"):
            add("do", "%d clean new record(s) from files taken by the rules are waiting for the next build." % sub["clean_new_records_waiting_for_a_build"], "cycle")
        if sub.get("waiting_files"):
            n, d = sub["waiting_files"], sub.get("waiting_distinct_files") or sub["waiting_files"]
            add("look", "%d file(s) (%d distinct) wait for a person to accept or reject them. One decision covers all the versions of a file." % (n, d), "subs")
        if sub.get("records_held_back"):
            top = sorted((sub.get("held_back_by_reason") or {}).items(), key=lambda kv: -kv[1])[:1]
            add("look", "%d record(s) are held back%s. See why and what each country has to correct." %
                (sub["records_held_back"], (", mostly: %s (%d)" % (top[0][0].lower(), top[0][1])) if top else ""), "subs")
        fu = snap.get("followup_countries") or {}
        n_send = fu.get("To send", 0) + fu.get("New findings since it was sent", 0)
        if n_send:
            add("look", "%d countr%s have feedback to send (what to correct or send again). The workbooks are ready in Submissions > Feedback; record each one once sent." %
                (n_send, "y" if n_send == 1 else "ies"), "subs")
        n_remind = fu.get("No answer", 0)
        if n_remind:
            add("look", "%d countr%s did not answer the feedback sent 14 days ago or more: remind." % (n_remind, "y" if n_remind == 1 else "ies"), "subs")
        if sub.get("pending_rounds_nothing_received"):
            add("look", "%d campaign round(s) have no admin data 15 days after their start. Send the feedback to the countries and follow up." %
                sub["pending_rounds_nothing_received"], "pending")
    lj = snap.get("last_job")
    if lj and lj.get("status") == "failed":
        add("look", "The last job ('%s') failed: %s" % (lj.get("title"), lj.get("message")), "home")
    if not any(a["level"] in ("do", "look", "wait") for a in out):
        add("ok", "Everything is up to date. Nothing needs a person right now.", "home")
    return out


def write(ws, last_job=None, subs=None, live=None, lock=None):
    """Write workspace/status.json (the folder keeps it: see Workspace.single). Never raises: a status file must not break a job."""
    try:
        snap = snapshot(ws, subs=subs, live=live, lock=lock, last_job=last_job)
        ws.workspace.mkdir(parents=True, exist_ok=True)
        tmp = ws.workspace / "status.json.tmp"
        tmp.write_text(json.dumps(snap, indent=1, ensure_ascii=False), encoding="utf-8")
        tmp.replace(ws.workspace / "status.json")
        return snap
    except Exception:
        return None
