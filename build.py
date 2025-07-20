import argparse
import os
import re
import shutil
import subprocess
import sys
import tomllib


def get_app_name():
    """Get app name from pyproject.toml"""
    if os.path.exists("pyproject.toml"):
        with open("pyproject.toml", "rb") as f:
            data = tomllib.load(f)
        if "project" in data and "version" in data["project"]:
            return str(data["project"]["name"])
        print("App name not specified in pyproject.toml")
        sys.exit()
    print("pyproject.toml file not found")
    sys.exit()


def get_version_number():
    """Get version number from pyproject.toml"""
    if os.path.exists("pyproject.toml"):
        with open("pyproject.toml", "rb") as f:
            data = tomllib.load(f)
        if "project" in data and "version" in data["project"]:
            return str(data["project"]["version"])
        print("Version not specified in pyproject.toml")
        sys.exit()
    print("pyproject.toml file not found")
    sys.exit()


def patch_soundcard():
    """
    Search for soundcard/mediafoundation.py in .venv
    Prepend "if _ole32: " to "_ole32.CoUninitialize()" line while respecting indentation
    """
    if not os.path.exists(".venv"):
        print(".venv dir not found")
        return

    for root, dirs, files in os.walk(".venv"):
        if "soundcard" in dirs:
            soundcard_dir = os.path.join(root, "soundcard")
            path = os.path.join(soundcard_dir, "mediafoundation.py")
            if os.path.isfile(path):
                break
    else:
        print("Soundcard library not found")
        return

    with open(path, "r", encoding="utf-8") as f:
        lines = f.readlines()

    pattern = re.compile(r"^(\s*)_ole32\.CoUninitialize\(\)")
    changed = False
    for num, line in enumerate(lines):
        match = re.match(pattern, line)
        if match:
            indent = match.group(1)
            lines[num] = f"{indent}if _ole32: _ole32.CoUninitialize()\n"
            changed = True
            break

    if changed:
        with open(path, "w", encoding="utf-8") as f:
            f.writelines(lines)
        print(f"Patched file: {path}")
    else:
        print(f"Nothing to patch in file {path}")


def build_cython(clang):
    """Build cython extensions"""
    if clang:
        os.environ["CC"] = "clang"
        os.environ["CXX"] = "clang++"

    subprocess.run(["uv", "run", "python", "setup.py", "build_ext", "--inplace"], check=True)

    os.remove("spectrum_cython.c")
    shutil.rmtree("build")


def build_with_pyinstaller(onedir):
    """Build with pyinstaller"""
    pkgname = get_app_name()
    mode = "--onedir" if onedir else "--onefile"
    hidden_imports = ["--hidden-import=pyfftw"]
    package_data = []

    # platform-specific
    if sys.platform == "linux":
        options = []
    elif sys.platform == "win32":
        options = ["--console"]
    elif sys.platform == "darwin":
        options = []


    # prepare command and run it
    cmd = [
        "uv", "run", "python", "-m", "PyInstaller",
        mode,
        *hidden_imports,
        *package_data,
        *options,
        "--noconfirm",
        "--clean",
        f"--name={pkgname}",
        "main.py",
    ]
    cmd = [arg for arg in cmd if arg != ""]
    try:
        subprocess.run(cmd, check=True)
    except subprocess.CalledProcessError as e:
        print(f"Build failed: {e}")
        sys.exit(e.returncode)

    # cleanup
    try:
        os.remove(f"{pkgname}.spec")
        shutil.rmtree("build")
    except FileNotFoundError:
        pass


def build_with_nuitka(onedir, clang):
    """Build with nuitka"""
    pkgname = get_app_name()
    mode = "--standalone" if onedir else "--onefile"
    clang = "--clang" if clang else ""
    python_flags = ["--python-flag=-OO"]
    hidden_imports = ["--include-module=pyfftw"]
    package_data = [
        "--include-package-data=soundcard",
    ]

    # platform-specific
    if sys.platform == "linux":
        options = []
    elif sys.platform == "win32":
        patch_soundcard()
        options = ["--assume-yes-for-downloads"]
    elif sys.platform == "darwin":
        options = [
            f"--macos-app-name={get_app_name()}",
            f"--macos-app-version={get_version_number()}",
            '--macos-app-protected-resource="NSMicrophoneUsageDescription:Microphone access for recording voice message."',
        ]

    # prepare command and run it
    cmd = [
        "uv", "run", "python", "-m", "nuitka",
        mode,
        clang,
        *python_flags,
        *hidden_imports,
        *package_data,
        *options,
        "--lto=yes",
        "--remove-output",
        "--output-dir=dist",
        f"--output-filename={pkgname}",
        "main.py",
    ]
    cmd = [arg for arg in cmd if arg != ""]
    try:
        subprocess.run(cmd, check=True)
    except subprocess.CalledProcessError as e:
        print(f"Build failed: {e}")
        sys.exit(e.returncode)

    # cleanup
    try:
        os.remove(f"{pkgname}.spec")
        shutil.rmtree("build")
    except FileNotFoundError:
        pass


def parser():
    """Setup argument parser for CLI"""
    parser = argparse.ArgumentParser(
        prog="build.py",
        description="build script for spectroterm",
    )
    parser._positionals.title = "arguments"
    parser.add_argument(
        "--nuitka",
        action="store_true",
        help="build with nuitka, takes a long time, but more optimized executable",
    )
    parser.add_argument(
        "--clang",
        action="store_true",
        help="use clang when building with nuitka",
    )
    parser.add_argument(
        "--onedir",
        action="store_true",
        help="build into directory instead single executable",
    )
    parser.add_argument(
        "--nocython",
        action="store_true",
        help="build without compiling cython code",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = parser()
    if sys.platform not in ("linux", "win32", "darwin"):
        sys.exit(f"This platform is not supported: {sys.platform}")
    if not args.nocython:
        try:
            build_cython(args.clang)
        except Exception as e:
            print(f"Failed building cython extensions, error: {e}")
    if args.nuitka:
        build_with_nuitka(args.onedir, args.clang)
        sys.exit()
    else:
        build_with_pyinstaller(args.onedir)
        sys.exit()
