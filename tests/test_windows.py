"""On Windows (CI) the real thing: a Run entry in the real HKCU and a real scheduled task, switched off, on and
deleted; a real signature check. Everything is cleaned up even when a test fails. Skipped elsewhere."""
import os
import subprocess
import sys

import pytest

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="Windows only")

NAME = "Paragon PR7-AR CI test"


def test_a_real_run_entry():
    from pr7ar import entries, registry
    reg = registry.WinRegistry()
    key = entries.CV + "\\Run"
    reg.set("HKCU", key, NAME, f'"{sys.executable}" --version')
    try:
        es = entries.collect(reg, entries.Places.here())
        e = next(x for x in es if x.name == NAME)
        assert e.enabled and e.image.lower() == sys.executable.lower() and not e.missing
        entries.set_enabled(e, False, reg)
        assert reg.get("HKCU", key, NAME) is None and reg.get("HKCU", key + "\\" + registry.DISABLED, NAME)
        e2 = next(x for x in entries.collect(reg, entries.Places.here()) if x.name == NAME)
        assert not e2.enabled
        entries.set_enabled(e2, True, reg)
        assert reg.get("HKCU", key, NAME)
        entries.delete(e2, reg)
        assert reg.get("HKCU", key, NAME) is None
    finally:
        for where in (key, key + "\\" + registry.DISABLED):
            try:
                reg.delete_value("HKCU", where, NAME)
            except OSError:
                pass


def test_a_real_scheduled_task():
    from pr7ar import entries, registry, tasks
    path = "\\" + NAME
    r = subprocess.run(["schtasks.exe", "/create", "/tn", path, "/tr", "cmd.exe /c exit", "/sc", "once", "/st",
                        "23:59", "/f"], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    try:
        s = tasks.Scheduler()
        es = entries.collect(registry.WinRegistry(), entries.Places.here(), s)
        e = next(x for x in es if x.name == path)
        assert e.enabled and e.image.lower().endswith("cmd.exe")
        entries.set_enabled(e, False, registry.WinRegistry(), s)
        assert not next(t for t in s.list() if t.path == path).enabled
        entries.set_enabled(e, True, registry.WinRegistry(), s)
        assert next(t for t in s.list() if t.path == path).enabled
        entries.delete(e, registry.WinRegistry(), s)
        assert not any(t.path == path for t in s.list())
    finally:
        subprocess.run(["schtasks.exe", "/delete", "/tn", path, "/f"], capture_output=True)


def test_real_signatures(tmp_path):
    from pr7ar import signatures
    notepad = os.path.join(os.environ["SystemRoot"], "System32", "notepad.exe")
    unsigned = tmp_path / "unsigned.exe"
    unsigned.write_bytes(b"MZ" + b"\0" * 200)
    got = signatures.Checker(str(tmp_path / "cache.json")).check([notepad, str(unsigned)])
    assert got[notepad].verified is True and got[notepad].signer.startswith("Microsoft")
    assert got[str(unsigned)].verified is False
