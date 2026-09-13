from pathlib import Path
import shutil
import subprocess

try:
    import winreg
except ImportError:  # Allows static checks on non-Windows systems.
    winreg = None


def _find_in_path():
    exe = shutil.which("7z")
    if exe:
        return exe

    try:
        result = subprocess.run(
            ["where.exe", "7z"],
            capture_output=True,
            text=True
        )

        if result.returncode == 0:
            path = result.stdout.strip().splitlines()[0]
            if Path(path).exists():
                return path
    except (OSError, subprocess.SubprocessError):
        pass

    return None


def _find_registry():

    if winreg is None:
        return None

    keys = [
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\7-Zip"),
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\7-Zip"),
        (winreg.HKEY_CURRENT_USER, r"SOFTWARE\7-Zip"),
    ]

    for root, key in keys:
        try:
            with winreg.OpenKey(root, key) as k:
                install, _ = winreg.QueryValueEx(k, "Path")
                exe = Path(install) / "7z.exe"

                if exe.exists():
                    return str(exe)

        except OSError:
            continue

    return None


def _find_common():

    candidates = [
        r"C:\Program Files\7-Zip\7z.exe",
        r"C:\Program Files (x86)\7-Zip\7z.exe"
    ]

    for p in candidates:
        if Path(p).exists():
            return p

    return None


def find_7z():

    for finder in (
        _find_in_path,
        _find_registry,
        _find_common
    ):

        path = finder()

        if path:
            return path

    return None
