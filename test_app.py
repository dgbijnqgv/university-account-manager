import tempfile
from pathlib import Path
import unittest
import tkinter as tk
from unittest.mock import patch

from app import App, Store, crypt, portal_url
import json


class AccountTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=Path(__file__).parent)
        self.store = Store(Path(self.temp.name) / "accounts.vault")

    def tearDown(self):
        self.temp.cleanup()

    def test_encrypted_round_trip_and_failed_replace(self):
        account = dict(id="one", college="Example University", url="https://example.edu",
                       email="student@example.com", username="student", applicant_id="00123",
                       password="secret-123-xyz", notes="My notes", status="Applied")
        self.store.save([account])
        original = self.store.path.read_bytes()
        for value in (account["password"], account["username"], account["college"], account["notes"]):
            self.assertNotIn(value.encode(), original)
        self.assertEqual(self.store.load(), [account])
        with patch("app.os.replace", side_effect=OSError("disk failure")):
            with self.assertRaises(OSError):
                self.store.save([])
        self.assertEqual(self.store.path.read_bytes(), original)
        self.assertEqual(self.store.load(), [account])

    def test_corrupt_file_rejected_and_preserved(self):
        self.store.path.write_bytes(b"invalid encrypted data")
        with self.assertRaises(OSError):
            self.store.load()
        self.assertEqual(self.store.path.read_bytes(), b"invalid encrypted data")

    def test_existing_vault_migration_preserves_login_and_password(self):
        legacy = dict(id="one", college="Example", url="", username="old@example.com",
                      password="existing-secret", notes="Keep this", status="Applied")
        self.store.path.write_bytes(crypt(json.dumps({"version": 1, "accounts": [legacy]}).encode()))
        before = self.store.path.read_bytes()
        migrated = self.store.load()[0]
        for key, value in legacy.items():
            self.assertEqual(migrated[key], value)
        self.assertEqual(migrated["email"], "old@example.com")
        self.assertEqual(migrated["applicant_id"], "")
        self.assertEqual(self.store.path.read_bytes(), before)
        self.store.save([migrated])
        self.assertEqual(self.store.load(), [migrated])

    def test_paste_buttons_shortcut_selection_and_notes(self):
        app = App(self.store)
        try:
            app.update()
            for key in ("college", "url", "email", "username", "applicant_id", "password"):
                entry = app.entries[key]
                app.fields[key].set("replace me")
                entry.selection_range(0, "end")
                with patch.object(app, "clipboard_get", return_value="pasted value"):
                    app.paste_buttons[key].invoke()
                self.assertEqual(app.fields[key].get(), "pasted value")
                entry.selection_range(0, "end")
                with patch.object(app, "clipboard_get", return_value="virtual paste"):
                    entry.event_generate("<<Paste>>")
                self.assertEqual(app.fields[key].get(), "virtual paste")
                self.assertTrue(entry.bind("<Button-3>"))
                app.select_all(entry)
                with patch.object(app, "clipboard_get", return_value="keyboard paste"):
                    entry.focus_force()
                    app.update()
                    entry.event_generate("<Control-v>")
                    app.update()
                self.assertEqual(app.fields[key].get(), "keyboard paste")
            app.notes.insert("1.0", "old notes")
            app.select_all(app.notes)
            with patch.object(app, "clipboard_get", return_value="line one\nline two"):
                app.notes.event_generate("<<Paste>>")
            self.assertEqual(app.notes.get("1.0", "end-1c"), "line one\nline two")
            app.notes.edit_undo()
            self.assertEqual(app.notes.get("1.0", "end-1c"), "old notes")
            with patch.object(app, "clipboard_get", side_effect=tk.TclError):
                app.paste_buttons["password"].invoke()
            self.assertEqual(app.fields["password"].get(), "keyboard paste")
        finally:
            app.destroy()

    def test_portal_addresses(self):
        self.assertEqual(portal_url(" example.edu/portal "), "https://example.edu/portal")
        for value in ("javascript://alert(1)", "file:///etc/passwd", "https://", "https://a b.edu",
                      "https://user:password@example.edu", "https://example.edu:invalid"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                portal_url(value)

    def test_export_all_includes_filtered_accounts_and_preserves_vault(self):
        app = App(self.store)
        try:
            for name in ("Example University", "Université Two"):
                app.fields["college"].set(name)
                app.fields["email"].set("person@example.edu")
                app.fields["username"].set("student")
                app.fields["applicant_id"].set("001234")
                app.fields["password"].set("example-secret")
                app.fields["status"].set("Applied")
                app.notes.insert("1.0", "First line\nSecond line")
                self.assertTrue(app.save())
                app.new()
            app.search.set("Example University")
            app.update()
            self.assertEqual(len(app.tree.get_children()), 1)
            before = self.store.path.read_bytes()
            destination = Path(self.temp.name) / "export.json"
            with patch("app.filedialog.asksaveasfilename", return_value=str(destination)), \
                    patch("app.messagebox.showinfo") as success:
                app.export_menu.invoke(0)
            success.assert_called_once()
            payload = json.loads(destination.read_text(encoding="utf-8"))
            self.assertEqual(payload, {"version": 2, "accounts": app.accounts})
            self.assertEqual(len(payload["accounts"]), 2)
            self.assertEqual(payload["accounts"][1]["applicant_id"], "001234")
            self.assertEqual(self.store.path.read_bytes(), before)
            # Cancelling, a failed replacement, and selecting the vault must not destroy data.
            with patch("app.filedialog.asksaveasfilename", return_value=""):
                app.export_all()
            original = destination.read_bytes()
            with patch("app.filedialog.asksaveasfilename", return_value=str(destination)), \
                    patch("app.os.replace", side_effect=OSError("disk full")), \
                    patch("app.messagebox.showerror") as error:
                app.export_all()
                error.assert_called_once()
            self.assertEqual(destination.read_bytes(), original)
            self.assertFalse(list(destination.parent.glob(".college-export-*.tmp")))
            with patch("app.filedialog.asksaveasfilename", return_value=str(self.store.path)), \
                    patch("app.messagebox.showerror") as error:
                app.export_all()
                error.assert_called_once()
            self.assertEqual(self.store.path.read_bytes(), before)
            app.fields["college"].set("Unsaved college")
            with patch("app.messagebox.askyesnocancel", return_value=None), \
                    patch("app.filedialog.asksaveasfilename") as dialog:
                app.export_all()
                dialog.assert_not_called()
        finally:
            app.destroy()

    def test_readable_text_export_option(self):
        app = App(self.store)
        try:
            app.fields["college"].set("Université Example")
            app.fields["url"].set("https://example.edu")
            app.fields["email"].set("student@example.edu")
            app.fields["username"].set("student")
            app.fields["applicant_id"].set("000123")
            app.fields["password"].set("sample-password")
            app.fields["status"].set("Applied")
            app.notes.insert("1.0", "First note\nSecond note")
            self.assertTrue(app.save())
            original = self.store.path.read_bytes()
            destination = Path(self.temp.name) / "accounts.txt"
            with patch("app.filedialog.asksaveasfilename", return_value=str(destination)) as dialog, \
                    patch("app.messagebox.showinfo"):
                app.export_menu.invoke(1)
            self.assertEqual(dialog.call_args.kwargs["defaultextension"], ".txt")
            text = destination.read_text(encoding="utf-8")
            for expected in ("Profile: Default", "Saved accounts: 1", "1. Université Example",
                             "Portal address: https://example.edu", "Email: student@example.edu",
                             "Username: student", "Applicant / student ID: 000123",
                             "Password: sample-password", "Application status: Applied",
                             "Notes:\nFirst note\nSecond note"):
                self.assertIn(expected, text)
            self.assertEqual(self.store.path.read_bytes(), original)
        finally:
            app.destroy()

    def test_gui_account_lifecycle(self):
        app = App(self.store)
        try:
            app.update()
            app.fields["college"].set("Example University")
            app.fields["url"].set("example.edu/portal")
            app.fields["username"].set("student@example.com")
            app.fields["email"].set("separate@example.com")
            app.fields["applicant_id"].set("001234")
            app.fields["password"].set("demo-secret")
            app.notes.insert("1.0", "Check financial aid")
            self.assertTrue(app.save())
            first_id = app.current
            app.update()
            self.assertEqual(self.store.load()[0]["url"], "https://example.edu/portal")
            self.assertEqual(app.entries["password"].cget("show"), "•")
            app.toggle_password()
            self.assertEqual(app.entries["password"].cget("show"), "")
            app.hide_password()
            with patch("app.webbrowser.open", return_value=True) as browser:
                app.open_portal()
                browser.assert_called_once_with("https://example.edu/portal")
            app.new()
            app.fields["college"].set("Second College")
            self.assertTrue(app.save())
            app.search.set("EXAMPLE")
            app.update()
            self.assertEqual(app.tree.get_children(), (first_id,))
            app.tree.selection_set(first_id)
            app.update()
            self.assertEqual(app.fields["password"].get(), "demo-secret")
            self.assertEqual(app.fields["email"].get(), "separate@example.com")
            self.assertEqual(app.fields["applicant_id"].get(), "001234")
            for query in ("separate@example.com", "001234"):
                app.search.set(query)
                app.update()
                self.assertEqual(app.tree.get_children(), (first_id,))
            app.fields["status"].set("Accepted")
            self.assertTrue(app.save())
            # A cancelled navigation must retain the edited account and its changes.
            app.fields["username"].set("unsaved")
            with patch("app.messagebox.askyesnocancel", return_value=None):
                app.new()
            self.assertEqual(app.current, first_id)
            self.assertEqual(app.fields["username"].get(), "unsaved")
            with patch("app.messagebox.askyesnocancel", return_value=False):
                app.new()
            app.search.set("")
            app.tree.selection_set(first_id)
            app.update()
            self.assertEqual(app.fields["username"].get(), "student@example.com")
            with patch.object(app.store, "save", side_effect=OSError("disk full")), \
                    patch("app.messagebox.showerror") as error:
                app.fields["college"].set("Edited")
                self.assertFalse(app.save())
                error.assert_called_once()
            self.assertEqual(next(a for a in app.accounts if a["id"] == first_id)["college"], "Example University")
            app.load_account(next(a for a in app.accounts if a["id"] == first_id))
            with patch("app.messagebox.askyesno", return_value=True):
                app.delete()
            self.assertEqual([a["college"] for a in self.store.load()], ["Second College"])
            app.update()
            # All controls remain inside the client area at the minimum supported size.
            app.geometry("850x680")
            app.update()
            for widget in (app.form_canvas, app.delete_button, app.entries["college"], app.feedback):
                self.assertLessEqual(widget.winfo_rooty() + widget.winfo_height(), app.winfo_rooty() + app.winfo_height())
            app.form_canvas.yview_moveto(1)
            app.update()
            self.assertLessEqual(app.notes.winfo_rooty() + app.notes.winfo_height(),
                                 app.form_canvas.winfo_rooty() + app.form_canvas.winfo_height() + 1)
        finally:
            app.destroy()
        reopened = App(self.store)
        try:
            self.assertEqual(reopened.accounts[0]["college"], "Second College")
        finally:
            reopened.destroy()


if __name__ == "__main__":
    unittest.main()
