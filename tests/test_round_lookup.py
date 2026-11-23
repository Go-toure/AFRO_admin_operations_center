"""The lookup is the authority for the round number (author: Gorgui Ba Toure)."""
import sys
import unittest
from pathlib import Path

import pandas as pd
import openpyxl

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "engine"))
import add_coadmin_columns as b          # noqa: E402
import submissions as sm                 # noqa: E402

RESP = "ANG-2026-08-02_nOPV-NID"


def lookup():
    L = pd.DataFrame({"OBR Name": ["ANG-2026-08-02_nOPV_NID", "ANG-2026-08-02_nOPV_NID", "XXX-2026-01_bOPV", "XXX-2026-01_bOPV"],
                      "Round Number": ["Round 1", "Round 2", "Round 1", "Round 2"], "Country": ["ANGOLA"] * 4,
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
        log = b.align_rounds_to_lookup(ws, header, lookup())
        self.assertEqual([ws.cell(row=r, column=4).value for r in (2, 3)], ["Rnd1", "Rnd2"])
        self.assertEqual([ws.cell(row=r, column=5).value for r in (2, 3)], [100, 200])
        self.assertEqual(int(log["Records"].sum()), 2)
        self.assertEqual(len(b.align_rounds_to_lookup(ws, header, lookup())), 0)      # second run: nothing to do

    def test_submission_takes_the_lookup_round(self):
        ctx = type("C", (), {})()
        ctx.builder, ctx.lookup = b, lookup()
        P = pd.DataFrame({"Country": ["ANGOLA", "ANGOLA"], "Response": [RESP, RESP], "SIA_date": pd.to_datetime(["2026-08-21", "2026-10-23"]),
                          "Round_Add": ["Rnd3", "Rnd2"], "_src_row": [2, 3]})

        class N:
            rows = []

            def add(self, *a):
                self.rows.append(a)
        out = sm.align_round_to_lookup(P, ctx, N())
        self.assertEqual(list(P["Round_Add"]), ["Rnd1", "Rnd2"])
        self.assertEqual(len(out), 1)


if __name__ == "__main__":
    unittest.main()
