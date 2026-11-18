#!/usr/bin/env python3
"""Start the Operations Center on this PC (no Posit Connect Cloud needed).

    python run_local.py            start the app and open it in the browser (http://127.0.0.1:8765)
    python run_local.py --check    say which settings were found (never their values) and stop

In Positron you can also open app.py and press 'Run Shiny App'. The settings are read from the file .env in this folder (create it once with
python tools/make_env.py); nothing is read from any other repository.
The app listens on this machine only. With no OPS_USERS set you are the operator; set OPS_USERS to get the sign-in page back."""
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))


def main(argv):
    from opscenter import config, localenv
    print("Operations Center - local run (%s)" % ("this PC" if config.LOCAL else "no .env found: run python tools/make_env.py"))
    for name, ok, where in localenv.report():
        print("  [%s] %-28s %s" % ("ok" if ok else "!!", name, where if ok else "missing"))
    print("  work folder: %s" % config.WORKDIR)
    miss = config.missing_settings()
    if miss:
        print("\nMissing: %s\nPut them in the file .env next to app.py: python tools/make_env.py creates it once (see .env.example)." % ", ".join(miss))
    if "--check" in argv:
        return 1 if miss else 0
    if miss:
        return 1
    port = "8765"
    print("\nStarting on http://127.0.0.1:%s  (Ctrl+C stops it)\n" % port)
    return subprocess.call([sys.executable, "-m", "shiny", "run", "app.py", "--host", "127.0.0.1", "--port", port, "--launch-browser"], cwd=str(HERE))


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
