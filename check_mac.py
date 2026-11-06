"""Run during Mac setup: real Keychain, encrypted vault and Tk startup check."""
import sys
import tempfile
from pathlib import Path


def main():
    if sys.platform != "darwin":
        raise SystemExit("Run this check on macOS.")
    from app import App, Store
    account = dict(id="setup-check", college="Setup check", url="", email="", username="",
                   applicant_id="001", password="temporary-test-value", notes="", status="Not started")
    with tempfile.TemporaryDirectory() as folder:
        store = Store(Path(folder) / "check.vault")
        store.save([account])
        if store.load() != [account] or account["password"].encode() in store.path.read_bytes():
            raise RuntimeError("Native encrypted vault check failed")
        app = App(store)
        try:
            app.withdraw()
            app.update()
            app.load_account(app.accounts[0])
            if app.fields["applicant_id"].get() != "001":
                raise RuntimeError("Mac account interface check failed")
        finally:
            app.destroy()
    print("Native Keychain encryption and Mac GUI startup checks passed.")


if __name__ == "__main__":
    main()
