"""The Live data tab: filters, charts and downloads on the live file (newest backup) or another source.

The tab reads the table the same way as 'Find records' (the engine's own loader, every value as text, cached), keeps a slim copy of the columns it
filters and charts on, and goes back to the full table only for the download, so the file has every column. Nothing here changes any data.
The charts are plain SVG built here (no chart library to install, the same on the PC and in the cloud).

Coverage: the share of districts reaching 95% or more. The unit is a district in a campaign round (country, province, district, response, round):
its coverage is the polio doses given divided by its polio target (PopPolio, TotalNbrVaccPolio), summed over the rows of that district and round;
a unit with no target is left out of the share and counted apart.
"""
import html
import io
import math

import pandas as pd

MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"]
NEEDED = ["Country", "Province", "District", "Admin_3", "Response", "Vaccine_type", "Round_Add", "SIA_date", "PopPolio", "TotalNbrVaccPolio", "CVPolio"]
TABLE_COLUMNS = ["Excel_row", "Country", "Province", "District", "Admin_3", "Response", "Round_Add", "Vaccine_type", "SIA_date",
                 "PopPolio", "TotalNbrVaccPolio", "CVPolio"]
MEASURES = {"records": "Records", "target": "Target population (polio)", "vaccinated": "Vaccinated (polio)"}
THRESHOLD = 95.0
COV_COLUMNS = ["Group", "District-rounds with a target", "Reaching 95% or more", "Proportion (%)", "Without a target (left out)"]
COLOR = "#009ADE"
_COL = {"country": "Country", "year": "_year", "month": "_ym", "vaccine": "Vaccine_type", "response": "Response", "round": "Round_Add"}


# ------------------------------------------------------------------------------------------------------------- data
def slim(df):
    """The columns the tab works on, from the normalised (all text) table. The index of `df` is kept: the Excel row is index + 2."""
    s = df[[c for c in NEEDED if c in df.columns]].copy()
    for c in NEEDED:
        if c not in s.columns:
            s[c] = ""
    s.insert(0, "Excel_row", df.index + 2)
    d = pd.to_datetime(s["SIA_date"].astype(str).str[:10], errors="coerce")
    s["_date"] = d
    s["_year"] = d.dt.year
    s["_month"] = d.dt.month
    s["_ym"] = d.dt.strftime("%Y-%m")
    s["_target"] = pd.to_numeric(s["PopPolio"], errors="coerce")
    s["_vac"] = pd.to_numeric(s["TotalNbrVaccPolio"], errors="coerce")
    return s


def choices(s, col):
    """Sorted distinct non-empty values of a column, as the lists of the filters."""
    return sorted({str(x) for x in s[col].dropna() if str(x).strip()})


def year_choices(s):
    return sorted({str(int(y)) for y in s["_year"].dropna()}, reverse=True)


def apply_filters(s, countries=(), provinces=(), districts=(), responses=(), vaccines=(), rounds=(), year="All", month="All", last=0, today=None):
    m = pd.Series(True, index=s.index)
    for col, vals in (("Country", countries), ("Province", provinces), ("District", districts),
                      ("Response", responses), ("Vaccine_type", vaccines), ("Round_Add", rounds)):
        if vals:
            m &= s[col].isin(list(vals))
    if year not in (None, "", "All"):
        m &= s["_year"] == int(year)
    if month in MONTHS:
        m &= s["_month"] == MONTHS.index(month) + 1
    try:
        last = int(last or 0)
    except (TypeError, ValueError):
        last = 0
    if last > 0:
        today = pd.Timestamp.now().normalize() if today is None else today
        m &= s["_date"] >= today - pd.DateOffset(months=last)
    return s[m]


def totals(f):
    """The numbers of the tiles for a filtered table."""
    n = len(f)
    return {"records": n,
            "countries": int(f["Country"].replace("", pd.NA).nunique()) if n else 0,
            "districts": int(f.groupby(["Country", "Province", "District"]).ngroups) if n else 0,
            "responses": int(f["Response"].replace("", pd.NA).nunique()) if n else 0,
            "target": float(f["_target"].sum()) if n else 0.0,
            "vaccinated": float(f["_vac"].sum()) if n else 0.0,
            "no_date": int(f["_date"].isna().sum()) if n else 0}


def aggregate(f, by, measure="records"):
    """[(label, value)] for a measure grouped by country / year / month / vaccine / response / round. Years and months in time order, the others largest first."""
    if len(f) == 0:
        return []
    key = f[_COL[by]]
    if by == "year":
        key = key.dropna().astype(int).astype(str)
    elif by == "month":
        key = key.dropna()
    else:
        key = key.astype(str)
        key = key.where(key.str.strip() != "", "(blank)")
    if measure == "records":
        val = pd.Series(1.0, index=f.index)
    else:
        val = f["_target" if measure == "target" else "_vac"].fillna(0)
    g = val.loc[key.index].groupby(key).sum()
    items = list(g.items())
    if by in ("year", "month", "round"):
        return sorted(items, key=lambda x: x[0])
    return sorted(items, key=lambda x: (-x[1], x[0]))


def _units(f, threshold=THRESHOLD):
    """One row per district in a campaign round (country, province, district, response, round): target, doses, first date, vaccine, and
    _u (has a target), _n (no target), _r (has a target and reaches the threshold)."""
    g = f.groupby(["Country", "Province", "District", "Response", "Round_Add"], sort=False, dropna=False).agg(
        t=("_target", "sum"), v=("_vac", "sum"), start=("_date", "min"), vaccine=("Vaccine_type", "first")).reset_index()
    has = g["t"] > 0
    g["_u"] = has.astype(int)
    g["_n"] = (~has).astype(int)
    g["_r"] = (has & (g["v"] / g["t"].where(has) * 100 >= threshold)).astype(int)
    return g


def coverage(f, by="country", threshold=THRESHOLD):
    """The share of districts reaching the threshold, by country / year / vaccine / response / round (see the module note)."""
    if len(f) == 0:
        return pd.DataFrame(columns=COV_COLUMNS)
    g = _units(f, threshold)
    if by == "year":
        key = g["start"].dt.year.map(lambda y: str(int(y)) if y == y else "(no date)")
    else:
        key = g[{"country": "Country", "vaccine": "vaccine", "response": "Response", "round": "Round_Add"}[by]].astype(str)
        key = key.where(key.str.strip() != "", "(blank)")
    out = g.assign(_k=key).groupby("_k").agg(u=("_u", "sum"), r=("_r", "sum"), n=("_n", "sum")).reset_index()
    out["p"] = (out["r"] / out["u"].where(out["u"] > 0) * 100).round(1)
    out.columns = COV_COLUMNS[:1] + ["u", "r", "n", "p"]
    out = out.rename(columns={"u": COV_COLUMNS[1], "r": COV_COLUMNS[2], "p": COV_COLUMNS[3], "n": COV_COLUMNS[4]})[COV_COLUMNS]
    if by in ("year", "round"):
        return out.sort_values("Group").reset_index(drop=True)
    return out.sort_values([COV_COLUMNS[3], COV_COLUMNS[1]], ascending=[False, False], na_position="last").reset_index(drop=True)


LEVELS = ("country", "province", "district")
_LEVEL_COL = {"country": "Country", "province": "Province", "district": "District"}
BLANK = "(blank)"


def drill(f, level):
    """The table of one level of the drill-down (country, province or district), for the rows of `f`: records, districts, responses, target,
    doses, coverage and the share of district-rounds at 95% or more. The first column is the name; an empty name is shown as (blank)."""
    cols = ["Records", "Districts", "Responses", "Target (polio)", "Vaccinated (polio)", "Coverage (%)", "Districts at 95%+ (%)"]
    name = _LEVEL_COL[level]
    if len(f) == 0:
        return pd.DataFrame(columns=[name] + cols)
    g = f.groupby(name, dropna=False)
    out = pd.DataFrame({"Records": g.size(), "Responses": g["Response"].nunique(), "Target (polio)": g["_target"].sum(), "Vaccinated (polio)": g["_vac"].sum()})
    out["Districts"] = f.drop_duplicates(["Country", "Province", "District"]).groupby(name).size()
    out["Coverage (%)"] = (out["Vaccinated (polio)"] / out["Target (polio)"].where(out["Target (polio)"] > 0) * 100).round(1)
    u = _units(f)
    k = u.groupby(name).agg(u=("_u", "sum"), r=("_r", "sum"))
    out["Districts at 95%+ (%)"] = (k["r"] / k["u"].where(k["u"] > 0) * 100).round(1)
    out = out.reset_index().rename(columns={"index": name})
    out[name] = out[name].astype(str)
    out[name] = out[name].where(out[name].str.strip() != "", BLANK)
    out["Target (polio)"] = out["Target (polio)"].round(0).astype("int64")
    out["Vaccinated (polio)"] = out["Vaccinated (polio)"].round(0).astype("int64")
    return out[[name] + cols].sort_values(["Records", name], ascending=[False, True]).reset_index(drop=True)


def drill_rows(f, path):
    """The rows of `f` inside the chosen path (a dict with country, province, district; None where not chosen yet)."""
    m = pd.Series(True, index=f.index)
    for lv in LEVELS:
        v = path.get(lv)
        if v is not None:
            m &= f[_LEVEL_COL[lv]] == ("" if v == BLANK else v)
    return f[m]


def top(items, n):
    """The n largest items; the rest are not shown (a chart of hundreds of campaigns would be unreadable)."""
    return sorted(items, key=lambda x: -x[1])[:n] if len(items) > n else items


# ------------------------------------------------------------------------------------------------------------- text
def fmt_int(v):
    return "{:,.0f}".format(v)


def _trim(x):
    return ("%.1f" % x).rstrip("0").rstrip(".")


def fmt_compact(v):
    a = abs(v)
    if a >= 1e9:
        return _trim(v / 1e9) + "B"
    if a >= 1e6:
        return _trim(v / 1e6) + "M"
    if a >= 1e3:
        return _trim(v / 1e3) + "k"
    return "%g" % v


def _esc(x):
    return html.escape(str(x), quote=True)


def _scale(v):
    """(step, number of intervals) of a value axis that starts at 0 and covers v with 3 to 6 round steps (1, 2 or 5 times a power of ten)."""
    if v <= 0:
        return 1.0, 1
    e = 10 ** math.floor(math.log10(v))
    for m in (0.5, 1, 2, 5, 10, 20):
        step = m * e
        k = math.ceil(v / step - 1e-9)
        if 3 <= k <= 6:
            return step, k
    return e, math.ceil(v / e)


# ------------------------------------------------------------------------------------------------------------- charts (SVG)
def hbar(items, fmt=fmt_int, vmax=None, label_chars=30, aria="bar chart"):
    """Horizontal bars. items: (label, value, tooltip or None, text at the end of the bar or None). Hover on a row gives the tooltip."""
    if not items:
        return '<p class="note">No records for these filters.</p>'
    items = [(i + (None, None))[:4] if len(i) < 4 else i for i in items]
    w, row, top_, right = 760, 24, 6, 130
    lab = [(str(l) if len(str(l)) <= label_chars else str(l)[:label_chars - 1] + "…") for l, _, _, _ in items]
    lab_w = int(min(270, max(90, 8.0 * max(len(x) for x in lab) + 14)))
    area = w - lab_w - right
    vmax = vmax or max((v for _, v, _, _ in items), default=0) or 1
    h = top_ + len(items) * row + 6
    out = ['<div class="chart" style="max-height:440px;overflow-y:auto;"><svg viewBox="0 0 %d %d" width="100%%" role="img" aria-label="%s" '
           'preserveAspectRatio="xMinYMin meet">' % (w, h, _esc(aria))]
    for i, ((l, v, tip, txt), short) in enumerate(zip(items, lab)):
        y = top_ + i * row
        bw = 0 if v <= 0 else max(2.0, v / vmax * area)
        tip = tip if tip is not None else "%s: %s" % (l, fmt(v))
        txt = txt if txt is not None else fmt(v)
        out.append('<g class="bar"><title>%s</title><rect x="0" y="%d" width="%d" height="%d" fill="transparent"/>'
                   '<text x="%d" y="%d" text-anchor="end">%s</text>'
                   '<rect class="m" x="%d" y="%d" width="%.1f" height="12" rx="2" fill="%s"/>'
                   '<text x="%.1f" y="%d">%s</text></g>'
                   % (_esc(tip), y, w, row, lab_w - 8, y + 16, _esc(short), lab_w, y + 6, bw, COLOR, lab_w + bw + 6, y + 16, _esc(txt)))
    out.append("</svg></div>")
    return "".join(out)


def vbar(items, fmt=fmt_int, aria="column chart"):
    """Vertical columns (time). items: (label, value). Light grid, values on the left axis, a label under every k-th column, tooltip on each."""
    if not items:
        return '<p class="note">No records for these filters.</p>'
    w, h, ml, mr, mt, mb = 760, 250, 60, 10, 10, 42
    pw, ph = w - ml - mr, h - mt - mb
    step, k_int = _scale(max(v for _, v in items))
    vmax = step * k_int
    n = len(items)
    slot = pw / n
    bw = max(2.0, min(40.0, slot * 0.7))
    per = 52 if max(len(str(l)) for l, _ in items) > 4 else 36
    every = max(1, math.ceil(n / max(1, int(pw / per))))
    out = ['<div class="chart"><svg viewBox="0 0 %d %d" width="100%%" role="img" aria-label="%s">' % (w, h, _esc(aria))]
    for k in range(k_int + 1):
        y = mt + ph - ph * k / k_int
        out.append('<line x1="%d" x2="%d" y1="%.1f" y2="%.1f" stroke="#dde5ea" stroke-width="1"/><text x="%d" y="%.1f" text-anchor="end" fill="#5f6f7c">%s</text>'
                   % (ml, w - mr, y, y, ml - 6, y + 4, fmt_compact(step * k)))
    for i, (l, v) in enumerate(items):
        bh = ph * v / vmax if v > 0 else 0
        x = ml + i * slot + (slot - bw) / 2
        out.append('<g class="bar"><title>%s</title><rect x="%.1f" y="%d" width="%.1f" height="%d" fill="transparent"/>'
                   '<rect class="m" x="%.1f" y="%.1f" width="%.1f" height="%.1f" rx="2" fill="%s"/></g>'
                   % (_esc("%s: %s" % (l, fmt(v))), ml + i * slot, mt, slot, ph, x, mt + ph - bh, bw, bh, COLOR))
        if i % every == 0:
            out.append('<text x="%.1f" y="%d" text-anchor="middle">%s</text>' % (ml + i * slot + slot / 2, h - mb + 16, _esc(l)))
    out.append("</svg></div>")
    return "".join(out)


def coverage_chart(cov, n=40):
    """Horizontal bars of the share (0 to 100%) with the counts at the end; the table behind it is the data frame under the chart."""
    if cov is None or len(cov) == 0:
        return '<p class="note">No records for these filters.</p>'
    items = []
    for _, r in cov.head(n).iterrows():
        u, k, p = int(r[COV_COLUMNS[1]]), int(r[COV_COLUMNS[2]]), r[COV_COLUMNS[3]]
        if u == 0:
            items.append((r["Group"], 0, "%s: no district with a target" % r["Group"], "no target"))
        else:
            items.append((r["Group"], p, "%s: %d of %d district-rounds reached 95%% or more (%.1f%%)" % (r["Group"], k, u, p), "%.0f%% (%d/%d)" % (p, k, u)))
    return hbar(items, vmax=100, aria="share of districts reaching 95% or more")


# ------------------------------------------------------------------------------------------------------------- downloads
def records_csv(full):
    return full.to_csv(index=False).encode("utf-8-sig")


def _column_values(col):
    """A column as Excel values: numbers where every filled value is a plain number (no leading zero, at most 15 digits), text otherwise, None when empty."""
    s = col.astype(str)
    filled = s.str.strip() != ""
    if filled.any():
        num = pd.to_numeric(s.where(filled), errors="coerce")
        plain = (~s[filled].str.match(r"^0\d")).all() and (s[filled].str.len() <= 15).all()
        if plain and num[filled].notna().all():
            return [None if x != x else (int(x) if float(x).is_integer() else float(x)) for x in num]
    return [v if v.strip() else None for v in s]


def records_xlsx(full):
    """The rows as one sheet; written row by row (openpyxl write-only), so a large table does not need much memory."""
    import openpyxl
    wb = openpyxl.Workbook(write_only=True)
    ws = wb.create_sheet("Live data")
    ws.append([str(c) for c in full.columns])
    cols = [_column_values(full[c]) for c in full.columns]
    for row in zip(*cols):
        ws.append(list(row))
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()
