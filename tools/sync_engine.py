#!/usr/bin/env python3
"""Copy the engine into this app from the two repositories it comes from, so the app and the PC run the same code.

    python tools/sync_engine.py                       # from ../Admin_data_coadministration and ../SharePoint_version_backup
    python tools/sync_engine.py --admin-repo PATH --backup-repo PATH
    python tools/sync_engine.py --strip-links         # blank the SharePoint share links written in publish_admin_data.py
                                                      # (use this before pushing to a PUBLIC GitHub repository; the app
                                                      #  reads the links from OPS_ADMIN_SHARE_URL / OPS_DICT_SHARE_URL)

The engine files are never edited by hand in this repository: change them in Admin_data_coadministration, test them
there on the PC, then run this script and commit.
Two small, automatic adjustments are made to sp_versions.py (the Graph address and the token address may be set from
PUBLISH_GRAPH_BASE / PUBLISH_TOKEN_URL, which only the tests use)."""
import argparse
import hashlib
import re
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
ENGINE = HERE / "engine"
ADMIN_FILES = ("admin.py", "add_coadmin_columns.py", "publish_admin_data.py")


def patch_backup_tool(text):
    # f"https://graph.microsoft.com/v1.0/..." -> f"{GRAPH_V1}/..."
    text = text.replace("https://graph.microsoft.com/v1.0", "{GRAPH_V1}")
    text = text.replace('f"https://login.microsoftonline.com/{t}/oauth2/v2.0/token"', 'TOKEN_URL.format(tenant=t)')
    # the replaced literals must be f-strings; the original ones already were, except the tenant one
    head = 'GRAPH_V1 = os.environ.get("PUBLISH_GRAPH_BASE", "https://graph.microsoft.com/v1.0")\n' \
           'TOKEN_URL = os.environ.get("PUBLISH_TOKEN_URL", "https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token")\n'
    text = text.replace("ROOT = Path(__file__).resolve().parent\n", head + "ROOT = Path(__file__).resolve().parent\n", 1)
    return text


def strip_paths(text):
    """r"C:\\Users\\<name>\\Documents\\x" -> Path.home() / "Documents" / "x": the same place on that PC, no name in the code."""
    def one(m):
        parts = [x for x in m.group(1).split("\\") if x]
        return "Path.home() / " + " / ".join('"%s"' % x for x in parts)
    return re.sub(r'Path\(r"C:\\Users\\[^\\"]+\\([^"]+)"\)', one, text)


def strip_links(text):
    text = re.sub(r'ADMIN_SHARE_URL = \(.*?\)\n', 'ADMIN_SHARE_URL = ""      # set OPS_ADMIN_SHARE_URL\n', text, count=1, flags=re.S)
    text = re.sub(r'DICT_SHARE_URL = \(.*?\)\n', 'DICT_SHARE_URL = ""       # set OPS_DICT_SHARE_URL\n', text, count=1, flags=re.S)
    return text


PUBLIC_PATTERNS = [
    (r"sharepoint\.com", "a SharePoint address"),
    (r"sourcedoc=", "a SharePoint document link"),
    (r"[A-Z]:\\Users\\", "a personal Windows path"),
    (r"client_secret\s*=\s*[\"'][^\"']{8,}", "a client secret"),
    (r"SHAREPOINT_CLIENT_SECRET\s*=\s*\S{8,}", "a client secret"),
    (r"pbkdf2\$[0-9a-f]{8,}\$[0-9a-f]{20,}", "a password hash"),
]


def check_public():
    bad = 0
    for p in sorted(HERE.rglob("*")):
        if not p.is_file() or ".git" in p.parts or "__pycache__" in p.parts or p.suffix in (".pyc", ".xlsx", ".png"):
            continue
        if p == Path(__file__).resolve():
            continue
        try:
            text = p.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for pat, what in PUBLIC_PATTERNS:
            for m in re.finditer(pat, text):
                line = text.count("\n", 0, m.start()) + 1
                print("  %s:%d  %s" % (p.relative_to(HERE).as_posix(), line, what))
                bad += 1
    print("Nothing that should not be public was found." if not bad else "\n%d finding(s): fix them before pushing to a public repository." % bad)
    return 1 if bad else 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--admin-repo", default=str(HERE.parent / "Admin_data_coadministration"))
    ap.add_argument("--backup-repo", default=str(HERE.parent / "SharePoint_version_backup"))
    ap.add_argument("--strip-links", action="store_true",
                    help="blank the SharePoint links and the personal Windows paths in the engine (always, for a public repository)")
    ap.add_argument("--check-public", action="store_true",
                    help="scan this repository for SharePoint links, personal paths and secrets; exit 1 if any is found")
    a = ap.parse_args()
    if a.check_public:
        sys.exit(check_public())
    ar, br = Path(a.admin_repo), Path(a.backup_repo)
    for f in ADMIN_FILES:
        if not (ar / f).is_file():
            sys.exit("not found: %s" % (ar / f))
    if not (br / "sp_versions.py").is_file():
        sys.exit("not found: %s" % (br / "sp_versions.py"))
    (ENGINE / "backup_tool").mkdir(parents=True, exist_ok=True)
    stamp = []
    for f in ADMIN_FILES:
        t = (ar / f).read_text(encoding="utf-8")
        if a.strip_links and f == "publish_admin_data.py":
            t = strip_paths(strip_links(t))
        (ENGINE / f).write_text(t, encoding="utf-8")
        stamp.append("%s %s" % (hashlib.sha256(t.encode()).hexdigest()[:12], f))
    t = patch_backup_tool((br / "sp_versions.py").read_text(encoding="utf-8"))
    (ENGINE / "backup_tool" / "sp_versions.py").write_text(t, encoding="utf-8")
    stamp.append("%s sp_versions.py (patched)" % hashlib.sha256(t.encode()).hexdigest()[:12])
    (ENGINE / "VERSION.txt").write_text("\n".join(stamp) + "\n", encoding="utf-8")
    print("engine updated:\n  " + "\n  ".join(stamp))
    if a.strip_links:
        print("share links blanked in publish_admin_data.py")


if __name__ == "__main__":
    main()
