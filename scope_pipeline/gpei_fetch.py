"""The GPEI API part of the scope refresh: lookup.xlsx, gpei_scopes.csv and gpei_rounds_full.csv from poliogo.afro.who.int (GPEI_API_TOKEN).

Copied from the scope folder's prepare_the_AFRO_SIA_Dashboard_input.py (functions only, no browser, no dashboard steps) so that the app
repository carries everything it runs. Called by opscenter/scope_refresh.py."""
import os
import shutil
import sys
import time
from datetime import date, datetime
from pathlib import Path

try:
    sys.stdout.reconfigure(errors="replace")
except Exception:
    pass

GPEI_API_BASE_URL = "https://poliogo.afro.who.int"
DISTRICT_ORG_UNIT_TYPE_ID = 7
DEFAULT_START_DATE = "2019-01-01"
LOOKUP_REQUIRED_COLUMNS = ["Country", "OBR Name", "Vaccines", "Round Number", "Round Start Date"]
LOOKUP_STATUS_COLUMN = "Round Status"
LOOKUP_ALLOWED_STATUSES = {"Finished", "In Progress"}
LOOKUP_MIN_ROW_FRACTION_OF_PREVIOUS = 0.5
LOOKUP_MIN_ABSOLUTE_ROWS = 20


def log(msg):
    # Windows consoles frequently can't print accented characters (this
    # whole project is full of them -- country/district names like
    # COTE D'IVOIRE) unless the console codepage happens to be UTF-8.
    # print() raising UnicodeEncodeError here would kill the whole script
    # with an unhandled exception and no chance for the .bat's `pause` to
    # keep the window open long enough to read it -- so never let a log
    # line itself be the thing that crashes the run.
    try:
        print(f"[scope] {msg}", flush=True)
    except UnicodeEncodeError:
        safe = str(msg).encode("ascii", errors="replace").decode("ascii")
        print(f"[scope] {safe}", flush=True)


def validate_and_install_csv(new_path: Path, final_path: Path, backup_dir: Path) -> bool:
    import pandas as pd

    if not new_path.exists() or new_path.stat().st_size < 100:
        log(f"FAILED: downloaded file missing or too small ({new_path}). Nothing was replaced.")
        return False

    try:
        df = pd.read_csv(new_path)
    except Exception as e:
        log(f"FAILED: downloaded file is not a readable CSV ({e}). Nothing was replaced. "
            f"The raw download is still at {new_path} if you want to inspect it by hand.")
        return False

    log(f"Downloaded CSV has {len(df)} rows and columns: {list(df.columns)}")
    if len(df) == 0:
        log("WARNING: the CSV has 0 data rows. Double-check the date range and that the export actually ran "
            "for the full account scope, not an empty selection.")

    try:
        if final_path.exists():
            backup_dir.mkdir(parents=True, exist_ok=True)
            backup_path = backup_dir / f"gpei_scopes_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
            shutil.copy2(final_path, backup_path)
            log(f"Backed up previous file -> {backup_path}")

        # The site exports plain UTF-8 with no BOM. Excel can't reliably
        # tell that apart from an ANSI codepage on a plain
        # double-click-to-open, so accented characters (country/district
        # names with e -- COTE D'IVOIRE etc.) show up garbled and Excel
        # throws a "format and extension don't match" warning, even
        # though the downloaded data itself is correct. Re-saving with a
        # UTF-8 BOM (encoding="utf-8-sig") fixes both: Excel then
        # auto-detects UTF-8 and opens it cleanly.
        df.to_csv(final_path, index=False, encoding="utf-8-sig")
    except PermissionError as e:
        log(f"FAILED: could not write {final_path} ({e}). This almost always means the file is "
            f"currently open in Excel or another program -- close it and re-run. The freshly "
            f"downloaded data is safe at {new_path} in the meantime; nothing was lost.")
        return False

    try:
        new_path.unlink()
    except Exception:
        pass
    log(f"SUCCESS: {final_path} refreshed ({len(df)} rows), saved as UTF-8 with BOM for clean Excel opening.")
    return True


def validate_and_install_lookup_xlsx(new_path: Path, final_path: Path, backup_dir: Path) -> bool:
    """Ported from im_workflow's refresh_preparedness_lookup.py: the same
    required-columns / status-filter / row-count-vs-previous checks, so a
    silently-broken filter or a partial export never gets installed."""
    import pandas as pd

    if not new_path.exists() or new_path.stat().st_size < 1000:
        log(f"FAILED: downloaded file missing or too small ({new_path}). Nothing was replaced.")
        return False

    try:
        df = pd.read_excel(new_path)
    except Exception as e:
        log(f"FAILED: downloaded file is not a readable Excel file ({e}). Nothing was replaced. "
            f"The raw download is still at {new_path} if you want to inspect it by hand.")
        return False

    missing_cols = [c for c in LOOKUP_REQUIRED_COLUMNS if c not in df.columns]
    if missing_cols:
        log(f"FAILED: downloaded file is missing expected columns: {missing_cols}. "
            f"Got columns: {list(df.columns)}. Nothing was replaced.")
        return False

    if LOOKUP_STATUS_COLUMN in df.columns:
        bad_statuses = set(df[LOOKUP_STATUS_COLUMN].dropna().unique()) - LOOKUP_ALLOWED_STATUSES
        if bad_statuses:
            log(f"FAILED: exported rows include statuses other than {LOOKUP_ALLOWED_STATUSES}: {bad_statuses}. "
                f"This means the Finished/In Progress filter wasn't actually applied. Nothing was replaced.")
            return False
    else:
        log(f"WARNING: '{LOOKUP_STATUS_COLUMN}' column not present in the export -- can't verify the filter was applied.")

    new_rows = len(df)
    if new_rows < LOOKUP_MIN_ABSOLUTE_ROWS:
        log(f"FAILED: only {new_rows} rows in the download (expected at least {LOOKUP_MIN_ABSOLUTE_ROWS}). "
            f"Nothing was replaced.")
        return False

    if final_path.exists():
        try:
            prev_rows = len(pd.read_excel(final_path))
            if prev_rows > 0 and new_rows < prev_rows * LOOKUP_MIN_ROW_FRACTION_OF_PREVIOUS:
                log(f"FAILED: new file has {new_rows} rows, previous had {prev_rows} "
                    f"(< {int(LOOKUP_MIN_ROW_FRACTION_OF_PREVIOUS * 100)}% of previous). "
                    f"Looks like a partial/broken export. Nothing was replaced.")
                return False
        except Exception as e:
            log(f"Could not read the previous lookup.xlsx to compare row counts ({e}); proceeding anyway.")

    try:
        if final_path.exists():
            backup_dir.mkdir(parents=True, exist_ok=True)
            backup_path = backup_dir / f"lookup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
            shutil.copy2(final_path, backup_path)
            log(f"Backed up previous file -> {backup_path}")

        shutil.move(str(new_path), str(final_path))
    except PermissionError as e:
        log(f"FAILED: could not write {final_path} ({e}). This almost always means the file is "
            f"currently open in Excel or another program -- close it and re-run. The freshly "
            f"downloaded data is safe at {new_path} in the meantime; nothing was lost.")
        return False

    log(f"SUCCESS: {final_path} refreshed ({new_rows} rows, statuses: "
        f"{sorted(set(df[LOOKUP_STATUS_COLUMN].dropna().unique())) if LOOKUP_STATUS_COLUMN in df.columns else 'unknown'}).")
    return True


def fetch_all_campaigns(headers, fieldset, page_limit=100, max_pages=500):
    """Paginate GET /api/polio/campaigns/?fieldset=... and return every
    campaign row across all pages, keyed by campaign id. Two different
    fieldsets are fetched and merged elsewhere: "list" carries
    campaign_types/is_test/country, "detail" carries rounds/scopes/
    vaccine/dates -- confirmed via manual API exploration since neither
    fieldset alone has everything build_scope_file.R needs.

    NOTE: this used to fetch "calendar" for the round/scope side, but a
    direct comparison against the manual/original calendar.csv export
    (see fetch_gpei_data_via_api's comments) proved that fieldset's
    per-campaign "scopes" (used whenever a campaign applies one scope to
    every round, i.e. separate_scopes_per_round=false) comes back with
    only {"group": {"id": N}} -- no "org_units" -- so those campaigns
    silently contributed zero scope rows. A live test confirmed the
    SAME paginated bulk endpoint accepts fieldset=detail and returns the
    full {"id", "name", "org_units": [...]} for every campaign (286
    campaigns in ~25s), so "detail" is now used instead everywhere the
    round/scope side is needed. It returns strictly more data than
    "calendar" (rounds are still present with the same structure), so
    this is a safe superset swap, not a behavior change for campaigns
    that were already working.

    IMPORTANT: end-of-data is detected by page SIZE (fewer rows than
    page_limit), the same safe pattern fetch_district_lookup() already
    uses below -- not by trusting the response's "has_next" flag alone.
    A real production comparison against the manual/original Calendar
    export (261 campaigns, 41 countries, spanning 2020-2026) showed this
    endpoint returning only ~41 campaigns / 22 countries all clustered in
    a way consistent with just the FIRST page (page_limit=100, unfiltered
    by campaign type) ever being fetched -- i.e. "has_next" was not a
    reliable signal to keep paginating on. If a future API response's
    has_next is trustworthy this size check is harmless (a full last page
    just costs one extra now-empty-or-short request); if it isn't, this
    is what actually prevents silently truncating the whole dataset to
    page 1 again."""
    import requests

    by_id = {}
    page = 1
    while page <= max_pages:
        r = requests.get(
            f"{GPEI_API_BASE_URL}/api/polio/campaigns/",
            headers=headers,
            params={"fieldset": fieldset, "limit": page_limit, "page": page,
                    "campaign_category": "all", "show_test": "true",
                    "is_embedded": "false", "enabled": "true"},
            timeout=60,
        )
        if r.status_code == 404 and page > 1:
            # The previous page was exactly page_limit rows (total is an
            # exact multiple of page_limit), so this page doesn't exist and
            # the API answers 404 "invalid page" instead of an empty list.
            # That is the normal end of the data, not a failure.
            page -= 1
            break
        r.raise_for_status()
        data = r.json()
        campaigns = data.get("campaigns", [])
        for c in campaigns:
            by_id[c["id"]] = c
        if len(campaigns) < page_limit:
            break
        page += 1
    else:
        log(f"WARNING: fetch_all_campaigns(fieldset={fieldset!r}) hit the {max_pages}-page "
            f"safety cap without reaching a short/empty page -- pagination may still be "
            f"truncated. Raise max_pages if the GPEI dataset has grown that large.")
    log(f"  fieldset={fieldset}: fetched {len(by_id)} campaigns across {page} page(s).")
    return by_id


def fetch_district_lookup(headers, page_limit=500):
    """Paginate GET /api/orgunits/?orgUnitTypeId=7 (districts only,
    ~6,232 total -- orgUnitTypeId is the confirmed-working filter; other
    spellings tried during exploration were silently ignored and
    returned the full ~91,616-row unfiltered org-unit list instead) and
    return {org_unit_id: (country, province, district)}, resolved from
    each row's own name plus its parent/grandparent names."""
    import requests

    lookup = {}
    page = 1
    while True:
        r = requests.get(
            f"{GPEI_API_BASE_URL}/api/orgunits/",
            headers=headers,
            params={"orgUnitTypeId": DISTRICT_ORG_UNIT_TYPE_ID, "limit": page_limit, "page": page},
            timeout=90,
        )
        if r.status_code == 404 and page > 1:
            break  # exact-multiple-of-page_limit total: next page doesn't exist
        r.raise_for_status()
        data = r.json()
        rows = data.get("orgunits", [])
        if not rows:
            break
        for ou in rows:
            district = ou.get("name")
            parent = ou.get("parent") or {}
            province = parent.get("name")
            grandparent = parent.get("parent") or {}
            country = grandparent.get("name")
            lookup[ou["id"]] = (country, province, district)
        if len(rows) < page_limit:
            break
        page += 1
    return lookup


def is_polio_campaign(list_entry):
    return any(ct.get("slug") == "polio" for ct in (list_entry.get("campaign_types") or []))


def compute_round_status(round_obj, today):
    """Finished/In Progress, computed from round dates -- the site no
    longer exposes a separate status field in the fieldsets we use, and
    this is the same logic the old preparedness-dashboard slicer
    effectively applied (a round with no dates yet, or not started yet,
    is neither and gets excluded, matching that slicer never showing
    "Preparing" rounds)."""
    if round_obj.get("is_planned"):
        return None
    started = round_obj.get("started_at")
    ended = round_obj.get("ended_at")
    if not started:
        return None
    started_d = date.fromisoformat(started)
    if started_d > today:
        return None
    if ended:
        ended_d = date.fromisoformat(ended)
        return "Finished" if ended_d < today else "In Progress"
    return "In Progress"


def clean_vaccine_names(raw):
    """The GPEI API's per-round vaccine_names field sometimes lists both
    an individual vaccine AND a combined-scope label that already
    includes it for the same round -- e.g. "nOPV2, nOPV2 & bOPV"
    instead of just "nOPV2 & bOPV" (confirmed against real data pulled
    for the sibling LQAS and im_workflow projects: a few rows out of
    462 showed this pattern). lookup.xlsx's Vaccines column is used as
    part of a downstream join key in some consumers, so a redundant/
    inflated string here can silently break matches. Drop any
    comma-separated token that's a strict substring of another token in
    the same value, then de-duplicate what's left, preserving order.
    """
    if not raw:
        return raw
    tokens = [t.strip() for t in raw.split(",") if t.strip()]
    if not tokens:
        return raw
    kept = [t for i, t in enumerate(tokens)
            if not any(i != j and t != other and t in other for j, other in enumerate(tokens))]
    seen = set()
    deduped = []
    for t in kept:
        if t not in seen:
            seen.add(t)
            deduped.append(t)
    return ", ".join(deduped) if deduped else raw


def _gpei_flat(d, prefix, depth=1):
    """The scalar fields of one API object (and of its small sub-objects, one level), prefixed; lists of scalars are joined with |, lists of objects that have a
    slug / name are joined by it. Large nested lists (rounds, scopes, shapes) are left out. Used to keep EVERY field the API gives, not only the few the scope uses."""
    out = {}
    for k, v in (d or {}).items():
        key = prefix + str(k)
        if v is None or isinstance(v, (str, int, float, bool)):
            out[key] = v
        elif isinstance(v, dict) and depth > 0:
            out.update(_gpei_flat(v, key + ".", depth - 1))
        elif isinstance(v, list) and v and all(isinstance(x, (str, int, float, bool)) for x in v) and len(v) <= 50:
            out[key] = "|".join(str(x) for x in v)
        elif isinstance(v, list) and v and all(isinstance(x, dict) for x in v) and len(v) <= 50:
            names = [str(x.get("slug") or x.get("name") or x.get("id") or "") for x in v]
            if any(names):
                out[key] = "|".join(names)
    return out


def fetch_gpei_data_via_api(base_dir: Path, data_dir: Path, backup_dir: Path,
                             start_date: str, end_date: str, debug_dir=None):
    """Replaces the old Playwright login + preparedness-dashboard-export +
    Calendar-DOWNLOAD-SCOPES flow with direct calls to poliogo.afro.who.int's
    own REST API. Returns (lookup_ok, scopes_ok), same shape the old
    caller in run() expected.

    Two different filters, matching the two different old data sources:
      - lookup.xlsx: Finished/In Progress rounds only (old preparedness
        dashboard slicer filter), regardless of date.
      - gpei_scopes.csv: rounds whose start date falls in
        [start_date, end_date] (old Calendar date-range dialog filter),
        regardless of Finished/In Progress status.
    Both are restricted to campaigns whose type is "polio", matching the
    old Calendar URL's hardcoded campaignType/polio.
    """
    import pandas as pd

    token = os.environ.get("GPEI_API_TOKEN", "").strip()
    if not token:
        log("FAILED: GPEI_API_TOKEN is not set. Get it from "
            "https://poliogo.afro.who.int/dashboard/api/apitoken and add it to "
            "the .env file of the app (or the hosting variables) as GPEI_API_TOKEN=... (treat it like a password -- "
            "never paste it anywhere else).")
        return False, False

    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
    start_d = date.fromisoformat(start_date)
    end_d = date.fromisoformat(end_date)
    today = date.today()

    try:
        log("Fetching campaigns from the GPEI API (fieldset=list)...")
        list_by_id = fetch_all_campaigns(headers, "list")
        log("Fetching campaigns from the GPEI API (fieldset=detail)...")
        detail_by_id = fetch_all_campaigns(headers, "detail")
    except Exception as e:
        log(f"FAILED: could not fetch campaigns from the GPEI API ({e}).")
        return False, False

    polio_ids = [cid for cid, c in list_by_id.items() if is_polio_campaign(c)]
    log(f"{len(polio_ids)} of {len(list_by_id)} campaigns are Polio-type.")

    # DIAGNOSTIC: is_polio_campaign() only keeps campaigns carrying a
    # campaign_types entry whose slug is EXACTLY "polio". If the site
    # tags some genuinely-polio campaigns under a different/related slug
    # (a casing difference, a more specific sub-type, a renamed slug,
    # etc.) this filter would silently drop them the same way the old
    # round_start_date merge bug silently dropped whole countries -- no
    # error, it just looks like "no scope for that country/period". Log
    # the full slug breakdown every run so a mismatch is visible instead
    # of invisible.
    from collections import Counter
    slug_counts = Counter()
    for c in list_by_id.values():
        types = c.get("campaign_types") or []
        if not types:
            slug_counts["(none)"] += 1
        for ct in types:
            slug_counts[ct.get("slug") or "(blank slug)"] += 1
    log(f"campaign_types slug breakdown across all {len(list_by_id)} fetched campaigns "
        f"(a campaign can carry more than one, so this can sum to more than {len(list_by_id)}): "
        f"{dict(slug_counts.most_common())}")
    non_polio_ids = [cid for cid, c in list_by_id.items() if not is_polio_campaign(c)]
    non_polio_sample = []
    if non_polio_ids:
        for cid in non_polio_ids[:10]:
            c = list_by_id[cid]
            slugs = [ct.get("slug") for ct in (c.get("campaign_types") or [])]
            non_polio_sample.append(f"{c.get('obr_name')} ({c.get('top_level_org_unit_name')}): {slugs}")
        log(f"Sample of the {len(non_polio_ids)} campaigns EXCLUDED as non-Polio (check these "
            f"slugs by eye -- if any look like they should count as Polio, that's the bug, "
            f"not a real exclusion): {non_polio_sample}")

    try:
        log("Building the district id -> (country, province, district) lookup table...")
        district_lookup = fetch_district_lookup(headers)
    except Exception as e:
        log(f"FAILED: could not fetch the district org-unit lookup table ({e}).")
        return False, False
    log(f"Resolved {len(district_lookup)} districts.")

    lookup_rows = []
    scope_rows = []
    rounds_full_rows = []      # every round of every Polio campaign with every scalar field the API gives (data/gpei_rounds_full.csv)
    unresolved_ids = set()
    missing_detail_entries = []

    # DIAGNOSTIC: even with campaign selection now confirmed correct (252
    # of 286 fetched campaigns are genuinely Polio-type, matching the
    # non-Polio slugs seen), the automated gpei_scopes.csv row count has
    # stayed flat at 16,964 rows across code changes -- vs. ~49,824 in the
    # manual/original calendar.csv for a similar campaign count. That
    # means most of the shortfall is NOT which campaigns get included,
    # it's how many rounds/scopes each included campaign actually
    # contributes. Track that directly instead of guessing further.
    rounds_seen = 0
    rounds_missing_started_at = 0
    rounds_out_of_date_range = 0
    rounds_in_range_with_no_scopes = 0
    rounds_using_campaign_level_scopes = 0
    campaigns_with_zero_scope_rows = []

    for cid in polio_ids:
        list_entry = list_by_id[cid]
        detail_entry = detail_by_id.get(cid)
        if not detail_entry:
            # The "list" and "detail" fieldsets are fetched as two
            # separate paginated requests (see fetch_all_campaigns) with
            # the same filters, so every polio campaign id should appear
            # in both -- but if the API ever returns them inconsistently,
            # this silently drops the WHOLE campaign (every round, every
            # district) with no warning. Record it instead of just
            # `continue`-ing past it, so a real mismatch is visible in
            # the debug summary rather than looking like a country with
            # no scope for the period.
            missing_detail_entries.append({
                "id": cid,
                "obr_name": list_entry.get("obr_name"),
                "country": list_entry.get("top_level_org_unit_name"),
            })
            continue
        obr_name = list_entry.get("obr_name")
        country = list_entry.get("top_level_org_unit_name")
        scope_rows_before = len(scope_rows)
        had_rounds_in_range = False

        # ROOT CAUSE (confirmed by directly comparing the API's raw JSON
        # against the manual/original calendar.csv for known-good
        # campaigns like NIG-9DS-06-2021_Zinder and CHA-91DS-11-2020):
        # when a campaign has "separate_scopes_per_round": false, the
        # GPEI API puts the real scope groups/org_units on the CAMPAIGN
        # object itself (a sibling of "rounds"), and leaves every
        # individual round's own "scopes" list empty. The code below used
        # to only ever read rnd.get("scopes"), so every campaign-wide-
        # scope campaign (the majority -- 352 of 462 in-range rounds in
        # the last full run) silently produced zero scope rows even
        # though the district list was present one level up in the same
        # response. Fall back to the campaign-level scopes whenever a
        # round doesn't carry its own -- this does not affect campaigns
        # that already worked (separate_scopes_per_round: true, where
        # each round's own non-empty "scopes" list is used as before).
        #
        # UPDATE: the campaign-level "scopes" being hollow (group with no
        # org_units) turned out to be specific to fieldset=calendar --
        # fetch_all_campaigns now uses fieldset=detail instead, which
        # carries org_units at both levels (confirmed live: 286 campaigns
        # fetched in ~25s, NIG-9DS-06-2021_Zinder's campaign-level scope
        # showing all 9 districts, CHA-91DS-11-2020's showing all 126).
        # This fallback is kept anyway as defense-in-depth -- it's what
        # makes campaign-wide scoping (separate_scopes_per_round: false)
        # work at all, regardless of which fieldset is used.
        campaign_scopes = detail_entry.get("scopes") or []

        for rnd in detail_entry.get("rounds", []):
            rounds_seen += 1
            number = rnd.get("number")
            started_at = rnd.get("started_at")
            vaccine_names = clean_vaccine_names(rnd.get("vaccine_names") or "")

            status = compute_round_status(rnd, today)
            try:
                _sc = (rnd.get("scopes") or []) or campaign_scopes
                _row = {}
                _row.update(_gpei_flat(list_entry, "campaign."))
                _row.update({k: v for k, v in _gpei_flat(detail_entry, "campaign_detail.").items() if k.replace("campaign_detail.", "campaign.") not in _row})
                _row.update(_gpei_flat(rnd, "round."))
                _row.update({"computed.round_status": status or "", "computed.n_scope_groups": len(_sc), "computed.scope_level": "round" if (rnd.get("scopes") or []) else ("campaign" if campaign_scopes else "none"),
                             "computed.n_scope_districts": sum(len(((s_.get("group") or {}).get("org_units")) or []) for s_ in _sc),
                             "computed.scope_vaccines": "|".join(sorted({str(s_.get("vaccine")) for s_ in _sc if s_.get("vaccine")}))})
                rounds_full_rows.append(_row)
            except Exception as _e:
                if len(rounds_full_rows) == 0:
                    log(f"(round detail export: {_e})")
            if status and started_at:
                lookup_rows.append({
                    "Round Number": f"Round {number}",
                    "OBR Name": obr_name,
                    "Vaccines": vaccine_names,
                    "Country": country,
                    "Round Start Date": started_at,
                    "Round Status": status,
                })

            if not started_at:
                rounds_missing_started_at += 1
                continue
            started_d = date.fromisoformat(started_at)
            if not (start_d <= started_d <= end_d):
                rounds_out_of_date_range += 1
                continue
            had_rounds_in_range = True

            round_scopes = rnd.get("scopes") or []
            if round_scopes:
                scopes = round_scopes
            elif campaign_scopes:
                scopes = campaign_scopes
                rounds_using_campaign_level_scopes += 1
            else:
                scopes = []
            if not scopes:
                rounds_in_range_with_no_scopes += 1
            for scope in scopes:
                vaccine = scope.get("vaccine") or ""
                org_units = ((scope.get("group") or {}).get("org_units")) or []
                for oid in org_units:
                    resolved = district_lookup.get(oid)
                    if not resolved:
                        unresolved_ids.add(oid)
                        continue
                    r_country, province, district = resolved
                    scope_rows.append({
                        "ID": oid,
                        "Admin 2": district,
                        "Admin 1": province,
                        "Admin 0": r_country,
                        "OBR Name": obr_name,
                        "Round Number": f"R{number}",
                        "Start date": started_at,
                        "Vaccine": vaccine,
                    })

        if had_rounds_in_range and len(scope_rows) == scope_rows_before:
            campaigns_with_zero_scope_rows.append(f"{obr_name} ({country})")

    log(f"Round/scope diagnostic -- rounds seen: {rounds_seen}, missing started_at: "
        f"{rounds_missing_started_at}, out of [{start_date}..{end_date}]: {rounds_out_of_date_range}, "
        f"in-range rounds that fell back to the campaign-level 'scopes' (separate_scopes_per_round=false): "
        f"{rounds_using_campaign_level_scopes}, in-range rounds still with an EMPTY scopes list after "
        f"that fallback: {rounds_in_range_with_no_scopes}.")
    if campaigns_with_zero_scope_rows:
        log(f"WARNING: {len(campaigns_with_zero_scope_rows)} Polio campaign(s) had at least one "
            f"round inside the date range but produced ZERO scope rows (empty/unresolvable scopes "
            f"for every in-range round) -- sample: {campaigns_with_zero_scope_rows[:15]}. If a "
            f"country you expect scope data for is missing from gpei_scopes.csv, check here.")

    if unresolved_ids:
        log(f"WARNING: {len(unresolved_ids)} distinct org-unit IDs in scopes could not be "
            f"resolved to a district name (sample: {sorted(unresolved_ids)[:10]}) -- those "
            f"rows were dropped. This is usually a handful of old/merged org units from "
            f"pre-2020 campaigns and shouldn't affect current data.")

    if missing_detail_entries:
        sample = [f"{m['obr_name']} ({m['country']})" for m in missing_detail_entries[:10]]
        log(f"WARNING: {len(missing_detail_entries)} polio campaign(s) had no matching "
            f"'detail' fieldset entry and were skipped entirely -- no rounds, no scope "
            f"rows, for these (sample: {sample}). If a country you expect to see data for "
            f"is missing, check here first.")

    if debug_dir:
        try:
            debug_dir.mkdir(parents=True, exist_ok=True)
            summary_path = debug_dir / "gpei_api_fetch_summary.txt"
            summary_path.write_text(
                f"polio campaigns: {len(polio_ids)} of {len(list_by_id)}\n"
                f"campaign_types slug breakdown (all fetched campaigns): {dict(slug_counts.most_common())}\n"
                f"sample of campaigns excluded as non-Polio: {non_polio_sample if non_polio_ids else '(none excluded)'}\n"
                f"rounds seen: {rounds_seen}, missing started_at: {rounds_missing_started_at}, "
                f"out of date range: {rounds_out_of_date_range}, in-range rounds that used the "
                f"campaign-level scopes fallback: {rounds_using_campaign_level_scopes}, in-range "
                f"rounds still with empty scopes after that fallback: {rounds_in_range_with_no_scopes}\n"
                f"campaigns with an in-range round but zero scope rows: {campaigns_with_zero_scope_rows}\n"
                f"districts resolved: {len(district_lookup)}\n"
                f"lookup rows: {len(lookup_rows)}\n"
                f"scope rows: {len(scope_rows)}\n"
                f"unresolved org-unit ids: {sorted(unresolved_ids)}\n"
                f"campaigns missing a detail-fieldset entry (skipped entirely): {missing_detail_entries}\n",
                encoding="utf-8",
            )
            log(f"Saved fetch summary: {summary_path}")
        except Exception as e:
            log(f"(could not save debug summary: {e})")

    try:
        if rounds_full_rows:
            _rf = pd.DataFrame(rounds_full_rows)
            _rf.to_csv(data_dir / "gpei_rounds_full.csv", index=False, encoding="utf-8-sig")
            log(f"Saved data/gpei_rounds_full.csv: {len(_rf)} rounds of {len(polio_ids)} Polio campaigns, {len(_rf.columns)} fields from the API "
                f"(every scalar field of the campaign and of the round, plus the scope size and vaccines).")
    except Exception as _e:
        log(f"(could not save data/gpei_rounds_full.csv: {_e})")

    lookup_tmp = data_dir / f"_lookup_download_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
    scopes_tmp = data_dir / f"_gpei_scopes_download_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    try:
        pd.DataFrame(lookup_rows).to_excel(lookup_tmp, index=False)
        pd.DataFrame(scope_rows).to_csv(scopes_tmp, index=False, encoding="utf-8-sig")
    except PermissionError as e:
        log(f"FAILED: could not write a temp download file ({e}).")
        return False, False

    lookup_ok = validate_and_install_lookup_xlsx(lookup_tmp, data_dir / "lookup.xlsx", backup_dir)
    scopes_ok = validate_and_install_csv(scopes_tmp, data_dir / "gpei_scopes.csv", backup_dir)
    return lookup_ok, scopes_ok
