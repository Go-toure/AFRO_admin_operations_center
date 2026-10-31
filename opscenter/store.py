"""The SharePoint folder where the Operations Center keeps its runs, backups, inputs and history.

The folder is found through its share link. Files are addressed by a path inside it (runs/v25/manifest.json).
Only Microsoft Graph with the app registration is used; nothing is written outside that folder."""
import base64
import json
import re
import threading
import time
import datetime as dt
from pathlib import Path
from urllib.parse import quote

import requests

from . import config

CHUNK = 320 * 1024 * 32          # 10 MiB, a multiple of 320 KiB as Graph requires
SIMPLE_MAX = 4 * 1024 * 1024     # larger files go through an upload session


class StoreError(RuntimeError):
    pass


class Graph:
    """Token handling and calls with retries (429 / 5xx / network)."""

    def __init__(self):
        self._tok, self._at = None, 0.0
        self._lock = threading.Lock()

    def _refresh(self):
        if not (config.TENANT and config.CLIENT and config.SECRET):
            raise StoreError("The SharePoint credentials are not set (SHAREPOINT_TENANT_ID / _CLIENT_ID / _CLIENT_SECRET).")
        r = requests.post(config.TOKEN_URL.format(tenant=config.TENANT), timeout=30,
                          data={"client_id": config.CLIENT, "client_secret": config.SECRET, "grant_type": "client_credentials",
                                "scope": "https://graph.microsoft.com/.default"})
        if r.status_code != 200:
            raise StoreError("Could not sign in to SharePoint (HTTP %s). Check the credentials." % r.status_code)
        self._tok, self._at = r.json()["access_token"], time.time()

    def headers(self, extra=None):
        with self._lock:
            if not self._tok or time.time() - self._at > 1800:
                self._refresh()
            h = {"Authorization": "Bearer " + self._tok}
        h.update(extra or {})
        return h

    def request(self, method, url, ok=(200,), retries=4, **kw):
        kw.setdefault("timeout", 120)
        extra = kw.pop("headers", None)
        last = None
        for attempt in range(retries):
            try:
                r = requests.request(method, url, headers=self.headers(extra), **kw)
            except requests.exceptions.RequestException as e:
                last = e
                time.sleep(2 * (attempt + 1))
                continue
            if r.status_code == 401 and attempt == 0:
                self._tok = None
                continue
            if r.status_code in (429, 502, 503, 504):
                try:
                    wait = int(r.headers.get("Retry-After", 0))
                except ValueError:
                    wait = 0
                time.sleep(max(wait, 4 * (attempt + 1)))
                last = r
                continue
            return r
        if isinstance(last, requests.Response):
            return last
        raise StoreError("Network error talking to SharePoint (%s)." % (type(last).__name__ if last else "unknown"))

    def share_item(self, share_url):
        b64 = base64.b64encode(share_url.encode()).decode().rstrip("=").replace("/", "_").replace("+", "-")
        r = self.request("GET", f"{config.GRAPH}/shares/u!{b64}/driveItem")
        if r.status_code != 200:
            raise StoreError("Cannot open the SharePoint link (HTTP %s)." % r.status_code)
        return r.json()


def now_iso():
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class Store:
    def __init__(self, graph=None):
        self.g = graph or Graph()
        item = self.g.share_item(config.STORE_URL)
        if "folder" not in item and item.get("file"):
            raise StoreError("OPS_STORE_SHARE_URL points to a file, not to a folder.")
        self.drive = item["parentReference"]["driveId"]
        self.root = item["id"]
        self.name = item.get("name", "")

    # -- addressing
    def _base(self):
        return f"{config.GRAPH}/drives/{self.drive}/items/{self.root}"

    def _at(self, path):
        path = path.strip("/")
        return f"{self._base()}:/{quote(path)}:" if path else self._base()

    # -- reading
    def list(self, path=""):
        """Children of a folder: [{'name', 'size', 'is_dir', 'modified'}]; an unknown folder is empty."""
        out, url = [], self._at(path) + "/children?$top=200"
        while url:
            r = self.g.request("GET", url)
            if r.status_code == 404:
                return []
            if r.status_code != 200:
                raise StoreError("Cannot list %s (HTTP %s)." % (path or "/", r.status_code))
            b = r.json()
            for c in b.get("value", []):
                out.append({"name": c["name"], "size": int(c.get("size") or 0), "is_dir": "folder" in c,
                            "modified": c.get("lastModifiedDateTime", "")})
            url = b.get("@odata.nextLink")
        return out

    def walk(self, path="", skip=()):
        """Every file below a folder: {relative path: size}."""
        found = {}

        def rec(p, rel):
            for c in self.list(p):
                r = (rel + "/" + c["name"]) if rel else c["name"]
                if c["name"] in skip:
                    continue
                if c["is_dir"]:
                    rec((p + "/" + c["name"]) if p else c["name"], r)
                else:
                    found[r] = c["size"]
        rec(path.strip("/"), "")
        return found

    def exists(self, path):
        r = self.g.request("GET", self._at(path))
        return r.status_code == 200

    def get(self, path):
        r = self.g.request("GET", self._at(path) + "/content")
        if r.status_code == 404:
            return None
        if r.status_code != 200:
            raise StoreError("Cannot read %s (HTTP %s)." % (path, r.status_code))
        return r.content

    def download(self, path, dest):
        dest = Path(dest)
        dest.parent.mkdir(parents=True, exist_ok=True)
        r = self.g.request("GET", self._at(path) + "/content", stream=True, timeout=300)
        if r.status_code != 200:
            raise StoreError("Cannot download %s (HTTP %s)." % (path, r.status_code))
        tmp = dest.with_suffix(dest.suffix + ".part")
        with open(tmp, "wb") as f:
            for b in r.iter_content(1 << 20):
                f.write(b)
        tmp.replace(dest)
        return dest

    def get_json(self, path, default=None):
        b = self.get(path)
        if b is None:
            return default
        try:
            return json.loads(b.decode("utf-8"))
        except ValueError:
            return default

    # -- writing
    def put(self, path, data):
        """Write bytes (or a local file path) to a path in the folder; parent folders are created."""
        if isinstance(data, (str, Path)):
            data = Path(data).read_bytes()
        item_id = None
        if len(data) <= SIMPLE_MAX:
            r = self.g.request("PUT", self._at(path) + "/content", ok=(200, 201), data=data,
                               headers={"Content-Type": "application/octet-stream"})
            if r.status_code not in (200, 201):
                raise StoreError("Cannot write %s (HTTP %s)." % (path, r.status_code))
            try:
                item_id = r.json().get("id")
            except ValueError:
                pass
            self._drop_versions(item_id, len(data))
            return
        r = self.g.request("POST", self._at(path) + "/createUploadSession",
                           json={"item": {"@microsoft.graph.conflictBehavior": "replace"}})
        if r.status_code not in (200, 201):
            raise StoreError("Cannot start the upload of %s (HTTP %s)." % (path, r.status_code))
        url, size, start, tries = r.json()["uploadUrl"], len(data), 0, 0
        while start < size:
            chunk = data[start:start + CHUNK]
            end = start + len(chunk) - 1
            try:
                rr = requests.put(url, data=chunk, timeout=300, headers={
                    "Content-Length": str(len(chunk)), "Content-Range": f"bytes {start}-{end}/{size}"})
                code = rr.status_code
            except requests.exceptions.RequestException:
                code = 0
            if code in (200, 201, 202):
                start += len(chunk)
                tries = 0
                if code in (200, 201):
                    try:
                        item_id = rr.json().get("id")
                    except ValueError:
                        pass
                continue
            tries += 1
            if tries > 4:
                try:
                    requests.delete(url, timeout=30)
                except Exception:
                    pass
                raise StoreError("The upload of %s failed (HTTP %s)." % (path, code))
            time.sleep(4 * tries)
            try:
                rng = requests.get(url, timeout=60).json().get("nextExpectedRanges") or []
                if rng:
                    start = int(str(rng[0]).split("-")[0])
            except Exception:
                pass

    def _drop_versions(self, item_id, size):
        """SharePoint keeps every overwrite of a file as a full extra copy. Overwritten files of 1 MB or more lose
        those copies at once (best effort; the app's own history lives in the runs and the backups)."""
        if not item_id or size < 1_000_000:
            return 0
        try:
            return self.purge_versions(item_id)
        except Exception:
            return 0

    def purge_versions(self, item_id):
        base = f"{config.GRAPH}/drives/{self.drive}/items/{item_id}/versions"
        r = self.g.request("GET", base)
        if r.status_code != 200:
            return 0
        vs = sorted(r.json().get("value", []), key=lambda v: v.get("lastModifiedDateTime", ""), reverse=True)
        n = 0
        for v in vs[1:]:                          # the first is the current version
            d = self.g.request("DELETE", base + "/" + v["id"])
            if d.status_code in (200, 204, 404):
                n += 1
        return n

    def put_json(self, path, obj):
        self.put(path, json.dumps(obj, indent=1, ensure_ascii=False).encode("utf-8"))

    def delete(self, path):
        r = self.g.request("DELETE", self._at(path))
        if r.status_code not in (200, 204, 404):
            raise StoreError("Cannot delete %s (HTTP %s)." % (path, r.status_code))

    # -- one job at a time
    def acquire_lock(self, who, what):
        cur = self.get_json("lock.json")
        if cur:
            try:
                exp = dt.datetime.fromisoformat(cur["expires"].replace("Z", "+00:00"))
            except (KeyError, ValueError):
                exp = None
            if exp and exp > dt.datetime.now(dt.timezone.utc):
                raise StoreError("%s is running '%s' (started %s). Wait until it finishes." %
                                 (cur.get("who", "someone"), cur.get("what", "a job"), cur.get("since", "")))
        token = "%s-%s" % (int(time.time() * 1000), who)
        exp = dt.datetime.now(dt.timezone.utc) + dt.timedelta(minutes=config.LOCK_MINUTES)
        self.put_json("lock.json", {"who": who, "what": what, "token": token, "since": now_iso(),
                                    "expires": exp.strftime("%Y-%m-%dT%H:%M:%SZ")})
        back = self.get_json("lock.json") or {}
        if back.get("token") != token:
            raise StoreError("Another job took the lock at the same moment. Try again.")
        return token

    def renew_lock(self, token):
        cur = self.get_json("lock.json") or {}
        if cur.get("token") == token:
            exp = dt.datetime.now(dt.timezone.utc) + dt.timedelta(minutes=config.LOCK_MINUTES)
            cur["expires"] = exp.strftime("%Y-%m-%dT%H:%M:%SZ")
            self.put_json("lock.json", cur)

    def release_lock(self, token):
        cur = self.get_json("lock.json") or {}
        if cur.get("token") == token:
            self.delete("lock.json")

    def lock_info(self):
        cur = self.get_json("lock.json")
        if not cur:
            return None
        try:
            exp = dt.datetime.fromisoformat(cur["expires"].replace("Z", "+00:00"))
            if exp <= dt.datetime.now(dt.timezone.utc):
                return None
        except (KeyError, ValueError):
            return None
        return cur

    # -- activity log (small, one line per action)
    def log_activity(self, who, what, result, detail=""):
        rows = self.get_json("activity.json", []) or []
        rows.append({"at": now_iso(), "who": who, "action": what, "result": result, "detail": detail[:300]})
        self.put_json("activity.json", rows[-config.KEEP_ACTIVITY:])
