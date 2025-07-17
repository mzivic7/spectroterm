import argparse
import os
import re
import shutil
import sys
import tomllib

import numpy as np
import pyfftw  # noqa
from Cython.Build import cythonize
from setuptools import Extension, setup


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
    """Build cython modules"""
    if clang:
        os.environ["CC"] = "clang"
        os.environ["CXX"] = "clang++"

    extra_compile_args = [
        "-O3",
        "-flto",
        "-ffast-math",
        "-fomit-frame-pointer",
        "-funroll-loops",
    ]

    extensions = [
        Extension(
            "spectrum_cython",
            ["spectrum_cython.pyx"],
            extra_compile_args=extra_compile_args,
            extra_link_args=["-flto"],
            include_dirs=[np.get_include()],
        ),
    ]

    setup(
        name="spectrum",
        ext_modules=cythonize(extensions, language_level=3),
        script_args=["build_ext", "--inplace"],
    )
    os.remove("spectrum_cython.c")
    shutil.rmtree("build")


def build_with_pyinstaller(onedir):
    """Build with pyinstaller"""
    if onedir:
        onedir = "--onedir"
    else:
        onedir = "--onefile"
    hidden_imports = "--hidden-import pyfftw"
    app_name = get_app_name()

    if sys.platform == "linux":
        command = f'uv run python -m PyInstaller {onedir} {hidden_imports} --collect-data=emoji --noconfirm --clean --name {app_name} "main.py"'
        os.system(command)
    elif sys.platform == "win32":
        command = f'uv run python -m PyInstaller {onedir} {hidden_imports} --collect-data=emoji --noconfirm --console --clean --name {app_name} "main.py"'
        os.system(command)
    elif sys.platform == "darwin":
        command = f'uv run python -m PyInstaller {onedir} {hidden_imports} --collect-data=emoji --noconfirm --console --clean --name {app_name} "main.py"'
        os.system(command)
    else:
        sys.exit(f"This platform is not supported: {sys.platform}")
    # cleanup
    try:
        os.remove(f"{app_name}.spec")
        shutil.rmtree("build")
    except FileNotFoundError:
        pass


def build_with_nuitka(onedir, clang):
    """Build with nuitka"""
    if onedir:
        onedir = "--standalone"
    else:
        onedir = "--onefile"

    if clang:
        clang = "--clang"
    else:
        clang = ""
    hidden_imports = "--include-module=pyfftw"
    include_package_data = "--include-package-data=soundcard"
    app_name = get_app_name()

    if sys.platform == "linux":
        command = f"uv run python -m nuitka {clang} {onedir} {hidden_imports} {include_package_data} --remove-output --output-dir=dist --output-filename={app_name} main.py"
        os.system(command)
    elif sys.platform == "win32":
        patch_soundcard()
        command = f"uv run python -m nuitka {clang} {onedir} {hidden_imports} {include_package_data} --remove-output --output-dir=dist --output-filename={app_name} --assume-yes-for-downloads main.py"
        os.system(command)
    elif sys.platform == "darwin":
        command = f"uv run python -m nuitka {clang} {onedir} {hidden_imports} {include_package_data} --remove-output --output-dir=dist --output-filename={app_name} --macos-app-name={app_name} --macos-app-version={get_version_number()} main.py"
        os.system(command)
    else:
        sys.exit(f"This platform is not supported: {sys.platform}")


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
    return parser.parse_args()


if __name__ == "__main__":
    args = parser()
    try:
        build_cython(args.clang)
    except Exception:
        pass
    if args.nuitka:
        build_with_nuitka(args.onedir, args.clang)
        sys.exit()
    else:
        build_with_pyinstaller(args.onedir)
        sys.exit()
