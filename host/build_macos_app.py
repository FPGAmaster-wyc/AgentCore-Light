"""Build a relocatable native menu app with its Python runtime, then create a ZIP."""
import argparse
import importlib.metadata
import os
from pathlib import Path
import platform
import plistlib
import re
import shutil
import subprocess
import sys
import sysconfig


def minimum_system(app, python_target):
    versions = {python_target}
    for path in app.rglob("*"):
        if not path.is_file() or path.is_symlink():
            continue
        with path.open("rb") as source:
            header = source.read(4)
        if header not in (b"\xcf\xfa\xed\xfe", b"\xca\xfe\xba\xbe"):
            continue
        result = subprocess.run(["otool", "-l", str(path)], capture_output=True, text=True, check=True)
        versions.update(re.findall(r"\bminos\s+(\S+)", result.stdout))
        versions.update(re.findall(r"\bversion\s+(\S+)\n\s+sdk", result.stdout))
    return max(versions, key=lambda value: tuple(int(part) for part in value.split(".")))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, help="Output directory (default: .local/dist)")
    args = parser.parse_args()
    if sys.platform != "darwin":
        parser.error("Build on macOS with Xcode Command Line Tools and requirements-macos-build.txt")
    root = Path(__file__).resolve().parent.parent
    output = (args.output or root / ".local/dist").resolve()
    work = root / ".local/package-build"
    output.mkdir(parents=True, exist_ok=True)
    work.mkdir(parents=True, exist_ok=True)
    architecture = platform.machine()
    minimum = sysconfig.get_config_var("MACOSX_DEPLOYMENT_TARGET") or platform.mac_ver()[0]
    app = output / "AgentCore Light.app"
    if app.exists():
        shutil.rmtree(app)
    # Keep a console bootloader for hook stdin/stdout, while using PyInstaller's
    # BUNDLE layout to place Python frameworks and data correctly for codesign.
    spec = work / "agentcore-host.spec"
    spec.write_text(f"""a = Analysis([{str(root / 'host/macos_app.py')!r}],
    pathex=[{str(root / 'host')!r}], hiddenimports=['serial.tools.list_ports_osx'])
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name='agentcore-host',
    console=True, upx=False, target_arch={architecture!r})
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name='agentcore-host')
bundle = BUNDLE(coll, name='AgentCore Light.app',
    bundle_identifier='com.garyjiang.agentcore-light-menu')
""")
    subprocess.run([sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean",
                    "--distpath", str(work / "runtime"), "--workpath", str(work / "analysis"),
                    str(spec)], check=True,
                   env={**os.environ, "PYINSTALLER_CONFIG_DIR": str(work / "cache")})
    shutil.copytree(work / "runtime/AgentCore Light.app", app, symlinks=True)
    minimum = minimum_system(app, minimum)
    contents = app / "Contents"
    documents = contents / "Resources/Documents"
    documents.mkdir(parents=True)
    subprocess.run(["xcrun", "swiftc", str(root / "host/LightMenu.swift"), "-O",
                    "-target", f"{architecture}-apple-macos{minimum}",
                    "-o", str(contents / "MacOS/AgentCoreLight"),
                    "-module-cache-path", str(work / "swift-cache")], check=True)
    (contents / "Info.plist").write_bytes(plistlib.dumps({
        "CFBundleIdentifier": "com.garyjiang.agentcore-light-menu", "CFBundleName": "AgentCore Light",
        "CFBundleDisplayName": "AgentCore Light", "CFBundleExecutable": "AgentCoreLight",
        "CFBundlePackageType": "APPL", "CFBundleVersion": "2", "CFBundleShortVersionString": "0.2.0",
        "LSMinimumSystemVersion": minimum, "LSUIElement": True, "NSHighResolutionCapable": True,
    }))
    for filename in ("README.md", "LICENSE"):
        shutil.copy2(root / filename, documents / filename)
    shutil.copy2(root / "docs/MACOS_V3.md", documents / "MACOS_V3.md")
    licenses = documents / "ThirdPartyLicenses"
    licenses.mkdir()
    shutil.copy2(root / "host/macos_licenses/pyserial-LICENSE.txt", licenses / "pyserial-LICENSE.txt")
    for name in ("pyserial", "pyinstaller"):
        distribution = importlib.metadata.distribution(name)
        for file in distribution.files or []:
            if Path(str(file)).name.upper().startswith(("LICENSE", "COPYING")):
                shutil.copy2(distribution.locate_file(file), licenses / (name + "-" + Path(str(file)).name))
    python_license = Path(sysconfig.get_path("stdlib")) / "LICENSE.txt"
    if not python_license.exists():
        raise FileNotFoundError(f"Python license missing: {python_license}")
    shutil.copy2(python_license, licenses / "Python-LICENSE.txt")
    # Homebrew's Python may collect these libraries; retain their provided notices.
    for name in ("openssl@3", "xz", "zstd"):
        for prefix in (Path("/opt/homebrew/opt"), Path("/usr/local/opt")):
            folder = prefix / name
            if folder.exists():
                for notice in folder.iterdir():
                    if notice.is_file() and notice.name.upper().startswith(("LICENSE", "COPYING")):
                        shutil.copy2(notice, licenses / (name + "-" + notice.name))
                break
    subprocess.run(["codesign", "--force", "--deep", "--sign", "-", str(app)], check=True)
    subprocess.run(["codesign", "--verify", "--deep", "--strict", str(app)], check=True)
    archive = output / f"AgentCore-Light-macOS-{architecture}.zip"
    archive.unlink(missing_ok=True)
    subprocess.run(["ditto", "-c", "-k", "--sequesterRsrc", "--keepParent", str(app), str(archive)], check=True)
    print(f"App: {app}\nZIP: {archive}\nArchitecture: {architecture}; minimum declared macOS: {minimum}")


if __name__ == "__main__":
    main()
