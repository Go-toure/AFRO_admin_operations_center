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
SWEEP_REPLACE_MAX = 5 * 1024 * 1024        # files up to this size are replaced by a fresh copy to drop their history
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
        self._perm_ok = True               # permanentDelete accepted for this app (switched off at the first refusal)
        self._perm_probed = False
        self.site_id = (item.get("parentReference") or {}).get("siteId")
        self.cleaned = set()               # names of what the clean-up removed in this job (to find them in the recycle bin)
        self.versions_removed = 0
        self.versions_bytes = 0
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
                            "modified": c.get("lastModifiedDateTime", ""), "id": c.get("id")})
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
        """Write bytes (or a local file path) to a path in the folder; parent folders are created.

        A file that already exists is REPLACED, not overwritten: the new copy is uploaded under a temporary name, the old file is
        deleted for good and the new one takes its name. An overwrite would keep the old content as a version (and a removed
        version only moves to the site recycle bin); a replacement leaves no version and nothing in the recycle bin. If SharePoint
        does not allow the permanent delete for this app, the file is overwritten and its old versions are removed afterwards."""
        if isinstance(data, (str, Path)):
            data = Path(data).read_bytes()
        if path.strip("/") != "lock.json" and self._can_replace():
            old = self.g.request("GET", self._at(path))
            if old.status_code == 200 and old.json().get("id") and "folder" not in old.json():
                if self._replace(path, data, old.json()["id"]):
                    return
        self._write(path, data)

    def _can_replace(self):
        """Does SharePoint accept the permanent delete from this app? Tried once with a tiny file."""
        if self._perm_ok is False:
            return False
        if self._perm_probed:
            return True
        self._perm_probed = True
        probe = "_probe_%d.tmp" % int(time.time())
        try:
            self._write(probe, b"x", drop=False)
            g = self.g.request("GET", self._at(probe))
            iid = g.json().get("id") if g.status_code == 200 else None
            d = self.g.request("POST", f"{config.GRAPH}/drives/{self.drive}/items/{iid}/permanentDelete") if iid else None
            if d is not None and d.status_code in (200, 204):
                return True
            self._perm_ok = False
            self.cleaned.add(probe.lower())
            self.g.request("DELETE", self._at(probe))
        except StoreError:
            self._perm_ok = False
        return self._perm_ok

    def _rename(self, item_id, new_name):
        r = self.g.request("PATCH", f"{config.GRAPH}/drives/{self.drive}/items/{item_id}", json={"name": new_name})
        return r.status_code in (200, 201)

    def _replace(self, path, data, old_id):
        """Upload under a temporary name, move the old file aside, give the new one the name, delete the old one for good.
        Returns False (and changes nothing) when a step fails before the old file is gone."""
        name = path.strip("/").split("/")[-1]
        tmp, aside = path + ".incoming", path + ".old"
        try:
            self._write(tmp, data, drop=False)
        except StoreError:
            return False
        g = self.g.request("GET", self._at(tmp))
        new_id = g.json().get("id") if g.status_code == 200 else None
        if not new_id:
            return False
        if self.exists(aside):                                  # left over from an interrupted replacement
            self.delete(aside)
        if not self._rename(old_id, name + ".old"):
            self.delete(tmp, permanent=False)
            return False
        if not self._rename(new_id, name):
            self._rename(old_id, name)                            # put everything back
            self.delete(tmp, permanent=False)
            return False
        d = self.g.request("POST", f"{config.GRAPH}/drives/{self.drive}/items/{old_id}/permanentDelete")
        if d.status_code not in (200, 204):                       # new file is in place; the old one goes the normal way
            self._perm_ok = False
            self.g.request("DELETE", f"{config.GRAPH}/drives/{self.drive}/items/{old_id}")
            self.cleaned.add(name.lower() + ".old")
        return True

    def _write(self, path, data, drop=True):
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
            if drop:
                self._drop_versions(item_id, len(data), path)
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
        if drop:
            self._drop_versions(item_id, size, path)

    def _drop_versions(self, item_id, size, path=""):
        """SharePoint keeps every overwrite of a file as a full extra copy that counts against the storage. An overwritten file
        of config.VERSION_DROP_MIN bytes or more loses those copies at once (best effort; the app's own history lives in the
        runs and the backups)."""
        if not item_id or size < config.VERSION_DROP_MIN or path.strip("/") == "lock.json":
            return 0
        try:
            self.cleaned.add(path.strip("/").split("/")[-1].lower())
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
                self.versions_removed += 1
                self.versions_bytes += int(v.get("size") or 0)
        return n

    def _versions(self, item_id):
        r = self.g.request("GET", f"{config.GRAPH}/drives/{self.drive}/items/{item_id}/versions")
        if r.status_code != 200:
            return []
        return sorted(r.json().get("value", []), key=lambda v: v.get("lastModifiedDateTime", ""), reverse=True)

    def sweep_versions(self, prefix=""):
        """Get rid of the old versions of every file below a folder (the current version stays). A file of up to
        SWEEP_REPLACE_MAX bytes is replaced by a fresh copy (no version, nothing in the recycle bin); a bigger one has its old
        versions deleted (they pass through the recycle bin, see empty_recycle_bin). Leftovers of an interrupted replacement
        are deleted. Returns (versions removed, bytes)."""
        before_n, before_b = self.versions_removed, self.versions_bytes

        def rec(p):
            for c in self.list(p):
                child = (p + "/" + c["name"]) if p else c["name"]
                if c["is_dir"]:
                    rec(child)
                    continue
                nm = c["name"]
                if nm.endswith((".incoming", ".old")) or nm.startswith("_probe_"):
                    self.delete(child)
                    continue
                if not c.get("id") or child == "lock.json":
                    continue
                vs = self._versions(c["id"])
                if len(vs) <= 1:
                    continue
                top = child.split("/")[0]
                try:
                    if c["size"] <= SWEEP_REPLACE_MAX and top not in ("inspect", "compare") and self._can_replace():
                        data = self.get(child)
                        if data is not None and self._replace(child, data, c["id"]):
                            self.versions_removed += len(vs) - 1
                            self.versions_bytes += sum(int(v.get("size") or 0) for v in vs[1:])
                            continue
                    if self.purge_versions(c["id"]):
                        self.cleaned.add(nm.lower())
                except StoreError:
                    pass
        rec(prefix.strip("/"))
        return self.versions_removed - before_n, self.versions_bytes - before_b

    def empty_recycle_bin(self, since_iso):
        """Best effort: remove from the site recycle bin the versions and files this job deleted (same names, deleted since the
        job started), so the space is really freed. Uses the Graph beta recycle bin API; the app may lack the permission.
        Returns (items removed or None, text)."""
        if not self.site_id or not self.cleaned:
            return 0, "nothing to empty"
        try:
            ids, freed = [], 0
            url = f"{config.GRAPH_BETA}/sites/{self.site_id}/recycleBin/items?$top=200"
            pages = 0
            while url and pages < 30:
                r = self.g.request("GET", url)
                if r.status_code != 200:
                    return None, "recycle bin not readable (HTTP %s)" % r.status_code
                pages += 1
                body = r.json()
                for it in body.get("value", []):
                    if (it.get("name") or "").lower() in self.cleaned and (it.get("deletedDateTime") or "") >= since_iso:
                        ids.append(it["id"])
                        freed += int(it.get("size") or 0)
                url = body.get("@odata.nextLink")
            if not ids:
                return 0, "nothing of this job found in the recycle bin"
            removed = 0
            for k in range(0, len(ids), 50):
                r = self.g.request("POST", f"{config.GRAPH_BETA}/sites/{self.site_id}/recycleBin/items/delete", json={"ids": ids[k:k + 50]})
                if r.status_code not in (200, 204):
                    return removed, "recycle bin delete refused (HTTP %s); %d removed" % (r.status_code, removed)
                removed += len(ids[k:k + 50])
            return removed, "%d item(s), about %.1f MB" % (removed, freed / 1048576)
        except Exception as e:
            return None, type(e).__name__

    def put_json(self, path, obj):
        self.put(path, json.dumps(obj, indent=1, ensure_ascii=False).encode("utf-8"))

    def delete(self, path, permanent=True):
        """Remove a file or folder. By default it is deleted for good: a normal delete only moves it to the site recycle bin,
        where it keeps using the storage for weeks. If SharePoint refuses the permanent delete for this app, the normal
        delete is used (and not retried with the permanent one again)."""
        self.cleaned.add(path.strip("/").split("/")[-1].lower())
        if permanent and self._perm_ok:
            g = self.g.request("GET", self._at(path))
            if g.status_code == 404:
                return
            iid = g.json().get("id") if g.status_code == 200 else None
            if iid:
                d = self.g.request("POST", f"{config.GRAPH}/drives/{self.drive}/items/{iid}/permanentDelete")
                if d.status_code in (200, 204):
                    return
                if d.status_code in (400, 401, 403, 404, 405, 501):
                    self._perm_ok = False
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
