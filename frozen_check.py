"""Explicit diagnostic entry point used to verify the compiled application."""
import json
from pathlib import Path
import tempfile
from version import VERSION


def self_test(output):
    from app import App, Store, word_export, readable_export
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=output) as folder:
        store = Store(Path(folder) / "accounts.vault")
        account = dict(id="diagnostic", college="Example College", url="https://example.edu",
                       email="student@example.edu", username="student", applicant_id="000123",
                       password="diagnostic-only", status="Applied", notes="Line one\nLine two")
        store.save([account])
        assert store.load() == [account]
        assert account["password"].encode() not in store.path.read_bytes()
        app = App(store)
        try:
            app.withdraw()
            app.update()
            app.load_account(account)
            assert app.fields["applicant_id"].get() == "000123"
            assert app.entries["password"].cget("show") == "•"
            assert word_export(app.accounts, "Diagnostic").startswith(b"PK")
            assert "Example College" in readable_export(app.accounts, "Diagnostic")
            other = app.profiles.create("Diagnostic second profile")
            assert app.switch_profile(other["id"])
            assert app.accounts == []
            assert app.switch_profile("default")
            assert app.accounts == [account]
        finally:
            app.destroy()
    (output / "self-test.json").write_text(json.dumps({"version": VERSION, "passed": True,
        "checks": ["native encryption", "vault round trip", "Tk GUI", "account fields", "Word/text export", "profile switching"]}), encoding="utf-8")
