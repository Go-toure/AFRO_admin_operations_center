"""The lookup is the authority for the Response name, the start date and the round number (author: Gorgui Ba Toure)."""
import sys
import tempfile
import unittest
from pathlib import Path

import pandas as pd
import openpyxl

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "engine"))
import add_coadmin_columns as b          # noqa: E402
import submissions as sm                 # noqa: E402

RESP = "ANG-2026-08-02_nOPV_NID"


def lookup():
    L = pd.DataFrame({"OBR Name": ["ANG-2026-08-02_nOPV_NID", "ANG-2026-08-02_nOPV_NID", "XXX-2026-01_bOPV", "XXX-2026-01_bOPV"],
                      "Round Number": ["Rnd1", "Rnd2", "Rnd1", "Rnd2"], "Country": ["ANGOLA"] * 4,
                      "Round Start Date": ["2026-08-21", "2026-10-23", "2026-03-01", "2026-03-01"]})   # XXX: two numbers on one date = ambiguous
    L["_ck"] = L["Country"].map(b._lkc)
    L["_rk"] = L["OBR Name"].map(b._rk)
    L["_d"] = L["Round Start Date"]
    L["_rn"] = L["Round Number"].map(b._rnum)
    return L


def frame(rows):
    return pd.DataFrame(rows, columns=["Country", "Response", "SIA_date", "Round_Add"])


class RoundTests(unittest.TestCase):
    def test_lookup_number_replaces_the_one_of_the_file_or_live(self):
        df = frame([["ANGOLA", RESP, "2026-08-21", "Rnd3"], ["ANGOLA", RESP, "2026-10-23", "Rnd4"]])
        new, log = b.lookup_round_labels(df, lookup())
        self.assertEqual(list(new), ["Rnd1", "Rnd2"])
        self.assertEqual(int(log["Records"].sum()), 2)

    def test_unknown_or_ambiguous_rounds_are_left_alone(self):
        df = frame([["ANGOLA", "OTHER-CAMPAIGN", "2026-08-21", "Rnd3"], ["ANGOLA", "XXX-2026-01_bOPV", "2026-03-01", "Rnd5"],
                    ["ANGOLA", RESP, "2026-12-01", "Rnd7"]])
        new, log = b.lookup_round_labels(df, lookup())
        self.assertEqual(list(new), ["Rnd3", "Rnd5", "Rnd7"])
        self.assertEqual(len(log), 0)

    def test_a_round_the_data_labels_twice_on_one_date_is_left_to_the_copied_rounds_rule(self):
        df = frame([["ANGOLA", RESP, "2026-08-21", "Rnd3"], ["ANGOLA", RESP, "2026-08-21", "Rnd4"]])
        new, _ = b.lookup_round_labels(df, lookup())
        self.assertEqual(list(new), ["Rnd3", "Rnd4"])

    def test_sheet_is_relabelled_and_only_round_add_changes(self):
        wb = openpyxl.Workbook()
        ws = wb.active
        header = ["Country", "Response", "SIA_date", "Round_Add", "TotalNbrVaccPolio"]
        ws.append(header)
        ws.append(["ANGOLA", RESP, "2026-08-21", "Rnd3", 100])
        ws.append(["ANGOLA", RESP, "2026-10-23", "Rnd4", 200])
        log, _ = b.align_rounds_to_lookup(ws, header, lookup())
        self.assertEqual([ws.cell(row=r, column=4).value for r in (2, 3)], ["Rnd1", "Rnd2"])
        self.assertEqual([ws.cell(row=r, column=5).value for r in (2, 3)], [100, 200])
        self.assertEqual(int(log["Records"].sum()), 2)
        self.assertEqual(len(b.align_rounds_to_lookup(ws, header, lookup())[0]), 0)      # second run: nothing to do

    def test_lookup_writes_the_round_like_the_admin_data(self):
        self.assertEqual([b._rnd_text(x) for x in ("Round 1", "round 12", "Rnd3", " Round 0 ", "Other")], ["Rnd1", "Rnd12", "Rnd3", "Rnd0", "Other"])
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / "lookup.xlsx"
            pd.DataFrame({"Round Number": ["Round 1", "Round 2"], "OBR Name": ["X-2026-01_nOPV", "X-2026-01_nOPV"], "Country": ["ANGOLA"] * 2,
                          "Round Start Date": ["2026-01-05", "2026-02-05"]}).to_excel(f, index=False)
            L = b.load_lookup(str(f))
        self.assertEqual(list(L["Round Number"]), ["Rnd1", "Rnd2"])
        self.assertEqual(list(L["_rn"]), [1, 2])

    def test_response_follows_the_lookup_spelling(self):
        df = frame([["ANGOLA", "ANG-2026-08-02_nOPV-NID", "2026-08-21", "Rnd1"], ["ANGOLA", "ang-2026-08-02_nopv_nid.", "2026-10-23", "Rnd2"],
                    ["ANGOLA", "OTHER", "2026-08-21", "Rnd1"]])
        new, log = b.lookup_response_names(df, lookup())
        self.assertEqual(list(new), ["ANG-2026-08-02_nOPV_NID", "ANG-2026-08-02_nOPV_NID", "OTHER"])
        self.assertEqual(int(log["Records"].sum()), 2)

    def test_date_moves_to_the_planned_start_only_when_safe(self):
        df = pd.DataFrame({"Country": ["ANGOLA"] * 4, "Response": [RESP] * 4, "SIA_date": ["2026-08-24", "2026-08-24", "2026-09-20", "2026-10-23"],
                           "Round_Add": ["Rnd1", "Rnd1", "Rnd1", "Rnd2"], "Province": ["A", "B", "C", "A"], "District": ["x", "y", "z", "x"]})
        new, log, skipped = b.lookup_dates(df, lookup())
        self.assertEqual(list(new), ["2026-08-21", "2026-08-21", "2026-09-20", "2026-10-23"])     # 3 days from a start: moved; 28 days from any: left
        self.assertEqual(len(skipped), 1)
        # records of the same place already on the planned start: not moved (it would make duplicates)
        df2 = pd.DataFrame({"Country": ["ANGOLA"] * 2, "Response": [RESP] * 2, "SIA_date": ["2026-08-21", "2026-08-24"], "Round_Add": ["Rnd1"] * 2,
                            "Province": ["A", "A"], "District": ["x", "x"]})
        new2, _, sk2 = b.lookup_dates(df2, lookup())
        self.assertEqual(list(new2), ["2026-08-21", "2026-08-24"])
        self.assertIn("duplicates", sk2[0]["Why"])

    def test_a_clash_left_as_it_is_can_make_another_group_clash(self):
        # 09-20 is not in the lookup and is Rnd1; 08-21 (Rnd2 -> Rnd1) would clash with it and is left; then 10-23 (Rnd3 -> Rnd2) would clash with 08-21 and is left too
        df = frame([["ANGOLA", RESP, "2026-09-20", "Rnd1"], ["ANGOLA", RESP, "2026-08-21", "Rnd2"], ["ANGOLA", RESP, "2026-10-23", "Rnd3"]])
        new, log = b.lookup_round_labels(df, lookup())
        self.assertEqual(list(new), ["Rnd1", "Rnd2", "Rnd3"])
        self.assertEqual(len(log), 0)

    def test_a_round_never_ends_on_two_dates_of_one_campaign(self):
        df = frame([["ANGOLA", RESP, "2026-08-21", "Rnd3"], ["ANGOLA", RESP, "2026-09-20", "Rnd1"]])   # 09-20 is not in the lookup and already is Rnd1
        new, _ = b.lookup_round_labels(df, lookup())
        self.assertEqual(list(new), ["Rnd3", "Rnd1"])

    def test_submission_takes_the_lookup_round(self):
        ctx = type("C", (), {})()
        ctx.builder, ctx.lookup = b, lookup()
        P = pd.DataFrame({"Country": ["ANGOLA", "ANGOLA"], "Response": [RESP, RESP], "SIA_date": pd.to_datetime(["2026-08-21", "2026-10-23"]),
                          "Round_Add": ["Rnd3", "Rnd2"], "_src_row": [2, 3]})
        P["Response"] = ["ANG-2026-08-02_nOPV-NID", RESP]

        class N:
            rows = []

            def add(self, *a):
                self.rows.append(a)
        out = sm.align_round_to_lookup(P, ctx, N())
        self.assertEqual(list(P["Round_Add"]), ["Rnd1", "Rnd2"])
        self.assertEqual(P.at[0, "Response"], "ANG-2026-08-02_nOPV_NID")
        self.assertEqual(len(out), 2)


if __name__ == "__main__":
    unittest.main()
