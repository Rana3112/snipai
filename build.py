"""Build script for SnipAI desktop client.

Produces a single SnipAI.exe via PyInstaller.

Usage:
    python build.py
"""
import os
import sys
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).parent
BUILD_DIR = ROOT / "build"
DIST_DIR = ROOT / "dist"
ENTRY = ROOT / "snipai" / "__main__.py"
APP_NAME = "SnipAI"


def clean():
    """Remove previous build artifacts."""
    for d in [BUILD_DIR, DIST_DIR]:
        if d.exists():
            print(f"Cleaning {d}...")
            shutil.rmtree(d, ignore_errors=True)
    for spec in ROOT.glob("*.spec"):
        spec.unlink()


def build():
    """Run PyInstaller."""
    clean()

    # Build command
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--name", APP_NAME,
        "--onefile",         # single .exe
        "--windowed",        # no console window
        "--noconfirm",
        "--clean",
        # Hidden imports for things PyInstaller may miss
        "--hidden-import", "openai",
        "--hidden-import", "anthropic",
        "--hidden-import", "google.genai",
        "--hidden-import", "httpx",
        "--hidden-import", "PIL._tkinter_finder",
        "--collect-all", "PySide6",
        str(ENTRY),
    ]
    print(f"Building {APP_NAME}.exe...")
    print(" ".join(cmd))
    result = subprocess.run(cmd, cwd=str(ROOT))
    if result.returncode != 0:
        print("Build failed!")
        sys.exit(1)

    exe_path = DIST_DIR / f"{APP_NAME}.exe"
    if not exe_path.exists():
        print(f"Build did not produce {exe_path}")
        sys.exit(1)

    size_mb = exe_path.stat().st_size / (1024 * 1024)
    print(f"\n[OK] Built {exe_path} ({size_mb:.1f} MB)")
    return exe_path


if __name__ == "__main__":
    build()
