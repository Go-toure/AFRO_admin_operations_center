#!/usr/bin/env python3
"""One-time set-up of this PC: writes the app's own `.env` (git-ignored) from the settings that already exist on the machine, so that from then
on the app reads nothing but this repository and the SharePoint folder.

    python tools/make_env.py [--from-backup-tool FOLDER] [--from-engine FOLDER] [--from-scope FOLDER] [--force]

The three folders default to the usual neighbours of this repository (Gith_repositories). They are read here, once; the app itself never
looks at them. Secrets are copied, never printed: the output lists only which settings were found. An existing `.env` is kept unless --force."""
import argparse
import ast
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))
from opscenter import localenv


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--from-backup-tool", default=str(HERE.parent / "SharePoint_version_backup"))
    ap.add_argument("--from-engine", default=str(HERE.parent / "Admin_data_coadministration"))
    ap.add_argument("--from-scope", default=str(HERE.parent / "scope"))
    ap.add_argument("--force", action="store_true", help="replace an existing .env")
    a = ap.parse_args()
    out = HERE / ".env"
    if out.is_file() and not a.force:
        sys.exit(".env exists already: nothing changed (use --force to rebuild it).")
    vals = {}
    s = localenv._read_env_file(Path(a.from_backup_tool) / "config" / "secrets.env")
    for k in ("SHAREPOINT_TENANT_ID", "SHAREPOINT_CLIENT_ID", "SHAREPOINT_CLIENT_SECRET"):
        vals[k] = s.get(k, "")
    vals["OPS_STORE_SHARE_URL"] = s.get("ADMIN_STORE_SHARE_URL", "")
    vals["OPS_SUBMISSIONS_SHARE_URL"] = s.get("ADMIN_SUBMISSIONS_SHARE_URL", "")
    try:
        tree = ast.parse((Path(a.from_engine) / "publish_admin_data.py").read_text(encoding="utf-8"))
        for node in tree.body:
            if isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str) \
                    and node.value.value.startswith("http"):
                for t in node.targets:
                    name = {"ADMIN_SHARE_URL": "OPS_ADMIN_SHARE_URL", "DICT_SHARE_URL": "OPS_DICT_SHARE_URL"}.get(getattr(t, "id", ""))
                    if name:
                        vals[name] = node.value.value
    except (OSError, SyntaxError):
        pass
    vals["GPEI_API_TOKEN"] = localenv._read_env_file(Path(a.from_scope) / "config" / "secrets.env").get("GPEI_API_TOKEN", "")
    lines = ["# Settings of the Operations Center on this PC. Git-ignored: never commit this file.",
             "# The same names are the Variables of the content on the hosting service.", "OPS_LOCAL=1"]
    for k in localenv.NAMES:
        lines.append("%s=%s" % (k, vals.get(k, "")))
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("Written: %s" % out)
    for k in localenv.NAMES:
        print("  [%s] %s" % ("ok" if vals.get(k) else "!!", k))
    print("A setting marked !! is empty in .env: fill it by hand.")


if __name__ == "__main__":
    main()
