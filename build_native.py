"""Build a self-contained app on the target OS, then test and package it."""
from pathlib import Path
import platform
import plistlib
import subprocess
import sys
import zipfile
from version import VERSION

ROOT = Path(__file__).resolve().parent


def main():
    if sys.platform not in ("win32", "darwin"):
        raise SystemExit("Build on Windows or macOS.")
    dist = ROOT / "dist" / "native"
    work = ROOT / "build" / "native"
    dist.mkdir(parents=True, exist_ok=True)
    work.mkdir(parents=True, exist_ok=True)
    command = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--onedir", "--windowed",
               "--name", "College Portals", "--distpath", str(dist), "--workpath", str(work),
               "--specpath", str(work), "--hidden-import", "frozen_check"]
    if sys.platform == "darwin":
        command += ["--osx-bundle-identifier", "local.collegeportals.manager",
                    "--hidden-import", "keyring.backends.macOS"]
    else:
        # Windows DPAPI needs no third-party crypto/Keychain dependencies.
        command += ["--exclude-module", "mac_crypto", "--exclude-module", "keyring",
                    "--exclude-module", "cryptography"]
    command.append(str(ROOT / "app.py"))
    subprocess.run(command, check=True)
    if sys.platform == "darwin":
        bundle = dist / "College Portals.app"
        info = bundle / "Contents" / "Info.plist"
        metadata = plistlib.loads(info.read_bytes())
        metadata["CFBundleShortVersionString"] = VERSION
        metadata["CFBundleVersion"] = VERSION
        info.write_bytes(plistlib.dumps(metadata))
        # Ad-hoc signing preserves bundle integrity; this is not Apple notarization.
        subprocess.run(["codesign", "--force", "--deep", "--sign", "-", str(bundle)], check=True)
        executable = bundle / "Contents" / "MacOS" / "College Portals"
        label = "Mac-AppleSilicon" if platform.machine() == "arm64" else "Mac-Intel"
        readme = ("Open College Portals.app. Python is bundled; no setup script or Python installation is needed.\n"
                  "You can move the app to Applications. macOS may ask for login Keychain access.\n"
                  "This app is ad-hoc signed, not Developer ID signed or notarized. macOS may block downloaded builds.\n"
                  "Records stay in ~/Library/Application Support/College Portals. Keep backups of this folder and your Keychain.\n")
    else:
        bundle = dist / "College Portals"
        executable = bundle / "College Portals.exe"
        label = "Windows-x64"
        readme = ("Extract the whole ZIP, then open College Portals.exe. Keep the _internal folder beside it.\n"
                  "Python is bundled; no separate installation is needed. This portable build is not code-signed.\n"
                  "Records are stored in the data folder beside the executable. Keep the extracted folder somewhere writable.\n"
                  "To upgrade from the source version, close the app and copy its data folder beside this executable. Keep a backup.\n")
    report = ROOT / "build" / "native-check"
    subprocess.run([str(executable), "--self-test", str(report)], check=True, timeout=120)
    import json
    assert json.loads((report / "self-test.json").read_text())["passed"]
    readme += ("\nCollege Portals JSON, TXT, and DOCX exports can be imported on another computer. Keep the TXT/DOCX layout and labels.\n"
               "All exports contain readable passwords: keep them private. Local profiles separate records without extra access restrictions.\n")
    output = ROOT / "dist" / f"College-Portals-{VERSION}-{label}.zip"
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for source in sorted(bundle.rglob("*")):
            # PyInstaller's Mac bundle uses symlinks; preserve them for signing integrity.
            if source.is_symlink():
                import os
                entry = zipfile.ZipInfo(source.relative_to(dist).as_posix())
                entry.create_system = 3
                entry.external_attr = 0o120777 << 16
                archive.writestr(entry, os.readlink(source).encode())
            elif source.is_file():
                archive.write(source, source.relative_to(dist).as_posix())
        archive.writestr("README.txt", f"College Portals {VERSION}\n\n" + readme)
    print(output)


if __name__ == "__main__":
    main()
