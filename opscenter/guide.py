"""The Quick Start Guide: one text, shown on the Quick start page of the app and printed by tools/make_quick_start_pdf.py.
Keep it short and in plain words. Nothing secret here: this repository is public."""
import os

TITLE = "WHO AFRO Administrative Data Operations Center"
SUBTITLE = ("Integrated platform to build, check, correct and publish the administrative (SIA) coverage data "
            "across the WHO African Region")

ABOUT = [
    "The Operations Center brings the whole life of the AFRO administrative data file into one place: the backup of the live file, "
    "the build of the next version (rules and corrections), the checks, the values, and the publication on SharePoint. "
    "It runs the same engine as the PC, so a build here and a build on a PC give the same file.",
    "Everything the app keeps lives in a SharePoint folder, so nothing depends on this server staying up. "
    "Only one job runs at a time.",
]

OBJECTIVES = [
    "Keep one trusted live file that every dashboard and report reads.",
    "Correct what can be corrected safely, and list the rest for the countries.",
    "Show what changed in each version, so nothing is published without being checked.",
    "Give each country its own list of records to check or correct.",
    "Keep SharePoint tidy: no old versions, no leftover big files.",
]

MOBILE = "Scan this QR code with the camera of your phone or tablet to open the live Operations Center."

# (heading, [paragraph (str) or list item (bold, text)])
SECTIONS = [
    ("The cycle in five steps (Cycle tab)", [
        ("1  Back up", "saves the file that is on SharePoint now as a new backup version (only if it changed). Everybody can do it."),
        ("2  Build", "refreshes the lookup from the GPEI API, starts from the live file, applies every rule and writes the new version, "
                     "the data dictionary, the audit, the quality report, the feedback workbook and the fix list."),
        ("3  Check", "compares the build with the file it started from: columns, rows, wrong-country Responses, duplicates, errors, "
                     "and every cell that changed. It stops the cycle on a real problem."),
        ("4  Store values", "writes the check_dp values into the file (no Excel needed)."),
        ("5  Publish", "replaces the data file and the data dictionary on SharePoint, backs up again, and cleans the SharePoint folder "
                       "as its last step. It stops if the live file changed since the build."),
        ("Run the whole cycle", "does the build, check, values and publish in one go and stops at the first problem."),
    ]),
    ("What the Build corrects for you", [
        ("Co-administration", "merges an nOPV2 and a bOPV record of the same district into one combined record."),
        ("Copy and drag-fill errors", "restores a Response of another country or a wrong nOPV label from the lookup and the backups."),
        ("Response", "fills an empty Response and renames a shortened one to the lookup's spelling."),
        ("Names", "standard country names (TANZANIA, CAMEROUN ...) and province spelling (MAI NDOMBE = MAINDOMBE, PROVINCIA DE NAMPULA = NAMPULA)."),
        ("Population", "corrects an impossible target population, and a target that is 10 or 100 times off when the reported coverage "
                       "and the district's other campaigns agree."),
        ("Coverage", "fills an empty CVPolio with vaccinated / target."),
        ("Hygiene", "removes stray characters, turns text dates into dates, removes exact duplicate records."),
        ("Only when the answer is unique", "otherwise the record is left as it is and listed. Every change is in the audit workbook."),
    ]),
    ("What it only flags: the fix list", [
        "Some problems have no safe answer: missing key fields, a report date before the SIA start, a target larger than the total "
        "population, coverage above the ceiling, a target very different from the other campaigns, a province to confirm, "
        "a record entered twice.",
        ("Fix list by country", "has one sheet per problem with the row, the column to correct, the current value and, when there is one, "
                                "a suggested value. In Files & feedback, choose a country and download its fix list to send to the focal point."),
    ]),
    ("Duplicates: check and fix", [
        "A record entered twice is the same Country, Province, District, date, round, vaccine and Response with the same population "
        "and results. Records with the same names but other figures are different units and are never treated as duplicates.",
        ("Find duplicates", "(Quality & compare) lists each group with the record a fix would keep and the one it would remove. It changes nothing."),
        ("Duplicates choice", "(Cycle tab) decides what Build does: flag only (default), or remove the extra copy and keep the most "
                              "complete or the first record. Removing asks for a confirmation."),
    ]),
    ("The tabs", [
        ("Overview", "the live file, the newest build, the backups and who did what last."),
        ("Cycle", "the steps above. Operators only, except the backup."),
        ("Explore", "find records in the live file, a build or a backup by country, province, district, Response, round or date."),
        ("Quality & compare", "inspect a version, find duplicates, compare two versions column by column."),
        ("Files & feedback", "download the files of a build and the feedback or fix list of one country."),
        ("Rules", "every rule the build applies, with its source and its switch."),
        ("Activity", "the log of every job: who, what, when, result."),
    ]),
    ("Good to know", [
        "One job at a time. If the app says a job is running, wait for it to finish. 'Release the lock' is only for a job that crashed or "
        "an app that was restarted; never use it while someone is really running a job.",
        "A build needs about 2.7 GB of memory. On the Posit Free plan (4 GB) it works when nobody else uses the server; if the app says "
        "there is not enough memory, build on the PC with 'python admin.py build'.",
        "The live file on SharePoint keeps no version history. The backups (every published version) are kept for you.",
        "Publish skips the upload only when the live file is identical to the build. If someone re-saved the live file in Excel, "
        "the file is replaced by the build (same data).",
    ]),
    ("Data sources", [
        "The live file AFRO_admin_data.xlsx and its data dictionary on SharePoint.",
        "The campaign lookup, refreshed from the GPEI API at the start of every build and inspect.",
        "The geography reference (country, province, district of the region) and the backups of the live file.",
    ]),
]

SUPPORT_TEXT = "For technical assistance or data questions, please contact the WHO AFRO GIS Centre team:"
SUPPORT_EMAIL = os.environ.get("OPS_SUPPORT_EMAIL", "dimafro@who.int").strip()
PDF_NAME = "WHO_AFRO_Admin_Operations_Center_Quick_Start.pdf"
