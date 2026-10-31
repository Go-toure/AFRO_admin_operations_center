"""What the Overview tab shows: the live files on SharePoint, the backups, the runs."""
import json

from . import config
from .pipelines import catalog, local_runs, run_state


def human(n):
    n = float(n or 0)
    for u in ("B", "KB", "MB", "GB"):
        if n < 1024 or u == "GB":
            return ("%d %s" % (n, u)) if u == "B" else ("%.1f %s" % (n, u))
        n /= 1024


def item_info(g, url):
    try:
        it = g.share_item(url)
        by = ((it.get("lastModifiedBy") or {}).get("user") or {}).get("displayName", "?")
        return {"ok": True, "name": it.get("name"), "size": human(it.get("size")), "modified": (it.get("lastModifiedDateTime") or "")[:16].replace("T", " "),
                "by": by}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def load(store, ws):
    """Refresh the small files from the SharePoint folder and collect everything for the Overview."""
    ws.prepare()
    ws.pull_light()
    out = {"live": item_info(store.g, config.ADMIN_URL), "dictionary": item_info(store.g, config.DICT_URL)}
    st = {}
    p = ws.workspace / "state.json"
    if p.is_file():
        try:
            st = json.loads(p.read_text(encoding="utf-8"))
        except ValueError:
            st = {}
    out["state"] = st
    cat = catalog(ws)
    out["backups"] = [{"version": r["version"], "saved": (r.get("sharepoint_modified_utc") or "")[:16].replace("T", " "),
                       "by": r.get("modified_by") or "", "rows": r.get("rows") or "",
                       "size": human(r.get("size_bytes"))} for r in reversed(cat)]
    runs = []
    for n, m in reversed(local_runs(ws)):
        pub = m.get("published") or {}
        runs.append({"version": "v%d" % n, "state": run_state(m), "built": (m.get("created") or "")[:16],
                     "records": m.get("build", {}).get("rows_out") or "", "errors": m.get("build", {}).get("errors") or "",
                     "published": (pub.get("at") or "")[:16], "dictionary": pub.get("dictionary") or ""})
    out["runs"] = runs
    out["lock"] = store.lock_info()
    out["activity"] = list(reversed((store.get_json("activity.json", []) or [])[-60:]))
    # what to do next
    unpub = [(n, m) for n, m in local_runs(ws) if not m.get("published")]
    if unpub:
        n, m = unpub[-1]
        out["next"] = "v%d is %s." % (n, run_state(m))
    else:
        out["next"] = "Nothing waiting. Build the next version when the live file has changed or the rules changed."
    return out
