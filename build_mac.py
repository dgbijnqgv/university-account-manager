"""Package a Python-based macOS app, preserving executable bits in the ZIP."""
from pathlib import Path
import plistlib
import zipfile

ROOT = Path(__file__).resolve().parent
PREFIX = "College Portals Mac/"
APP = "College Portals.app/Contents/"

SETUP = '''#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")"
fail() { printf '\\n%s\\n' "$1"; read -r -p "Press Return to close. " _; exit 1; }
[[ "$(uname -s)" == Darwin ]] || fail "This installer is for macOS."
PYTHON=""
for candidate in /usr/local/bin/python3 /opt/homebrew/bin/python3 /Library/Frameworks/Python.framework/Versions/3.*/bin/python3 /usr/bin/python3; do
    if [[ -x "$candidate" ]] && "$candidate" -c 'import sys, tkinter, venv; assert sys.version_info >= (3, 10)' 2>/dev/null; then
        PYTHON="$candidate"
        break
    fi
done
[[ -n "$PYTHON" ]] || fail "Install Python 3.10 or newer from https://www.python.org/downloads/macos/ (includes Tk), then run Setup.command again."
SUPPORT="$HOME/Library/Application Support/College Portals"
RESOURCES="$PWD/College Portals.app/Contents/Resources"
umask 077
mkdir -p "$SUPPORT"
printf 'Setting up College Portals with %s\\n' "$PYTHON"
"$PYTHON" -m venv "$SUPPORT/runtime" || fail "Could not create the private Python runtime."
"$SUPPORT/runtime/bin/python3" -m pip install --only-binary=:all: -r "$RESOURCES/requirements-mac.txt" || fail "Dependency installation failed. Check your internet connection and try again."
"$SUPPORT/runtime/bin/python3" "$RESOURCES/check_mac.py" || fail "The Mac startup check failed. The error above explains what needs attention."
printf '\\nSetup and native Mac checks passed. Opening College Portals.\\n'
open "$PWD/College Portals.app"
'''

LAUNCH = '''#!/bin/bash
set -euo pipefail
RESOURCES="$(cd "$(dirname "$0")/../Resources" && pwd)"
PYTHON="$HOME/Library/Application Support/College Portals/runtime/bin/python3"
if [[ ! -x "$PYTHON" ]]; then
    /usr/bin/osascript -e 'display alert "College Portals needs setup" message "Run Setup.command from the extracted Mac download first. Install Python from python.org if requested." as warning'
    exit 1
fi
exec "$PYTHON" "$RESOURCES/app.py"
'''

README = '''COLLEGE PORTALS FOR MAC

1. Extract College-Portals-Mac.zip on your Mac.
2. Install Python 3.10 or newer using the macOS installer at:
   https://www.python.org/downloads/macos/
   The python.org installation includes Tk, needed for the interface.
3. Double-click Setup.command once. It downloads the encryption and Keychain
   libraries into a private runtime and checks native encryption and Tk.
   macOS may ask you to unlock or allow access to your login Keychain.
4. Open College Portals.app. You may move the .app into Applications or put
   an alias on the Desktop. Keep the Python installation in place.

This is a Python-based, unsigned app bundle, not a standalone signed installer.
If macOS blocks opening it, follow the normal macOS process for an app you
trust; this package does not disable Gatekeeper or remove quarantine flags.
An internet connection is required for the first setup only.

All Windows-version features are included: colleges, portal links, separate
Email / Username / Applicant ID fields, password show/copy, notes, application
status, search, paste buttons and right-click editing.
Use Command+S to save, Command+N to add, Command+A to select all, and
Command+C / X / V to copy / cut / paste. Control-click opens editing menus.
Scroll the form with your trackpad or scrollbar; Save stays visible.
Export all saves every saved account into one UTF-8 JSON file, including
passwords, notes and status, regardless of the search filter. The export is
readable plaintext: keep it private. Save any edits first when prompted.
The Export all menu also offers Readable text (.txt): a single file with
clearly labeled details grouped by college, including passwords and notes.
Open it in TextEdit. Choose JSON for importing records later; text reports
are for reading and do not support import.
Choose Word document (.docx) for a formatted, editable Word document with
college headings and labeled details. Word exports include readable passwords
and do not support import. No extra dependency is needed for Word export.
Import adds records from that JSON file into the active local profile. Exact
duplicates are skipped; different records with the same ID are both kept.
This JSON format can move records between Windows and Mac.
The Account switch tab creates and switches independent local profiles.
There are no additional logins or access restrictions. Existing data stays
in Default, which opens on startup. Import / Export all use the active profile.
Additional encrypted profiles live in the profiles subfolder of Application
Support/College Portals; names are in profiles.json. Back up that whole folder
and the login Keychain to preserve all profiles.

DATA AND BACKUP
Encrypted accounts: ~/Library/Application Support/College Portals/accounts.vault
Encryption key: your login Keychain, service "College Portals", account
"vault-encryption-key-v1". The app uses authenticated Fernet encryption and
the native macOS Keychain backend. No passwords go in command arguments.
Anyone using your unlocked login with Keychain access may open the app.
There is no separate master password, auto-lock or cloud sync.
Copied text clears after 30 seconds or normal exit if it is still on the
clipboard. Clipboard history apps may retain copies.

Keep backups of both the vault and your Mac login Keychain. The vault alone
cannot recover accounts if its Keychain encryption key is lost. Reinstalling
or moving the .app keeps data in Application Support. Windows DPAPI vaults
cannot be opened by this version; Windows data is not included or transferred.

VERIFICATION
This package was assembled on Windows. Encryption logic, package structure
and shared GUI behavior were tested there. Native Keychain, Command-key,
trackpad and Finder behavior require verification on a Mac. Setup.command
runs a native Keychain encryption round-trip and a Tk window startup check.
'''


def build(destination=None):
    destination = Path(destination or ROOT / "dist" / "College-Portals-Mac.zip")
    destination.parent.mkdir(parents=True, exist_ok=True)
    files = {
        "Setup.command": (SETUP.encode(), True),
        "README-MAC.txt": (README.encode(), False),
        APP + "MacOS/CollegePortals": (LAUNCH.encode(), True),
        APP + "Info.plist": (plistlib.dumps({
            "CFBundleName": "College Portals", "CFBundleDisplayName": "College Portals",
            "CFBundleIdentifier": "local.collegeportals.manager",
            "CFBundleExecutable": "CollegePortals", "CFBundlePackageType": "APPL",
            "CFBundleShortVersionString": "1.0", "CFBundleVersion": "1",
            "NSHighResolutionCapable": True,
        }), False),
    }
    # Explicit allowlist: never package local account data or Keychain keys.
    for name in ("app.py", "mac_crypto.py", "requirements-mac.txt", "check_mac.py", "word_export.py"):
        files[APP + "Resources/" + name] = (ROOT.joinpath(name).read_bytes(), False)
    with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, (data, executable) in files.items():
            entry = zipfile.ZipInfo(PREFIX + name)
            entry.create_system = 3
            entry.external_attr = (0o100755 if executable else 0o100644) << 16
            entry.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(entry, data)
    return destination


if __name__ == "__main__":
    print(build())
