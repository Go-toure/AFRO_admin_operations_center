"""Tests of what the Submissions tab, the Home card and the follow-up compute, on small invented data (no SharePoint, no real file).

Run:  python -m unittest discover -s tests -v"""
import datetime as dt
import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd  # noqa: E402

from opscenter import followup, provenance, status, submissions_view as sv  # noqa: E402
from opscenter.workspace import Workspace  # noqa: E402


def entry(name, path, stem, country="ALGERIA", status_="review", new=10, clean=10, held=0, why="", inspected="2026-11-19 12:00", **kw):
    e = {"decision": None, "name": name, "path": path, "size": 100, "hash": name, "layout": "template", "rows_used": new, "new": new, "clean_new": clean,
         "held_new": held, "status": status_, "why": why, "stem": stem, "country_folder": country, "countries": country, "last_inspected": inspected,
         "first_seen": "2026-11-18 14:00", "present": True, "prepared": "prepared/%s.xlsx" % name[:6]}
    e.update(kw)
    return e


def make_ws(files, runs=None):
    tmp = Path(tempfile.mkdtemp())
    (tmp / "submissions").mkdir(parents=True)
    led = {"files": {("%012d" % i): e for i, e in enumerate(files)}}
    (tmp / "submissions" / "ledger.json").write_text(json.dumps(led), encoding="utf-8")
    for n, m in (runs or {}).items():
        (tmp / "runs" / ("v%d" % n)).mkdir(parents=True)
        (tmp / "runs" / ("v%d" % n) / "manifest.json").write_text(json.dumps(m), encoding="utf-8")
    return SimpleNamespace(workspace=tmp, backup_repo=tmp / "backup")


class Groups(unittest.TestCase):
    def test_versions_of_one_file_are_one_group(self):
        ws = make_ws([entry("a1.xlsx", "Algeria/a.xlsx", "r2 adm"), entry("a2.xlsx", "Algeria/z/a.zip/a.xlsx", "r2 adm"),
                      entry("a3.xlsx", "Algeria/b.xlsx", "r2 adm"), entry("b1.xlsx", "Algeria/other.xlsx", "other")])
        folder = {p: {"size": 100, "modified": "x"} for p in ("Algeria/a.xlsx", "Algeria/b.xlsx", "Algeria/other.xlsx", "Algeria/z/a.zip")}
        d = sv.build(ws, folder)
        self.assertEqual(d["waiting"], 4)
        self.assertEqual(d["waiting_distinct"], 2)
        self.assertEqual(len(d["groups"]), 1)
        self.assertEqual(len(next(iter(d["groups"].values()))["ids"]), 3)


class Zips(unittest.TestCase):
    def test_zip_whose_files_were_read_is_not_unread(self):
        ws = make_ws([entry("in.xlsx", "Algeria/pack.zip/in.xlsx", "in")])
        folder = {"Algeria/pack.zip": {"size": 5, "modified": "x"}}
        self.assertEqual(sv.build(ws, folder)["not_inspected"], [])

    def test_new_file_is_listed_with_its_country(self):
        ws = make_ws([entry("in.xlsx", "Algeria/in.xlsx", "in")])
        folder = {"Algeria/in.xlsx": {"size": 100, "modified": "x"}, "Angola Admin Data/new.xlsx": {"size": 9, "modified": "2026-11-19 10:00"}}
        d = sv.build(ws, folder)
        self.assertEqual([f["File"] for f in d["not_inspected"]], ["Angola Admin Data/new.xlsx"])
        self.assertEqual(d["not_inspected"][0]["Country"], "Angola")


class NotAdminData(unittest.TestCase):
    def test_kinds(self):
        self.assertEqual(sv._kind("NOT ADMIN DATA: looks like an LQAS file; no row with column names"), "LQAS")
        self.assertEqual(sv._kind("NOT ADMIN DATA: looks like a monitoring (IM) file; x"), "monitoring (IM)")
        self.assertEqual(sv._kind("1 row(s) left out; layout: mapped"), "")
        self.assertEqual(sv._kind_group("monitoring (IM)"), "IM / monitoring")
        self.assertEqual(sv._kind_group("a vaccine vials tally"), "other")

    def test_not_admin_files_hold_no_records(self):
        ws = make_ws([entry("q.xlsx", "Algeria/q.xlsx", "q", status_="blocked", new=0, clean=0, why="NOT ADMIN DATA: looks like an LQAS file; x"),
                      entry("a.xlsx", "Algeria/a.xlsx", "a", held=5)])
        d = sv.build(ws, {"Algeria/q.xlsx": {"size": 100, "modified": "x"}, "Algeria/a.xlsx": {"size": 100, "modified": "x"}})
        self.assertEqual(d["not_admin"], 1)
        self.assertEqual(d["held_back"], 5)
        self.assertEqual(d["blocked_admin"], 0)


class AddedByBuild(unittest.TestCase):
    def test_file_added_by_a_published_build_is_not_waiting(self):
        run = {"build": {"ok": True, "submissions": ["a.xlsx"]}, "published": {"at": "2026-11-19 13:00:00"}}
        ws = make_ws([entry("a.xlsx", "Algeria/a.xlsx", "a", inspected="2026-11-19 12:00")], runs={7: run})
        d = sv.build(ws, {"Algeria/a.xlsx": {"size": 100, "modified": "x"}})
        self.assertEqual(d["added"], 1)
        self.assertEqual(d["clean_new"], 0)
        self.assertEqual(d["rows"][0]["Added in"], "v7")

    def test_a_later_inspection_resets_it(self):
        run = {"build": {"ok": True, "submissions": ["a.xlsx"]}, "published": {"at": "2026-11-19 13:00:00"}}
        ws = make_ws([entry("a.xlsx", "Algeria/a.xlsx", "a", inspected="2026-11-19 14:00")], runs={7: run})
        d = sv.build(ws, {"Algeria/a.xlsx": {"size": 100, "modified": "x"}})
        self.assertEqual(d["added"], 0)


class HeldReasons(unittest.TestCase):
    def test_reasons_in_plain_words(self):
        ws = make_ws([])
        with pd.ExcelWriter(ws.workspace / "submissions" / "Submissions_report.xlsx") as w:
            pd.DataFrame({"Country": ["CHAD", "CHAD", "ETHIOPIA", "DRC"],
                          "Hold_reason": ["possible duplicate: same place ...", "same names as several live records, none identical", "validation error: Target population missing or zero",
                                          "missing after standardising: Province"]}).to_excel(w, sheet_name="Held_back_records", index=False)
        got = {r["Reason"][:12]: r["Records"] for r in sv.held_reasons(ws)}
        self.assertEqual(sum(got.values()), 4)
        self.assertEqual(len(got), 4)


class PrunePrepared(unittest.TestCase):
    def test_clean_and_held_files_are_kept(self):
        e = entry("abcdef.xlsx", "Algeria/a.xlsx", "a", prepared_clean="prepared/abcdef_clean.xlsx")
        ws = make_ws([e])
        pdir = ws.workspace / "submissions" / "prepared"
        pdir.mkdir()
        for n in ("abcdef.xlsx", "abcdef_clean.xlsx", "abcdef_held.xlsx", "gone.xlsx"):
            (pdir / n).write_bytes(b"x")
        stub = SimpleNamespace(workspace=ws.workspace, store=SimpleNamespace(list=lambda p: [], delete=lambda *a, **k: None), _forget=lambda p: None)
        Workspace.prune_prepared(stub)
        self.assertEqual(sorted(p.name for p in pdir.iterdir()), ["abcdef.xlsx", "abcdef_clean.xlsx", "abcdef_held.xlsx"])


class NextActions(unittest.TestCase):
    def test_all_quiet(self):
        self.assertEqual([a["level"] for a in status.next_actions({"submissions": {"configured": True}})], ["ok"])

    def test_priorities(self):
        snap = {"lock": {"who": "X", "what": "Autopilot", "since": "2026-11-19T10:00"},
                "live_file": {"modified_utc": "2026-11-19 12:00", "modified_by": "Y"}, "newest_backup": {"saved_utc": "2026-11-18 12:00"},
                "build_waiting_to_be_published": {"version": 9, "state": "ready to publish"},
                "submissions": {"configured": True, "not_inspected": 2, "waiting_files": 5, "waiting_distinct_files": 3, "records_held_back": 7,
                                "held_back_by_reason": {"No target population": 7}},
                "last_job": {"title": "Publish", "status": "failed", "message": "x"}}
        levels = [a["level"] for a in status.next_actions(snap)]
        self.assertEqual(levels[0], "wait")
        self.assertIn("do", levels)
        self.assertEqual(levels.count("look"), 3)
        self.assertNotIn("ok", levels)


class FollowUp(unittest.TestCase):
    def make(self):
        tmp = Path(tempfile.mkdtemp())
        (tmp / "submissions" / "feedback_by_country").mkdir(parents=True)
        pd.DataFrame({"Country": ["NIGERIA", "NIGERIA", "MALI"], "Records": [4, 6, 0]}).to_excel(tmp / "submissions" / "Feedback_to_countries.xlsx", sheet_name="Feedback", index=False)
        pd.DataFrame({"Country": ["NIGERIA"], "Days_since_start": [300]}).to_excel(tmp / "submissions" / "Pending_admin_data.xlsx", sheet_name="Pending_now", index=False)
        (tmp / "submissions" / "feedback_by_country" / "Feedback_NIGERIA_2026-11-19.xlsx").write_bytes(b"x")
        return SimpleNamespace(workspace=tmp)

    def test_cycle_to_send_sent_remind_answered(self):
        ws = self.make()
        st = lambda c: next(r["Follow-up"] for r in followup.table(ws) if r["Country"] == c)   # noqa: E731
        self.assertEqual(st("NIGERIA"), "To send")
        followup.add_entry(ws, "nigeria", "sent", "T")
        self.assertEqual(st("NIGERIA"), "Sent, waiting for an answer")
        log = followup.load_log(ws)
        log["entries"][0]["at"] = (dt.datetime.now() - dt.timedelta(days=20)).strftime("%Y-%m-%d %H:%M")
        (ws.workspace / "submissions" / "feedback_log.json").write_text(json.dumps(log), encoding="utf-8")
        self.assertTrue(st("NIGERIA").startswith("No answer for 20"))
        followup.add_entry(ws, "NIGERIA", "answered", "T")
        self.assertTrue(st("NIGERIA").startswith("Answered"))

    def test_unknown_kind_is_refused(self):
        with self.assertRaises(ValueError):
            followup.add_entry(self.make(), "MALI", "deleted", "T")



class HeldTriageAndClose(unittest.TestCase):
    def report(self, ws):
        h = pd.DataFrame({"File": ["f.xlsx"] * 3 + ["g.xlsx"], "Country": ["NIGERIA"] * 3 + ["CHAD"],
                          "Hold_reason": ["possible duplicate: same place ..."] * 3 + ["same names as several live records"],
                          "Triage": ["Probably the same campaign re-sent"] * 2 + ["Needs a look"] * 2,
                          "Held_key": ["k1", "k2", "k3", "k4"]})
        with pd.ExcelWriter(ws.workspace / "submissions" / "Submissions_report.xlsx") as w:
            h.to_excel(w, sheet_name="Held_back_records", index=False)

    def test_close_reopen_and_counts(self):
        from opscenter import heldclose
        ws = make_ws([])
        self.report(ws)
        self.assertEqual({(g["File"], g["Triage"]): g["Records"] for g in heldclose.groups(ws)},
                         {("f.xlsx", "Probably the same campaign re-sent"): 2, ("f.xlsx", "Needs a look"): 1, ("g.xlsx", "Needs a look"): 1})
        e = heldclose.close_group(ws, "f.xlsx", "Probably the same campaign re-sent", "T", "same as live")
        self.assertEqual(e["n"], 2)
        self.assertEqual(heldclose.closed_in_report(ws), 2)
        self.assertEqual(sum(r["Records"] for r in sv.held_reasons(ws)), 2)          # 4 held - 2 closed
        with self.assertRaises(ValueError):
            heldclose.close_group(ws, "f.xlsx", "Probably the same campaign re-sent", "T")       # nothing left to close
        heldclose.reopen(ws, e["id"])
        self.assertEqual(heldclose.closed_in_report(ws), 0)

    def test_close_all_files_of_one_triage(self):
        from opscenter import heldclose
        ws = make_ws([])
        h = pd.DataFrame({"File": ["f.xlsx"] * 2 + ["g.xlsx"] * 2 + ["h.xlsx"], "Country": ["NIGERIA", "NIGERIA", "CHAD", "CHAD", "CHAD"],
                          "Hold_reason": ["possible duplicate"] * 5,
                          "Triage": ["Probably the same campaign re-sent"] * 4 + ["Needs a look"],
                          "Held_key": ["k1", "k2", "k3", "k4", "k5"]})
        with pd.ExcelWriter(ws.workspace / "submissions" / "Submissions_report.xlsx") as w:
            h.to_excel(w, sheet_name="Held_back_records", index=False)
        es = heldclose.close_triage(ws, "Probably the same campaign re-sent", "T", "re-sent")
        self.assertEqual(sorted((e["file"], e["n"]) for e in es), [("f.xlsx", 2), ("g.xlsx", 2)])   # one entry per file
        self.assertEqual({(g["File"], g["Triage"]) for g in heldclose.groups(ws)}, {("h.xlsx", "Needs a look")})   # 'Needs a look' untouched
        with self.assertRaises(ValueError):
            heldclose.close_triage(ws, "Probably the same campaign re-sent", "T")
        heldclose.reopen(ws, es[0]["id"])                                                           # each file reopens on its own
        self.assertEqual(heldclose.closed_in_report(ws), 2)

    def test_engine_triage_and_key(self):
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "engine"))
        import submissions as sm
        dup = "possible duplicate: same place, date and vaccine ... other figures"
        self.assertEqual(sm.triage_label(dup, 1005, 1000, 500, 500), sm.TRIAGE_SAME)
        self.assertEqual(sm.triage_label(dup, 1005, 1000, 700, 500), sm.TRIAGE_FAR)
        self.assertEqual(sm.triage_label(dup, 1200, 1000, 500, 500), sm.TRIAGE_LOOK)
        self.assertEqual(sm.triage_label("same names as several live records", 1, 1, 1, 1), sm.TRIAGE_LOOK)
        self.assertEqual(sm.held_key("DRC", " Kasai", "Dibaya", "2026-04-26 00:00:00", "R", "Rnd1", "nOPV2"), "drc|kasai|dibaya|2026-04-26|r|rnd1|nopv2")



class Provenance(unittest.TestCase):
    def test_records_are_traced_to_file_and_build(self):
        tmp = Path(tempfile.mkdtemp())
        for n, pub in ((28, {"at": "2026-11-19T13:05:00Z"}), (29, None)):
            d = tmp / "runs" / ("v%d" % n)
            d.mkdir(parents=True)
            m = {"build": {"ok": True, "added_records": 2, "submissions": ["a.xlsx"]}}
            if pub:
                m["published"] = pub
            (d / "manifest.json").write_text(json.dumps(m), encoding="utf-8")
        pd.DataFrame({"Country": ["ANGOLA", "ANGOLA"], "Province": ["P", "P"], "District": ["D1", "D2"], "Response": ["r", "r"], "Source_file": ["a.xlsx", "a.xlsx"],
                      "SIA_date": ["2026-10-01", "2026-10-03"]}).to_csv(tmp / "runs" / "v28" / "records_added_from_submissions_v28.csv", index=False)
        ws = SimpleNamespace(workspace=tmp)
        t = provenance.table(ws)
        self.assertEqual(len(t), 2)    # v29 has no record list: shown from its manifest, without record lines
        v28 = next(r for r in t if r["Build"] == "v28")
        self.assertEqual((v28["Records"], v28["Districts"], v28["State"], v28["First campaign date"]), (2, 2, "in the live file", "2026-10-01"))
        self.assertEqual(next(r for r in t if r["Build"] == "v29")["State"], "built, not published yet")



class IncrementalInspection(unittest.TestCase):
    """inspect_folder reuses the result of a file that did not change, and reads everything again when the live file, the file or the rules change.
    prepare_file (the real reading) is replaced by a counter, so only the reuse logic is tested."""

    def setUp(self):
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "engine"))
        import types
        import submissions as sm
        self.sm = sm
        self.tmp = Path(tempfile.mkdtemp())
        self.folder = self.tmp / "in"
        (self.folder / "ALGERIA").mkdir(parents=True)
        (self.folder / "ALGERIA" / "a.xlsx").write_bytes(b"file a")
        (self.folder / "ALGERIA" / "b.xlsx").write_bytes(b"file b")
        self.out = self.tmp / "out"
        bmod = types.ModuleType("fake_builder")
        bmod.__file__ = str(self.tmp / "fake_builder.py")
        (self.tmp / "fake_builder.py").write_text("x = 1", encoding="utf-8")
        self.ctx = SimpleNamespace(builder=bmod, live=pd.DataFrame({"Country": ["ALGERIA"], "v": [1]}), lookup=pd.DataFrame({"r": [1]}), geo=None)
        self.calls = []
        self.orig = (sm.prepare_file, sm.learn_profile, sm.write_report, sm.overlap_between_files, sm.folder_country_of)

        def fake_prepare(path, ctx, prof, cols, folder_country=None):
            self.calls.append(Path(path).name)
            h = sm.sha256_of(path)
            P = pd.DataFrame({"Country": ["ALGERIA", "ALGERIA"], "District": ["d1", "d2"]})
            ctx._file_records = getattr(ctx, "_file_records", {})
            ctx._file_records[h] = (Path(path).name, P.copy())
            s = {"name": Path(path).name, "size": 6, "hash": h, "layout": "template", "rows_read": 2, "rows_used": 2, "excluded": [], "new": 2, "existing_same": 0,
                 "existing_different": 0, "existing_units": 0, "qc_errors": 0, "qc_warnings": 0, "countries": "ALGERIA", "status": "ready", "why": "",
                 "codes": [], "lookup_rounds": 0, "lookup_ok": 0}
            return s, P, {"hold": ["", "possible duplicate"], "held_other": pd.DataFrame(), "_builder": ctx.builder}
        sm.prepare_file = fake_prepare
        sm.learn_profile = lambda *a, **k: {}
        sm.write_report = lambda *a, **k: None
        sm.overlap_between_files = lambda *a, **k: pd.DataFrame()
        sm.folder_country_of = lambda *a, **k: "ALGERIA"

    def tearDown(self):
        sm = self.sm
        sm.prepare_file, sm.learn_profile, sm.write_report, sm.overlap_between_files, sm.folder_country_of = self.orig

    def run_it(self):
        self.calls.clear()
        self.sm.inspect_folder(self.ctx, self.folder, self.out, ["Country", "District"], log=lambda *a: None)
        return sorted(self.calls)

    def test_reuse_and_invalidation(self):
        self.assertEqual(self.run_it(), ["a.xlsx", "b.xlsx"])            # first time: both read
        self.assertEqual(self.run_it(), [])                              # nothing changed: nothing read again
        led = json.loads((self.out / "ledger.json").read_text(encoding="utf-8"))["files"]
        self.assertEqual(sorted(e["name"] for e in led.values()), ["a.xlsx", "b.xlsx"])
        self.assertTrue(all(e["held_new"] == 1 and e["clean_new"] == 1 for e in led.values()))   # the reused result still fills the ledger
        (self.folder / "ALGERIA" / "b.xlsx").write_bytes(b"file b changed")
        self.assertEqual(self.run_it(), ["b.xlsx"])                      # only the changed file is read again
        (self.folder / "ALGERIA" / "c.xlsx").write_bytes(b"file c")
        self.assertEqual(self.run_it(), ["c.xlsx"])                      # a new file: only that one
        self.ctx.live = pd.DataFrame({"Country": ["ALGERIA"], "v": [2]})   # the live file changed (a publish): every file is read again
        self.assertEqual(self.run_it(), ["a.xlsx", "b.xlsx", "c.xlsx"])
        self.assertEqual(self.run_it(), [])

    def test_missing_prepared_file_is_read_again(self):
        self.run_it()
        for f in (self.out / "prepared").glob("*_held.xlsx"):             # a clean-up removed what the result points to
            f.unlink()
        self.assertEqual(self.run_it(), ["a.xlsx", "b.xlsx"])

    def test_switch_off(self):
        import os
        self.run_it()
        os.environ["OPS_NO_INSPECT_CACHE"] = "1"
        try:
            self.assertEqual(self.run_it(), ["a.xlsx", "b.xlsx"])
        finally:
            del os.environ["OPS_NO_INSPECT_CACHE"]


if __name__ == "__main__":
    unittest.main()

