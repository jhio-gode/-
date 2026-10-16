#!/usr/bin/env python3
"""Build self-contained Windows bundles without running Windows code.

Use CPython's official NuGet distribution because it contains the complete
standard library. Check its published NuGet SHA512 and each wheel's published
PyPI SHA256 before unpacking. TLS verification is always enabled.
"""
from __future__ import annotations

import argparse
import base64
import gzip
import hashlib
import json
import os
import shutil
import struct
import subprocess
import sys
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VERSION = "3.0.0"
PYTHON_VERSION = "3.8.10"


def fetch(url, dest=None):
    if not url.startswith("https://"):
        raise ValueError("Only verified HTTPS downloads are permitted")
    with urllib.request.urlopen(url, timeout=120) as response:
        if not response.url.startswith("https://"):
            raise ValueError("Refusing an insecure redirect")
        data = response.read()
    if dest:
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)
    return data


def json_url(url):
    data = fetch(url)
    if data.startswith(b"\x1f\x8b"):
        data = gzip.decompress(data)
    return json.loads(data)


def verified_download(url, path, algorithm, expected, encoding="hex"):
    if not path.exists():
        fetch(url, path)
    actual = hashlib.new(algorithm, path.read_bytes()).digest()
    wanted = base64.b64decode(expected) if encoding == "base64" else bytes.fromhex(expected)
    if actual != wanted:
        raise RuntimeError("Checksum mismatch; refusing artifact: " + str(path))
    return {"filename": path.name, "url": url, "verification": algorithm,
            "published_digest": expected, "digest_encoding": encoding,
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def safe_extract(zf, target, prefix=""):
    for info in zf.infolist():
        if not info.filename.startswith(prefix):
            continue
        rel = info.filename[len(prefix):]
        if not rel or info.is_dir():
            continue
        parts = Path(rel).parts
        if ".." in parts or Path(rel).is_absolute() or ":" in rel:
            raise ValueError("Unsafe archive member: " + rel)
        dest = target.joinpath(*parts)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(zf.read(info))


def runtime(arch, cache, target):
    package = "python" if arch == "x64" else "pythonx86"
    registration_url = "https://api.nuget.org/v3/registration5-gz-semver2/{}/{version}.json".format(
        package, version=PYTHON_VERSION)
    registration = json_url(registration_url)
    catalog_url = registration["catalogEntry"]
    catalog = json_url(catalog_url)
    if (catalog["authors"] != "Python Software Foundation"
            or catalog["projectUrl"].rstrip("/") != "https://www.python.org"
            or catalog["packageHashAlgorithm"].upper() != "SHA512"
            or catalog["version"] != PYTHON_VERSION):
        raise RuntimeError("Unexpected CPython publisher or package metadata")
    archive = cache / "{}.{}.nupkg".format(package, PYTHON_VERSION)
    evidence = verified_download(registration["packageContent"], archive,
                                 "sha512", catalog["packageHash"], "base64")
    evidence["metadata_url"] = catalog_url
    evidence["publisher"] = catalog["authors"]
    with zipfile.ZipFile(archive) as zf:
        nuspec = zf.read(package + ".nuspec").decode("utf-8-sig")
        if "Python Software Foundation" not in nuspec or "https://github.com/Python/CPython.git" not in nuspec:
            raise RuntimeError("Unexpected Python NuGet nuspec")
        if ".signature.p7s" not in zf.namelist():
            raise RuntimeError("NuGet repository signature is missing")
        safe_extract(zf, target, "tools/")
    # NuGet includes build-only pip/setuptools launchers for *both* bitnesses.
    # They are not application dependencies; omit them from the end-user runtime.
    for name in ("pip", "pip-21.1.1.dist-info", "setuptools", "setuptools-56.0.0.dist-info",
                 "pkg_resources", "_distutils_hack"):
        shutil.rmtree(target / "Lib/site-packages" / name, ignore_errors=True)
    pth = target / "Lib/site-packages/distutils-precedence.pth"
    if pth.exists():
        pth.unlink()
    evidence["repository_signature"] = "present; authoritative SHA512 verified; CMS not independently validated by this builder"
    return evidence


def pins():
    return [line.strip().split("==") for line in
            (ROOT / "scripts/windows-requirements.txt").read_text().splitlines()
            if line.strip() and not line.startswith("#")]


def wheel_matches(filename, platform):
    # Pure-Python wheels, CPython 3.8 wheels, and stable ABI wheels built for
    # CPython <=3.8. We never select Linux, source, newer CPython or wrong bitness.
    py, abi, plat = filename[:-4].rsplit("-", 3)[1:]
    if plat == "any":
        return abi == "none" and bool(set(py.split(".")) & {"py3", "py2"})
    if plat != platform:
        return False
    if "cp38" in py.split(".") and abi in {"cp38", "none"}:
        return True
    return abi == "abi3" and py in {"cp32", "cp33", "cp34", "cp35", "cp36", "cp37", "cp38"}


def wheels(arch, cache, target):
    platform = "win_amd64" if arch == "x64" else "win32"
    evidence = []
    for name, version in pins():
        metadata_url = "https://pypi.org/pypi/{}/{}/json".format(name, version)
        metadata = json_url(metadata_url)
        matches = [entry for entry in metadata["urls"]
                   if entry["packagetype"] == "bdist_wheel"
                   and not entry.get("yanked")
                   and wheel_matches(entry["filename"], platform)]
        if len(matches) != 1:
            raise RuntimeError("Expected one wheel for {} {} {}: {}".format(
                name, version, platform, [m["filename"] for m in matches]))
        entry = matches[0]
        path = cache / entry["filename"]
        record = verified_download(entry["url"], path, "sha256", entry["digests"]["sha256"])
        record.update({"metadata_url": metadata_url, "package": name, "version": version})
        with zipfile.ZipFile(path) as zf:
            safe_extract(zf, target)
        evidence.append(record)
        print("Verified {} {} ({})".format(name, version, arch), flush=True)
    trim_qt(target)
    # Wheels may contain precompiled support bytecode for a different Python
    # minor version (for example cpython-36). Python 3.8 can compile the
    # retained sources itself; omit these generated files from the portable
    # runtime so the bundle contains no stale or opaque bytecode.
    for bytecode in target.rglob("*.pyc"):
        bytecode.unlink()
    return evidence


def trim_qt(site_packages):
    """Ship only the LGPL Qt modules used by this application.

    Retain original license metadata and dynamic linking. In particular do not
    accidentally redistribute unused GPL-only Charts/DataVisualization modules.
    """
    package = site_packages / "PySide2"
    # The application imports these four Python bindings. QtQml and QtNetwork
    # are retained only because pyside2.abi3.dll/Qt5Qml.dll link to them;
    # they are not exposed as optional application modules.
    modules = {"QtCore", "QtGui", "QtWidgets", "QtSvg"}
    libraries = {"Qt5Core.dll", "Qt5Gui.dll", "Qt5Widgets.dll", "Qt5Svg.dll",
                 "Qt5Qml.dll", "Qt5Network.dll",  # libpyside's link-time dependencies
                 "pyside2.abi3.dll", "libEGL.dll", "libGLESv2.dll",
                 "d3dcompiler_47.dll", "opengl32sw.dll"}
    for file in package.iterdir():
        if not file.is_file():
            continue
        keep = (file.suffix in {".py", ".typed"} or file.name == "qt.conf"
                or file.name in libraries
                or file.stem in modules and file.suffix in {".pyd", ".pyi"}
                or file.suffix == ".dll" and file.name.startswith(("msvcp140", "vcruntime140", "concrt140")))
        if not keep:
            file.unlink()
    for directory in package.iterdir():
        if not directory.is_dir() or directory.name in {"support", "plugins"}:
            continue
        shutil.rmtree(directory)
    plugin_dirs = {"platforms", "styles", "imageformats", "iconengines"}
    for directory in (package / "plugins").iterdir():
        if directory.is_dir() and directory.name not in plugin_dirs:
            shutil.rmtree(directory)
    allowed_plugins = {
        "platforms": {"qwindows.dll", "qoffscreen.dll", "qminimal.dll"},
        "styles": {"qwindowsvistastyle.dll"},
        "imageformats": {"qgif.dll", "qicns.dll", "qico.dll", "qjpeg.dll", "qsvg.dll",
                         "qtga.dll", "qtiff.dll", "qwbmp.dll", "qwebp.dll"},
        "iconengines": {"qsvgicon.dll"},
    }
    for folder, names in allowed_plugins.items():
        for plugin in (package / "plugins" / folder).iterdir():
            if plugin.is_file() and plugin.name not in names:
                plugin.unlink()
    # Both upstream x64 wheels include a misplaced 32-bit ucrtbase.dll. Rely on
    # the OS UCRT, which Python itself also requires, for both architectures.
    for folder in (package, site_packages / "shiboken2"):
        (folder / "ucrtbase.dll").unlink(missing_ok=True)
    # The wheel also carries vccorlib140.dll for optional C++/WinRT support.
    # No retained binding imports it; leaving it would add WinRT API-set
    # dependencies which are unnecessary for this desktop application.
    (site_packages / "shiboken2" / "vccorlib140.dll").unlink(missing_ok=True)


def pe_machine(path):
    data = path.read_bytes()
    if data[:2] != b"MZ":
        raise ValueError("Not a Windows PE file: " + str(path))
    offset = struct.unpack_from("<I", data, 0x3C)[0]
    if data[offset:offset+4] != b"PE\0\0":
        raise ValueError("Invalid Windows PE file: " + str(path))
    return struct.unpack_from("<H", data, offset+4)[0]


def pe_imports(path):
    """Read normal and delay-load DLL imports without executing a PE file."""
    data = path.read_bytes()
    pe = struct.unpack_from("<I", data, 0x3C)[0]
    sections, optional_size = struct.unpack_from("<H12xH", data, pe + 6)
    optional = pe + 24
    is64 = struct.unpack_from("<H", data, optional)[0] == 0x20B
    directory = optional + (112 if is64 else 96)
    section_table = optional + optional_size
    maps = []
    for index in range(sections):
        vs, va, size, offset = struct.unpack_from("<IIII", data, section_table + index*40 + 8)
        maps.append((va, max(vs, size), offset))
    def rva_offset(rva):
        for va, size, offset in maps:
            if va <= rva < va + size:
                return offset + rva - va
        if rva < len(data):
            return rva
        raise ValueError("Invalid PE RVA in " + str(path))
    def cstring(rva):
        offset = rva_offset(rva)
        return data[offset:data.index(b"\0", offset)].decode("ascii").lower()
    imports = set()
    for index, stride, name_offset in ((1, 20, 12), (13, 32, 4)):
        rva, size = struct.unpack_from("<II", data, directory + index*8)
        if not rva:
            continue
        offset = rva_offset(rva)
        for entry in range(offset, offset+size, stride):
            if not any(data[entry:entry+stride]):
                break
            name = struct.unpack_from("<I", data, entry + name_offset)[0]
            if name:
                imports.add(cstring(name))
    return sorted(imports)


def validate_bundle(bundle, arch):
    machine = 0x8664 if arch == "x64" else 0x14C
    required = ["runtime/python.exe", "runtime/pythonw.exe", "runtime/python38.dll",
                "runtime/vcruntime140.dll", "runtime/Lib/site-packages/PySide2/Qt5Core.dll",
                "runtime/Lib/site-packages/PySide2/plugins/platforms/qwindows.dll"]
    for name in required:
        if pe_machine(bundle / name) != machine:
            raise RuntimeError("Wrong PE bitness: " + name)
    binaries = []
    for file in (bundle / "runtime").rglob("*"):
        if file.is_file() and file.suffix.lower() in {".exe", ".dll", ".pyd"}:
            if pe_machine(file) != machine:
                raise RuntimeError("Mixed Windows binary architectures: " + str(file))
            binaries.append(file)
    bundled_names = {f.name.lower() for f in binaries}
    system = {"kernel32.dll", "user32.dll", "advapi32.dll", "gdi32.dll", "shell32.dll",
              "ole32.dll", "oleaut32.dll", "comdlg32.dll", "comctl32.dll", "ws2_32.dll",
              "winmm.dll", "winspool.drv", "version.dll", "imm32.dll", "uxtheme.dll",
              "dwmapi.dll", "d3d9.dll", "d3d11.dll", "dxgi.dll", "dxguid.dll", "opengl32.dll",
              "shlwapi.dll", "msvcrt.dll", "ucrtbase.dll", "ntdll.dll", "rpcrt4.dll",
              "crypt32.dll", "bcrypt.dll", "bcryptprimitives.dll", "secur32.dll", "sspicli.dll",
              "userenv.dll", "wtsapi32.dll", "netapi32.dll", "iphlpapi.dll", "dnsapi.dll",
              "mpr.dll", "normaliz.dll", "psapi.dll", "powrprof.dll", "winhttp.dll",
              "wininet.dll", "setupapi.dll", "cfgmgr32.dll", "dwrite.dll", "d2d1.dll",
              "usp10.dll", "msimg32.dll", "propsys.dll", "avrt.dll", "synchronization.dll",
              "cabinet.dll", "msi.dll", "imagehlp.dll"}
    imported_names = set()
    unresolved = []
    for binary in binaries:
        for dependency in pe_imports(binary):
            imported_names.add(dependency)
            if dependency in bundled_names or dependency in system or dependency.startswith(("api-ms-win-", "ext-ms-win-")):
                continue
            unresolved.append("{} required by {}".format(dependency, binary.relative_to(bundle)))
    if unresolved:
        raise RuntimeError("Missing or unclassified PE imports: " + "; ".join(unresolved))
    return {"pe_machine": hex(machine), "required_binaries": required,
            "binary_count": len(binaries), "static_dll_imports": sorted(imported_names),
            "qt_modules": ["QtCore", "QtGui", "QtWidgets", "QtSvg"],
            "qt_link_dependencies": ["QtQml", "QtNetwork"],
            "windows_execution_test": "not performed by this Linux build"}


def copy_app(bundle):
    # Explicit allowlist excludes uploaded databases/logs, secrets and local venv.
    for name in ("tvra", "samples", "docs", "tests", "scripts"):
        source = ROOT / name
        if source.exists():
            shutil.copytree(source, bundle / name, dirs_exist_ok=True,
                            ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.db", "*.log", ".venv"))
    for name in ("README.md", "LICENSE", "THIRD_PARTY_NOTICES.md", "requirements.txt", "pyproject.toml"):
        if (ROOT / name).exists():
            shutil.copy2(ROOT / name, bundle / name)
    (bundle / "launcher.py").write_text(
        "from pathlib import Path\nimport os, runpy, sys\n"
        "base = Path(__file__).resolve().parent\n"
        "sys.path.insert(0, str(base))\n"
        "os.chdir(str(base))\n"
        "runpy.run_module('tvra', run_name='__main__')\n", encoding="utf-8")
    (bundle / "Start-TVRA.bat").write_bytes((
        '@echo off\r\nsetlocal\r\ncd /d "%~dp0"\r\n'
        '"%~dp0runtime\\pythonw.exe" -E -s -B "%~dp0launcher.py" %*\r\n'
        'if errorlevel 1 (\r\n echo Startup failed. Run Diagnose-TVRA.bat for details.\r\n pause\r\n)\r\n'
    ).encode("ascii"))
    (bundle / "Diagnose-TVRA.bat").write_bytes((
        '@echo off\r\nsetlocal\r\ncd /d "%~dp0"\r\n'
        '"%~dp0runtime\\python.exe" -E -s -B "%~dp0scripts\\windows_smoke.py" %*\r\n'
        'echo.\r\n echo If this check failed, copy the output for support.\r\n pause\r\n'
    ).encode("ascii"))
    shutil.copy2(ROOT / "docs/WINDOWS.md", bundle / "WINDOWS-README.md")


def archive_bundle(bundle, output):
    path = output / (bundle.name + ".zip")
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for file in sorted(bundle.rglob("*")):
            if file.is_file():
                zf.write(file, str(Path(bundle.name) / file.relative_to(bundle)))
    return path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--arch", choices=("x86", "x64", "both"), default="both")
    parser.add_argument("--output", type=Path, default=ROOT.parent / "artifacts")
    parser.add_argument("--cache", type=Path, default=ROOT.parent / "windows-build-cache")
    parser.add_argument("--prepare-only", action="store_true", help="Download/extract runtime; do not capture unfinished application source")
    parser.add_argument("--makensis", help="Optional path to NSIS makensis to compile real installers")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    args.cache.mkdir(parents=True, exist_ok=True)
    architectures = ("x86", "x64") if args.arch == "both" else (args.arch,)
    for arch in architectures:
        bundle = args.output / ("TVRA-{}-windows-{}".format(VERSION, arch))
        bundle.mkdir(parents=True, exist_ok=True)
        runtime_dir = bundle / "runtime"
        if runtime_dir.exists():
            shutil.rmtree(runtime_dir)
        provenance = [runtime(arch, args.cache, runtime_dir)]
        provenance += wheels(arch, args.cache, runtime_dir / "Lib/site-packages")
        validation = validate_bundle(bundle, arch)
        (bundle / "BUILD-MANIFEST.json").write_text(json.dumps({
            "app_version": VERSION, "architecture": arch, "python_version": PYTHON_VERSION,
            "source_of_runtime": "CPython official Python Software Foundation NuGet package",
            "artifacts": provenance, "validation": validation,
        }, ensure_ascii=False, indent=2), encoding="utf-8")
        print("Runtime ready: " + str(bundle), flush=True)
        if args.prepare_only:
            continue
        copy_app(bundle)
        archive = archive_bundle(bundle, args.output)
        print("Portable ZIP: " + str(archive), flush=True)
        if args.makensis:
            installer = args.output / (bundle.name + "-setup.exe")
            subprocess.run([args.makensis, "-DARCH=" + arch,
                            "-DBUNDLE_DIR=" + str(bundle.resolve()),
                            "-DOUTPUT_FILE=" + str(installer.resolve()),
                            str(ROOT / "scripts/windows_installer.nsi")], check=True)
            print("Installer: " + str(installer), flush=True)


if __name__ == "__main__":
    main()
