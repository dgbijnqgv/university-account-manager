"""Create installers from checksum-verified, already-tested release bundles."""
import argparse
import hashlib
import json
import os
import plistlib
from pathlib import Path
import shutil
import subprocess
import sys
import urllib.request
from version import VERSION


def download(url, path):
    with urllib.request.urlopen(url, timeout=60) as response, path.open("wb") as output:
        shutil.copyfileobj(response, output)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--label", required=True, choices=("Windows-x64", "Mac-AppleSilicon", "Mac-Intel"))
    args = parser.parse_args()
    root = Path(__file__).resolve().parent
    work = root / "build" / "installers" / args.label
    work.mkdir(parents=True, exist_ok=True)
    output = root / "dist" / "installers"
    output.mkdir(parents=True, exist_ok=True)
    base = f"{os.environ['GITHUB_SERVER_URL']}/{os.environ['GITHUB_REPOSITORY']}/releases/download/v{VERSION}"
    name = f"College-Portals-{VERSION}-{args.label}.zip"
    archive = work / name
    sums = work / "SHA256SUMS.txt"
    download(base + "/SHA256SUMS.txt", sums)
    expected = dict(line.split(None, 1)[::-1] for line in sums.read_text().splitlines())
    download(base + "/" + name, archive)
    if hashlib.sha256(archive.read_bytes()).hexdigest() != expected[name]:
        raise ValueError("Released application checksum did not match")
    if sys.platform == "darwin":
        # ditto preserves app framework symlinks and signing metadata.
        subprocess.run(["ditto", "-x", "-k", str(archive), str(work)], check=True)
        app = work / "College Portals.app"
        subprocess.run(["codesign", "--verify", "--deep", "--strict", str(app)], check=True)
        installer = output / f"College-Portals-{VERSION}-{args.label}.pkg"
        staging = work / "package-root"
        target = staging / "Applications" / "College Portals.app"
        target.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(["ditto", str(app), str(target)], check=True)
        components = work / "components.plist"
        components.write_bytes(plistlib.dumps([{"RootRelativeBundlePath": "Applications/College Portals.app",
            "BundleIsRelocatable": False, "BundleHasStrictIdentifier": True,
            "BundleIsVersionChecked": True, "BundleOverwriteAction": "upgrade"}]))
        subprocess.run(["pkgbuild", "--root", str(staging), "--component-plist", str(components),
                        "--identifier", "local.collegeportals.manager", "--version", VERSION,
                        "--install-location", "/", str(installer)], check=True)
        # CI runs on a disposable native Mac, with an isolated test Keychain.
        subprocess.run(["sudo", "installer", "-pkg", str(installer), "-target", "/"], check=True)
        installed = Path("/Applications/College Portals.app/Contents/MacOS/College Portals")
        subprocess.run(["codesign", "--verify", "--deep", "--strict", "/Applications/College Portals.app"], check=True)
    elif sys.platform == "win32":
        import zipfile
        with zipfile.ZipFile(archive) as source:
            source.extractall(work)
        app = work / "College Portals"
        compiler = Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")) / "Inno Setup 6" / "ISCC.exe"
        if not compiler.exists():
            raise FileNotFoundError("Install Inno Setup 6 before building Windows installers")
        filename = f"College-Portals-{VERSION}-{args.label}-Setup"
        script = work / "installer.iss"
        script.write_text(f'''[Setup]
AppId=CollegePortals
AppName=College Portals
AppVersion={VERSION}
AppPublisher=College Portals contributors
DefaultDirName={{localappdata}}\\Programs\\College Portals
DefaultGroupName=College Portals
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
DisableWelcomePage=yes
DisableDirPage=yes
DisableProgramGroupPage=yes
DisableReadyPage=yes
DisableFinishedPage=yes
CloseApplications=yes
UninstallDisplayIcon={{app}}\\College Portals.exe
OutputDir={output}
OutputBaseFilename={filename}
Compression=lzma2
SolidCompression=yes
[Files]
Source: "{app}\\*"; DestDir: "{{app}}"; Flags: ignoreversion recursesubdirs createallsubdirs
[Icons]
Name: "{{autoprograms}}\\College Portals"; Filename: "{{app}}\\College Portals.exe"
Name: "{{autodesktop}}\\College Portals"; Filename: "{{app}}\\College Portals.exe"
[Run]
Filename: "{{app}}\\College Portals.exe"; Flags: nowait skipifsilent
''', encoding="utf-8-sig")
        subprocess.run([str(compiler), str(script)], check=True)
        installer = output / (filename + ".exe")
        destination = work / "installed"
        subprocess.run([str(installer), "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/NOICONS",
                        "/DIR=" + str(destination)], check=True, timeout=120)
        installed = destination / "College Portals.exe"
        assert installed.read_bytes() == (app / "College Portals.exe").read_bytes()
    else:
        raise RuntimeError("Build the installer on its target OS")
    report = work / "installed-check"
    subprocess.run([str(installed), "--self-test", str(report)], check=True, timeout=120)
    checks = json.loads((report / "self-test.json").read_text())
    assert checks["passed"] and checks["version"] == VERSION
    # Verify that uninstalling Windows binaries keeps user-created records.
    if sys.platform == "win32":
        data = installed.parent / "data"
        data.mkdir(exist_ok=True)
        sentinel = data / "preservation-check.txt"
        sentinel.write_text("synthetic preservation check")
        subprocess.run([str(installed.parent / "unins000.exe"), "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART"],
                       check=True, timeout=120)
        assert sentinel.read_text() == "synthetic preservation check"
        assert not installed.exists()
        checks["uninstall_keeps_user_data"] = True
    checks["installer"] = installer.name
    checks["sha256"] = hashlib.sha256(installer.read_bytes()).hexdigest()
    (output / f"{args.label}-installer-verification.json").write_text(json.dumps(checks, indent=2) + "\n", encoding="utf-8")
    print("Installer and installed application checks passed:", installer.name)


if __name__ == "__main__":
    main()
