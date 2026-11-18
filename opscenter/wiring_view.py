"""What the Lookup & wiring tab shows: the state of the scope file and of the decided files, the lookup issues the last inspection found, the
proposals of `lookup-fix propose`, and the rounds still pending. All of it is read from files the jobs wrote (nothing is computed here)."""
import csv
import io

import pandas as pd

from . import scope_refresh


def _sheets(path):
    try:
        return pd.read_excel(path, sheet_name=None)
    except Exception:
        return {}


def _lines(raw):
    """Number of decided lines in a csv (header excluded), or None when the file is not there."""
    if raw is None:
        return None
    try:
        return max(sum(1 for _ in csv.reader(io.StringIO(raw.decode("utf-8-sig")))) - 1, 0)
    except Exception:
        return None


def load(store, ws):
    sub = ws.workspace / "submissions"
    pend = _sheets(sub / "Pending_admin_data.xlsx")
    prop = _sheets(sub / "lookup_fix_proposals.xlsx")
    info = {}
    try:
        for c in store.list("inputs"):
            if not c["is_dir"]:
                info[c["name"]] = {"size": c["size"], "modified": (c["modified"] or "")[:16].replace("T", " ")}
    except Exception:
        pass
    corr = _lines(store.get("inputs/corrections.csv"))
    over = _lines(store.get("inputs/lookup_overrides.csv"))
    empty = pd.DataFrame()
    return {
        "scope_in_store": info.get("scope_.csv"),
        "corrections_lines": corr, "overrides_lines": over,
        "issues": pend.get("Lookup_issues", empty), "accepted": pend.get("Lookup_accepted", empty),
        "pending": pend.get("Pending_now", empty), "check_other": pend.get("Check_other_name", empty),
        "p_corr": prop.get("Corrections", empty), "p_chg": prop.get("Lookup_changes", empty), "p_skip": prop.get("Not_proposed", empty),
        "has_proposals": bool(prop), "has_pending": bool(pend),
        "scope_status": scope_refresh.status(),
    }


def round_key(row):
    """The text the engine wants to close a pending round: COUNTRY|campaign|round."""
    return "%s|%s|%s" % (str(row["Country"]).strip().upper(), str(row["Campaign"]).strip(), str(row["Round"]).strip())
