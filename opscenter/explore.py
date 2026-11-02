"""Reading the data in the app: find records, list sources, per-country feedback files.
Uses the engine's own loader (admin.load_norm) so the values are normalised exactly as in checks and compares."""
import importlib.util
import os
import re
import threading
from pathlib import Path

from . import config
from .pipelines import catalog, local_runs

_engine = None
_cache = {"key": None, "df": None}
_mu = threading.Lock()


def engine_admin(ws):
    """The engine's admin.py imported once, reading the settings that Workspace.prepare() wrote."""
    global _engine
    if _engine is None:
        os.environ["ADMIN_SETTINGS"] = str(ws.engine / "admin_settings.json")
        os.environ["ADMIN_LOGDIR"] = str(ws.logs)
        spec = importlib.util.spec_from_file_location("ops_engine_admin", ws.engine / "admin.py")
        m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(m)
        _engine = m
    return _engine


def sources(ws):
    """[(value, label)] for the pickers: the live file, every finished build, every backup."""
    out = [("live", "live file (newest backup)")]
    for n, m in reversed(local_runs(ws)):
        if m.get("build", {}).get("ok") and ws.has_run_data(n):
            out.append(("v%d" % n, "build v%d (%s)" % (n, "published" if m.get("published") else "not published")))
    for r in reversed(catalog(ws)):
        out.append(("b%s" % r["version"], "backup %s - %s by %s" % (r["version"], (r.get("sharepoint_modified_utc") or "")[:10],
                                                              r.get("modified_by") or "?")))
    return out


def source_file(ws, spec):
    """Download (when needed) and return the file for a source, with a short label."""
    from . import pipelines
    spec = (spec or "live").strip()
    if spec == "live":
        rows = catalog(ws)
        if not rows:
            raise RuntimeError("No backup of the live file yet: run 'Back up the live file' in the Cycle tab.")
        r = rows[-1]
        ws.pull_snapshots({Path(r["snapshot"]).name})
        return ws.backup_repo / r["snapshot"], "backup %s" % r["version"]
    m = re.match(r"^b(\d+)$", spec)
    if m:
        for r in catalog(ws):
            if r["version"] == m.group(1):
                ws.pull_snapshots({Path(r["snapshot"]).name})
                return ws.backup_repo / r["snapshot"], "backup %s" % r["version"]
        raise RuntimeError("Backup %s not found." % spec)
    m = re.match(r"^v(\d+)$", spec)
    if m:
        n = int(m.group(1))
        mf = dict(local_runs(ws)).get(n, {})
        name = re.split(r"[\\/]", str(mf.get("build", {}).get("file", "")))[-1] or "AFRO_admin_data_v%d.xlsx" % n
        dest = ws.local_of("runs/v%d/%s" % (n, name))
        if not (dest.is_file() and str(dest) in ws.sig):
            ws.store.download("runs/v%d/%s" % (n, name), dest)
            ws._remember(dest)
        return dest, "build v%d" % n
    raise RuntimeError("Unknown source '%s'." % spec)


def load_frame(ws, spec):
    """The normalised table of a source. One table is kept in memory; others are cached on disk as pickles."""
    import pandas as pd
    path, label = source_file(ws, spec)
    key = (str(path), path.stat().st_size)
    with _mu:
        if _cache["key"] == key:
            return _cache["df"], label
    pk = ws.root / "cache" / ("%s_%d.pkl" % (path.stem, path.stat().st_size))
    if pk.is_file():
        df = pd.read_pickle(pk)
    else:
        df = engine_admin(ws).load_norm(path)
        pk.parent.mkdir(parents=True, exist_ok=True)
        df.to_pickle(pk)
    with _mu:
        _cache["key"], _cache["df"] = key, df
    return df, label


def free_memory():
    with _mu:
        _cache["key"], _cache["df"] = None, None


SHOW = ["Country", "Province", "District", "Admin_3", "SIA_date", "Round_Add", "Response", "Vaccine_type",
        "Year", "PopPolio", "TotalNbrVaccPolio", "CVPolio"]


def find(ws, spec, country="", province="", district="", response="", vaccine="", round_="", date="", limit=2000):
    import pandas as pd
    df, label = load_frame(ws, spec)
    d = df.copy()
    d.index = d.index + 2                       # the row number in Excel
    m = pd.Series(True, index=d.index)
    for col, val in (("Country", country), ("Province", province), ("District", district),
                     ("Response", response), ("Vaccine_type", vaccine)):
        if val and col in d.columns:
            m &= d[col].str.upper().str.contains(re.escape(val.strip().upper()), regex=True, na=False)
    if round_ and "Round_Add" in d.columns:
        m &= d["Round_Add"].str.upper() == round_.strip().upper()
    if date and "SIA_date" in d.columns:
        m &= d["SIA_date"].str.startswith(date.strip())
    r = d[m]
    cols = [c for c in SHOW if c in r.columns]
    t = r[cols].head(limit).copy()
    if "SIA_date" in t.columns:
        t["SIA_date"] = t["SIA_date"].str[:10]
    t.insert(0, "Excel_row", t.index)
    return t.reset_index(drop=True), len(r), label


def feedback_for_country(src_xlsx, country, dest):
    """A copy of the feedback workbook that holds only one country."""
    import pandas as pd
    sheets = pd.read_excel(src_xlsx, sheet_name=None)
    key = country.strip().upper()
    with pd.ExcelWriter(dest, engine="openpyxl") as w:
        for name, df in sheets.items():
            if "Country" in df.columns:
                df = df[df["Country"].astype(str).str.strip().str.upper() == key]
            elif name.lower().startswith("read"):
                pass
            df.to_excel(w, sheet_name=name[:31], index=False)
            ws_ = w.sheets[name[:31]]
            for i, c in enumerate(df.columns, 1):
                try:
                    q = df[c].astype(str).str.len().quantile(0.9) if len(df) else 12
                    width = min(45, max(10, len(str(c)) + 2, int(q) + 2 if q == q else 12))
                except (TypeError, ValueError):
                    width = 14
                ws_.column_dimensions[ws_.cell(1, i).column_letter].width = width
            ws_.freeze_panes = "A2"
    return dest


def countries_in_feedback(src_xlsx):
    import pandas as pd
    try:
        d = pd.read_excel(src_xlsx, sheet_name="By_country")
        return sorted(d["Country"].dropna().astype(str).unique())
    except Exception:
        return []
