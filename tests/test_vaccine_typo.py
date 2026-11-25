"""mOPV2 written for a campaign is read as nOPV2: by the lookup, or by the year when the campaign is not in the lookup (author: Gorgui Ba Toure)."""
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "engine"))
import add_coadmin_columns as b          # noqa: E402
import submissions as sm                 # noqa: E402

NOPV = "ALG-2025-09-01_nOPV_NID"
BOPV = "ALG-2025-10-01_bOPV_NID"


def ctx():
    L = pd.DataFrame({"OBR Name": [NOPV, NOPV, BOPV], "Round Number": ["Rnd1", "Rnd2", "Rnd1"], "Country": ["ALGERIA"] * 3,
                      "Vaccines": ["nOPV2", "nOPV2", "bOPV"]})
    L["_ck"] = L["Country"].map(b._lkc)
    L["_rk"] = L["OBR Name"].map(b._rk)
    L["_vs"] = L["Vaccines"].map(b._vset)
    return SimpleNamespace(builder=b, lookup=L)


def frame(rows):
    P = pd.DataFrame(rows, columns=["Country", "Response", "SIA_date", "Vaccine_type", "TotalNbrVaccPolio"])
    P["_src_row"] = range(2, len(P) + 2)
    return P


class T(unittest.TestCase):
    def run_it(self, rows):
        P = frame(rows)
        before = P.copy()
        notes = sm.Notes()
        msgs = sm.correct_mopv2(P, ctx(), notes)
        return before, P, msgs, notes

    def test_lookup_has_nopv2(self):
        before, P, msgs, notes = self.run_it([("ALGERIA", NOPV, "2025-12-21", "mOPV2", 10), ("ALGERIA", NOPV, "2025-12-21", "mOPV2", 20)])
        self.assertEqual(list(P["Vaccine_type"]), ["nOPV2", "nOPV2"])
        self.assertEqual(len(msgs), 1)
        self.assertIn("2 record(s)", msgs[0])
        self.assertIn("lookup", msgs[0])
        self.assertEqual(len(notes.rows), 2)
        self.assertEqual(sm.vaccine_vs_lookup(P, ctx()), [])          # nothing left to ask the country
        self.assertEqual(list(P["TotalNbrVaccPolio"]), [10, 20])

    def test_lookup_has_no_nopv2(self):
        # a bOPV campaign written mOPV2 is not the nOPV2 typo: left to vaccine_vs_lookup
        before, P, msgs, notes = self.run_it([("ALGERIA", BOPV, "2025-11-01", "mOPV2", 10)])
        self.assertEqual(list(P["Vaccine_type"]), ["mOPV2"])
        self.assertEqual(msgs, [])
        self.assertEqual(len(sm.vaccine_vs_lookup(P, ctx())), 1)

    def test_not_in_lookup_year_rule(self):
        before, P, msgs, notes = self.run_it([("ALGERIA", "ALG-2025-99_unknown", "2025-03-01", "mOPV2", 1),
                                              ("ALGERIA", "ALG-2021-01_old", "2021-06-01", "mOPV2", 2),      # real mOPV2 year: untouched
                                              ("ALGERIA", "ALG-2026-01_new", "2026-02-01", "mvpo2", 3),
                                              ("ALGERIA", "ALG-2026-01_new", None, "mOPV2", 4)])             # no date: untouched
        self.assertEqual(list(P["Vaccine_type"]), ["nOPV2", "mOPV2", "nOPV2", "mOPV2"])
        self.assertEqual(len(msgs), 2)

    def test_only_the_targeted_records_change(self):
        rows = [("ALGERIA", NOPV, "2025-12-21", "mOPV2", 1), ("ALGERIA", NOPV, "2025-12-21", "nOPV2", 2),
                ("ALGERIA", NOPV, "2025-12-21", "nOPV2 & mOPV2", 3), ("ALGERIA", BOPV, "2025-11-01", "bOPV", 4),
                ("ALGERIA", NOPV, "2025-12-21", None, 5)]
        before, P, msgs, notes = self.run_it(rows)
        changed = (before["Vaccine_type"].fillna("") != P["Vaccine_type"].fillna(""))
        self.assertEqual(list(changed), [True, False, False, False, False])
        self.assertTrue((before.drop(columns="Vaccine_type") == P.drop(columns="Vaccine_type")).all().all())

    def test_no_vaccine_column(self):
        P = pd.DataFrame({"Country": ["ALGERIA"], "_src_row": [2]})
        self.assertEqual(sm.correct_mopv2(P, ctx(), sm.Notes()), [])


if __name__ == "__main__":
    unittest.main()
