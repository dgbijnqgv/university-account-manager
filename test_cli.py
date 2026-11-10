from io import StringIO
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from app import Profiles, Store, StoreConflict, readable_export, write_lock
from college_portals_cli import main


class CLITests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory(dir=Path(__file__).parent)
        self.vault = Path(self.folder.name) / "accounts.vault"
        self.addCleanup(self.folder.cleanup)

    def cli(self, *args, data=None, code=0):
        stdout, stderr = StringIO(), StringIO()
        actual = main(["--vault", str(self.vault), *args], StringIO(json.dumps(data)), stdout, stderr)
        self.assertEqual(actual, code, stderr.getvalue())
        if code:
            self.assertEqual(stdout.getvalue(), "")
            return json.loads(stderr.getvalue())
        self.assertEqual(stderr.getvalue(), "")
        return json.loads(stdout.getvalue())

    def test_machine_workflow_and_password_redaction(self):
        account = {"college": "Example College", "password": "test-only-credential", "applicant_id": "00012"}
        result = self.cli("add", data=account)
        key = result["account"]["id"]
        self.assertNotIn("password", result["account"])
        self.assertTrue(result["account"]["has_password"])
        self.assertFalse(self.cli("add", data=account)["created"])
        self.cli("add", data={"college": "Second College"})
        page = self.cli("list", "--limit", "1", "--offset", "1")
        self.assertEqual(page["total"], 2)
        self.assertEqual(page["accounts"][0]["college"], "Second College")
        self.assertEqual(self.cli("list", "--query", "00012")["accounts"][0]["id"], key)
        self.cli("update", key, data={"status": "Applied"})
        self.assertEqual(self.cli("get", key)["account"]["status"], "Applied")
        self.assertNotIn("test-only-credential", self.vault.read_bytes().decode(errors="ignore"))
        saved = Store(self.vault).load()[0]
        self.assertEqual(saved["password"], account["password"])
        self.assertEqual(saved["applicant_id"], "00012")
        profile_id = self.cli("profile-add", "Other student")["profile"]["id"]
        report = self.vault.parent / "report.txt"
        report.write_text(readable_export([saved], "Default") + "\n", encoding="utf-8")
        self.assertEqual(self.cli("--profile", profile_id, "import", str(report))["added"], 1)
        self.assertEqual(self.cli("--profile", "Other student", "import", str(report))["skipped"], 1)
        self.cli("--profile", profile_id, "get", key, code=3)
        self.cli("delete", key)
        self.cli("get", key, code=3)
        self.assertEqual(self.cli("--profile", profile_id, "list")["total"], 1)

    def test_conflicts_never_replace_a_newer_snapshot(self):
        self.cli("add", data={"college": "Original"})
        older = Store(self.vault)
        account, = older.load()
        self.cli("update", account["id"], data={"notes": "Saved in another process"})
        with self.assertRaises(StoreConflict):
            older.save([{**account, "notes": "Stale edit"}])
        self.assertEqual(older.load()[0]["notes"], "Saved in another process")
        with write_lock(self.vault):
            result = self.cli("update", account["id"], data={"notes": "Busy write"}, code=4)
        self.assertEqual(result["error"]["code"], "conflict")
        self.assertEqual(older.load()[0]["notes"], "Saved in another process")
        stale_profiles = Profiles(self.vault)
        self.cli("profile-add", "New profile")
        with self.assertRaises(StoreConflict):
            stale_profiles.create("Stale profile")

    def test_subprocess_json_contract_and_invalid_input(self):
        command = [sys.executable, str(Path(__file__).with_name("college_portals_cli.py")), "--vault", str(self.vault)]
        result = subprocess.run([*command, "schema"], capture_output=True, text=True, timeout=15, check=True)
        self.assertEqual(json.loads(result.stdout)["api_version"], 1)
        self.assertFalse(self.vault.exists())
        result = subprocess.run([*command, "add"], input='{"password":"test-only-secret"}', capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 2)
        self.assertFalse(json.loads(result.stderr)["ok"])
        self.assertNotIn("test-only-secret", result.stdout + result.stderr)
        self.assertFalse(self.vault.exists())
        result = subprocess.run([*command, "add"], input='{"college":"Example College"}',
                                capture_output=True, text=True, timeout=15, check=True)
        account_id = json.loads(result.stdout)["account"]["id"]
        result = subprocess.run([*command, "get", account_id], capture_output=True, text=True,
                                timeout=15, check=True)
        self.assertEqual(json.loads(result.stdout)["account"]["college"], "Example College")


if __name__ == "__main__":
    unittest.main()
