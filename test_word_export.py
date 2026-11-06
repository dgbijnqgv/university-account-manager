from io import BytesIO
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch
from xml.etree import ElementTree as ET
import zipfile

from app import App, Store
from word_export import word_export, W


class WordExportTests(unittest.TestCase):
    def test_word_menu_exports_valid_document_with_all_fields(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as folder:
            store = Store(Path(folder) / "accounts.vault")
            account = dict(id="test", college="Université Example & College", url="https://example.edu/portal",
                           email="student@example.edu", username="student", applicant_id="000123",
                           password="<secret>&value", status="Applied", notes="First line\nSecond line")
            store.save([account])
            before = store.path.read_bytes()
            app = App(store)
            try:
                output = Path(folder) / "report.docx"
                with patch("app.filedialog.asksaveasfilename", return_value=str(output)) as dialog, \
                        patch("app.messagebox.showinfo"):
                    app.export_menu.invoke(2)
                self.assertEqual(dialog.call_args.kwargs["defaultextension"], ".docx")
                with zipfile.ZipFile(output) as archive:
                    self.assertIsNone(archive.testzip())
                    for name in archive.namelist():
                        ET.fromstring(archive.read(name))
                    root = ET.fromstring(archive.read("word/document.xml"))
                    text = "\n".join(n.text or "" for n in root.iter(f"{{{W}}}t"))
                    for key in ("college", "url", "email", "username", "applicant_id", "password", "status"):
                        self.assertIn(account[key], text)
                    self.assertIn("First line", text)
                    self.assertIn("Second line", text)
                    self.assertIsNotNone(root.find(f".//{{{W}}}br"))
                self.assertEqual(store.path.read_bytes(), before)
            finally:
                app.destroy()

    def test_empty_profile_and_invalid_xml_characters(self):
        with zipfile.ZipFile(BytesIO(word_export([], "Empty profile"))) as archive:
            xml = archive.read("word/document.xml")
            self.assertIn(b"No saved accounts", xml)
            ET.fromstring(xml)
        with self.assertRaises(ValueError):
            word_export([], "invalid\x00profile")


if __name__ == "__main__":
    unittest.main()
