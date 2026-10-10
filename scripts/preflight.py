#!/usr/bin/env python3
"""Phase 0 preflight. Run this ON THE PHONE after rsyncing the code over:

    python3 ~/vault-app/scripts/preflight.py

Checks the things the brief requires before anything else proceeds: python
version, sqlite FTS5, pdftotext/pdftoppm/tesseract + languages, llama-server
health, free RAM, free disk. Installs missing Termux packages where it can.
Exits non-zero if anything fails.
"""
from __future__ import annotations

import os
import shutil
import socket
import subprocess
import sys
import urllib.error
import urllib.request

MIN_PYTHON = (3, 11)  # tomllib needs 3.11+
MIN_FREE_DISK_GB = 1.0
MIN_FREE_RAM_MB = 200

PKG_FOR_BINARY = {
    "pdftotext": "poppler",
    "pdftoppm": "poppler",
    "pdfinfo": "poppler",
    "tesseract": "tesseract",
}


def is_termux() -> bool:
    return "com.termux" in os.environ.get("PREFIX", "")


def ensure_packages_installed(binaries: list[str]) -> None:
    if not is_termux():
        return
    missing_pkgs = sorted(
        {PKG_FOR_BINARY[b] for b in binaries if b in PKG_FOR_BINARY and shutil.which(b) is None}
    )
    if not missing_pkgs:
        return
    print(f"installing missing termux packages: {', '.join(missing_pkgs)}")
    subprocess.run(["pkg", "install", "-y", *missing_pkgs], check=False)


def check_python_version():
    ok = sys.version_info >= MIN_PYTHON
    detail = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
    if not ok:
        detail += f" (need >= {'.'.join(map(str, MIN_PYTHON))}, for stdlib tomllib)"
    return ok, detail


def check_sqlite_fts5():
    import sqlite3

    conn = sqlite3.connect(":memory:")
    try:
        conn.execute("CREATE VIRTUAL TABLE t USING fts5(x)")
        return True, f"sqlite3 {sqlite3.sqlite_version}"
    except sqlite3.OperationalError as e:
        return False, f"sqlite3 {sqlite3.sqlite_version} lacks FTS5: {e}"
    finally:
        conn.close()


def check_binary(name: str):
    path = shutil.which(name)
    return path is not None, path or "not found"


def check_tesseract_langs():
    if shutil.which("tesseract") is None:
        return False, "tesseract not installed"
    proc = subprocess.run(
        ["tesseract", "--list-langs"], capture_output=True, text=True, timeout=15
    )
    langs = set(proc.stdout.splitlines()[1:]) if proc.returncode == 0 else set()
    wanted = {"eng", "hin", "mar"}
    have = sorted(langs & wanted)
    missing = sorted(wanted - langs)
    ok = "eng" in langs
    detail = f"have={have or 'none'} missing={missing or 'none'}"
    return ok, detail


def check_llama_health(url: str = "http://127.0.0.1:8080/health", timeout: float = 5.0):
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            return resp.status == 200, f"HTTP {resp.status} from {url}"
    except (urllib.error.URLError, socket.timeout) as e:
        return False, f"unreachable at {url}: {type(e).__name__}"


def check_free_ram():
    try:
        with open("/proc/meminfo") as f:
            meminfo = dict(
                (parts[0].rstrip(":"), parts[1]) for parts in (l.split() for l in f if l.strip())
            )
        available_kb = int(meminfo.get("MemAvailable", "0"))
        available_mb = available_kb / 1024
        return available_mb >= MIN_FREE_RAM_MB, f"{available_mb:.0f} MB available"
    except OSError as e:
        return False, f"could not read /proc/meminfo: {e}"


def check_free_disk():
    target = os.path.expanduser("~")
    usage = shutil.disk_usage(target)
    free_gb = usage.free / (1024**3)
    return free_gb >= MIN_FREE_DISK_GB, f"{free_gb:.1f} GB free on {target}"


CHECKS = [
    ("python_version", check_python_version),
    ("sqlite_fts5", check_sqlite_fts5),
    ("pdftotext", lambda: check_binary("pdftotext")),
    ("pdftoppm", lambda: check_binary("pdftoppm")),
    ("pdfinfo", lambda: check_binary("pdfinfo")),
    ("tesseract", lambda: check_binary("tesseract")),
    ("tesseract_langs", check_tesseract_langs),
    ("llama_server_health", check_llama_health),
    ("free_ram", check_free_ram),
    ("free_disk", check_free_disk),
]


def main() -> int:
    ensure_packages_installed(["pdftotext", "pdftoppm", "pdfinfo", "tesseract"])

    results = []
    for name, fn in CHECKS:
        try:
            ok, detail = fn()
        except Exception as e:
            ok, detail = False, f"{type(e).__name__}: {e}"
        results.append((name, ok, detail))

    name_w = max(len(n) for n, _, _ in results)
    print(f"{'CHECK'.ljust(name_w)}  RESULT  DETAIL")
    for name, ok, detail in results:
        print(f"{name.ljust(name_w)}  {'PASS' if ok else 'FAIL'}    {detail}")

    all_ok = all(ok for _, ok, _ in results)
    print()
    print("ALL CHECKS PASSED" if all_ok else "SOME CHECKS FAILED - fix before proceeding")
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
