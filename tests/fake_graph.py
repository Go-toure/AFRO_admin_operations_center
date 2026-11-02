"""A small fake of Microsoft Graph for testing the Operations Center without touching SharePoint.

    python tests/fake_graph.py PORT STORE_DIR ADMIN_FILE DICT_FILE [mode]

It serves: the token endpoint, share links (admin file, dictionary, the store folder), folder listing / content /
upload sessions / delete below the store folder, version listing and deletion, a recycle bin. Testing only."""
import base64
import io
import json
import shutil
import sys
import threading
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

PORT = int(sys.argv[1])
STORE = Path(sys.argv[2])
PATHS = {"ITEM1": Path(sys.argv[3]), "ITEM2": Path(sys.argv[4])}
MODE = sys.argv[5] if len(sys.argv) > 5 else "ok"
NAMES = {"ITEM1": "AFRO_admin_data.xlsx", "ITEM2": "AFRO_admin_data_dictionary.xlsx"}
BASE = "http://127.0.0.1:%d" % PORT
STORE.mkdir(parents=True, exist_ok=True)
FV = {}          # versions of store files: {item id: [version dicts]}
IDPATH = {}      # an item id that was renamed keeps pointing at the item (as real item ids do): {id: current relative path}
state = {"etag": {"ITEM1": "e1", "ITEM2": "d1"}, "upload": {}, "log": [],
         "versions": {"ITEM1": [{"id": "3.0", "lastModifiedDateTime": "2026-10-28T14:08:00Z", "size": 11000000},
                                {"id": "2.0", "lastModifiedDateTime": "2026-10-28T10:30:00Z", "size": 10900000}],
                      "ITEM2": [{"id": "4.0", "lastModifiedDateTime": "2026-10-28T14:08:00Z", "size": 24000},
                                {"id": "3.0", "lastModifiedDateTime": "2026-10-27T10:30:00Z", "size": 23000}]},
         "bin": []}
MOD = {"ITEM1": "2026-10-28T14:08:19Z", "ITEM2": "2026-10-28T14:08:19Z"}
USER = {"user": {"displayName": "Test User"}}


def file_item(iid):
    return {"id": iid, "name": NAMES[iid], "size": PATHS[iid].stat().st_size, "eTag": state["etag"][iid],
            "lastModifiedDateTime": MOD[iid], "lastModifiedBy": USER, "file": {},
            "parentReference": {"driveId": "DRIVE1", "siteId": "SITE1"},
            "@microsoft.graph.downloadUrl": BASE + "/dl/" + iid}


def store_item():
    return {"id": "STORE", "name": "AdminOps", "folder": {"childCount": 1}, "parentReference": {"driveId": "DRIVE1", "siteId": "SITE1"}}


def parse_store_path(path):
    """/drives/DRIVE1/items/STORE:/a/b.txt:/content -> ('a/b.txt', 'content'); /drives/DRIVE1/items/STORE/children -> ('', 'children')"""
    p = urlparse(path).path
    pre = "/drives/DRIVE1/items/STORE"
    if not p.startswith(pre):
        return None
    rest = p[len(pre):]
    if rest.startswith(":/"):
        inner, _, tail = rest[2:].partition(":")
        return unquote(inner).strip("/"), tail.strip("/")
    return "", rest.strip("/")


def item_of(path):
    for k in NAMES:
        if "/items/%s" % k in path:
            return k


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def send(self, code, body=b"", ctype="application/json"):
        if isinstance(body, (dict, list)):
            body = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def body(self):
        n = int(self.headers.get("Content-Length") or 0)
        return self.rfile.read(n) if n else b""

    def child_meta(self, p):
        st = p.stat()
        d = {"name": p.name, "size": st.st_size if p.is_file() else 0, "lastModifiedDateTime": __import__("datetime").datetime.utcfromtimestamp(st.st_mtime).strftime("%Y-%m-%dT%H:%M:%SZ")}
        d["folder" if p.is_dir() else "file"] = {}
        return d

    def add_version(self, key, existed):
        """A SharePoint overwrite keeps the old content as a version; a new file has one version only."""
        if not existed:
            IDPATH.pop(key, None)            # a new file at this path gets a fresh id
        n = len(FV.get(key, [])) if existed else 0
        FV[key] = [{"id": "%d.0" % (n + 2), "lastModifiedDateTime": "2026-10-30T12:00:%02dZ" % min(59, n + 1), "size": 1000}] + (FV.get(key, []) if existed else [])
        if existed and n == 0:
            FV[key].append({"id": "1.0", "lastModifiedDateTime": "2026-10-29T12:00:00Z", "size": 1000})

    def do_PATCH(self):
        p, b = self.path, self.body()
        if p.startswith("/drives/DRIVE1/items/F:"):
            rel = unquote(p[len("/drives/DRIVE1/items/F:"):])
            iid0 = "F:" + rel
            rel = IDPATH.get(iid0, rel)
            src = STORE / rel
            new = json.loads(b)["name"]
            dst = src.parent / new
            if not src.exists():
                return self.send(404, {"error": "nf"})
            if dst.exists():
                return self.send(409, {"error": "nameAlreadyExists"})
            src.rename(dst)
            nk = "F:" + dst.relative_to(STORE).as_posix()
            if "F:" + rel in FV:
                FV[nk] = FV.pop("F:" + rel)
            IDPATH[iid0] = dst.relative_to(STORE).as_posix()
            return self.send(200, {"id": iid0, "name": new})
        self.send(404)

    def do_POST(self):
        p, b = self.path, self.body()
        if p.endswith("/token"):
            return self.send(200, {"access_token": "T", "expires_in": 3600})
        if p.startswith("/drives/DRIVE1/items/F:") and p.endswith("/permanentDelete"):
            if state.get("noperm"):
                return self.send(403, {"error": "denied"})
            rel = unquote(p[len("/drives/DRIVE1/items/F:"):-len("/permanentDelete")])
            rel = IDPATH.pop("F:" + rel, rel)
            t = STORE / rel
            if t.is_file():
                t.unlink()
            elif t.is_dir():
                shutil.rmtree(t)
            else:
                return self.send(404, {"error": "nf"})
            state["perm"] = state.get("perm", 0) + 1
            return self.send(204)
        sp = parse_store_path(p)
        if sp and sp[1] == "createUploadSession":
            state["upload"][sp[0]] = bytearray()
            return self.send(200, {"uploadUrl": "%s/sup/%s" % (BASE, sp[0])})
        if p.endswith("/createUploadSession"):
            k = item_of(p)
            if MODE == "dict_locked" and k == "ITEM2":
                return self.send(423, {"error": "locked"})
            if self.headers.get("If-Match") != state["etag"][k]:
                return self.send(412, {"error": "etag"})
            state["upload"][k] = bytearray()
            return self.send(200, {"uploadUrl": BASE + "/up/" + k})
        if p.endswith("/recycleBin/items/delete"):
            ids = json.loads(b)["ids"]
            state["bin"] = [x for x in state["bin"] if x["id"] not in ids]
            return self.send(204)
        self.send(404)

    def do_PUT(self):
        p, b = self.path, self.body()
        if p.startswith("/sup/"):
            rel = unquote(p[5:])
            total = int(self.headers["Content-Range"].split("/")[1])
            state["upload"][rel] += b
            if len(state["upload"][rel]) >= total:
                t = STORE / rel
                t.parent.mkdir(parents=True, exist_ok=True)
                existed = t.exists()
                t.write_bytes(bytes(state["upload"][rel]))
                self.add_version("F:" + rel, existed)
                return self.send(201, {"name": t.name, "id": "F:" + rel})
            return self.send(202, {})
        if p.startswith("/up/"):
            k = p.rsplit("/", 1)[1]
            total = int(self.headers["Content-Range"].split("/")[1])
            state["upload"][k] += b
            if len(state["upload"][k]) >= total:
                PATHS[k].write_bytes(bytes(state["upload"][k]))
                state["etag"][k] += "x"
                MOD[k] = "2026-10-30T12:00:00Z"
                return self.send(201, {"id": k})
            return self.send(202, {})
        sp = parse_store_path(p)
        if sp and sp[1] == "content":
            t = STORE / sp[0]
            t.parent.mkdir(parents=True, exist_ok=True)
            existed = t.exists()
            t.write_bytes(b)
            self.add_version("F:" + sp[0], existed)
            return self.send(201, {"name": t.name, "id": "F:" + sp[0]})
        self.send(404)

    def do_GET(self):
        p = self.path
        if p.startswith("/shares/"):
            b64 = p.split("u!")[1].split("/")[0]
            url = base64.urlsafe_b64decode(b64 + "=" * (-len(b64) % 4)).decode()
            if "dictionary" in url:
                return self.send(200, file_item("ITEM2"))
            if "AdminOps" in url or "/:f:/" in url:
                return self.send(200, store_item())
            return self.send(200, file_item("ITEM1"))
        if p.startswith("/__ctl"):
            q = parse_qs(urlparse(p).query)
            if "noperm" in q:
                state["noperm"] = q["noperm"][0] == "1"
            if q.get("addver"):
                FV["F:" + q["addver"][0]] = [{"id": "%d.0" % i, "lastModifiedDateTime": "2026-10-2%dT10:00:00Z" % i, "size": 5000} for i in (4, 3, 2, 1)]
            return self.send(200, {"perm": state.get("perm", 0), "store_bin": len([x for x in state["bin"] if x.get("store")])})
        if p.startswith("/dl/"):
            return self.send(200, PATHS[p.rsplit("/", 1)[1]].read_bytes(), "application/octet-stream")
        if p.startswith("/up/") or p.startswith("/sup/"):
            return self.send(200, {"nextExpectedRanges": ["0-"]})
        if p.startswith("/drives/DRIVE1/items/F:") and p.endswith("/versions"):
            return self.send(200, {"value": FV.get(unquote(p[len("/drives/DRIVE1/items/"):-len("/versions")]), [])})
        sp = parse_store_path(p)
        if sp is not None:
            rel, tail = sp
            t = STORE / rel if rel else STORE
            if tail == "children":
                if not t.is_dir():
                    return self.send(404, {"error": "nf"})
                return self.send(200, {"value": [self.child_meta(c) | {"id": "F:" + c.relative_to(STORE).as_posix()} for c in sorted(t.iterdir())]})
            if tail == "content":
                if not t.is_file():
                    return self.send(404, {"error": "nf"})
                return self.send(200, t.read_bytes(), "application/octet-stream")
            if not t.exists():
                return self.send(404, {"error": "nf"})
            return self.send(200, self.child_meta(t) | {"id": "F:" + rel})
        k = item_of(p)
        if k:
            if p.endswith("/versions"):
                return self.send(200, {"value": state["versions"][k]})
            if p.endswith("/content"):
                return self.send(200, PATHS[k].read_bytes(), "application/octet-stream")
            return self.send(200, file_item(k))
        if "/recycleBin/items" in p:
            return self.send(200, {"value": state["bin"]})
        self.send(404)

    def do_DELETE(self):
        p = self.path
        if p.startswith("/drives/DRIVE1/items/F:") and "/versions/" in p:
            iid, _, vid = unquote(p[len("/drives/DRIVE1/items/"):]).partition("/versions/")
            FV[iid] = [v for v in FV.get(iid, []) if v["id"] != vid]
            state["bin"].append({"id": "BV" + iid + vid, "name": iid.rsplit("/", 1)[-1][2:] if iid.startswith("F:") and "/" not in iid else iid.rsplit("/", 1)[-1],
                                 "deletedDateTime": "2099-01-01T00:00:00Z", "size": 1000, "store": True})
            return self.send(204)
        if "/versions/" in p:
            k, vid = item_of(p), p.rsplit("/", 1)[1]
            v = [x for x in state["versions"][k] if x["id"] == vid]
            if v:
                state["versions"][k].remove(v[0])
                state["bin"].append({"id": "B" + k + vid, "name": NAMES[k], "deletedDateTime": "2099-01-01T00:00:00Z", "size": v[0]["size"]})
            return self.send(204)
        sp = parse_store_path(p)
        if sp:
            t = STORE / sp[0]
            if t.exists():
                state["bin"].append({"id": "BS" + sp[0], "name": t.name, "deletedDateTime": "2099-01-01T00:00:00Z", "store": True})
            if t.is_file():
                t.unlink()
            elif t.is_dir():
                shutil.rmtree(t)
            return self.send(204)
        self.send(404)


if __name__ == "__main__":
    ThreadingHTTPServer(("127.0.0.1", PORT), H).serve_forever()
