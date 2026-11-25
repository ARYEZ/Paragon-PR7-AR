"""Check a real install of PR7-AR-Setup.exe (CI, Windows): verify_install.py installed|uninstalled

`installed`: the files, the Start menu entry, the uninstall entry, and the installed exe's --selftest: the real
startup entries read (services and scheduled tasks among them, signatures checked), then a Run entry of its own added
to HKCU, switched off (Autoruns' AutorunsDisabled key), on, and deleted. `uninstalled`: all of it gone, and the
self-test's entry nowhere."""
import json
import os
import subprocess
import sys
import tempfile
import time
import winreg
from pathlib import Path

HKCU = winreg.HKEY_CURRENT_USER
APP = Path(os.environ["LOCALAPPDATA"]) / "Programs" / "PR7-AR"
SHORTCUT = Path(os.environ["APPDATA"]) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Paragon PR7-AR.lnk"
UNINSTALL = r"Software\Microsoft\Windows\CurrentVersion\Uninstall\{5DD7DA56-83DC-421E-8D0F-E7FB868B3860}_is1"
RUN = r"Software\Microsoft\Windows\CurrentVersion\Run"


def value(root, path, name=""):
    try:
        with winreg.OpenKey(root, path) as k:
            return winreg.QueryValueEx(k, name)[0]
    except OSError:
        return None


def check(ok, what, p):
    print(("ok    " if ok else "FAIL  ") + what)
    if not ok:
        p.append(what)


def installed():
    p = []
    exe = APP / "PR7-AR.exe"
    for f in (exe, APP / "unins000.exe", APP / "_internal" / "pr7ar" / "fonts" / "Inter-Regular.ttf"):
        check(f.is_file(), f"file {f}", p)
    check(SHORTCUT.is_file(), "Start menu shortcut", p)
    check(value(HKCU, UNINSTALL, "DisplayName") == "Paragon PR7-AR", "Installed apps entry", p)
    with tempfile.TemporaryDirectory() as d:
        out = Path(d) / "out.json"
        try:
            subprocess.run([str(exe), "--selftest", str(out)], timeout=600, check=False)
        except subprocess.TimeoutExpired:
            pass
        got = json.loads(out.read_text(encoding="utf-8")) if out.exists() else {}
        check(got.get("entries", 0) > 20 and got.get("services", 0) > 5 and got.get("tasks", 0) > 5
              and got.get("fonts") is True, f"the installed exe reads the real startup entries ({got})", p)
        check(got.get("verified", 0) > 5 and got.get("windows", 0) > 5, "signatures checked (Windows' own known)", p)
        check(got.get("found") is True and got.get("switched_off") is True and got.get("switched_on") is True
              and got.get("deleted") is True, "its own Run entry: found, switched off, on, deleted", p)
    check(value(HKCU, RUN, "Paragon PR7-AR self-test") is None, "nothing left behind in Run", p)
    return p


def uninstalled():
    deadline = time.time() + 60
    while True:
        p = []
        check(not (APP / "PR7-AR.exe").exists(), "program files removed", p)
        check(not SHORTCUT.exists(), "Start menu shortcut removed", p)
        check(value(HKCU, UNINSTALL, "DisplayName") is None, "Installed apps entry removed", p)
        if not p or time.time() > deadline:
            return p
        print("... waiting for the uninstaller to finish")
        time.sleep(3)


if __name__ == "__main__":
    problems = {"installed": installed, "uninstalled": uninstalled}[sys.argv[1]]()
    print("\nALL OK" if not problems else f"\n{len(problems)} problem(s)")
    sys.exit(1 if problems else 0)
