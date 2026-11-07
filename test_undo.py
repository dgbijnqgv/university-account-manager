from pathlib import Path
import tempfile
import tkinter as tk
import unittest
from unittest.mock import patch

from app import App, Store


class UndoTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory(dir=Path(__file__).parent)
        self.app = App(Store(Path(self.folder.name) / "accounts.vault"))
        self.app.update()

    def tearDown(self):
        self.app.destroy()
        self.folder.cleanup()

    def key(self, entry, key):
        entry.focus_force()
        self.app.update()
        entry.event_generate(key)
        self.app.update()

    def test_ctrl_z_and_redo_across_fields(self):
        for entry in [*self.app.entries.values(), self.app.search_entry]:
            with self.subTest(field=str(entry)):
                entry.insert(0, "original")
                entry.history.reset()
                entry.insert("end", " mistake")
                self.key(entry, "<Control-z>")
                self.assertEqual(entry.get(), "original")
                self.key(entry, "<Control-y>")
                self.assertEqual(entry.get(), "original mistake")
                self.key(entry, "<Control-z>")
                entry.insert("end", " new")
                self.key(entry, "<Control-y>")
                self.assertEqual(entry.get(), "original new")

    def test_paste_replacement_is_one_undo_and_cut_restores(self):
        entry = self.app.entries["password"]
        entry.insert(0, "original-secret")
        entry.history.reset()
        entry.selection_range(0, "end")
        with patch.object(self.app, "clipboard_get", return_value="replacement"):
            self.app.paste_buttons["password"].invoke()
        self.key(entry, "<Control-z>")
        self.assertEqual(entry.get(), "original-secret")
        self.key(entry, "<Control-Shift-Z>")
        self.assertEqual(entry.get(), "replacement")
        entry.selection_range(0, "end")
        with patch.object(self.app, "copy_text"):
            entry.event_generate("<<Cut>>")
        self.assertEqual(entry.get(), "")
        self.key(entry, "<Control-z>")
        self.assertEqual(entry.get(), "replacement")
        self.assertEqual(entry.cget("show"), "•")

    def test_notes_shortcuts_and_account_history_reset(self):
        notes = self.app.notes
        notes.insert("1.0", "original notes")
        notes.edit_reset()
        self.app.select_all(notes)
        with patch.object(self.app, "clipboard_get", return_value="new notes"):
            self.app.paste(notes)
        self.key(notes, "<Control-z>")
        self.assertEqual(notes.get("1.0", "end-1c"), "original notes")
        self.key(notes, "<Control-y>")
        self.assertEqual(notes.get("1.0", "end-1c"), "new notes")
        entry = self.app.entries["password"]
        entry.insert(0, "another-account-password")
        self.app.load_account(None)
        self.key(entry, "<Control-z>")
        self.assertEqual(entry.get(), "")
        self.key(notes, "<Control-z>")
        self.assertEqual(notes.get("1.0", "end-1c"), "")
        for index in range(150):
            self.app.fields["password"].set(str(index))
        self.assertLessEqual(len(entry.history.states), 101)


if __name__ == "__main__":
    unittest.main()
