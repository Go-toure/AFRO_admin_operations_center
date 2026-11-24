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

SHEETS = ["Records", "Held_back_records", "Integrated_additions", "Integrated_interventions", "Decisions_needed", "Overlap_between_files"]
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
        out.update(add=0, campaigns=[], held=[], ignored={}, integrated=None, interventions=[], open_questions=[], situation=[], suggest=("Reject", "no record of this file was read in the report."))
        return out
    R["_k"] = _key(R)
    # the same record sent in several versions of the file counts once
    rows_before = len(R)
    R = R.drop_duplicates(subset=["_k"], keep="first")
    copies = round(rows_before / max(len(R), 1), 1)
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
    present = R[st.str.startswith(("already in the live file", "possible duplicate", "same names as several"))]
    there = present.groupby(["Response", "Round_Add"], dropna=False).size().to_dict() if len(present) else {}
    if len(added):
        for (c, resp, rnd), g in added.groupby(["Country", "Response", "Round_Add"], dropna=False):
            e = int(there.get((resp, rnd), 0))
            camps.append({"Country": c, "Campaign": resp, "Round": rnd, "Vaccine": ", ".join(sorted(set(g["Vaccine_type"].dropna().astype(str)))),
                          "Dates": _span(g["SIA_date"]), "Records": int(len(g)), "Districts": int(g[["Province", "District"]].drop_duplicates().shape[0]),
                          "In live": ("yes: completes it (%d records already there)" % e) if e else "no: new round"})
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

    O = x.get("Overlap_between_files", pd.DataFrame())
    ov = []
    if len(O) and "File" in O.columns:
        for _, r in O[O["File"].isin(names) | O["Also_in_earlier_file"].isin(names)].iterrows():
            ov.append({"File": str(r["File"]), "Earlier": str(r["Also_in_earlier_file"]), "Both": int(r["New_records_in_both"]),
                       "Same": int(r["Same_figures"]), "Other": int(r["Other_figures"])})

    n_same, n_other = ign.get("same figures", 0), ign.get("other figures", 0)
    n_new_in_live = sum(c["Records"] for c in camps if c["In live"].startswith("yes"))
    n_new_round = sum(c["Records"] for c in camps if c["In live"].startswith("no"))
    k_in_live = sum(1 for c in camps if c["In live"].startswith("yes"))
    k_new_round = sum(1 for c in camps if c["In live"].startswith("no"))
    sit = []
    for o in ov:
        a, b = o["Earlier"], o["File"]
        if a in names and b in names:
            t = "Two submissions of the same data: %d new records are in both \"%s\" and \"%s\"" % (o["Both"], a, b)
            t += ("; %d have the same figures and %d have different figures in the two files. Only the first accepted file's copy is added, so accept the version with the right figures and reject the other." % (o["Same"], o["Other"])) if o["Other"] else \
                 ("; the figures are the same, so they are added once.")
            sit.append(t)
        elif o["Both"] > 2:
            sit.append("%d new records are also in the file \"%s\" (another submission): they are added once, by the file accepted first." % (o["Both"], b if a in names else a))
    if copies >= 1.5 and not any(o["Earlier"] in names and o["File"] in names for o in ov):
        sit.append("This file was sent %d times (same records in every copy): they are counted once." % round(copies))
    if not len(added) and (n_same or n_other):
        sit.append("Nothing new: every record of this file is already in the live file.")
    elif len(added) and (n_same + n_other) > 0:
        sit.append("The file repeats earlier data and adds the missing part: %s record(s) are already in the live file, %s are new." % (format(n_same + n_other, ","), format(len(added), ",")))
        if n_new_in_live:
            sit.append("%s new record(s) complete %d campaign round(s) that the live file already has (districts or dates that were missing)." % (format(n_new_in_live, ","), k_in_live))
        if n_new_round:
            sit.append("%s new record(s) are of %d campaign round(s) that the live file does not have yet." % (format(n_new_round, ","), k_new_round))
    elif len(added):
        sit.append("All the records are new: %d campaign round(s) not in the live file yet." % k_new_round)
    if n_other:
        sit.append("%s record(s) of this file are in the live file with other figures. The live figures stay: if the country corrected its figures, that is a correction to make in the live file, not an accept." % format(n_other, ","))
    if ign.get("possible duplicate"):
        sit.append("%s record(s) look like records already in the live file under another campaign name, round or date: they are not added." % format(ign["possible duplicate"], ","))
    if held_rows:
        sit.append("%s record(s) are held back (see below)." % format(sum(h["Records"] for h in held_rows), ","))

    warn = [q for q in qs if not q["Question"].startswith("Campaign details")]
    if not len(added) and not integ:
        sug = ("Reject", "accepting adds nothing: there is no new record in this file.")
    elif not len(added):
        sug = ("Accept", "no new record, but it completes %s empty integrated cell(s) of live records." % format(integ["cells"], ","))
    elif any(o["Other"] for o in ov if o["Earlier"] in names and o["File"] in names):
        sug = ("Look first", "the two versions differ on some figures: accept only the version with the right figures.")
    elif warn:
        sug = ("Look first", warn[0]["Question"] + " (see below).")
    elif held_rows and not len(added):
        sug = ("Reject", "everything new is held back.")
    else:
        sug = ("Accept", "the new records are clean and the campaigns are known.")

    out.update(situation=sit, suggest=sug, add=int(len(added)), campaigns=camps, held=held_rows, ignored=ign, integrated=integ, interventions=found, open_questions=qs,
               countries=sorted(set(R["Country"].dropna().astype(str))))
    return out
