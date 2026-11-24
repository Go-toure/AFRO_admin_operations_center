"""What accepting a file really does, in plain numbers, read from the report of the last inspection (Submissions_report.xlsx).

Author: Gorgui Ba Toure

The Decide tab shows this before the operator presses Accept, and again in the confirmation window, so that nobody accepts
a file without knowing which records will enter the live file, which will not, and what else changes.

Rules the numbers follow (the same as the Build):
  - only the NEW records that are not held back are added;
  - records already in the live file are never changed (same figures or other figures);
  - possible duplicates and records that match several live records are not added;
  - INTEGRATED DATA: empty integrated cells of live records are completed from the file (Integrated_additions).
"""
import pandas as pd

SHEETS = ["Records", "Held_back_records", "Integrated_additions", "Integrated_interventions", "Decisions_needed"]
_cache = {}


def _report(ws):
    p = ws.workspace / "submissions" / "Submissions_report.xlsx"
    if not p.is_file():
        return None
    key = (str(p), p.stat().st_mtime_ns)
    if key not in _cache:
        _cache.clear()
        try:
            x = pd.read_excel(p, sheet_name=SHEETS)
        except Exception:
            x = {}
            for s in SHEETS:                     # a report written by an older engine can lack a sheet
                try:
                    x[s] = pd.read_excel(p, sheet_name=s)
                except Exception:
                    x[s] = pd.DataFrame()
        _cache[key] = x
    return _cache[key]


def _key(df):
    """The key the inspection gives a held record (Held_key): country|province|district|date|response|round|vaccine, in lower case."""
    d = pd.to_datetime(df["SIA_date"], errors="coerce").dt.strftime("%Y-%m-%d").fillna("")
    parts = [df[c].fillna("").astype(str).str.strip().str.lower() for c in ("Country", "Province", "District")]
    parts.append(d)
    parts += [df[c].fillna("").astype(str).str.strip().str.lower() for c in ("Response", "Round_Add", "Vaccine_type")]
    k = parts[0]
    for p in parts[1:]:
        k = k + "|" + p
    return k


def _span(s):
    d = pd.to_datetime(s, errors="coerce").dropna()
    if not len(d):
        return ""
    a, b = d.min().strftime("%Y-%m-%d"), d.max().strftime("%Y-%m-%d")
    return a if a == b else "%s to %s" % (a, b)


def preview(ws, names):
    """names: the file names (ledger 'name', as in the column File of the report) of one file or of all the versions of a file.
    Returns a dict, or None when there is no report to read."""
    x = _report(ws)
    if not x or not len(x.get("Records", [])):
        return None
    names = set(names)
    R = x["Records"]
    R = R[R["File"].isin(names)].copy()
    out = {"files": sorted(names), "read": len(R)}
    if not len(R):
        out.update(add=0, campaigns=[], held=[], ignored={}, integrated=None, interventions=[], open_questions=[])
        return out
    R["_k"] = _key(R)
    # the same record sent in several versions of the file counts once
    R = R.drop_duplicates(subset=["_k"], keep="first")
    st = R["Status"].fillna("").astype(str)
    new = R[st == "new"]

    # held back: not added, with the reason in plain words (the Held_back_records sheet has the technical reason)
    H = x.get("Held_back_records", pd.DataFrame())
    held_keys = set()
    held_rows = []
    if len(H) and "Held_key" in H.columns:
        Hn = H[H["File"].isin(names)]
        held_keys = set(Hn["Held_key"].dropna().astype(str))
    is_held = new["_k"].isin(held_keys)
    added = new[~is_held]
    held = new[is_held]
    if len(held) and len(H) and "Hold_reason" in H.columns:
        from .submissions_view import HOLD_KINDS
        why = H.drop_duplicates("Held_key").set_index("Held_key")["Hold_reason"].astype(str)

        def lab(k):
            r = why.get(k, "")
            return next((l for kk, l in HOLD_KINDS if kk in r), "Other reason (see the report)")
        held_rows = (held["_k"].map(lab).value_counts().rename_axis("Reason").reset_index(name="Records").to_dict("records"))
    elif len(held):
        held_rows = [{"Reason": "Held back (see the report)", "Records": int(len(held))}]

    camps = []
    if len(added):
        for (c, resp, rnd), g in added.groupby(["Country", "Response", "Round_Add"], dropna=False):
            camps.append({"Country": c, "Campaign": resp, "Round": rnd, "Vaccine": ", ".join(sorted(set(g["Vaccine_type"].dropna().astype(str)))),
                          "Dates": _span(g["SIA_date"]), "Records": int(len(g)), "Districts": int(g[["Province", "District"]].drop_duplicates().shape[0])})
        camps.sort(key=lambda r: (str(r["Country"]), str(r["Campaign"]), str(r["Round"])))

    ign = {
        "same figures": int(st.str.startswith("already in the live file, same figures").sum()),
        "other figures": int(st.str.startswith("already in the live file, other figures").sum()),
        "possible duplicate": int(st.str.startswith("possible duplicate").sum()),
        "several live records": int(st.str.startswith("same names as several live records").sum()),
    }
    ign = {k: v for k, v in ign.items() if v}

    I = x.get("Integrated_additions", pd.DataFrame())
    integ = None
    if len(I) and "File" in I.columns:
        Ii = I[I["File"].isin(names)]
        if len(Ii):
            integ = {"cells": int(len(Ii)), "records": int(Ii["Live_row"].nunique()),
                     "antigens": sorted(set(Ii["Antigen"].dropna().astype(str)))}

    J = x.get("Integrated_interventions", pd.DataFrame())
    found = []
    if len(J) and "File" in J.columns:
        for _, r in J[J["File"].isin(names)].groupby("Intervention", as_index=False)["Records with figures"].max().iterrows():
            found.append({"Intervention": str(r["Intervention"]), "Records": int(r["Records with figures"])})

    D = x.get("Decisions_needed", pd.DataFrame())
    qs = []
    if len(D) and "File" in D.columns:
        Dd = D[D["File"].isin(names)].drop_duplicates(["Question", "Proposed"])
        qs = [{"Question": str(r["Question"]), "Detail": str(r["Proposed"])} for _, r in Dd.iterrows()]

    out.update(add=int(len(added)), campaigns=camps, held=held_rows, ignored=ign, integrated=integ, interventions=found, open_questions=qs,
               countries=sorted(set(R["Country"].dropna().astype(str))))
    return out
