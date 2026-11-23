"""Integrated campaigns: the figures decide which interventions a file carries, a live record is completed and never duplicated (author: Gorgui Ba Toure)."""
import sys
import tempfile
import unittest
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "engine"))
import add_coadmin_columns as b          # noqa: E402


def live_row(**kw):
    r = {c: None for c in ("Country", "Province", "District", "Admin_3", "SIA_date", "Round_Add", "Vaccine_type", "Response", "IntegMeasles", "PopMeasles", "AgeGMeasles",
                           "NbrVacMeasles", "CVMeasles", "IntegYF", "PopYF", "NbrVacYF", "IntegIPV", "TotalNbrVaccIPV", "SIA_Integrated", "TotalNbrVaccPolio")}
    r.update({"Country": "ANGOLA", "Province": "BENGO", "District": "AMBRIZ", "SIA_date": "2026-10-23", "Round_Add": "Rnd4", "Vaccine_type": "nOPV2",
              "Response": "ANG-2026-08-02_nOPV-NID", "IntegMeasles": "No", "IntegYF": "No", "IntegIPV": "No", "TotalNbrVaccPolio": 7859})
    r.update(kw)
    return r


class IntegratedTests(unittest.TestCase):
    def test_figures_decide_not_flags(self):
        df = pd.DataFrame([live_row(NbrVacMeasles=8125, IntegMeasles="Yes"), live_row(NbrVacYF=500, IntegYF="No"), live_row(IntegMeasles="Yes")])
        ev = b.integrated_evidence(df)
        self.assertEqual(list(ev["measles-rubella"]), [True, False, False])      # the third says Yes and has no figure: no evidence
        self.assertEqual(list(ev["yellow fever"]), [False, True, False])          # the flag said No: the figures are the evidence
        self.assertFalse(any(ev["IPV"]))

    def test_additions_complete_a_polio_only_record_and_keep_polio(self):
        f = live_row(IntegMeasles="Yes", PopMeasles=10638, AgeGMeasles="9M-14Y", NbrVacMeasles=8125, CVMeasles=0.76, IntegYF="No", NbrVacYF=0, TotalNbrVaccPolio=9999)
        lv = live_row()
        lines, diffs = b.integrated_additions(f, lv, {"Row_in_file": 2})
        cols = {l["Column"]: l["Restored"] for l in lines}
        self.assertEqual(cols["IntegMeasles"], "Yes")
        self.assertEqual(cols["NbrVacMeasles"], 8125)
        self.assertEqual(cols["SIA_Integrated"], "Yes")
        self.assertNotIn("TotalNbrVaccPolio", cols)                              # the polio figures are never touched
        self.assertNotIn("IntegYF", cols)                                        # nothing for yellow fever: no figure
        self.assertEqual(diffs, [])

    def test_existing_integrated_figures_are_not_overwritten(self):
        f = live_row(IntegMeasles="Yes", NbrVacMeasles=8125)
        lv = live_row(IntegMeasles="Yes", NbrVacMeasles=1111)
        lines, diffs = b.integrated_additions(f, lv, {})
        self.assertEqual(lines, [])
        self.assertEqual(len(diffs), 1)
        self.assertEqual(diffs[0]["Live_value"], 1111)

    def test_enrich_records_is_guarded_and_idempotent(self):
        import openpyxl
        header = ["Country", "Province", "District", "Admin_3", "SIA_date", "Round_Add", "Vaccine_type", "Response", "IntegMeasles", "NbrVacMeasles", "SIA_Integrated"]
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.append(header)
        import datetime as dt
        ws.append(["ANGOLA", "BENGO", "AMBRIZ", None, dt.datetime(2026, 10, 23), "Rnd4", "nOPV2", "ANG-2026-08-02_nOPV-NID", "No", None, "No"])
        ws.append(["ANGOLA", "BENGO", "DANDE", None, dt.datetime(2026, 10, 23), "Rnd4", "nOPV2", "ANG-2026-08-02_nOPV-NID", "Yes", 1111, "Yes"])
        ident = {"Country": "ANGOLA", "Province": "BENGO", "Admin_3": "", "SIA_date": "2026-10-23", "Round_Add": "Rnd4", "Vaccine_type": "nOPV2", "Response": "ANG-2026-08-02_nOPV-NID"}
        rows = []
        for dist, col, found, new in (("AMBRIZ", "IntegMeasles", "No", "Yes"), ("AMBRIZ", "NbrVacMeasles", "", 8125), ("AMBRIZ", "SIA_Integrated", "No", "Yes"),
                                      ("DANDE", "NbrVacMeasles", "", 24965)):          # DANDE: the live cell holds 1111, not what the inspection saw
            rows.append(dict(ident, District=dist, Antigen="measles-rubella", Column=col, Found=found, Restored=new))
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "prepared.xlsx"
            with pd.ExcelWriter(p) as xw:
                pd.DataFrame({"Country": []}).to_excel(xw, sheet_name="Sheet1", index=False)
                pd.DataFrame(rows).to_excel(xw, sheet_name="Integrated_additions", index=False)
            done, skipped = b.enrich_records(ws, header, [str(p)])
            self.assertEqual(len(done), 3)
            self.assertEqual(len(skipped), 1)                                       # DANDE: not changed
            self.assertEqual(ws.cell(row=2, column=10).value, 8125)
            self.assertEqual(ws.cell(row=3, column=10).value, 1111)
            done2, skipped2 = b.enrich_records(ws, header, [str(p)])               # again: nothing changes, nothing duplicated
            self.assertEqual(len(done2), 0)
            self.assertEqual(ws.max_row, 3)


if __name__ == "__main__":
    unittest.main()
