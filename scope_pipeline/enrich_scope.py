"""Adds to data/scope_.csv the round-level facts the GPEI API gives and the scope build does not carry.

scope_.csv says WHERE a campaign round was planned (one row per district). The API also knows WHEN the round ended,
its stable ids, its planned population and age range, whether it is on hold / a test / preventive, and the
mop-up window. data/gpei_rounds_full.csv (written by prepare_the_AFRO_SIA_Dashboard_input.py from the same API call
as lookup.xlsx) holds all of it; this step copies the useful fields onto every district row of the round, joined by
campaign name + round number. The original 14 columns are untouched; the new ones are appended at the end.

Run on its own:  python scripts/enrich_scope.py            (uses data/scope_.csv and data/gpei_rounds_full.csv)
It never raises when called from the pipeline: a problem is logged and scope_.csv is left as it was.
"""
import sys
from pathlib import Path

import pandas as pd

# new column in scope_.csv -> column of gpei_rounds_full.csv
FIELDS = {
    "campaign_id": "campaign.id",
    "round_id": "round.id",
    "round_end_date": "round.ended_at",
    "mop_up_start_date": "round.mop_up_started_at",
    "mop_up_end_date": "round.mop_up_ended_at",
    "round_target_population": "round.target_population",
    "age_min": "round.age_min",
    "age_max": "round.age_max",
    "age_unit": "round.age_type",
    "round_on_hold": "round.on_hold",
    "campaign_on_hold": "campaign.on_hold",
    "is_preventive": "campaign.is_preventive",
    "is_test": "campaign.is_test",
    "virus": "campaign_detail.virus",
    "campaign_status": "campaign.general_status",
    "n_districts_planned": "computed.n_scope_districts",
    "scope_level": "computed.scope_level",
}


def enrich_scope_with_rounds(scope_path, rounds_path, out_path=None, log=print):
    scope_path, rounds_path = Path(scope_path), Path(rounds_path)
    out_path = Path(out_path) if out_path else scope_path
    if not scope_path.is_file() or not rounds_path.is_file():
        log(f"scope enrichment skipped: {scope_path if not scope_path.is_file() else rounds_path} not found")
        return False
    S = pd.read_csv(scope_path, low_memory=False)
    R = pd.read_csv(rounds_path, low_memory=False)
    S = S.drop(columns=[c for c in FIELDS if c in S.columns])          # idempotent: re-running replaces the columns
    need = ["campaign.obr_name", "round.number"] + [v for v in FIELDS.values() if v in R.columns]
    R = R[need].copy()
    R["_k"] = R["campaign.obr_name"].astype(str).str.strip() + "|Rnd" + R["round.number"].astype("Int64").astype(str)
    R = R.drop_duplicates("_k")
    for c in ("round.ended_at", "round.mop_up_started_at", "round.mop_up_ended_at"):
        if c in R.columns:
            R[c] = pd.to_datetime(R[c], errors="coerce").dt.strftime("%Y-%m-%d")
    S["_k"] = S["response"].astype(str).str.strip() + "|" + S["roundNumber"].astype(str).str.strip()
    add = R.rename(columns={v: k for k, v in FIELDS.items() if v in R.columns}).drop(columns=["campaign.obr_name", "round.number"])
    out = S.merge(add, on="_k", how="left").drop(columns="_k")
    for c in ("round_id", "round_target_population", "age_min", "age_max", "n_districts_planned"):
        if c in out.columns:
            out[c] = pd.to_numeric(out[c], errors="coerce").round().astype("Int64")
    matched = out["round_id"].notna().mean() * 100 if "round_id" in out.columns else 0
    out.to_csv(out_path, index=False, encoding="utf-8")
    log(f"scope enrichment: {len(add.columns) - 1} column(s) added to {out_path.name}; "
        f"{matched:.1f}% of the {len(out)} district rows matched a GPEI round")
    return True


if __name__ == "__main__":
    base = Path(__file__).resolve().parent.parent / "data"
    src = Path(sys.argv[1]) if len(sys.argv) > 1 else base / "scope_.csv"
    rnd = Path(sys.argv[2]) if len(sys.argv) > 2 else base / "gpei_rounds_full.csv"
    dst = Path(sys.argv[3]) if len(sys.argv) > 3 else None
    enrich_scope_with_rounds(src, rnd, dst)
