import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from app import App, Profiles, Store


class ProfileImportTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory(dir=Path(__file__).parent)
        self.root = Path(self.folder.name)
        self.store = Store(self.root / "accounts.vault")
        self.app = App(self.store)
        self.app.update()

    def tearDown(self):
        self.app.destroy()
        self.folder.cleanup()

    def save_college(self, name):
        self.app.fields["college"].set(name)
        self.app.fields["password"].set("sample-secret")
        self.app.fields["applicant_id"].set("000123")
        self.app.notes.insert("1.0", "Notes\nSecond line")
        self.assertTrue(self.app.save())

    def import_file(self, path):
        with patch("app.filedialog.askopenfilename", return_value=str(path)), patch("app.messagebox.showinfo"):
            self.app.import_button.invoke()
        self.app.update()

    def test_export_import_round_trip_profile_isolation_and_restart(self):
        self.save_college("Original College")
        default = self.store.path.read_bytes()
        export = self.root / "transfer.json"
        with patch("app.filedialog.asksaveasfilename", return_value=str(export)), patch("app.messagebox.showinfo"):
            self.app.export_all()
        with patch("app.simpledialog.askstring", return_value="Second student"):
            self.app.create_profile()
        second_id = self.app.active_profile
        self.assertNotEqual(second_id, "default")
        self.assertEqual(self.app.accounts, [])
        self.import_file(export)
        self.assertEqual(len(self.app.accounts), 1)
        self.assertEqual(self.app.accounts[0]["applicant_id"], "000123")
        self.assertEqual(self.app.accounts[0]["password"], "sample-secret")
        self.import_file(export)
        self.assertEqual(len(self.app.accounts), 1)
        self.assertEqual(self.store.path.read_bytes(), default)
        self.app.tree.selection_set(self.app.accounts[0]["id"])
        self.app.update()
        self.app.fields["college"].set("Second student college")
        self.assertTrue(self.app.save())
        self.assertTrue(self.app.switch_profile("default"))
        self.assertEqual(self.app.accounts[0]["college"], "Original College")
        self.assertEqual(self.app.fields["password"].get(), "")
        self.assertEqual(self.app.search.get(), "")
        catalog = Profiles(self.store.path)
        self.assertEqual(len(catalog.items), 2)
        self.assertEqual(catalog.store_for(second_id).load()[0]["college"], "Second student college")
        self.assertEqual(catalog.store_for("default").load()[0]["college"], "Original College")
        # Exports belong to only the current profile.
        with patch("app.filedialog.asksaveasfilename", return_value=str(export)), patch("app.messagebox.showinfo"):
            self.app.export_all()
        self.assertEqual([a["college"] for a in json.loads(export.read_text())["accounts"]], ["Original College"])

    def test_import_conflicts_invalid_records_and_failed_save(self):
        self.save_college("Keep this")
        existing = dict(self.app.accounts[0])
        different = {**existing, "college": "Imported conflict"}
        source = self.root / "source.json"
        source.write_text(json.dumps({"version": 2, "accounts": [different]}), encoding="utf-8")
        self.import_file(source)
        self.assertEqual([a["college"] for a in self.app.accounts], ["Keep this", "Imported conflict"])
        self.assertEqual(len({a["id"] for a in self.app.accounts}), 2)
        self.import_file(source)
        self.assertEqual(len(self.app.accounts), 2)
        before = self.app.store.path.read_bytes()
        invalid = {**existing, "id": "invalid", "password": 123}
        new = {**existing, "id": "new", "college": "Should not partially import"}
        source.write_text(json.dumps({"version": 2, "accounts": [new, invalid]}), encoding="utf-8")
        with patch("app.messagebox.showerror") as error:
            self.import_file(source)
            error.assert_called_once()
        self.assertEqual(self.app.store.path.read_bytes(), before)
        self.assertEqual(len(self.app.accounts), 2)
        source.write_text(json.dumps({"version": 2, "accounts": [new]}), encoding="utf-8")
        with patch.object(self.app.store, "save", side_effect=OSError("read only")), patch("app.messagebox.showerror"):
            self.import_file(source)
        self.assertEqual(self.app.store.path.read_bytes(), before)
        self.assertEqual(len(self.app.accounts), 2)
        with patch("app.filedialog.askopenfilename", return_value=""):
            self.app.import_accounts()
        self.assertEqual(len(self.app.accounts), 2)

    def test_cancelled_and_failed_switch_keep_current_form(self):
        profile = self.app.profiles.create("Other")
        self.app.refresh_profiles()
        self.app.fields["college"].set("Unsaved")
        with patch("app.messagebox.askyesnocancel", return_value=None):
            self.assertFalse(self.app.switch_profile(profile["id"]))
        self.assertEqual(self.app.active_profile, "default")
        self.assertEqual(self.app.fields["college"].get(), "Unsaved")
        other = self.app.profiles.store_for(profile["id"])
        other.path.parent.mkdir(parents=True)
        other.path.write_bytes(b"broken vault")
        with patch("app.messagebox.askyesnocancel", return_value=False), patch("app.messagebox.showerror"):
            self.assertFalse(self.app.switch_profile(profile["id"]))
        self.assertEqual(self.app.active_profile, "default")
        self.assertEqual(self.app.fields["college"].get(), "Unsaved")
        with self.assertRaises(ValueError):
            self.app.profiles.create("other")


if __name__ == "__main__":
    unittest.main()
