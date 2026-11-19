"""Follow-up with the countries: what each country has to correct or send, what was sent to it, when, and whether it answered.

The app sends nothing to any country. A person sends the feedback workbook (from Submissions > Feedback) by the usual means and records it here
(sent / answered / note); the log lives in the SharePoint folder (submissions/feedback_log.json) so every operator sees the same follow-up."""
import datetime as dt
import json
import re

import pandas as pd

KINDS = {"sent": "Feedback sent", "answered": "Country answered", "note": "Note"}


def _path(ws):
    return ws.workspace / "submissions" / "feedback_log.json"


def load_log(ws):
    try:
        d = json.loads(_path(ws).read_text(encoding="utf-8"))
        return d if isinstance(d.get("entries"), list) else {"entries": []}
    except (OSError, ValueError):
        return {"entries": []}


def _now():
    return dt.datetime.now().strftime("%Y-%m-%d %H:%M")


def findings(ws):
    """{country: {'items': rows of the feedback, 'records': records concerned, 'pending_rounds': n, 'oldest_days': n, 'workbook': newest file name}}
    from what the last inspection wrote (Feedback_to_countries.xlsx, Pending_admin_data.xlsx, feedback_by_country/)."""
    out = {}
    sub = ws.workspace / "submissions"

    def get(c):
        return out.setdefault(str(c).strip().upper(), {"items": 0, "records": 0, "pending_rounds": 0, "oldest_days": 0, "workbook": ""})
    try:
        fb = pd.read_excel(sub / "Feedback_to_countries.xlsx", sheet_name="Feedback")
        for c, g in fb.groupby("Country"):
            r = get(c)
            r["items"] = len(g)
            r["records"] = int(pd.to_numeric(g["Records"], errors="coerce").fillna(0).sum())
    except Exception:
        pass
    try:
        pn = pd.read_excel(sub / "Pending_admin_data.xlsx", sheet_name="Pending_now")
        for c, g in pn.groupby("Country"):
            r = get(c)
            r["pending_rounds"] = len(g)
            r["oldest_days"] = int(pd.to_numeric(g["Days_since_start"], errors="coerce").fillna(0).max())
    except Exception:
        pass
    d = sub / "feedback_by_country"
    if d.is_dir():
        for p in sorted(d.glob("Feedback_*.xlsx")):
            m = re.match(r"Feedback_(.+)_(\d{4}-\d{2}-\d{2})\.xlsx$", p.name)
            if m:
                get(m.group(1).replace("_", " "))["workbook"] = p.name
    return out


def table(ws, today=None):
    """One row per country: what is open, what was sent and when, whether it answered, and the follow-up status in words."""
    today = today or dt.date.today()
    log = load_log(ws)["entries"]
    rows = []
    for country, f in sorted(findings(ws).items()):
        mine = [e for e in log if str(e.get("country", "")).upper() == country]
        sent = [e for e in mine if e.get("kind") == "sent"]
        ans = [e for e in mine if e.get("kind") == "answered"]
        last_sent = max(sent, key=lambda e: e["at"]) if sent else None
        last_ans = max(ans, key=lambda e: e["at"]) if ans else None
        days = None
        if last_sent:
            try:
                days = (today - dt.datetime.strptime(last_sent["at"][:10], "%Y-%m-%d").date()).days
            except ValueError:
                days = None
        open_items = f["items"] + f["pending_rounds"]
        answered_after = bool(last_ans and (not last_sent or last_ans["at"] >= last_sent["at"]))
        if not open_items:
            status = "Nothing open"
        elif not last_sent:
            status = "To send"
        elif answered_after:
            status = "Answered, check the new files"
        elif (last_sent.get("items_open") is not None and open_items > int(last_sent["items_open"])):
            status = "New findings since it was sent"
        elif days is not None and days >= 14:
            status = "No answer for %d days: remind" % days
        else:
            status = "Sent, waiting for an answer"
        rows.append({"Country": country, "To correct / confirm": f["items"], "Records concerned": f["records"], "Rounds not received": f["pending_rounds"],
                     "Oldest round (days since start)": f["oldest_days"] or "", "Workbook": f["workbook"],
                     "Sent on": (last_sent or {}).get("at", "")[:10], "Days since sent": days if days is not None else "",
                     "Answered on": (last_ans or {}).get("at", "")[:10], "Follow-up": status,
                     "Last note": (mine[-1].get("note") or "")[:80] if mine else ""})
    order = {"To send": 0, "New findings since it was sent": 1, "No answer for": 2, "Answered, check the new files": 3, "Sent, waiting for an answer": 4, "Nothing open": 5}
    rows.sort(key=lambda r: (next((v for k, v in order.items() if r["Follow-up"].startswith(k)), 9), r["Country"]))
    return rows


def add_entry(ws, country, kind, by, note=""):
    """Append one line to the log (the caller holds the SharePoint lock; the job pushes the file)."""
    if kind not in KINDS:
        raise ValueError("unknown kind %r" % kind)
    f = findings(ws).get(str(country).strip().upper(), {})
    log = load_log(ws)
    log["entries"].append({"country": str(country).strip().upper(), "kind": kind, "at": _now(), "by": by, "note": (note or "").strip(),
                           "items_open": f.get("items", 0) + f.get("pending_rounds", 0), "workbook": f.get("workbook", "")})
    p = _path(ws)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(log, indent=1, ensure_ascii=False), encoding="utf-8")
    tmp.replace(p)
    return log["entries"][-1]
