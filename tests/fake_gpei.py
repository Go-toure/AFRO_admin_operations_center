"""A tiny fake of poliogo.afro.who.int (/api/polio/campaigns/) for the tests. It serves the rows of a lookup workbook as campaigns,
one round per row. GET /mode?extra=N adds N rounds, ?down=1 makes it answer 503. Usage: fake_gpei.py PORT LOOKUP.xlsx"""
import json
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlparse

import pandas as pd

df = pd.read_excel(sys.argv[2])
MODE = {"extra": 0, "down": False}


def campaigns(fieldset):
    out = {}
    for i, r in df.iterrows():
        k = (r["OBR Name"], r["Country"])
        c = out.setdefault(k, {"id": len(out) + 1, "obr_name": r["OBR Name"], "top_level_org_unit_name": r["Country"],
                               "campaign_types": [{"slug": "polio"}], "rounds": []})
        c["rounds"].append({"number": int(str(r["Round Number"]).split()[-1]), "started_at": str(r["Round Start Date"])[:10],
                            "ended_at": "2026-01-01" if r["Round Status"] == "Finished" else None,
                            "vaccine_names": r["Vaccines"] if isinstance(r["Vaccines"], str) else ""})
    res = list(out.values())
    for j in range(MODE["extra"]):
        res.append({"id": 9000 + j, "obr_name": "NEW-%d-2026" % j, "top_level_org_unit_name": "TESTLAND", "campaign_types": [{"slug": "polio"}],
                    "rounds": [{"number": 1, "started_at": "2026-09-0%d" % (1 + j % 8), "ended_at": "2026-01-01", "vaccine_names": "nOPV2"}]})
    if fieldset == "list":
        return [{k: v for k, v in c.items() if k != "rounds"} for c in res]
    return res


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, body=b""):
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        u = urlparse(self.path)
        q = parse_qs(u.query)
        if u.path == "/mode":
            MODE["extra"] = int(q.get("extra", [MODE["extra"]])[0])
            MODE["down"] = q.get("down", ["0"])[0] == "1"
            return self._send(200, b"ok")
        if MODE["down"]:
            return self._send(503)
        if self.headers.get("Authorization") != "Bearer TESTTOKEN":
            return self._send(401)
        lim, pg = int(q["limit"][0]), int(q["page"][0])
        allc = campaigns(q["fieldset"][0])
        chunk = allc[(pg - 1) * lim: pg * lim]
        if pg > 1 and not chunk:
            return self._send(404)
        self._send(200, json.dumps({"campaigns": chunk}).encode())


HTTPServer(("127.0.0.1", int(sys.argv[1])), H).serve_forever()
