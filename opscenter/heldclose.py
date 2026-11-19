"""Held records that a person closes as 'duplicate, not added'.

The inspection holds back every new-looking record that looks like a live record under another campaign name, round or date (it never drops one
silently) and, since 1.7.2, sorts them (Triage column of the sheet Held_back_records): probably the same campaign sent again, figures that differ a lot,
needs a look. A person can close a whole group in one step. Closing changes nothing in the live file: it only says 'these records are duplicates, do not
add them and do not ask again'. The decision is kept in submissions/held_closed.json (SharePoint folder); the engine reads it at the next inspection and
no longer holds those records, so they leave the feedback to the countries too. Until then this module hides them from the counts."""
import datetime as dt
import hashlib
import json

import pandas as pd

_CACHE = {}
COLS = ["File", "Country", "Hold_reason", "Triage", "Held_key"]


def _report(ws):
    return ws.workspace / "submissions" / "Submissions_report.xlsx"


def _closed_path(ws):
    return ws.workspace / "submissions" / "held_closed.json"


def load_closed(ws):
    try:
        d = json.loads(_closed_path(ws).read_text(encoding="utf-8"))
        return d if isinstance(d.get("closed"), list) else {"closed": []}
    except (OSError, ValueError):
        return {"closed": []}


def closed_keys(ws):
    return {k for g in load_closed(ws)["closed"] for k in g.get("keys", [])}


def held_table(ws):
    """The held-back records of the last inspection (File, Country, Hold_reason, Triage, Held_key), read once per version of the report. Triage and
    Held_key are empty for a report written before 1.7.2 (inspect again)."""
    p = _report(ws)
    try:
        key = (str(p), p.stat().st_mtime_ns)
    except OSError:
        return pd.DataFrame(columns=COLS)
    if key not in _CACHE:
        try:
            names = pd.read_excel(p, sheet_name="Held_back_records", nrows=0).columns
            h = pd.read_excel(p, sheet_name="Held_back_records", usecols=[c for c in COLS if c in names], dtype=str)
        except Exception:
            h = pd.DataFrame(columns=COLS)
        for c in COLS:
            if c not in h.columns:
                h[c] = ""
        h = h[COLS].fillna("")
        _CACHE.clear()
        _CACHE[key] = h
    return _CACHE[key]


def open_table(ws):
    """The held records not closed by a person."""
    h = held_table(ws)
    ck = closed_keys(ws)
    return h[~h["Held_key"].isin(ck)] if ck else h


def closed_in_report(ws):
    """How many records of the last report are closed by a person (the report is not rewritten until the next inspection)."""
    h = held_table(ws)
    ck = closed_keys(ws)
    return int(h["Held_key"].isin(ck).sum()) if ck and len(h) else 0


def groups(ws):
    """[{'File', 'Triage', 'Records', 'Countries'}]: the open held records by file and triage (the unsorted ones of an old report are 'Not sorted yet')."""
    h = open_table(ws)
    if not len(h):
        return []
    h = h.assign(T=h["Triage"].replace("", "Not sorted yet (inspect again)"))
    out = []
    for (f, t), g in h.groupby(["File", "T"]):
        out.append({"File": f, "Triage": t, "Records": len(g), "Countries": ", ".join(sorted(set(g["Country"])))})
    order = {"Probably the same campaign re-sent": 0, "Needs a look": 1, "Figures differ a lot from the live record": 2}
    out.sort(key=lambda r: (order.get(r["Triage"], 3), -r["Records"]))
    return out


def close_group(ws, file, triage, by, note=""):
    """Close every open held record of a file and triage group. Returns the entry (the caller holds the SharePoint lock; the job pushes the file)."""
    h = open_table(ws)
    g = h[(h["File"] == file) & (h["Triage"] == triage) & (h["Held_key"] != "")]
    if not len(g):
        raise ValueError("Nothing to close: no sorted held record of this file and group (inspect again to sort them).")
    d = load_closed(ws)
    gid = hashlib.sha1(("%s|%s|%s" % (file, triage, dt.datetime.now().isoformat())).encode("utf-8")).hexdigest()[:8]
    e = {"id": gid, "file": file, "triage": triage, "n": len(g), "keys": sorted(set(g["Held_key"])), "by": by,
         "at": dt.datetime.now().strftime("%Y-%m-%d %H:%M"), "note": (note or "").strip(), "countries": ", ".join(sorted(set(g["Country"])))}
    d["closed"].append(e)
    _write(ws, d)
    return e


def reopen(ws, gid):
    d = load_closed(ws)
    n0 = len(d["closed"])
    d["closed"] = [g for g in d["closed"] if g.get("id") != gid]
    if len(d["closed"]) == n0:
        raise ValueError("No closed group %s." % gid)
    _write(ws, d)


def closed_groups(ws):
    return [{"id": g["id"], "File": g["file"], "Triage": g["triage"], "Records": g["n"], "Closed by": g["by"], "On": g["at"], "Note": g.get("note", "")}
            for g in load_closed(ws)["closed"]]


def _write(ws, d):
    p = _closed_path(ws)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(d, indent=1, ensure_ascii=False), encoding="utf-8")
    tmp.replace(p)
