"""Where the records that came from the countries' submissions entered the live file: which file, which build, when it was published.

The engine writes, for every build that added records, runs/vNN/records_added_from_submissions_vNN.csv (one line per added record). This module
only reads those small files, with the manifest of the build (published or not). Nothing is changed. Builds made before this feature have no such file:
their added files are still shown from the manifest, without the record lines."""
import pandas as pd

from .pipelines import local_runs

COLS = ["Build", "State", "Published", "Source file", "Country", "Records", "Districts", "First campaign date", "Last campaign date"]


def _state(m):
    pub = m.get("published") or {}
    if pub.get("at"):
        return "in the live file", str(pub.get("at"))[:16].replace("T", " ")
    return "built, not published yet", ""


def records(ws):
    """One line per record added by a build: Build, State, Published, Source file, Country, Province, District, Response, SIA_date, Round_Add, Vaccine_type."""
    frames = []
    for n, m in local_runs(ws):
        p = ws.workspace / "runs" / ("v%d" % n) / ("records_added_from_submissions_v%d.csv" % n)
        if not p.is_file():
            continue
        try:
            df = pd.read_csv(p, dtype=str, keep_default_na=False)
        except Exception:
            continue
        st, at = _state(m)
        df.insert(0, "Published", at)
        df.insert(0, "State", st)
        df.insert(0, "Build", "v%d" % n)
        frames.append(df)
    if not frames:
        return pd.DataFrame(columns=["Build", "State", "Published", "Source_file", "Country"])
    return pd.concat(frames, ignore_index=True)


def table(ws):
    """The summary: one line per build, source file and country, newest first. A build that was made again keeps only its last version in the list of
    the builds that were not published (an earlier unpublished build of the same records is not repeated)."""
    df = records(ws)
    out, seen = [], set()
    if len(df):
        for n in sorted(df["Build"].unique(), key=lambda b: -int(b[1:])):
            d = df[df["Build"] == n]
            st = d["State"].iat[0]
            for (f, c), g in d.groupby(["Source_file", "Country"], sort=False):
                key = (f, c, st == "in the live file")
                if st != "in the live file" and key in seen:
                    continue
                seen.add(key)
                dates = sorted(x for x in g.get("SIA_date", pd.Series(dtype=str)) if x)
                out.append({"Build": n, "State": st, "Published": d["Published"].iat[0], "Source file": f, "Country": c, "Records": len(g),
                            "Districts": g["District"].nunique() if "District" in g else "",
                            "First campaign date": dates[0] if dates else "", "Last campaign date": dates[-1] if dates else ""})
    # builds that added files but have no record lines (made before the record list existed)
    have = {r["Build"] for r in out}
    for n, m in reversed(local_runs(ws)):
        b = "v%d" % n
        files = (m.get("build") or {}).get("submissions") or []
        if b in have or not files or not (m.get("build") or {}).get("added_records"):
            continue
        st, at = _state(m)
        for f in files:
            out.append({"Build": b, "State": st, "Published": at, "Source file": f, "Country": "(not listed for this build)", "Records": "",
                        "Districts": "", "First campaign date": "", "Last campaign date": ""})
    out.sort(key=lambda r: -int(r["Build"][1:]))
    return out
