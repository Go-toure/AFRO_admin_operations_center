"""AFRO Administrative Data Operations Center - Shiny for Python app (deployed from GitHub to Posit Connect Cloud)."""
import asyncio
import io
import subprocess
import sys
import tempfile
from pathlib import Path

import pandas as pd
from shiny import App, reactive, render, ui

from opscenter import __version__, auth, config, explore, guide, overview, pipelines, submissions_view
from opscenter.jobs import JobManager
from opscenter.store import Store, StoreError
from opscenter.workspace import Workspace

# ------------------------------------------------------------------------------------------------ shared objects
_store = None
_ws = None


def get_store():
    global _store
    if _store is None:
        _store = Store()
    return _store


def get_ws(store=None):
    global _ws
    if _ws is None:
        _ws = Workspace(store or get_store())
    _ws.store = store or get_store()
    return _ws


JM = JobManager(get_store, get_ws)

CSS = """
:root { --who:#009ADE; --ink:#1d2b36; --mut:#5f6f7c; --line:#dde5ea; --bg:#f5f8fa; }
body { background: var(--bg); color: var(--ink); }
.ops-head { display:flex; justify-content:space-between; align-items:center; padding:14px 0 6px; }
.ops-head h2 { margin:0; font-size:1.35rem; font-weight:650; }
.ops-head .sub { color:var(--mut); font-size:.88rem; }
.tile { background:#fff; border:1px solid var(--line); border-radius:10px; padding:14px 16px; height:100%; }
.tile .k { color:var(--mut); font-size:.78rem; text-transform:uppercase; letter-spacing:.04em; }
.tile .v { font-size:1.15rem; font-weight:650; margin-top:2px; word-break:break-word; }
.tile .s { color:var(--mut); font-size:.85rem; margin-top:2px; }
.stepcard { background:#fff; border:1px solid var(--line); border-radius:10px; padding:14px 16px; margin-bottom:10px; }
.stepcard h5 { margin:0 0 4px; font-size:1rem; }
.stepcard p { margin:0 0 10px; color:var(--mut); font-size:.88rem; }
.pill { display:inline-block; padding:2px 10px; border-radius:99px; font-size:.8rem; font-weight:600; background:#e8f4fb; color:#046; }
.pill.ok { background:#e3f5e8; color:#145a2a; } .pill.bad { background:#fde8e8; color:#8a1c1c; } .pill.wait { background:#fff3d6; color:#7a5400; }
pre.console, .consolewrap pre { background:#0f1b24; color:#d6e4ee; padding:12px 14px; border-radius:8px; max-height:420px; overflow:auto; font-size:.8rem; white-space:pre-wrap; }
.btn-who { background:var(--who); border-color:var(--who); color:#fff; }
.btn-who:hover { background:#0083bd; color:#fff; }
.note { color:var(--mut); font-size:.85rem; }
.nav-tabs .nav-link.active { border-top:3px solid var(--who); font-weight:600; }
.guide-card { background:#fff; border:1px solid var(--line); border-radius:12px; padding:18px 22px; margin-bottom:14px; }
.guide-head { display:flex; justify-content:space-between; align-items:center; gap:16px; flex-wrap:wrap; background:linear-gradient(135deg,#f3f8fc,#e9f1f8); }
.guide-head h3 { margin:8px 0 4px; font-weight:700; color:#0b3a5a; }
.guide-head p { margin:0; max-width:640px; }
.guide-card h4 { font-size:1.05rem; font-weight:700; color:#0b3a5a; border-bottom:1px solid var(--line); padding-bottom:6px; margin:0 0 10px; }
.guide-card ul { margin:0 0 8px; padding-left:20px; } .guide-card li { margin-bottom:5px; }
.guide-qr { display:flex; gap:22px; align-items:center; flex-wrap:wrap; }
.guide-qr img.qr { width:170px; height:170px; border:2px solid var(--line); border-radius:10px; padding:6px; background:#fff; }
"""

app_ui = ui.page_fluid(
    ui.head_content(ui.tags.title("Administrative Data Operations Center"), ui.tags.style(CSS)),
    ui.div(ui.output_ui("main"), style="max-width:1280px;margin:0 auto;padding:0 12px 40px;"),
    title="Administrative Data Operations Center",
)


def pill(text, kind=""):
    return ui.span(text, class_="pill " + kind)


def tile(k, v, s=""):
    return ui.div(ui.div(k, class_="k"), ui.div(v, class_="v"), ui.div(s, class_="s"), class_="tile")


def login_view():
    miss = config.missing_settings()
    if miss:
        return ui.div(ui.h3("Operations Center - set-up needed"),
                      ui.p("These variables are not set (Posit Connect Cloud: content settings > Variables):"),
                      ui.tags.ul(*[ui.tags.li(ui.code(m)) for m in miss]), style="max-width:560px;margin:80px auto;")
    return ui.div(
        ui.h2("Administrative Data Operations Center"),
        ui.p("WHO AFRO GIS Centre. Sign in with your name and your key.", class_="note"),
        ui.input_text("u_name", "User"),
        ui.input_password("u_key", "Key"),
        ui.input_action_button("do_login", "Sign in", class_="btn-who"),
        ui.output_text("login_msg"),
        style="max-width:380px;margin:90px auto;background:#fff;border:1px solid var(--line);border-radius:12px;padding:26px;",
    )


# ------------------------------------------------------------------------------------------------ server
def server(input, output, session):
    user = reactive.value(None)
    msg = reactive.value("")
    ov = reactive.value(None)
    last_find = reactive.value(None)
    rules_text = reactive.value("")
    subs = reactive.value(None)

    # ---------------------------------------------------------------- login
    @render.text
    def login_msg():
        return msg()

    @reactive.effect
    @reactive.event(input.do_login)
    def _login():
        u, m = auth.login(input.u_name(), input.u_key())
        msg.set(m)
        if u:
            user.set(u)
            ov_task()
            rules_task()
            subs_task()

    @reactive.effect
    @reactive.event(input.logout)
    def _logout():
        user.set(None)
        ov.set(None)

    # ---------------------------------------------------------------- background loads
    @reactive.extended_task
    async def ov_task():
        def work():
            store = get_store()
            return overview.load(store, get_ws(store))
        return await asyncio.to_thread(work)

    @reactive.effect
    def _ov_done():
        if ov_task.status() == "success":
            ov.set(ov_task.result())
            d = ov()
            ws = get_ws()
            try:
                src = explore.sources(ws)
                ch = {v: l for v, l in src}
                for i in ("x_source", "q_source", "d_source", "q_a", "q_b"):
                    ui.update_select(i, choices=ch, selected=list(ch)[0] if i != "q_b" else (list(ch)[1] if len(ch) > 1 else list(ch)[0]))
                ui.update_select("f_run", choices=[r["version"] for r in d["runs"]] or [""])
            except Exception:
                pass
        elif ov_task.status() == "error":
            ui.notification_show("Could not read SharePoint: %s" % ov_task.error(), type="error", duration=12)

    @reactive.extended_task
    async def rules_task():
        def work():
            ws = get_ws()
            ws.prepare()
            p = subprocess.run([sys.executable, str(ws.engine / "admin.py"), "rules"], cwd=str(ws.engine), env=ws.env(),
                               capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120)
            return p.stdout or p.stderr
        return await asyncio.to_thread(work)

    @reactive.effect
    def _rules_done():
        if rules_task.status() == "success":
            rules_text.set(rules_task.result())

    @reactive.extended_task
    async def subs_task():
        def work():
            store = get_store()
            return submissions_view.load(store, get_ws(store))
        return await asyncio.to_thread(work)

    @reactive.effect
    def _subs_done():
        if subs_task.status() == "success":
            subs.set(subs_task.result())
        elif subs_task.status() == "error":
            ui.notification_show("Could not read the submissions: %s" % subs_task.error(), type="error", duration=12)

    @reactive.effect
    @reactive.event(input.refresh)
    def _refresh():
        if JM.busy():
            ui.notification_show("A job is running; the overview refreshes when it ends.", duration=5)
            return
        ov_task()
        subs_task()

    # ---------------------------------------------------------------- jobs
    def is_operator():
        u = user()
        return bool(u and u["role"] == "operator")

    def start(title, fn, operator=True):
        u = user()
        if not u:
            return
        if operator and not is_operator():
            ui.notification_show("Only operators can do this.", type="warning")
            return
        if JM.busy():
            ui.notification_show("A job is already running: %s" % JM.current.title, type="warning")
            return
        explore.free_memory()
        try:
            JM.start(title, u, fn)
        except RuntimeError as e:
            ui.notification_show(str(e), type="warning")

    @reactive.effect
    @reactive.event(input.j_unlock)
    def _unlock_ask():
        if not is_operator() or JM.busy():
            return
        lk = get_store().lock_info()
        if not lk:
            ui.notification_show("There is no lock any more.", duration=4)
            ov_task()
            return
        ui.modal_show(ui.modal(
            ui.p("%s started '%s' at %s and the folder is still locked." % (lk.get("who"), lk.get("what"), lk.get("since", "")[:16].replace("T", " "))),
            ui.p("Release the lock only if that job is not running any more (the app was restarted, or the job crashed). If someone is "
                 "really running it, for example from their PC, releasing the lock lets two jobs write to the folder at the same time."),
            title="Release the lock?", easy_close=True,
            footer=ui.TagList(ui.modal_button("Cancel"), ui.input_action_button("j_unlock_yes", "Release the lock", class_="btn-danger"))))

    @reactive.effect
    @reactive.event(input.j_unlock_yes)
    def _unlock_do():
        ui.modal_remove()
        u = user()
        if not u or not is_operator() or JM.busy():
            return
        try:
            st = get_store()
            old = st.break_lock()
            if old:
                st.log_activity(u["name"], "Release the lock", "ok",
                                "lock held by %s for '%s' since %s" % (old.get("who"), old.get("what"), old.get("since", "")))
        except StoreError as e:
            ui.notification_show("Could not release the lock: %s" % e, type="error")
            return
        ui.notification_show("The lock is released.", duration=5)
        ov_task()

    @reactive.effect
    @reactive.event(input.j_backup)
    def _j1():
        start("Back up the live file", pipelines.p_backup, operator=False)

    pending_dup = reactive.Value(None)      # ("build" | "all", mode) waiting for the operator's yes

    def start_with_duplicates(kind):
        """Build / whole cycle with the duplicates choice. Removing records is asked once before it starts."""
        try:
            mode = input.c_dup()
        except Exception:
            mode = "none"
        if mode not in ("complete", "first"):
            mode = "none"
        title = "Build the next version" if kind == "build" else "Run the whole cycle"
        make = pipelines.make_build if kind == "build" else pipelines.make_all
        if mode == "none":
            start(title, make("none"))
            return
        if not is_operator() or JM.busy():
            start(title, make("none"))      # shows the usual 'operators only' / 'a job is running' message
            return
        pending_dup.set((kind, mode))
        ui.modal_show(ui.modal(
            ui.p("This build will remove the extra copy of every record that was entered twice (same names, same population and results), "
                 "keeping %s. Records with the same names but other figures are never removed." %
                 ("the most complete record" if mode == "complete" else "the first record")),
            ui.p("To see which records that is first, close this window and use 'Find duplicates' in the Quality & compare tab. "
                 "The Check step then shows the number of duplicates before and after, and the quality report lists every removed row." +
                 (" The whole cycle goes on to publish the result." if kind == "all" else "")),
            title="Remove duplicate records?", easy_close=True,
            footer=ui.TagList(ui.modal_button("Cancel"), ui.input_action_button("j_dup_yes", "Yes, remove them", class_="btn-danger"))))

    @reactive.effect
    @reactive.event(input.j_dup_yes)
    def _dup_go():
        ui.modal_remove()
        p = pending_dup()
        pending_dup.set(None)
        if not p:
            return
        kind, mode = p
        start(("Build the next version" if kind == "build" else "Run the whole cycle") + " (duplicates: %s)" % mode,
              (pipelines.make_build if kind == "build" else pipelines.make_all)(mode))

    @reactive.effect
    @reactive.event(input.j_build)
    def _j2():
        start_with_duplicates("build")

    @reactive.effect
    @reactive.event(input.j_check)
    def _j3():
        start("Check the newest build", pipelines.p_check)

    @reactive.effect
    @reactive.event(input.j_values)
    def _j4():
        start("Store the check_dp values", pipelines.p_values)

    @reactive.effect
    @reactive.event(input.j_publish)
    def _j5():
        start("Publish the data and the dictionary", pipelines.p_publish)

    @reactive.effect
    @reactive.event(input.j_all)
    def _j7():
        start_with_duplicates("all")

    @reactive.effect
    @reactive.event(input.s_inspect)
    def _s_inspect():
        start("Inspect the submissions", pipelines.p_sub_inspect)

    def decide(action):
        d = subs()
        fid = input.s_file()
        if not d or not fid:
            ui.notification_show("Choose a file first (inspect the submissions if the list is empty).", type="warning")
            return
        row = next((r for r in d["rows"] if r["id"] == fid), None)
        if row is None:
            return
        if action == "accept" and row["Status"] == "blocked":
            ui.notification_show("A blocked file cannot be accepted: %s" % row["Why"], type="warning", duration=10)
            return
        start("%s %s" % ("Accept" if action == "accept" else "Reject", row["File"]),
              pipelines.make_sub_decide(action, fid, (input.s_note() or "").strip()))

    @reactive.effect
    @reactive.event(input.s_accept)
    def _s_accept():
        decide("accept")

    @reactive.effect
    @reactive.event(input.s_reject)
    def _s_reject():
        decide("reject")

    @reactive.effect
    @reactive.event(input.q_inspect)
    def _j8():
        start("Inspect %s" % input.q_source(), pipelines.make_inspect(input.q_source(), input.q_country().strip()), operator=False)

    @reactive.effect
    @reactive.event(input.q_dups)
    def _q_dups():
        start("Find duplicates in %s" % input.d_source(), pipelines.make_duplicates(input.d_source(), input.d_country().strip()), operator=False)

    @reactive.effect
    @reactive.event(input.q_compare)
    def _j9():
        start("Compare %s with %s" % (input.q_a(), input.q_b()), pipelines.make_compare(input.q_a(), input.q_b()), operator=False)

    # job console + finished-job refresh
    seen_done = reactive.value(None)

    @render.code
    def console():
        reactive.invalidate_later(1.5)
        j = JM.current
        if j is None:
            return "No job has run in this session of the server yet."
        head = "%s  [%s]  started %s by %s\n%s\n" % (j.title, j.status.upper(), j.started.strftime("%H:%M:%S"), j.user, "-" * 60)
        return head + j.text()

    @render.ui
    def job_badge():
        reactive.invalidate_later(2)
        j = JM.current
        if j is None:
            return ui.span()
        kind = {"running": "wait", "done": "ok", "failed": "bad"}[j.status]
        return pill("%s: %s" % (j.title, j.status), kind)

    @reactive.effect
    def _after_job():
        reactive.invalidate_later(3)
        j = JM.last
        if j is not None and j is not seen_done.get() and j.status in ("done", "failed") and not JM.busy():
            seen_done.set(j)
            ui.notification_show("%s: %s" % (j.title, j.status), type="message" if j.status == "done" else "error", duration=8)
            with reactive.isolate():
                if user() is not None:
                    ov_task()
                    subs_task()

    # ---------------------------------------------------------------- explore
    @reactive.extended_task
    async def find_task(spec, country, province, district, response, vaccine, round_, date):
        return await asyncio.to_thread(explore.find, get_ws(), spec, country, province, district, response, vaccine, round_, date)

    @reactive.effect
    @reactive.event(input.x_go)
    def _find():
        if JM.busy():
            ui.notification_show("A job is running; try again when it ends (memory).", type="warning")
            return
        ui.notification_show("Reading the file (the first time takes about a minute) ...", duration=6)
        find_task(input.x_source(), input.x_country(), input.x_province(), input.x_district(), input.x_response(),
                  input.x_vaccine(), input.x_round(), input.x_date())

    @reactive.effect
    def _find_done():
        if find_task.status() == "success":
            last_find.set(find_task.result())
        elif find_task.status() == "error":
            ui.notification_show("Search failed: %s" % find_task.error(), type="error", duration=10)

    @render.ui
    def x_count():
        r = last_find()
        if r is None:
            return ui.p("Choose a source and filters, then Search.", class_="note")
        t, total, label = r
        extra = " (showing the first %d)" % len(t) if total > len(t) else ""
        return ui.p("%s: %d record(s) match%s." % (label, total, extra), class_="note")

    @render.data_frame
    def x_table():
        r = last_find()
        return render.DataGrid(r[0] if r else pd.DataFrame(), height="520px", filters=True)

    @render.download(filename="records.csv")
    def x_csv():
        r = last_find()
        yield (r[0] if r else pd.DataFrame()).to_csv(index=False).encode("utf-8-sig")

    # ---------------------------------------------------------------- overview
    @render.ui
    def overview_ui():
        d = ov()
        if d is None:
            return ui.p("Reading SharePoint ... (one moment)", class_="note")
        lv, dc, st = d["live"], d["dictionary"], d["state"]
        pub = st.get("published") or {}
        tiles = [
            tile("Live data file", lv.get("name", "not reachable") if lv["ok"] else "not reachable",
                 ("%s - %s by %s" % (lv["size"], lv["modified"], lv["by"])) if lv["ok"] else lv.get("error", "")),
            tile("Data dictionary", dc.get("name", "not reachable") if dc["ok"] else "not reachable",
                 ("%s - %s by %s" % (dc["size"], dc["modified"], dc["by"])) if dc["ok"] else dc.get("error", "")),
            tile("Last published", "v%s" % pub["version"] if pub.get("version") else "none yet",
                 pub.get("at", "") + ("  (backup %s)" % pub["backup_version"] if pub.get("backup_version") else "")),
            tile("Backups kept", str(len(d["backups"])), "newest: version %s" % d["backups"][0]["version"] if d["backups"] else "run a backup"),
        ]
        lock = d.get("lock")
        banner = ui.div(pill("Busy: %s is running '%s' since %s" % (lock.get("who"), lock.get("what"), lock.get("since", "")[:16]), "wait"),
                        ui.input_action_button("j_unlock", "Release the lock", class_="btn-sm btn-outline-danger", style="margin-left:10px;")
                        if is_operator() and not JM.busy() else None) if lock else ui.div()
        return ui.div(
            ui.layout_columns(*tiles, col_widths=[3, 3, 3, 3]),
            ui.div(ui.p(ui.strong("Next: "), d["next"]), banner, style="margin:14px 0 6px;"),
            ui.p(ui.strong("SharePoint folder: "), "%s in total (%s). Older backups, builds, results and file versions are cleaned up automatically%s." %
                 (d["storage"]["total"], d["storage"]["parts"],
                  (" (last full clean-up %s: %s version(s), %s MB freed)" % (d["storage"]["cleaned"].get("at", "")[:16].replace("T", " "),
                                                                          d["storage"]["cleaned"].get("versions_removed", 0),
                                                                          d["storage"]["cleaned"].get("freed_mb", 0))) if d["storage"].get("cleaned") else ""),
                 class_="note") if d.get("storage") else ui.div(),
            ui.h5("Builds"),
            ui.output_data_frame("runs_table"),
            ui.h5("Backups of the live file", style="margin-top:18px;"),
            ui.output_data_frame("backups_table"),
        )

    @render.data_frame
    def runs_table():
        d = ov()
        return render.DataGrid(pd.DataFrame(d["runs"] if d else []), height="auto")

    @render.data_frame
    def backups_table():
        d = ov()
        return render.DataGrid(pd.DataFrame(d["backups"] if d else []), height="auto")

    # ---------------------------------------------------------------- cycle
    @render.ui
    def cycle_ui():
        d = ov()
        u = user()
        op = is_operator()
        cur = None
        if d and d["runs"]:
            unpub = [r for r in d["runs"] if not r["published"]]
            cur = unpub[0] if unpub else d["runs"][0]
        status = ui.div(pill("%s: %s" % (cur["version"], cur["state"]), "ok" if cur["state"] in ("published", "ready to publish") else "wait")) if cur else ui.div()

        def card(title, text, btn_id, label, primary=False):
            b = ui.input_action_button(btn_id, label, class_="btn-who" if primary else "btn-outline-secondary") if op or btn_id == "j_backup" else ui.span("operators only", class_="note")
            return ui.div(ui.h5(title), ui.p(text), b, class_="stepcard")
        sd = subs()
        sub_note = ui.p(ui.strong("Submissions: "), "%d accepted file(s) will be added to the next build as new records." % sd["accepted"],
                        class_="note") if sd and sd.get("configured") and sd.get("accepted") else ui.div()
        return ui.div(
            ui.p("Every step runs on the server with the same engine as admin.py on the PC. Files are read from and saved to the "
                 "SharePoint folder, so nothing depends on this server staying up. Only one job runs at a time.", class_="note"),
            status, sub_note,
            (ui.div(ui.h5("Duplicates"),
                    ui.p("A record entered twice (same names, same population and results) is always listed in the quality report. "
                         "Choose here whether the Build and the whole cycle also remove the extra copy. Records with the same names but "
                         "other figures are different units and are never removed. See them first with 'Find duplicates' in the "
                         "Quality & compare tab.", class_="note"),
                    ui.input_select("c_dup", None, choices=pipelines.DUP_MODES, selected="none", width="100%"),
                    class_="stepcard") if op else ui.div()),
            ui.layout_columns(
                ui.div(
                    card("1  Back up the live file", "Saves the file that is on SharePoint now as a new backup version (only if it changed).", "j_backup", "Back up now"),
                    card("2  Build the next version", "First refreshes the lookup from the GPEI API, then starts from the live file, adds the records of the accepted submissions, applies every rule and writes the build, dictionary, audit, quality report, feedback workbook and the fix list by country.", "j_build", "Build"),
                    card("3  Check", "Compares the build with the file it started from: columns, rows, wrong-country Responses, duplicates, errors.", "j_check", "Check"),
                ),
                ui.div(
                    card("4  Store the check_dp values", "Writes the check_dp values into the file (no Excel needed).", "j_values", "Store values"),
                    card("5  Publish", "Replaces the data file and then the data dictionary on SharePoint, keeps no version history there, backs up again. Stops if the live file changed since the build. Its last step cleans up the SharePoint folder (old versions, old builds and results, the recycle bin).", "j_publish", "Publish data + dictionary", True),
                    card("All steps", "Build, check, store values and publish (with the clean-up) in one go. Stops at the first problem.", "j_all", "Run the whole cycle", True),
                ),
                col_widths=[6, 6]),
        )

    # ---------------------------------------------------------------- submissions
    @render.ui
    def subs_ui():
        d = subs()
        op = is_operator()
        if d is None:
            return ui.p("Reading the submissions ... (one moment)", class_="note")
        if not d.get("configured"):
            return ui.div(ui.p("The submissions folder is not connected. Set the variable OPS_SUBMISSIONS_SHARE_URL to the share link of the "
                               "Admin_data_submissions folder (see DEPLOY.md).", class_="note"), class_="stepcard")
        tiles = [tile("Files in the folder", str(d["in_folder"]), "%d not inspected yet" % len(d["not_inspected"]) if d["not_inspected"] else "all inspected"),
                 tile("Waiting for a decision", str(d["waiting"]), "ready or to review"),
                 tile("Accepted", str(d["accepted"]), "added to the next build"),
                 tile("Changed since inspected", str(len(d["changed"])), "inspect again" if d["changed"] else "none")]
        report = ui.download_button("s_report", "Download the full report (xlsx)", class_="btn-outline-secondary") if d.get("report") else ui.span()
        decide_card = ui.div(
            ui.h5("2  Decide"),
            ui.p("Open the report first: it lists, file by file, the layout found, every correction made to the values, the records that "
                 "are new, the ones already in the live file (with other figures: listed, never changed), and the issues. An accepted file "
                 "goes into the next Build as new records only; nothing that is already in the live file is changed. A blocked file cannot be "
                 "accepted.", class_="note"),
            ui.input_select("s_file", "File", choices={r["id"]: "%s  (%s, %s)" % (r["File"], r["Status"], r["Decision"]) for r in d["rows"]}, width="100%"),
            ui.output_ui("s_why"),
            ui.input_text("s_note", "Note (optional, kept in the ledger)", width="100%"),
            ui.input_action_button("s_accept", "Accept", class_="btn-who"),
            ui.input_action_button("s_reject", "Reject", class_="btn-outline-danger", style="margin-left:8px;"),
            class_="stepcard") if op else ui.div(ui.p("Only operators accept or reject a file.", class_="note"))
        return ui.div(
            ui.layout_columns(*tiles, col_widths=[3, 3, 3, 3]),
            ui.div(ui.h5("1  Inspect"),
                   ui.p("Reads every file of the submissions folder (the folder itself is never changed), says whether it is in the template "
                        "format or which of its columns could be mapped with certainty, checks every record and value against what the live file "
                        "and the lookup teach, corrects what has one safe answer, and compares with the live file. Nothing is published.",
                        class_="note"),
                   (ui.input_action_button("s_inspect", "Inspect the submissions", class_="btn-who") if op else ui.span("operators only", class_="note")),
                   ui.span(" "), report, class_="stepcard", style="margin-top:14px;"),
            ui.h5("Files"),
            ui.output_data_frame("subs_table"),
            (ui.div(ui.h5("In the folder, not inspected yet", style="margin-top:14px;"), ui.output_data_frame("subs_new")) if d["not_inspected"] else ui.div()),
            ui.div(style="height:10px;"),
            decide_card,
            ui.p("The records of the accepted files are added by the next Build (or the whole cycle); the Check step shows how many. "
                 "Files stay where they are and a ledger in the SharePoint folder of the app keeps every decision.", class_="note"),
        )

    @render.data_frame
    def subs_table():
        d = subs()
        cols = ["File", "Layout", "Status", "Decision", "Countries", "Records read", "New", "Already there", "Other figures", "Several units",
                "Possible duplicates", "Also in another file", "Errors", "Warnings", "Left out", "Note"]
        rows = [{c: r[c] for c in cols} for r in (d or {}).get("rows", [])]
        return render.DataGrid(pd.DataFrame(rows, columns=cols), height="auto", width="100%")

    @render.ui
    def s_why():
        d = subs()
        try:
            fid = input.s_file()
        except Exception:
            fid = None
        row = next((r for r in (d or {}).get("rows", []) if r["id"] == fid), None)
        if not row:
            return ui.div()
        return ui.div(ui.strong("What the inspection found: "), row["Why"] or "nothing to report", ui.br(),
                      ui.span("Layout: %s. Inspected %s." % (row["Layout"], row["Inspected"]), class_="note"), style="margin:0 0 12px;")

    @render.data_frame
    def subs_new():
        d = subs()
        return render.DataGrid(pd.DataFrame((d or {}).get("not_inspected", [])), height="auto")

    @render.download(filename="Submissions_report.xlsx")
    def s_report():
        p = get_ws().workspace / "submissions" / "Submissions_report.xlsx"
        yield p.read_bytes()

    # ---------------------------------------------------------------- files and feedback
    @reactive.calc
    def run_files():
        d = ov()
        v = input.f_run()
        if not d or not v:
            return []
        store = get_store()
        return sorted(c["name"] for c in store.list("runs/" + v) if not c["is_dir"])

    @reactive.effect
    def _upd_files():
        ui.update_select("f_file", choices=run_files())

    @render.download(filename=lambda: input.f_file() or "file")
    def f_dl():
        store, ws = get_store(), get_ws()
        dest = ws.root / "downloads" / input.f_run() / input.f_file()
        store.download("runs/%s/%s" % (input.f_run(), input.f_file()), dest)
        yield dest.read_bytes()

    @reactive.calc
    def fb_file():
        v = input.f_run()
        for n in run_files():
            if n.startswith("Feedback_suspicious_coverage"):
                return n
        return None

    @reactive.effect
    def _fb_countries():
        n = fb_file()
        if not n:
            ui.update_select("f_country", choices=[])
            return
        ws, store = get_ws(), get_store()
        dest = ws.root / "downloads" / input.f_run() / n
        if not dest.is_file():
            store.download("runs/%s/%s" % (input.f_run(), n), dest)
        ui.update_select("f_country", choices=explore.countries_in_feedback(dest))

    @render.download(filename=lambda: "Feedback_%s_%s.xlsx" % (input.f_country().replace(" ", "_"), input.f_run()))
    def f_fb():
        ws = get_ws()
        src = ws.root / "downloads" / input.f_run() / fb_file()
        out = ws.root / "downloads" / ("fb_%s.xlsx" % input.f_country().replace(" ", "_"))
        explore.feedback_for_country(src, input.f_country(), out)
        yield out.read_bytes()

    @reactive.calc
    def fix_file():
        for n in run_files():
            if n.startswith("Fix_list_by_country"):
                return n
        return None

    @render.download(filename=lambda: "Fix_list_%s_%s.xlsx" % (input.f_country().replace(" ", "_"), input.f_run()))
    def f_fix():
        ws, store = get_ws(), get_store()
        n = fix_file()
        if not n:
            raise RuntimeError("This build has no fix list (it was built before the fix list existed).")
        src = ws.root / "downloads" / input.f_run() / n
        if not src.is_file():
            store.download("runs/%s/%s" % (input.f_run(), n), src)
        out = ws.root / "downloads" / ("fix_%s.xlsx" % input.f_country().replace(" ", "_"))
        explore.feedback_for_country(src, input.f_country(), out)
        yield out.read_bytes()

    # ---------------------------------------------------------------- quick start guide
    @render.download(filename=lambda: guide.PDF_NAME)
    def g_pdf():
        pdf = Path(__file__).parent / "www" / guide.PDF_NAME
        if not pdf.is_file():
            raise RuntimeError("The PDF is not in this installation: run tools/make_quick_start_pdf.py.")
        yield pdf.read_bytes()

    @render.ui
    def guide_ui():
        www = Path(__file__).parent / "www"
        qr = None
        if config.PUBLIC_URL:
            try:
                import segno
                qr = segno.make(config.PUBLIC_URL, error="m").svg_data_uri(scale=6, border=1)
            except Exception:
                qr = None
        gis = ui.tags.img(src="afro_gis_logo.png", alt="AFRO GIS Centre", style="height:54px;margin-top:8px;") if (www / "afro_gis_logo.png").is_file() else None

        def card(title, *body):
            return ui.div(ui.h4(title), *body, class_="guide-card")

        def block(items):
            if all(isinstance(it, str) for it in items):
                return [ui.tags.ul(*[ui.tags.li(it) for it in items])]
            out, li = [], []
            for it in items:
                if isinstance(it, tuple):
                    li.append(ui.tags.li(ui.tags.b(it[0] + ": "), it[1]))
                else:
                    if li:
                        out.append(ui.tags.ul(*li))
                        li = []
                    out.append(ui.p(it))
            if li:
                out.append(ui.tags.ul(*li))
            return out
        head = ui.div(
            ui.div(ui.tags.img(src="https://www.who.int/ResourcePackages/WHO/assets/dist/images/logos/en/h-logo-blue.svg",
                               alt="World Health Organization", style="height:46px;", onerror="this.style.display='none'"),
                   ui.h3(guide.TITLE), ui.p(guide.SUBTITLE, class_="note")),
            ui.download_button("g_pdf", "Download PDF", class_="btn-who"), class_="guide-card guide-head")
        mobile = None
        if qr:
            mobile = card("Open the Operations Center on a mobile device",
                          ui.div(ui.tags.img(src=qr, class_="qr", alt="QR code of the Operations Center"),
                                 ui.div(ui.p(guide.MOBILE), gis), class_="guide-qr"))
        elif is_operator():
            mobile = card("Open the Operations Center on a mobile device",
                          ui.p("Set the variable OPS_PUBLIC_URL to the address of this app and a QR code appears here.", class_="note"))
        return ui.div(
            head,
            card("About the Operations Center", *[ui.p(t) for t in guide.ABOUT],
                 ui.tags.b("Key objectives"), ui.tags.ul(*[ui.tags.li(t) for t in guide.OBJECTIVES])),
            mobile,
            *[card(h, *block(items)) for h, items in guide.SECTIONS],
            card("Technical support", ui.p(guide.SUPPORT_TEXT, ui.br(),
                                           *[x for k, m in enumerate(guide.SUPPORT_EMAILS)
                                             for x in ((" | ",) if k else ()) + (ui.tags.a(m, href="mailto:" + m),)])),
            ui.p("WHO AFRO GIS Centre  |  version %s" % __version__, class_="note", style="text-align:center;"))

    # ---------------------------------------------------------------- rules, activity
    @render.code
    def rules_out():
        return rules_text() or "Loading ..."

    @render.data_frame
    def activity_table():
        d = ov()
        return render.DataGrid(pd.DataFrame(d["activity"] if d else []), height="auto")

    # ---------------------------------------------------------------- page
    @render.ui
    def main():
        u = user()
        if u is None:
            return login_view()
        sel = {"": ""}
        return ui.div(
            ui.div(ui.div(ui.h2("Administrative Data Operations Center"),
                          ui.div("WHO AFRO GIS Centre  -  v%s" % __version__, class_="sub")),
                   ui.div(ui.span("%s (%s)  " % (u["name"], u["role"]), class_="note"), ui.input_action_button("refresh", "Refresh", class_="btn-sm btn-outline-secondary"),
                          ui.input_action_button("logout", "Sign out", class_="btn-sm btn-outline-secondary", style="margin-left:6px;")),
                   class_="ops-head"),
            ui.navset_tab(
                ui.nav_panel("Quick start", ui.output_ui("guide_ui")),
                ui.nav_panel("Overview", ui.output_ui("overview_ui")),
                ui.nav_panel("Cycle", ui.output_ui("cycle_ui")),
                ui.nav_panel("Submissions", ui.output_ui("subs_ui")),
                ui.nav_panel("Explore",
                             ui.layout_columns(
                                 ui.input_select("x_source", "Source", choices={"live": "live file"}),
                                 ui.input_text("x_country", "Country"), ui.input_text("x_province", "Province"),
                                 ui.input_text("x_district", "District"), col_widths=[3, 3, 3, 3]),
                             ui.layout_columns(
                                 ui.input_text("x_response", "Response (campaign name)"), ui.input_text("x_vaccine", "Vaccine type"),
                                 ui.input_text("x_round", "Round (e.g. Rnd1)"), ui.input_text("x_date", "Date starts with (2026-04)"),
                                 col_widths=[3, 3, 3, 3]),
                             ui.input_action_button("x_go", "Search", class_="btn-who"),
                             ui.download_button("x_csv", "Download the result", class_="btn-outline-secondary", style="margin-left:8px;"),
                             ui.output_ui("x_count"), ui.output_data_frame("x_table")),
                ui.nav_panel("Quality & compare",
                             ui.layout_columns(
                                 ui.div(ui.h5("Inspect a version"), ui.p("Portal quality checks, stray characters, wrong-country Responses and the campaign rounds against the lookup.", class_="note"),
                                        ui.input_select("q_source", "Source", choices={"live": "live file"}),
                                        ui.input_text("q_country", "Country (optional)"),
                                        ui.input_action_button("q_inspect", "Inspect", class_="btn-who"), class_="stepcard"),
                                 ui.div(ui.h5("Find duplicates"), ui.p("The records entered twice (same names, same population and results), with the one a fix would keep and the one it would remove. Changes nothing.", class_="note"),
                                        ui.input_select("d_source", "Source", choices={"live": "live file"}),
                                        ui.input_text("d_country", "Country (optional)"),
                                        ui.input_action_button("q_dups", "Find duplicates", class_="btn-who"), class_="stepcard"),
                                 ui.div(ui.h5("Compare two versions"), ui.p("What changed between two builds or backups, column by column.", class_="note"),
                                        ui.layout_columns(ui.input_select("q_a", "A", choices={"live": "live file"}), ui.input_select("q_b", "B", choices={"live": "live file"})),
                                        ui.input_action_button("q_compare", "Compare", class_="btn-who"), class_="stepcard"),
                                 col_widths=[4, 4, 4]),
                             ui.p("The result appears in the job log below.", class_="note")),
                ui.nav_panel("Files & feedback",
                             ui.layout_columns(
                                 ui.div(ui.h5("Files of a build"), ui.input_select("f_run", "Build", choices=[""]),
                                        ui.input_select("f_file", "File", choices=[]),
                                        ui.download_button("f_dl", "Download", class_="btn-who"), class_="stepcard"),
                                 ui.div(ui.h5("Feedback and fix list for one country"), ui.p("The feedback workbook (coverage to confirm) and the fix list (records to correct at the source) of the chosen build, reduced to one country.", class_="note"),
                                        ui.input_select("f_country", "Country", choices=[]),
                                        ui.download_button("f_fb", "Download the feedback", class_="btn-who"),
                                        ui.download_button("f_fix", "Download the fix list", class_="btn-who", style="margin-left:8px;"), class_="stepcard"),
                                 col_widths=[6, 6])),
                ui.nav_panel("Rules", ui.output_code("rules_out")),
                ui.nav_panel("Activity", ui.output_data_frame("activity_table")),
                id="tabs", selected="Overview"),
            ui.hr(),
            ui.div(ui.strong("Job log  "), ui.output_ui("job_badge"), style="margin-bottom:6px;"),
            ui.tags.div(ui.output_code("console"), class_="consolewrap"),
        )


app = App(app_ui, server, static_assets=Path(__file__).parent / "www")
