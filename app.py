"""AFRO Administrative Data Operations Center - Shiny for Python app (deployed from GitHub to Posit Connect Cloud)."""
import asyncio
import io
import subprocess
import sys
import tempfile
from pathlib import Path

import pandas as pd
from shiny import App, reactive, render, ui

from opscenter import __version__, auth, config, explore, guide, overview, pipelines, scope_refresh, submissions_view, wiring_view
from opscenter.jobs import JobManager
from opscenter.store import Store, StoreError
from opscenter.workspace import Workspace

MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"]

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
    wiring = reactive.value(None)

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
            wiring_task()

    @reactive.effect
    def _auto_login():
        """On a PC without OPS_USERS (Positron / run_local.py): the person at the keyboard is the operator, no sign-in page."""
        if config.LOCAL_LOGIN and user() is None:
            with reactive.isolate():
                user.set(dict(config.LOCAL_USER))
                ov_task()
                rules_task()
                subs_task()
                wiring_task()

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
            if JM.busy() or isinstance(ov_task.error(), PermissionError):
                ui.notification_show("A file was in use while a job was running: the overview refreshes when the job ends.", duration=6)
            else:
                ui.notification_show("Could not read SharePoint: %s" % ov_task.error(), type="error", duration=12)

    @reactive.extended_task
    async def rules_task():
        def work():
            ws = get_ws()
            ws.prepare()
            p = subprocess.run([sys.executable, str(ws.engine / "admin.py"), "rules"], cwd=str(ws.engine), env=ws.env(),
                               capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120)
            if p.returncode and not p.stdout:
                return "The rules could not be read (admin.py rules stopped, exit %s):\n%s" % (p.returncode, (p.stderr or "")[-1500:])
            return p.stdout or p.stderr or "admin.py rules printed nothing."
        return await asyncio.to_thread(work)

    @reactive.effect
    def _rules_done():
        if rules_task.status() == "success":
            rules_text.set(rules_task.result())
        elif rules_task.status() == "error":
            rules_text.set("The rules could not be read: %s: %s\nPress Refresh to try again." % (type(rules_task.error()).__name__, rules_task.error()))

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
        elif subs_task.status() == "error" and not (JM.busy() or isinstance(subs_task.error(), PermissionError)):
            ui.notification_show("Could not read the submissions: %s" % subs_task.error(), type="error", duration=12)

    @reactive.extended_task
    async def wiring_task():
        def work():
            store = get_store()
            return wiring_view.load(store, get_ws(store))
        return await asyncio.to_thread(work)

    @reactive.effect
    def _wiring_done():
        if wiring_task.status() == "success":
            wiring.set(wiring_task.result())
        elif wiring_task.status() == "error" and not (JM.busy() or isinstance(wiring_task.error(), PermissionError)):
            ui.notification_show("Could not read the lookup and wiring files: %s" % wiring_task.error(), type="error", duration=12)

    @reactive.effect
    @reactive.event(input.refresh)
    def _refresh():
        if JM.busy():
            ui.notification_show("A job is running; the overview refreshes when it ends.", duration=5)
            return
        ov_task()
        subs_task()
        wiring_task()
        if not rules_text() or rules_text().startswith("The rules could not"):
            rules_task()

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
        try:
            scope_mode = input.c_scope()
        except Exception:
            scope_mode = "due"

        def make(m):
            return pipelines.make_build(m) if kind == "build" else pipelines.make_all(m, scope_mode)
        if mode == "none":
            start(title, make("none"))
            return
        if not is_operator() or JM.busy():
            start(title, make("none"))      # shows the usual 'operators only' / 'a job is running' message
            return
        pending_dup.set((kind, mode, scope_mode))
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
        kind, mode, scope_mode = p
        start(("Build the next version" if kind == "build" else "Run the whole cycle") + " (duplicates: %s)" % mode,
              pipelines.make_build(mode) if kind == "build" else pipelines.make_all(mode, scope_mode))

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

    pending_auto = reactive.Value(None)

    @reactive.effect
    @reactive.event(input.j_auto)
    def _j_auto():
        if not is_operator() or JM.busy():
            start("Autopilot", pipelines.make_autopilot())      # shows the usual message
            return
        try:
            mode = input.c_dup()
        except Exception:
            mode = "none"
        if mode not in ("complete", "first"):
            mode = "none"
        try:
            scope_mode = input.c_scope()
        except Exception:
            scope_mode = "due"
        try:
            publish = input.c_publish() != "prepare"
        except Exception:
            publish = True
        pending_auto.set((mode, scope_mode, publish))
        ui.modal_show(ui.modal(
            ui.p("The autopilot will run the whole cycle and PUBLISH the result to SharePoint (the data file and its dictionary) if the check passes. "
                 "The live file is backed up first, and the cycle stops at the first problem without publishing. After the publish the live file is read "
                 "back and compared with the build." if publish else
                 "The autopilot will run the whole cycle up to the check and stop BEFORE the publish: the live file on SharePoint stays as it is, "
                 "and you publish when you have read the check report."),
            ui.p(("It will also remove the extra copy of each duplicate record (%s). " % mode) if mode != "none" else "Duplicates are only listed, none removed. ",
                 "Scope: %s." % pipelines.SCOPE_CHOICES.get(scope_mode, scope_mode)),
            title="Run the autopilot?", easy_close=True,
            footer=ui.TagList(ui.modal_button("Cancel"), ui.input_action_button("j_auto_yes", "Yes, run it", class_="btn-who"))))

    @reactive.effect
    @reactive.event(input.j_auto_yes)
    def _j_auto_go():
        ui.modal_remove()
        p = pending_auto()
        pending_auto.set(None)
        if p:
            start("Autopilot (duplicates: %s, scope: %s, %s)" % (p[0], p[1], "publish" if p[2] else "prepare only"), pipelines.make_autopilot(*p))

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
                    wiring_task()

    # ---------------------------------------------------------------- scope and lookup wiring
    @reactive.effect
    @reactive.event(input.w_scope)
    def _w_scope():
        mode = input.w_mode()
        if mode not in scope_refresh.MODES:
            mode = "scope"
        start("Refresh the scope (%s)" % mode, pipelines.make_scope_refresh(mode))

    @reactive.effect
    @reactive.event(input.w_propose)
    def _w_propose():
        start("Propose the lookup fixes", pipelines.p_lookup_propose)

    @reactive.effect
    @reactive.event(input.w_corr)
    def _w_corr():
        start("Preview the decided corrections", pipelines.p_corrections_preview)

    @reactive.effect
    @reactive.event(input.w_adopt)
    def _w_adopt():
        if not is_operator() or JM.busy():
            start("Adopt the lookup fixes", pipelines.make_lookup_adopt())      # shows the usual message
            return
        ui.modal_show(ui.modal(
            ui.p("This writes the proposed fixes as decided lines into corrections.csv (a live campaign renamed to the lookup name) and "
                 "lookup_overrides.csv (a round added to the lookup, a campaign entered twice removed), saves both to the SharePoint folder "
                 "and keeps the old files as .bak copies. Nothing in the live file changes now: the next Build applies the lines."),
            ui.p("Review the proposals first (Propose the lookup fixes, then the tables below). Only the lines the evidence decides are adopted; "
                 "the others stay listed as 'review'."),
            title="Adopt the proposed fixes?", easy_close=True,
            footer=ui.TagList(ui.modal_button("Cancel"), ui.input_action_button("w_adopt_yes", "Yes, adopt them", class_="btn-who"))))

    @reactive.effect
    @reactive.event(input.w_adopt_yes)
    def _w_adopt_go():
        ui.modal_remove()
        start("Adopt the lookup fixes", pipelines.make_lookup_adopt())

    @reactive.effect
    @reactive.event(input.w_close)
    def _w_close():
        d = wiring()
        key = input.w_round()
        if not d or not key:
            ui.notification_show("Choose a pending round first.", type="warning")
            return
        start("Close the pending round %s" % key, pipelines.make_pending_close(key, (input.w_note() or "").strip()))

    def wgrid(name, cap=300):
        d = wiring()
        df = (d or {}).get(name)
        if df is None or len(df) == 0:
            return render.DataGrid(pd.DataFrame({"": ["nothing"]}), width="100%")
        return render.DataGrid(df.head(cap).astype(str), height="auto", width="100%")

    @render.data_frame
    def w_issues():
        return wgrid("issues")

    @render.data_frame
    def w_accepted():
        return wgrid("accepted")

    @render.data_frame
    def w_pcorr():
        return wgrid("p_corr")

    @render.data_frame
    def w_pchg():
        return wgrid("p_chg")

    @render.data_frame
    def w_pskip():
        return wgrid("p_skip")

    # ---------------------------------------------------------------- pending admin data
    PEND_SHEETS = {"Pending_now": "Pending now: nothing received, ask the country", "Check_other_name": "To check: the data may be under another campaign name",
                   "Date_differs_in_live": "In the live file, but at another date", "Received_not_in_live": "Received in a file, not in the live file yet",
                   "Not_yet_due": "Not yet due (started less than 15 days ago)", "Resolved": "Resolved: the data arrived",
                   "Closed": "Closed by a person", "Older_rounds_no_data": "Older rounds with no data (reference)"}

    def pend_df(name):
        d = wiring()
        df = ((d or {}).get("pend_all") or {}).get(name)
        if df is None:
            return pd.DataFrame()
        try:
            c = input.p_country()
        except Exception:
            c = "All"
        if c and c != "All":
            if "Country" in df.columns:
                df = df[df["Country"].astype(str) == c]
            elif "Round" in df.columns:
                df = df[df["Round"].astype(str).str.upper().str.startswith(c.upper() + "|")]
        return df

    @reactive.effect
    def _pend_selects():
        d = wiring()
        if not d:
            return
        pa = d.get("pend_all") or {}
        countries = set()
        for df in pa.values():
            if hasattr(df, "columns") and "Country" in df.columns:
                countries |= set(df["Country"].dropna().astype(str))
        countries = sorted(countries)
        with reactive.isolate():
            try:
                cur = input.p_country()
            except Exception:
                cur = "All"
        ui.update_select("p_country", choices=["All"] + countries, selected=cur if cur in countries else "All")
        pv = d.get("pview")
        if pv is not None and len(pv):
            years = sorted({str(int(y)) for y in pv["_start"].dt.year.dropna()}, reverse=True)
            with reactive.isolate():
                try:
                    cy = input.p_year()
                except Exception:
                    cy = "All"
            ui.update_select("p_year", choices=["All"] + years, selected=cy if cy in years else "All")
        pend = pa.get("Pending_now")
        choices = {}
        if pend is not None and len(pend):
            for _, r in pend.iterrows():
                choices[wiring_view.round_key(r)] = "%s | %s | %s (planned %s)" % (r["Country"], r["Campaign"], r["Round"], str(r["Planned_start"])[:10])
        ui.update_select("w_round", choices=choices)

    def pview_filtered():
        """The combined pending view with the filters of the tab: country, status, year, month, last X months."""
        d = wiring()
        df = (d or {}).get("pview")
        if df is None or len(df) == 0:
            return pd.DataFrame(columns=wiring_view.VIEW_COLUMNS + ["_start"])

        def val(name, default):
            try:
                v = input[name]()
                return default if v is None else v
            except Exception:
                return default
        c, st, yr, mo, last = val("p_country", "All"), val("p_status", "All"), val("p_year", "All"), val("p_month", "All"), val("p_last", 0)
        if c != "All":
            df = df[df["Country"].astype(str) == c]
        if st != "All":
            df = df[df["Status"] == st]
        if yr != "All":
            df = df[df["_start"].dt.year == int(yr)]
        if mo != "All" and mo in MONTHS:
            df = df[df["_start"].dt.month == MONTHS.index(mo) + 1]
        try:
            last = int(last or 0)
        except (TypeError, ValueError):
            last = 0
        if last > 0:
            df = df[df["_start"] >= (pd.Timestamp.now().normalize() - pd.DateOffset(months=last))]
        return df

    @render.ui
    def pend_tiles():
        d = wiring()
        if d is None:
            return ui.p("Reading the pending list ... (one moment)", class_="note")
        pa = d.get("pend_all") or {}
        if not pa:
            return ui.p("No pending list yet: run 'Inspect the submissions' or 'Refresh the pending list'.", class_="note")
        v = pview_filtered()
        cnt = lambda s_: int((v["Status"] == s_).sum()) if len(v) else 0
        delay = pd.to_numeric(v["Delay (days past due)"], errors="coerce").max() if len(v) else None
        n = lambda k: len(pa.get(k, []))
        longest = ("longest delay: %d days past due" % delay) if delay is not None and delay == delay else "nothing received: ask the country"
        return ui.layout_columns(
            tile("Pending", str(cnt("Pending")), longest),
            tile("Not due yet", str(cnt("Not due yet")), "started less than 15 days ago"),
            tile("To check", str(cnt("To check")), "may be under another campaign name"),
            tile("Other date in live", str(cnt("Other date in live")), "campaign and round are there"),
            tile("Received, not in live", str(cnt("Received, not in live")), "held back or already there"),
            tile("Resolved / closed", "%d / %d" % (n("Resolved"), n("Closed")), "all time, not filtered"),
            col_widths=[4, 4, 4, 4, 4, 4])

    @render.data_frame
    def p_view():
        v = pview_filtered()
        if len(v) == 0:
            return render.DataGrid(pd.DataFrame({"": ["nothing for these filters"]}), width="100%")
        return render.DataGrid(v[wiring_view.GRID_COLUMNS].astype(str), height="460px", width="100%")

    @render.ui
    def p_note():
        v = pview_filtered()
        if len(v) == 0 or "Next step" not in v.columns:
            return ui.div()
        items = []
        for st in ["Pending", "Not due yet", "To check", "Other date in live", "Received, not in live"]:
            notes = sorted({str(x) for x in v.loc[v["Status"] == st, "Next step"].dropna() if str(x).strip() and str(x) != "None"})
            if notes:
                items.append(ui.p(ui.strong(st + ": "), " ".join(notes), class_="note", style="margin:2px 0;"))
        return ui.div(ui.h6("Note: next step", style="margin-top:10px;"), *items) if items else ui.div()

    @render.download(filename="Pending_admin_data_view.xlsx")
    def p_dl_view():
        v = pview_filtered()
        buf = io.BytesIO()
        v[wiring_view.GRID_COLUMNS].to_excel(buf, index=False, sheet_name="Pending view")
        yield buf.getvalue()

    @render.data_frame
    def p_table():
        try:
            sheet = input.p_sheet()
        except Exception:
            sheet = "Pending_now"
        df = pend_df(sheet)
        if len(df) == 0:
            return render.DataGrid(pd.DataFrame({"": ["nothing"]}), width="100%")
        return render.DataGrid(df.head(500).astype(str), height="380px", width="100%")

    @render.data_frame
    def p_bycountry():
        d = wiring()
        df = ((d or {}).get("pend_all") or {}).get("By_country")
        if df is None or len(df) == 0:
            return render.DataGrid(pd.DataFrame({"": ["nothing"]}), width="100%")
        return render.DataGrid(df.astype(str), height="320px", width="100%")

    @render.download(filename="Pending_admin_data.xlsx")
    def p_dl():
        yield (get_ws().workspace / "submissions" / "Pending_admin_data.xlsx").read_bytes()

    @reactive.effect
    @reactive.event(input.p_refresh)
    def _p_refresh():
        start("Refresh the pending list", pipelines.p_pending_refresh)

    @render.download(filename="lookup_fix_proposals.xlsx")
    def w_dl_prop():
        yield (get_ws().workspace / "submissions" / "lookup_fix_proposals.xlsx").read_bytes()

    @render.ui
    def wiring_ui():
        d = wiring()
        op = is_operator()
        if d is None:
            return ui.p("Reading the lookup and wiring files ... (one moment)", class_="note")
        st = d["scope_status"]
        sc = d["scope_in_store"]
        needs = ui.tags.ul(*[ui.tags.li(("met: " if ok else "MISSING: ") + n + ("" if ok else " - " + why)) for n, ok, why in st["items"]])
        scope_card = ui.div(
            ui.h5("1  Scope"),
            ui.p("The scope file lists the districts each GPEI round plans (with the standardized geo codes). The refresh reads the GPEI API, "
                 "runs R with the geo reference kept in the SharePoint folder (geo_reference/), adds the GPEI round facts, then saves scope_.csv in "
                 "the inputs of the SharePoint folder, where the engine reads it. Nothing is published. It needs R on the machine that runs the "
                 "app: run it from the PC.", class_="note"),
            ui.p(ui.strong("In the SharePoint folder: "),
                 ("scope_.csv, %.1f MB, saved %s" % (sc["size"] / 1024 ** 2, sc["modified"])) if sc else "no scope_.csv yet"),
            needs,
            ui.input_select("w_mode", "What to run", choices=dict(scope_refresh.MODES), width="100%"),
            (ui.input_action_button("w_scope", "Refresh the scope", class_="btn-who") if op else ui.span("operators only", class_="note")),
            ui.p("" if st["ready"] else "Some needs are missing, so the job will stop at once and say which.", class_="note"),
            class_="stepcard")
        prop_btns = ui.div(
            ui.input_action_button("w_propose", "Propose the lookup fixes", class_="btn-who"),
            ui.input_action_button("w_adopt", "Adopt the proposed fixes", class_="btn-outline-danger", style="margin-left:8px;"),
            ui.input_action_button("w_corr", "Preview the decided corrections", class_="btn-outline-secondary", style="margin-left:8px;"),
            (ui.download_button("w_dl_prop", "Proposals (xlsx)", class_="btn-outline-secondary", style="margin-left:8px;") if d["has_proposals"] else ui.span()),
        ) if op else ui.p("Only operators propose, adopt or close.", class_="note")
        cl, ov_ = d["corrections_lines"], d["overrides_lines"]
        wire_card = ui.div(
            ui.h5("2  Lookup wiring"),
            ui.p("Where the live file names a campaign or round that the lookup does not have, the engine looks for evidence in the scope and the GPEI round "
                 "windows. 'Propose' lists what the evidence supports (nothing changes). 'Adopt' writes it as decided lines that every build applies. "
                 "A round inside its GPEI window, or within 35 days of it and matching its districts, is accepted and not an issue.", class_="note"),
            ui.p(ui.strong("Decided now: "),
                 "%s correction line(s), %s lookup change(s)." % ("?" if cl is None else cl, "?" if ov_ is None else ov_)),
            prop_btns, class_="stepcard", style="margin-top:14px;")
        return ui.div(
            scope_card, wire_card,
            ui.h5("3  What the last inspection and proposal found", style="margin-top:14px;"),
            ui.p("Read from the last 'Inspect the submissions' and 'Propose the lookup fixes'. Run them again after a scope refresh.", class_="note"),
            ui.h6("Lookup issues (rounds in the live file the lookup cannot place)"), ui.output_data_frame("w_issues"),
            ui.h6("Accepted by the GPEI round window", style="margin-top:12px;"), ui.output_data_frame("w_accepted"),
            ui.h6("Proposed: live campaign renamed to the lookup name", style="margin-top:12px;"), ui.output_data_frame("w_pcorr"),
            ui.h6("Proposed: changes to the lookup", style="margin-top:12px;"), ui.output_data_frame("w_pchg"),
            ui.h6("Not proposed (needs a person)", style="margin-top:12px;"), ui.output_data_frame("w_pskip"),
            ui.p("The rounds with no admin data received are in the tab Pending admin data.", class_="note", style="margin-top:12px;"))

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
        sub_note = ui.p(ui.strong("Submissions: "), "%d accepted file(s) and %d file(s) taken by the automatic rules will be added to the next build as new records (%d clean new records; %d records are held back with a reason)." % (
                        sd["accepted"], sd["by_rules"], sd["clean_new"], sd["held_back"]),
                        class_="note") if sd and sd.get("configured") and (sd.get("accepted") or sd.get("by_rules")) else ui.div()
        return ui.div(
            ui.p("Every step runs on the server with the same engine as admin.py on the PC. Files are read from and saved to the "
                 "SharePoint folder, so nothing depends on this server staying up. Only one job runs at a time.", class_="note"),
            status, sub_note,
            (ui.div(ui.h5("Scope"),
                    ui.p("The scope is the evidence the engine uses to wire the campaigns of the live file to the lookup. Refreshing it takes 5 to 15 "
                         "minutes and needs R (on the PC). The Autopilot and the whole-cycle button follow this choice.", class_="note"),
                    ui.input_select("c_scope", None, choices=pipelines.SCOPE_CHOICES, selected="due", width="100%"),
                    class_="stepcard") if op else ui.div()),
            (ui.div(ui.h5("Duplicates"),
                    ui.p("A record entered twice (same names, same population and results) is always listed in the quality report. "
                         "Choose here whether the Build and the whole cycle also remove the extra copy. Records with the same names but "
                         "other figures are different units and are never removed. See them first with 'Find duplicates' in the "
                         "Quality & compare tab.", class_="note"),
                    ui.input_select("c_dup", None, choices=pipelines.DUP_MODES, selected="none", width="100%"),
                    class_="stepcard") if op else ui.div()),
            ((ui.div(ui.h5("Autopilot"),
                     ui.p("One button for the whole cycle, with nothing to decide on the way: the scope if it is due, the inspection of the submissions "
                          "(the automatic rules accept and fix what is safe), the build (lookup wired by the evidence, decided corrections applied, "
                          "accepted files added), the check, the check_dp values and the publish, then the pending list and the feedback of the "
                          "countries. It stops at the first problem and then nothing is published. At the end the log lists what is left for a "
                          "person (files no rule takes, rounds with nothing received). Nothing is sent to any country.", class_="note"),
                     ui.input_select("c_publish", "Publish", choices=pipelines.PUBLISH_CHOICES, selected="publish", width="100%"),
                     ui.input_action_button("j_auto", "Run the autopilot", class_="btn-who"),
                     ui.p("The duplicates choice above applies to the autopilot too.", class_="note"),
                     class_="stepcard", style="border:2px solid var(--who, #009ADE);")) if op else ui.div()),
            ui.layout_columns(
                ui.div(
                    card("1  Back up the live file", "Saves the file that is on SharePoint now as a new backup version (only if it changed).", "j_backup", "Back up now"),
                    card("2  Build the next version", "First refreshes the lookup from the GPEI API, then starts from the live file, adds the records of the accepted submissions, applies every rule and writes the build, dictionary, audit, quality report, feedback workbook and the fix list by country.", "j_build", "Build"),
                    card("3  Check", "Compares the build with the file it started from: columns, rows, wrong-country Responses, duplicates, errors.", "j_check", "Check"),
                ),
                ui.div(
                    card("4  Store the check_dp values", "Writes the check_dp values into the file (no Excel needed).", "j_values", "Store values"),
                    card("5  Publish", "Replaces the data file and then the data dictionary on SharePoint, keeps no version history there, backs up again. Stops if the live file changed since the build. Its last step cleans up the SharePoint folder (old versions, old builds and results, the recycle bin).", "j_publish", "Publish data + dictionary", True),
                    card("All steps", "Refresh the scope if it is due, inspect the submissions, build, check, store values and publish (with the clean-up) in one go. Stops at the first problem.", "j_all", "Run the whole cycle", True),
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
                 tile("Waiting for a person", str(d["waiting"]), "files that no rule takes"),
                 tile("Taken by rules or accepted", str(d["by_rules"] + d["accepted"]), "%d by the automatic rules; %d new clean records" % (d["by_rules"], d["clean_new"])),
                 tile("Records held back", str(d["held_back"]), "with a reason, see the country feedback"),
                 tile("Pending admin data", str(d["pending"][0]) if d.get("pending") else "-", ("rounds with nothing received 15 days after the start; %d to check" % d["pending"][1]) if d.get("pending") else "inspect to compute"),
                 tile("Changed since inspected", str(len(d["changed"])), "inspect again" if d["changed"] else "none")]
        report = ui.download_button("s_report", "Download the full report (xlsx)", class_="btn-outline-secondary") if d.get("report") else ui.span()
        decide_card = ui.div(
            ui.h5("2  Decide"),
            ui.p("Four automatic rules already take what is safe (see the Rules tab): harmless findings only, findings the lookup confirms, the "
                 "same findings as a file a person accepted before, and the clean records of any file that is not in the wrong folder or "
                 "against the lookup's vaccine. Records that fail a check are held back with their reason. What is left is for you: open the report, "
                 "then accept or reject. A person's decision always wins over the rules. An accepted file goes into the next Build as new "
                 "records only; nothing that is already in the live file is changed. A blocked file cannot be accepted.", class_="note"),
            ui.input_select("s_file", "File", choices={r["id"]: "%s  (%s, %s)" % (r["File"], r["Status"], r["Decision"]) for r in d["rows"]}, width="100%"),
            ui.output_ui("s_why"),
            ui.input_text("s_note", "Note (optional, kept in the ledger)", width="100%"),
            ui.input_action_button("s_accept", "Accept", class_="btn-who"),
            ui.input_action_button("s_reject", "Reject", class_="btn-outline-danger", style="margin-left:8px;"),
            class_="stepcard") if op else ui.div(ui.p("Only operators accept or reject a file.", class_="note"))
        return ui.div(
            ui.layout_columns(*tiles, col_widths=[4, 4, 4, 4, 4, 4]),
            ui.div(ui.h5("1  Inspect"),
                   ui.p("Reads every file of the submissions folder (the folder itself is never changed), says whether it is in the template "
                        "format or which of its columns could be mapped with certainty, checks every record and value against what the live file "
                        "and the lookup teach, corrects what has one safe answer, and compares with the live file. Nothing is published.",
                        class_="note"),
                   (ui.input_action_button("s_inspect", "Inspect the submissions", class_="btn-who") if op else ui.span("operators only", class_="note")),
                   ui.span(" "), report, class_="stepcard", style="margin-top:14px;"),
            feedback_card(d),
            ui.h5("Files"),
            ui.output_data_frame("subs_table"),
            (ui.div(ui.h5("In the folder, not inspected yet", style="margin-top:14px;"), ui.output_data_frame("subs_new")) if d["not_inspected"] else ui.div()),
            ui.div(style="height:10px;"),
            decide_card,
            ui.p("The records of the accepted files are added by the next Build (or the whole cycle); the Check step shows how many. "
                 "Files stay where they are and a ledger in the SharePoint folder of the app keeps every decision.", class_="note"),
        )

    def feedback_card(d):
        """Downloads written by the last inspection: the summary, the pending admin data, and what each country has to correct or send."""
        btns = []
        if d.get("summary"):
            btns.append(ui.download_button("s_summary", "Summary (xlsx)", class_="btn-outline-secondary"))
        if d.get("pending_file"):
            btns.append(ui.download_button("s_pending", "Pending admin data (xlsx)", class_="btn-outline-secondary"))
        if d.get("feedback_all"):
            btns.append(ui.download_button("s_fb_all", "Feedback, all countries (xlsx)", class_="btn-outline-secondary"))
        country = ui.div()
        if d.get("feedback"):
            country = ui.div(ui.input_select("s_fb_file", "Workbook of one country, ready to send", choices=d["feedback"], width="100%"),
                             ui.download_button("s_fb_one", "Download it", class_="btn-who"))
        if not btns and not d.get("feedback"):
            return ui.div()
        return ui.div(ui.h5("3  Feedback to the countries and pending data"),
                      ui.p("Written by every inspection, in plain words: what each country has to correct, confirm or send again (records held back, "
                           "campaign names that differ, vaccine that differs from the lookup, sheets not read), and the rounds of the lookup whose admin data "
                           "were not received 15 days after their start (pending admin data). The francophone countries get a French sheet. "
                           "Sending the workbooks to the countries is a person's step; the app sends nothing.", class_="note"),
                      ui.div(*[ui.span(b, style="margin-right:8px;") for b in btns]), country, class_="stepcard", style="margin-top:14px;")

    @render.data_frame
    def subs_table():
        d = subs()
        cols = ["File", "Layout", "Status", "Decision", "Countries", "Records read", "New", "Clean new", "Held back", "Already there", "Other figures", "Several units",
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

    @render.download(filename="Submissions_summary.xlsx")
    def s_summary():
        yield (get_ws().workspace / "submissions" / "Submissions_summary.xlsx").read_bytes()

    @render.download(filename="Pending_admin_data.xlsx")
    def s_pending():
        yield (get_ws().workspace / "submissions" / "Pending_admin_data.xlsx").read_bytes()

    @render.download(filename="Feedback_to_countries.xlsx")
    def s_fb_all():
        yield (get_ws().workspace / "submissions" / "Feedback_to_countries.xlsx").read_bytes()

    @render.download(filename=lambda: input.s_fb_file() or "Feedback.xlsx")
    def s_fb_one():
        name = Path(input.s_fb_file() or "").name            # a file name only, never a path
        yield (get_ws().workspace / "submissions" / "feedback_by_country" / name).read_bytes()

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
                ui.nav_panel("Home", ui.output_ui("overview_ui"),
                             ui.accordion(ui.accordion_panel("Quick start guide", ui.output_ui("guide_ui")), id="home_guide", open=False, class_="mt-3")),
                ui.nav_panel("Cycle", ui.navset_pill(
                    ui.nav_panel("Run", ui.output_ui("cycle_ui")),
                    ui.nav_panel("Submissions", ui.output_ui("subs_ui")),
                    ui.nav_panel("Lookup & wiring", ui.output_ui("wiring_ui")),
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
                    id="tabs_cycle")),
                ui.nav_panel("Pending admin data",
                             ui.p("The rounds of the lookup (GPEI) whose admin data are not in the live file 15 days after their planned start date. "
                                  "Read from the last inspection; 'Refresh the pending list' rebuilds it from the newest live file. Nothing is sent to the countries.",
                                  class_="note"),
                             ui.layout_columns(
                                 ui.input_select("p_country", "Country", choices=["All"], width="100%"),
                                 ui.input_select("p_status", "Status", choices=["All", "Pending", "Not due yet", "To check", "Other date in live", "Received, not in live"], width="100%"),
                                 ui.input_select("p_year", "Year of the start date", choices=["All"], width="100%"),
                                 ui.input_select("p_month", "Month", choices=["All"] + MONTHS, width="100%"),
                                 ui.input_numeric("p_last", "Last X months (0 = all)", 0, min=0, max=120, width="100%"),
                                 col_widths=[2, 3, 2, 2, 3]),
                             ui.output_ui("pend_tiles"),
                             ui.output_data_frame("p_view"),
                             ui.output_ui("p_note"),
                             ui.div(ui.input_action_button("p_refresh", "Refresh the pending list", class_="btn-who"),
                                    ui.download_button("p_dl_view", "Download this view (xlsx)", class_="btn-outline-secondary", style="margin-left:8px;"),
                                    ui.download_button("p_dl", "All sheets (xlsx)", class_="btn-outline-secondary", style="margin-left:8px;"),
                                    style="margin:10px 0 14px;"),
                             ui.accordion(
                                 ui.accordion_panel("Other lists (pending now, to check, resolved, closed, older rounds, lookup issues ...)",
                                                    ui.input_select("p_sheet", "Show", choices=PEND_SHEETS, selected="Pending_now", width="100%"),
                                                    ui.output_data_frame("p_table")),
                                 ui.accordion_panel("By country", ui.output_data_frame("p_bycountry")),
                                 ui.accordion_panel("Close a round",
                                                    ui.p("A round that did not take place, or whose data are not expected, can be closed: it leaves this list and the country "
                                                         "feedback. The decision is kept in the SharePoint folder. Operators only.", class_="note"),
                                                    ui.input_select("w_round", "Round (from 'Pending now')", choices={}, width="100%"),
                                                    ui.input_text("w_note", "Why (kept with the decision)", width="100%"),
                                                    ui.input_action_button("w_close", "Close this round", class_="btn-outline-danger")),
                                 id="p_more", open=False, class_="mt-3")),
                ui.nav_panel("Explore & quality", ui.navset_pill(
                ui.nav_panel("Find records",
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
                    id="tabs_explore")),
                ui.nav_panel("Rules & activity", ui.navset_pill(
                    ui.nav_panel("Rules", ui.output_code("rules_out")),
                    ui.nav_panel("Activity", ui.output_data_frame("activity_table")), id="tabs_ref")),
                id="tabs", selected="Home"),
            ui.hr(),
            ui.div(ui.strong("Job log  "), ui.output_ui("job_badge"), style="margin-bottom:6px;"),
            ui.tags.div(ui.output_code("console"), class_="consolewrap"),
        )


app = App(app_ui, server, static_assets=Path(__file__).parent / "www")
