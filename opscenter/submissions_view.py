"""What the Submissions tab shows: the files of the countries, what the last inspection found, and the operator's decisions."""
import pandas as pd

from . import config
from .pipelines import sub_ledger
from .store import Store


def list_folder(sub):
    """Every .xlsx / .xlsm / .csv below the submissions folder: {relative path: {'size', 'modified'}}."""
    out = {}

    def rec(path, rel):
        for c in sub.list(path):
            r = (rel + "/" + c["name"]) if rel else c["name"]
            if c["is_dir"]:
                rec((path + "/" + c["name"]) if path else c["name"], r)
            elif c["name"].lower().endswith((".xlsx", ".xlsm", ".xls", ".xlsb", ".csv", ".zip")) and not c["name"].startswith(("~$", ".")):
                out[r] = {"size": c["size"], "modified": (c["modified"] or "")[:16].replace("T", " ")}
    rec("", "")
    return out


def _auto_names(ws):
    """Names of the files the automatic rules take (the inspection writes them in Submissions_summary.xlsx, sheet Files, column Auto)."""
    try:
        f = pd.read_excel(ws.workspace / "submissions" / "Submissions_summary.xlsx", sheet_name="Files")
        return set(f.loc[f["Auto"].astype(bool), "File"].astype(str))
    except Exception:
        return set()


def _pending_count(ws):
    """(rounds pending with nothing received, rounds to check for another campaign name) from Pending_admin_data.xlsx, or None."""
    try:
        x = pd.read_excel(ws.workspace / "submissions" / "Pending_admin_data.xlsx", sheet_name=None)
        return len(x["Pending_now"]), len(x.get("Check_other_name", []))
    except Exception:
        return None


def load(store, ws):
    if not config.SUBMISSIONS_URL:
        return {"configured": False}
    ws.prepare()
    ws.pull_submissions()
    led = sub_ledger(ws)
    folder = list_folder(Store(store.g, config.SUBMISSIONS_URL))
    auto = _auto_names(ws)
    rows, inspected, changed_files = [], set(), []
    for h, e in led.get("files", {}).items():
        if not e.get("present", True) or e.get("superseded"):
            continue
        path = e.get("path") or e.get("name")
        f = folder.get(path)
        changed = f is None or f["size"] != e.get("size")
        if f is not None and not changed:
            inspected.add(path)
        elif f is not None:
            changed_files.append(path)
        rows.append({"id": h[:12], "File": path, "Layout": e.get("layout", ""), "Status": e.get("status", ""),
                     "Decision": e.get("decision") or ("cannot be accepted" if e.get("status") == "blocked" else
                                           "changed since inspected" if changed and f is not None else
                                           "taken by rules" if e.get("name") in auto else "waiting"),
                     "Decided by": e.get("decided_by", ""), "Countries": e.get("countries", ""),
                     "Records read": e.get("rows_used", ""), "New": e.get("new", ""), "Already there": e.get("existing_same", ""),
                     "Other figures": e.get("existing_different", ""), "Several units": e.get("existing_units", ""),
                     "Possible duplicates": e.get("possible_dup", ""), "Also in another file": e.get("overlap", ""),
                     "Clean new": e.get("clean_new", ""), "Held back": e.get("held_new", ""),
                     "Errors": e.get("qc_errors", ""), "Warnings": e.get("qc_warnings", ""), "Left out": e.get("excluded", ""),
                     "Inspected": e.get("last_inspected", ""), "Why": e.get("why", ""), "Note": e.get("note", "")})
    new_files = [{"File": p, "Modified": f["modified"], "Size KB": round(f["size"] / 1024)} for p, f in sorted(folder.items()) if p not in inspected
                 and not any(r["File"] == p for r in rows)]
    changed = changed_files
    return {"configured": True, "rows": rows, "not_inspected": new_files, "changed": changed, "in_folder": len(folder),
            "accepted": sum(1 for r in rows if r["Decision"] == "accepted"),
            "by_rules": sum(1 for r in rows if r["Decision"] == "taken by rules"),
            "clean_new": sum(int(r["Clean new"] or 0) for r in rows if r["Status"] != "blocked"),
            "held_back": sum(int(r["Held back"] or 0) for r in rows),
            "pending": _pending_count(ws),
            "summary": (ws.workspace / "submissions" / "Submissions_summary.xlsx").is_file(),
            "pending_file": (ws.workspace / "submissions" / "Pending_admin_data.xlsx").is_file(),
            "feedback_all": (ws.workspace / "submissions" / "Feedback_to_countries.xlsx").is_file(),
            "feedback": sorted(q.name for q in (ws.workspace / "submissions" / "feedback_by_country").glob("Feedback_*.xlsx"))
            if (ws.workspace / "submissions" / "feedback_by_country").is_dir() else [],
            "waiting": sum(1 for r in rows if r["Decision"] in ("waiting", "changed since inspected") and r["Status"] not in ("blocked", "nothing new")),
            "report": (ws.workspace / "submissions" / "Submissions_report.xlsx").is_file()}
