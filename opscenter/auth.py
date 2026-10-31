"""Named users with a personal key. Keys are never stored, only a salted PBKDF2 hash (tools/make_user.py makes the entry)."""
import hashlib
import hmac
import secrets
import time

from . import config

ITER = 200_000
_failures = {}       # user -> (count, last_time)


def make_hash(key, salt=None):
    salt = salt or secrets.token_hex(8)
    dk = hashlib.pbkdf2_hmac("sha256", key.encode("utf-8"), salt.encode(), ITER).hex()
    return "pbkdf2$%s$%s" % (salt, dk)


def _check(key, stored):
    try:
        _, salt, dk = stored.split("$")
    except ValueError:
        return False
    cand = hashlib.pbkdf2_hmac("sha256", key.encode("utf-8"), salt.encode(), ITER).hex()
    return hmac.compare_digest(cand, dk)


def login(username, key):
    """Returns (user dict | None, message)."""
    u = (username or "").strip().lower()
    n, last = _failures.get(u, (0, 0))
    if n >= 5 and time.time() - last < 300:
        return None, "Too many wrong attempts. Wait five minutes."
    users = config.load_users()
    rec = users.get(u)
    ok = bool(rec) and _check(key or "", rec.get("hash", ""))
    if not rec:                                   # same work whether or not the user exists
        _check(key or "", "pbkdf2$x$00")
    if not ok:
        _failures[u] = (n + 1, time.time())
        return None, "Unknown user or wrong key."
    _failures.pop(u, None)
    role = rec.get("role", "viewer")
    return {"id": u, "name": rec.get("name") or u, "role": role if role in ("operator", "viewer") else "viewer"}, ""
