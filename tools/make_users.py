#!/usr/bin/env python3
"""Make the whole OPS_USERS value in one go, with ONE shared key asked once.

    python tools/make_users.py operator "gorgui=Gorgui Ba Toure" "ahmed=Ahmed Ibrahim" "carolyne=Carolyne Gathenjy"
    python tools/make_users.py viewer "someone=Some One"

Give the role first, then each person as username=Full Name. Put several roles in one call by repeating:
    python tools/make_users.py operator "a=A A" "b=B B" --viewer "c=C C"

The key is typed once (not shown, at least 10 characters). Every person gets their own hash (own salt) of that same key,
so everyone signs in with their username and the shared key. The printed line is the value of OPS_USERS (keep it private).
To give someone a personal key instead, use tools/make_user.py for that person."""
import getpass
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from opscenter.auth import make_hash   # noqa: E402


def parse(argv):
    role, people = None, []
    for a in argv:
        if a in ("operator", "viewer", "--operator", "--viewer"):
            role = a.lstrip("-")
        elif "=" in a and role:
            u, n = a.split("=", 1)
            people.append((u.strip().lower(), n.strip(), role))
        else:
            sys.exit(__doc__)
    if not people:
        sys.exit(__doc__)
    names = [p[0] for p in people]
    if len(set(names)) != len(names) or not all(names):
        sys.exit("Usernames must be unique and not empty.")
    return people


def main():
    people = parse(sys.argv[1:])
    k1 = getpass.getpass("Shared key for %d user(s): " % len(people))
    if len(k1) < 10:
        sys.exit("Use at least 10 characters.")
    if k1 != getpass.getpass("Again: "):
        sys.exit("The two keys differ.")
    print(json.dumps({u: {"name": n, "role": r, "hash": make_hash(k1)} for u, n, r in people}))


if __name__ == "__main__":
    main()
