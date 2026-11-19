"""What the Submissions tab shows: the files of the countries, what the last inspection found, and the operator's decisions."""
import re

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


DATA_EXT = (".xlsx", ".xlsm", ".xls", ".xlsb", ".csv")


def _container(path):
    """The file of the folder a ledger path belongs to: a file inside a .zip is listed as '<zip>/<file>'."""
    i = path.lower().find(".zip/")
    return path[:i + 4] if i >= 0 else path


def _zip_covered(ws, path, known_names):
    """A .zip of the folder with no ledger entry under its own name: True when every data file inside it was read under another path
    (a second copy of the same zip), so it is not new."""
    try:
        import zipfile
        with zipfile.ZipFile(ws.workspace / "submissions_in" / path) as z:
            names = [n.rsplit("/", 1)[-1] for n in z.namelist() if n.lower().endswith(DATA_EXT) and not n.endswith("/")]
    except Exception:
        return False
    return bool(names) and all(n in known_names for n in names)


def _kind(why):
    """What a file that is not admin data is (the inspection writes 'NOT ADMIN DATA: looks like an LQAS file; ...'), or '' for an admin file."""
    m = re.search(r"NOT ADMIN DATA: looks like (?:an? )?(.*?)(?: file)?(?:;|$)", why or "")
    return m.group(1).strip() if m else ""


def _kind_group(kind):
    k = kind.lower()
    return "LQAS" if "lqas" in k else "AEFI" if "aefi" in k else "IM / monitoring" if "monitoring" in k or "(im)" in k else "other"


# why a new-looking record is kept out of the live file, in plain words (first match wins; the engine writes the technical reason)
HOLD_KINDS = (
    ("missing after standardising", "A key variable is empty (country, province, district, date, round, campaign or vaccine)"),
    ("not a number", "The target or the number vaccinated is not a number"),
    ("Target population missing", "No target population (missing or zero)"),
    ("validation error", "Failed a data check"),
    ("another country", "Record of another country than the folder it was sent in"),
    ("possible duplicate", "Looks like a record already in the live file (same place and date, other campaign name or round)"),
    ("same names as several live records", "Matches several live records, none of them identical"),
)
_HELD = {}


def held_reasons(ws):
    """[{'Reason', 'Records', 'Countries'}] for the records the last inspection held back, from the report workbook (read once per version)."""
    p = ws.workspace / "submissions" / "Submissions_report.xlsx"
    try:
        key = (str(p), p.stat().st_mtime_ns)
    except OSError:
        return []
    if key not in _HELD:
        try:
            h = pd.read_excel(p, sheet_name="Held_back_records", usecols=["Country", "Hold_reason"], dtype=str)
        except Exception:
            h = None
        out = []
        if h is not None and len(h):
            def label(r):
                r = str(r)
                return next((lab for k, lab in HOLD_KINDS if k in r), "Other reason (see the report)")
            h["Reason"] = h["Hold_reason"].map(label)
            for reason, g in h.groupby("Reason"):
                out.append({"Reason": reason, "Records": len(g), "Countries": ", ".join(sorted(set(g["Country"].dropna())))})
            out.sort(key=lambda x: -x["Records"])
        _HELD.clear()
        _HELD[key] = out
    return _HELD[key]


def _country_of(e, path):
    c = (e.get("countries") or e.get("country_folder") or "").strip()
    if c:
        return c
    first = path.split("/", 1)[0]
    return re.sub(r"\s*admin data.*$", "", first, flags=re.I).strip() or first


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
                     "Inspected": e.get("last_inspected", ""), "Why": e.get("why", ""), "Note": e.get("note", ""),
                     "First seen": e.get("first_seen", ""), "Country": _country_of(e, path), "Not admin data": _kind(e.get("why", "")),
                     "In folder (modified)": (folder.get(_container(path)) or {}).get("modified", ""),
                     "Version": "changed version" if any(x is not e and (x.get("path") or x.get("name")) == path and x.get("first_seen", "") < e.get("first_seen", "")
                                                          for x in led.get("files", {}).values()) else ""})
    in_ledger = {r["File"] for r in rows}
    containers = {_container(p) for p in in_ledger if ".zip/" in p.lower()}
    known_names = {p.rsplit("/", 1)[-1] for p in in_ledger}
    new_files = [{"Country": _country_of({}, p), "File": p, "Modified": f["modified"], "Size KB": round(f["size"] / 1024)}
                 for p, f in sorted(folder.items())
                 if p not in inspected and p not in in_ledger and p not in containers
                 and not (p.lower().endswith(".zip") and _zip_covered(ws, p, known_names))]
    arrivals = sorted(({k: r[k] for k in ("First seen", "Country", "File", "Status", "Not admin data", "In folder (modified)", "Version", "Layout", "Records read", "New",
                                        "Clean new", "Held back", "Why")} for r in rows),
                      key=lambda a: (a["First seen"], a["Country"], a["File"]), reverse=True)
    kinds = {}
    for r in rows:
        if r["Not admin data"]:
            g = _kind_group(r["Not admin data"])
            kinds[g] = kinds.get(g, 0) + 1
    last_inspected = max((r["Inspected"] for r in rows if r["Inspected"]), default="")
    changed = changed_files
    return {"configured": True, "rows": rows, "not_inspected": new_files, "arrivals": arrivals, "last_inspected": last_inspected, "held_reasons": held_reasons(ws),
            "nothing_new": sum(1 for r in rows if r["Status"] == "nothing new"), "not_admin": sum(kinds.values()), "not_admin_kinds": kinds,
            "blocked_admin": sum(1 for r in rows if r["Status"] == "blocked" and not r["Not admin data"]), "changed": changed, "in_folder": len(folder),
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
