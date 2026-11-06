# College Portals

A small local desktop manager for college portal accounts, built with Python
and Tk. Supports Windows and a Python-based macOS app bundle.

- Separate email, username, applicant ID, password, status, and notes.
- Search, portal links, paste controls, and password copy/reveal.
- Local profiles with separate records and no extra login restrictions.
- JSON import/export, readable text export, and Word document export.
- Windows DPAPI encryption or a macOS Keychain-protected encryption key.

## Run on Windows

Install Python 3.10 or newer with Tk, then open `Launch.cmd` or run:

```powershell
python app.py
```

## Build the Mac download

```powershell
python build_mac.py
```

Transfer `dist/College-Portals-Mac.zip` to a Mac, extract it, and follow
`README-MAC.txt`. Python with Tk is required. `Setup.command` installs the
Mac dependencies and runs native startup checks. The bundle is unsigned;
it is not a standalone Python-free application. Native Mac behavior has
not been verified on a Mac by this project.

## Data and privacy

Account data stays local. Windows stores it in `data/`; macOS uses
`~/Library/Application Support/College Portals/`. Protect backups of the
vaults and their OS encryption keys. Profiles organize records and do not
provide access control between people using the same OS login.

JSON, text, and Word exports include readable passwords. JSON is the format
for moving accounts between Windows and Mac. Export files should remain private.

The repository uses an explicit source-file allowlist. Account vaults, profile
names, exported files, local QA documents, build packages, machine settings,
and caches are excluded. Tests use invented accounts and example addresses.
Review any future changes before uploading them; ignore rules can be bypassed
with `git add --force`.

See `README.txt` for usage and backup details.

## Tests

The shared Windows GUI tests need Python with Tk:

```powershell
python -m unittest -v test_app.py test_profiles.py test_word_export.py
```

`test_mac.py` also uses `cryptography` to test the Mac encryption logic with
a simulated Keychain. `check_mac.py` performs native checks on an actual Mac.
