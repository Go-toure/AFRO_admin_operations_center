"""What the Lookup & wiring tab shows: the state of the scope file and of the decided files, the lookup issues the last inspection found, the
proposals of `lookup-fix propose`, and the rounds still pending. All of it is read from files the jobs wrote (nothing is computed here)."""
import csv
import io
import re

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


STATUS_OF = [("Pending_now", "Pending"), ("Not_yet_due", "Not due yet"), ("Check_other_name", "To check"),
             ("Date_differs_in_live", "Other date in live"), ("Received_not_in_live", "Received, not in live")]
VIEW_COLUMNS = ["Country", "Response", "Round", "Start date", "End date", "Days since start", "Delay (days past due)", "Due in (days)", "Status",
                "Vaccines", "Live file", "Next step"]
GRID_COLUMNS = [c for c in VIEW_COLUMNS if c != "Next step"]   # the next step is shown once as a note under the table


def _round_no(x):
    m = re.search(r"(\d+)", str(x))
    return int(m.group(1)) if m else None


def end_dates(store):
    """{(campaign, round number): end date} from scope/gpei_rounds_full.csv of the SharePoint folder (written by the scope refresh); {} when absent."""
    try:
        raw = store.get("scope/gpei_rounds_full.csv")
        if not raw:
            return {}
        df = pd.read_csv(io.BytesIO(raw), usecols=["campaign.obr_name", "round.number", "round.ended_at"], low_memory=False)
        df["round.ended_at"] = pd.to_datetime(df["round.ended_at"], errors="coerce").dt.strftime("%Y-%m-%d")
        return {(str(a).strip(), int(b)): c for a, b, c in zip(df["campaign.obr_name"], pd.to_numeric(df["round.number"], errors="coerce").fillna(-1), df["round.ended_at"])
                if isinstance(c, str)}
    except Exception:
        return {}


def pending_view(pa, ends):
    """One table of every round that is pending, not due yet, or to check: country, response (campaign), round number, start and end date,
    the days since the start, the delay past the due date, and the status. `_start` (a date) is for the filters."""
    today = pd.Timestamp.now().normalize()
    rows = []
    for sheet, label in STATUS_OF:
        df = pa.get(sheet)
        if df is None or not len(df):
            continue
        for _, r in df.iterrows():
            rn = _round_no(r.get("Round"))
            start = pd.to_datetime(r.get("Planned_start"), errors="coerce")
            since = r.get("Days_since_start")
            if pd.isna(since) if since is not None else True:
                since = (today - start).days if pd.notna(start) else None

            def num(v):
                v = pd.to_numeric(v, errors="coerce")
                return "" if pd.isna(v) else int(v)
            rows.append({"Country": r.get("Country"), "Response": r.get("Campaign"), "Round": rn if rn is not None else r.get("Round"),
                         "Start date": start.strftime("%Y-%m-%d") if pd.notna(start) else "",
                         "End date": ends.get((str(r.get("Campaign")).strip(), rn), ""),
                         "Days since start": num(since), "Delay (days past due)": num(r.get("Days_overdue")) if label != "Not due yet" else "",
                         "Due in (days)": num(r.get("Days_to_due")) if label == "Not due yet" else "", "Status": label,
                         "Vaccines": r.get("Vaccines"), "Live file": r.get("Live_file"), "Next step": r.get("Next_step"), "_start": start})
    out = pd.DataFrame(rows, columns=VIEW_COLUMNS + ["_start"])
    return out.sort_values("_start", ascending=False).reset_index(drop=True) if len(out) else out


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
        "has_proposals": bool(prop), "has_pending": bool(pend), "pend_all": pend,
        "pview": pending_view(pend, end_dates(store)) if pend else empty,
        "scope_status": scope_refresh.status(),
    }


def round_key(row):
    """The text the engine wants to close a pending round: COUNTRY|campaign|round."""
    return "%s|%s|%s" % (str(row["Country"]).strip().upper(), str(row["Campaign"]).strip(), str(row["Round"]).strip())
