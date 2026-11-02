"""All settings come from environment variables (on Posit Connect Cloud: Variables in the content settings).
Nothing secret, no SharePoint link and no data is stored in this repository."""
import json
import os
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent

# SharePoint access (the same app registration the publish script and the backup tool use)
TENANT = os.environ.get("SHAREPOINT_TENANT_ID", "").strip()
CLIENT = os.environ.get("SHAREPOINT_CLIENT_ID", "").strip()
SECRET = os.environ.get("SHAREPOINT_CLIENT_SECRET", "").strip()

# Share links
STORE_URL = os.environ.get("OPS_STORE_SHARE_URL", "").strip()    # the folder where the app keeps runs, backups, inputs
ADMIN_URL = os.environ.get("OPS_ADMIN_SHARE_URL", "").strip()    # AFRO_admin_data.xlsx
DICT_URL = os.environ.get("OPS_DICT_SHARE_URL", "").strip()      # AFRO_admin_data_dictionary.xlsx

# Local scratch space (the cloud disk is not permanent: everything important is in the SharePoint folder)
WORKDIR = Path(os.environ.get("OPS_WORKDIR", "/tmp/ops"))

# Test hooks: the same variables the publish script reads
GRAPH = os.environ.get("PUBLISH_GRAPH_BASE", "https://graph.microsoft.com/v1.0")
GRAPH_BETA = os.environ.get("PUBLISH_GRAPH_BETA", "https://graph.microsoft.com/beta")
TOKEN_URL = os.environ.get("PUBLISH_TOKEN_URL", "https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token")

# Named users: {"operator1": {"name": "Operator One", "role": "operator", "hash": "pbkdf2$<salt>$<hex>"}, ...}
# create entries with  python tools/make_user.py
USERS_JSON = os.environ.get("OPS_USERS", "{}")

LOCK_MINUTES = int(os.environ.get("OPS_LOCK_MINUTES", "90"))      # a job holding the lock for longer is considered dead
MIN_BUILD_GB = float(os.environ.get("OPS_MIN_BUILD_GB", "5"))     # a build peaks at about 4 GB of memory
SKIP_MEMORY_CHECK = os.environ.get("OPS_SKIP_MEMORY_CHECK", "") == "1"
KEEP_BACKUPS = int(os.environ.get("OPS_KEEP_BACKUPS", "3"))       # backups of the live file kept on SharePoint (the PC keeps all)
KEEP_DICT_COPIES = int(os.environ.get("OPS_KEEP_DICT_COPIES", "3"))  # earlier live dictionaries kept on SharePoint
KEEP_ACTIVITY = 500
KEEP_RUNS = int(os.environ.get("OPS_KEEP_RUNS", "2"))             # builds that keep their big files on SharePoint (+ the last published one)
KEEP_RESULTS = int(os.environ.get("OPS_KEEP_RESULTS", "3"))       # newest inspect folders / compare files kept on SharePoint
RUN_BIG_BYTES = int(os.environ.get("OPS_RUN_BIG_KB", "250")) * 1024   # files of an old build at or above this size are removed
VERSION_DROP_MIN = 0                                              # an overwritten file of this size or more loses its version history at once (lock.json excepted)
SWEEP_EVERY_HOURS = int(os.environ.get("OPS_SWEEP_HOURS", "24"))   # full version clean-up of the whole folder, at the end of a job, at most this often


def load_users():
    try:
        d = json.loads(USERS_JSON)
        return d if isinstance(d, dict) else {}
    except ValueError:
        return {}


def missing_settings():
    """Names of the variables that must be set for the app to work."""
    need = {"SHAREPOINT_TENANT_ID": TENANT, "SHAREPOINT_CLIENT_ID": CLIENT, "SHAREPOINT_CLIENT_SECRET": SECRET,
            "OPS_STORE_SHARE_URL": STORE_URL, "OPS_ADMIN_SHARE_URL": ADMIN_URL, "OPS_DICT_SHARE_URL": DICT_URL}
    miss = [k for k, v in need.items() if not v]
    if not load_users():
        miss.append("OPS_USERS")
    return miss
