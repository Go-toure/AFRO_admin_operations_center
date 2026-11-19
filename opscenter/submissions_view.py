"""What the Submissions tab shows: the files of the countries, what the last inspection found, and the operator's decisions."""
import hashlib
import re

import pandas as pd

from . import config, heldclose
from .pipelines import local_runs, sub_ledger
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
def held_reasons(ws):
    """[{'Reason', 'Records', 'Countries'}] for the records the last inspection held back and nobody closed (read once per version of the report)."""
    h = heldclose.open_table(ws)
    if not len(h):
        return []

    def label(r):
        r = str(r)
        return next((lab for k, lab in HOLD_KINDS if k in r), "Other reason (see the report)")
    h = h.assign(Reason=h["Hold_reason"].map(label))
    out = [{"Reason": reason, "Records": len(g), "Countries": ", ".join(sorted(set(g["Country"].dropna())))} for reason, g in h.groupby("Reason")]
    out.sort(key=lambda x: -x["Records"])
    return out


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
    return build(ws, list_folder(Store(store.g, config.SUBMISSIONS_URL)))


def list_local(ws):
    """The same listing as list_folder, from the copy of the folder on this machine (what the last job read): no network."""
    out = {}
    base = ws.workspace / "submissions_in"
    if base.is_dir():
        import datetime as dt
        for p in base.rglob("*"):
            if p.is_file() and p.suffix.lower() in DATA_EXT + (".zip",) and not p.name.startswith(("~$", ".")):
                st = p.stat()
                out[p.relative_to(base).as_posix()] = {"size": st.st_size, "modified": dt.datetime.utcfromtimestamp(st.st_mtime).strftime("%Y-%m-%d %H:%M")}
    return out


def load_local(ws):
    """What load() returns, from the files on this machine only (used at the end of a job, for the status file)."""
    if not config.SUBMISSIONS_URL:
        return {"configured": False}
    return build(ws, list_local(ws))


def build(ws, folder):
    led = sub_ledger(ws)
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
                     "_name": e.get("name", ""), "Added in": "",
                     "First seen": e.get("first_seen", ""), "Country": _country_of(e, path), "Not admin data": _kind(e.get("why", "")),
                     "_gkey": (e.get("country_folder", ""), e.get("stem", "")),
                     "In folder (modified)": (folder.get(_container(path)) or {}).get("modified", ""),
                     "Version": "changed version" if any(x is not e and (x.get("path") or x.get("name")) == path and x.get("first_seen", "") < e.get("first_seen", "")
                                                          for x in led.get("files", {}).values()) else ""})
    # files whose records a published build has already added (a build published after the file was inspected): they are in the live file now,
    # so they are not "waiting for the next build" any more (until the next inspection says so itself)
    added_by = {}
    for n, m in local_runs(ws):
        pub = m.get("published") or {}
        if pub.get("at"):
            for nm in (m.get("build", {}).get("submissions") or []):
                added_by.setdefault(nm, []).append((str(pub["at"])[:16], n))
    for r in rows:
        for at, n in sorted(added_by.get(r["_name"], [])):
            if str(r["Inspected"])[:16] <= at:
                r["Added in"] = "v%d" % n
        if r["Added in"]:
            r["Decision"] = "added to the live file (%s)" % r["Added in"]
            r["Clean new"] = 0
    # the same file sent more than once (other folder, a zip, a later version): same country folder and same name once the date and the copy marks
    # are removed (the engine's 'stem'). One decision can be taken for the whole group.
    gmembers = {}
    for r in rows:
        if r["Status"] != "blocked" and r["_gkey"][1]:
            gmembers.setdefault(r["_gkey"], []).append(r)
    groups = {}
    for key, mem in gmembers.items():
        gid = hashlib.sha1("|".join(key).encode("utf-8")).hexdigest()[:8]
        for r in mem:
            r["Group"], r["Versions"] = gid, len(mem)
        if len(mem) > 1:
            groups[gid] = {"ids": [r["id"] for r in mem], "label": "%s: %s (%d versions)" % (mem[0]["Country"], mem[0]["File"].rsplit("/", 1)[-1], len(mem)),
                           "files": [r["File"] for r in mem]}
    for r in rows:
        r.setdefault("Group", ""), r.setdefault("Versions", 1)
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
            "added": sum(1 for r in rows if r["Added in"]),
            "added_records": sum(int(r["New"] or 0) for r in rows if r["Added in"]),
            "clean_new": sum(int(r["Clean new"] or 0) for r in rows if r["Status"] != "blocked"),
            "held_back": sum(int(r["Held back"] or 0) for r in rows) - heldclose.closed_in_report(ws),
            "held_closed": sum(int(g["Records"]) for g in heldclose.closed_groups(ws)),
            "pending": _pending_count(ws),
            "summary": (ws.workspace / "submissions" / "Submissions_summary.xlsx").is_file(),
            "pending_file": (ws.workspace / "submissions" / "Pending_admin_data.xlsx").is_file(),
            "feedback_all": (ws.workspace / "submissions" / "Feedback_to_countries.xlsx").is_file(),
            "feedback": sorted(q.name for q in (ws.workspace / "submissions" / "feedback_by_country").glob("Feedback_*.xlsx"))
            if (ws.workspace / "submissions" / "feedback_by_country").is_dir() else [],
            "waiting": sum(1 for r in rows if r["Decision"] in ("waiting", "changed since inspected") and r["Status"] not in ("blocked", "nothing new")),
            "waiting_distinct": len({(r["Group"] or r["id"]) for r in rows if r["Decision"] in ("waiting", "changed since inspected") and r["Status"] not in ("blocked", "nothing new")}),
            "groups": groups,
            "report": (ws.workspace / "submissions" / "Submissions_report.xlsx").is_file()}
