"""Settings for running the app on a PC (Positron, or `python run_local.py`).

On the hosting service the settings are Variables of the content. On a PC they are the same variables, read from ONE file in this repository,
`.env` (git-ignored; copy `.env.example`, or create it once with `python tools/make_env.py`). Nothing is read from any other repository or
folder, nothing is printed (`report()` says only which setting is present) and nothing is written. A real environment variable always wins
over the file. `OPS_ENV_FILE` can name another file. The app counts as running on a PC when `.env` exists or OPS_LOCAL=1.

Everything else the app needs lives in this repository (engine/, scope_pipeline/) or in the SharePoint folder (inputs, the geo reference,
the scope files, the runs), so the same code runs on the hosting service without any change.
"""
import os
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
_found = {}


def env_file():
    return Path(os.environ.get("OPS_ENV_FILE") or HERE / ".env")


def _read_env_file(p):
    out = {}
    try:
        for line in Path(p).read_text(encoding="utf-8-sig").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                out[k.strip()] = v.strip().strip("\"'")
    except OSError:
        pass
    return out


def is_local():
    flag = os.environ.get("OPS_LOCAL", "").strip()
    if flag in ("0", "1"):
        return flag == "1"
    return env_file().is_file()


def load():
    for k, v in _read_env_file(env_file()).items():
        if v and not os.environ.get(k):
            os.environ[k] = v
            _found[k] = ".env"
    if is_local() and not os.environ.get("OPS_LOCAL"):
        os.environ["OPS_LOCAL"] = "1"
        _found["OPS_LOCAL"] = "this PC"


NAMES = ["SHAREPOINT_TENANT_ID", "SHAREPOINT_CLIENT_ID", "SHAREPOINT_CLIENT_SECRET", "OPS_STORE_SHARE_URL", "OPS_ADMIN_SHARE_URL",
         "OPS_DICT_SHARE_URL", "OPS_SUBMISSIONS_SHARE_URL", "GPEI_API_TOKEN"]


def report():
    """[(setting, found?, where)] for the settings the app needs. Values are never returned."""
    return [(n, bool(os.environ.get(n)), _found.get(n, "the environment" if os.environ.get(n) else "")) for n in NAMES]
