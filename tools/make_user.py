#!/usr/bin/env python3
"""Make one entry for the OPS_USERS variable.

    python tools/make_user.py operator1 "Operator One" operator
    python tools/make_user.py viewer1 "Viewer One" viewer

You are asked for the key (typed, not shown). Paste the printed line into OPS_USERS, joined into one JSON object:
    {"gorgui": {...}, "aminata": {...}}
Roles: operator (can run build, publish, dictionary) or viewer (can only look and download)."""
import getpass
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from opscenter.auth import make_hash   # noqa: E402

if len(sys.argv) < 4 or sys.argv[3] not in ("operator", "viewer"):
    sys.exit(__doc__)
user, name, role = sys.argv[1].strip().lower(), sys.argv[2], sys.argv[3]
k1 = getpass.getpass("Key for %s: " % user)
if len(k1) < 10:
    sys.exit("Use at least 10 characters.")
if k1 != getpass.getpass("Again: "):
    sys.exit("The two keys differ.")
print(json.dumps({user: {"name": name, "role": role, "hash": make_hash(k1)}}))
