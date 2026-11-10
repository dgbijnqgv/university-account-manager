"""Non-interactive JSON interface to the College Portals desktop vault."""
import argparse
import json
from pathlib import Path
import sys
import uuid

from app import Profiles, STATES, StoreConflict, VAULT, account_payload, merge_accounts, read_import
from version import VERSION

WRITABLE = ("college", "url", "email", "username", "applicant_id", "password", "status", "notes")
COMMANDS = {
    "schema": "Describe the CLI without opening a vault.",
    "profiles": "List local profile IDs and names.",
    "profile-add": "Create a named local profile.",
    "list": "Search account summaries with offset/limit pagination.",
    "get": "Read a record by ID, excluding its password.",
    "add": "Create an account from a JSON object on stdin.",
    "update": "Apply a JSON field patch from stdin to an account ID.",
    "delete": "Delete the account with the supplied ID.",
    "import": "Merge a College Portals JSON, TXT, or DOCX export into the profile.",
}


class CLIError(Exception):
    def __init__(self, kind, message, code):
        super().__init__(message)
        self.kind, self.code = kind, code


class Parser(argparse.ArgumentParser):
    def error(self, message):
        raise CLIError("invalid_arguments", "Invalid arguments. Use --help or schema.", 2)


def parse(argv):
    parser = Parser(description=__doc__)
    parser.add_argument("--version", action="version", version=VERSION)
    parser.add_argument("--vault", type=Path, default=VAULT, help="Path to the Default accounts.vault")
    parser.add_argument("--profile", default="default", help="Profile ID or name (default: Default)")
    subparsers = parser.add_subparsers(dest="command", required=True)
    for command, description in COMMANDS.items():
        sub = subparsers.add_parser(command, help=description, description=description)
        if command in ("get", "update", "delete"):
            sub.add_argument("id")
        elif command == "profile-add":
            sub.add_argument("name")
        elif command == "import":
            sub.add_argument("file", type=Path)
        elif command == "list":
            sub.add_argument("--query", default="")
            sub.add_argument("--offset", type=int, default=0)
            sub.add_argument("--limit", type=int, default=50)
    return parser.parse_args(argv)


def json_input(stdin):
    if stdin.isatty():
        raise ValueError("Pipe a JSON object on stdin.")
    data = getattr(stdin, "buffer", stdin).read(1024 * 1024 + 1)
    if len(data) > 1024 * 1024:
        raise ValueError("Input exceeds 1 MiB.")
    value = json.loads(data)
    if not isinstance(value, dict) or not value or any(k not in WRITABLE or not isinstance(v, str) for k, v in value.items()):
        raise ValueError("Supply a JSON object with supported string fields.")
    if "status" in value and value["status"] not in STATES:
        raise ValueError("Unknown application status. See schema.")
    return value


def public_account(account):
    return {**{k: v for k, v in account.items() if k != "password"}, "has_password": bool(account["password"])}


def run(args, stdin):
    command = args.command
    if command == "schema":
        return {"api_version": 1, "app_version": VERSION, "commands": COMMANDS,
                "options": {"--vault": "Default vault path", "--profile": "Profile ID or name"},
                "writable_fields": WRITABLE, "required_on_add": ["college"], "statuses": STATES,
                "password": "Write-only through JSON stdin or file import.",
                "exit_codes": {"0": "success", "1": "storage error", "2": "invalid input",
                               "3": "not found", "4": "write conflict"}}
    profiles = Profiles(args.vault.resolve())
    if command == "profiles":
        return {"profiles": profiles.items}
    if command == "profile-add":
        return {"profile": profiles.create(args.name)}
    profile = next((p for p in profiles.items if p["id"] == args.profile), None)
    if profile is None:
        profile = next((p for p in profiles.items if p["name"].casefold() == args.profile.casefold()), None)
    if profile is None:
        raise CLIError("not_found", "Profile not found.", 3)

    # Read input before taking a vault snapshot so a slow pipe cannot stale it.
    changes = json_input(stdin) if command in ("add", "update") else None
    incoming = read_import(args.file) if command == "import" else None
    store = profiles.store_for(profile["id"])
    accounts = store.load()
    result = {"profile_id": profile["id"]}
    if command == "list":
        if not 1 <= args.limit <= 500 or args.offset < 0:
            raise ValueError("Limit must be 1–500 and offset must be nonnegative.")
        query = args.query.strip().casefold()
        matches = sorted((a for a in accounts if query in " ".join(a[k] for k in (
            "college", "email", "username", "applicant_id", "status")).casefold()),
            key=lambda a: (a["college"].casefold(), a["id"]))
        return {**result, "total": len(matches), "offset": args.offset, "limit": args.limit,
                "accounts": [{k: a[k] for k in ("id", "college", "status")}
                             for a in matches[args.offset:args.offset + args.limit]]}
    if command == "import":
        updated, added = merge_accounts(accounts, incoming)
        if added:
            store.save(updated)
        return {**result, "added": added, "skipped": len(incoming) - added}
    if command == "add":
        record = {**dict.fromkeys(WRITABLE, ""), "status": STATES[0], **changes, "id": str(uuid.uuid4())}
        record["college"] = record["college"].strip()
        record, = account_payload({"version": 2, "accounts": [record]})
        same = next((a for a in accounts if all(a[key] == record[key] for key in WRITABLE)), None)
        if same is not None:
            return {**result, "created": False, "account": public_account(same)}
        store.save(accounts + [record])
        return {**result, "created": True, "account": public_account(record)}
    index = next((i for i, a in enumerate(accounts) if a["id"] == args.id), None)
    if index is None:
        raise CLIError("not_found", "Account not found in this profile.", 3)
    if command == "delete":
        del accounts[index]
        store.save(accounts)
        return {**result, "deleted_id": args.id}
    if command == "update":
        record = {**accounts[index], **changes}
        record["college"] = record["college"].strip()
        record, = account_payload({"version": 2, "accounts": [record]})
        if record != accounts[index]:
            accounts[index] = record
            store.save(accounts)
    return {**result, "account": public_account(accounts[index])}


def main(argv=None, stdin=None, stdout=None, stderr=None):
    stdin = sys.stdin if stdin is None else stdin
    stdout = sys.stdout if stdout is None else stdout
    stderr = sys.stderr if stderr is None else stderr
    try:
        result = run(parse(argv), stdin)
    except CLIError as error:
        kind, message, code = error.kind, str(error), error.code
    except StoreConflict:
        kind, message, code = "conflict", "Vault or profiles changed. Reload and retry.", 4
    except ValueError:
        kind, message, code = "invalid_input", "Invalid account data, input, or export format. See schema.", 2
    except Exception:
        # Do not echo file contents, credentials, OS paths, or tracebacks into agent logs.
        kind, message, code = "storage_error", "Could not read or write the vault or import file. Check the path and OS login.", 1
    else:
        print(json.dumps({"ok": True, **result}, separators=(",", ":")), file=stdout)
        return 0
    print(json.dumps({"ok": False, "error": {"code": kind, "message": message}}, separators=(",", ":")), file=stderr)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
