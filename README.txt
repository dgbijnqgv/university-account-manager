COLLEGE PORTALS

Double-click Launch.cmd to open the app. Requires Windows and Python 3.10+
with Tk. No additional packages or services are needed on Windows.

Open Launch.cmd, or a desktop shortcut pointing to it.
Click Add college, enter its portal address, email, username, applicant /
student ID, password and optional application status / notes, then Save account.
Search by college, email, username or ID. IDs preserve leading zeroes.
Open launches a portal in your browser; Copy copies a login field.
Paste buttons, Ctrl+V and right-click Cut / Copy / Paste / Select all work in
editable fields and notes. Ctrl+A selects all text in a field. The form scrolls
on smaller windows; Save and Delete stay visible below it.
Existing accounts keep the old combined login as Username. If it looks like
an email address, Email is also prefilled. You can edit them independently.
Ctrl+S saves; Ctrl+N starts a new account. Show hides again after 15 seconds.
Ctrl+Z undoes text edits; Ctrl+Y or Ctrl+Shift+Z redoes them. On Mac use
Command+Z and Command+Shift+Z. Right-click menus also offer Undo and Redo.
Undo history is per field and resets when saving or loading an account.
Unsaved changes prompt you to save before changing accounts or closing.
Export all saves every saved account (including all login fields, passwords,
status and notes) in a single UTF-8 JSON file, regardless of the search filter.
The export is readable plaintext, so keep it private. Unsaved edits can be
saved first; choosing not to save exports the previously saved accounts.
Click Export all and choose Readable text (.txt) for a single, clearly labeled
file you can open in Notepad or TextEdit. It groups details by college and
includes the active profile name, passwords, status and multiline notes.
JSON is recommended for backups because it preserves internal record IDs.
Export all > Word document (.docx) creates a formatted Word file with college
headings and labeled details. It includes readable passwords. Word reports
require no additional packages.
Import reads College Portals JSON, TXT and DOCX exports into the active
profile on Windows or Mac. For TXT and DOCX, keep the original report layout,
field labels and account count. Older .doc files and arbitrary reports are
not supported. Identical records are skipped. If a JSON ID conflicts with
a different record, both are kept. Invalid files leave existing records intact.

Use the Account switch tab to create and switch local accounts / profiles.
These separate college records without adding logins or access restrictions.
Existing records stay in Default. The app starts in Default on each launch.
Import and Export all apply only to the active profile. Other profiles are
stored in data\profiles\; their names are in data\profiles.json. Back up the
entire data folder to preserve every profile, together with Windows DPAPI keys.
To move records between Windows and Mac, export and import on the other device.

MAC VERSION
The Mac package is dist\College-Portals-Mac.zip. Extract it on a Mac and
follow README-MAC.txt: install Python with Tk, run Setup.command once, then
open College Portals.app. It uses macOS Keychain instead of Windows DPAPI.
Windows account files are not portable to the Mac version.

PRIVACY AND BACKUP
All account fields are encrypted on disk with Windows DPAPI in
data\accounts.vault, beside the app. No accounts are sent to a server.
Encryption is tied to your Windows login: anyone using that login can open
the app. It does not have a separate master password or automatic locking.
Clipboard text is cleared after 30 seconds or when the app closes normally,
if it still contains what the app copied. Windows clipboard history and
other clipboard tools may retain copies.

Back up data\accounts.vault after saving. A backup requires the original
Windows user's DPAPI keys to decrypt; it is not a portable cross-computer
backup. Keep the app folder somewhere only you can access. Deleting the
folder also deletes your saved accounts. There is no recovery or cloud sync.
