import os
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["PARAGON_FAMILY_FILE"] = os.path.join(tempfile.mkdtemp(prefix="family-"), "finish")  # never the real choice
os.environ["PR7AR_DATA"] = tempfile.mkdtemp(prefix="pr7ar-data-")      # never the real data folder
os.environ["PR7AR_TRASH"] = tempfile.mkdtemp(prefix="pr7ar-trash-")    # never the real Recycle Bin

TASKS_XML = """<?xml version="1.0" encoding="UTF-16"?>
<Tasks>
<!-- \\Paragon\\PR7-IS Index -->
<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo><Date>2026-11-25T13:11:00</Date><Author>Studio</Author>
    <Description>Paragon PR7-IS file search</Description></RegistrationInfo>
  <Settings><Enabled>true</Enabled></Settings>
  <Actions Context="Author"><Exec><Command>C:\\Users\\Studio\\AppData\\Local\\Programs\\PR7-IS\\PR7-IS.exe</Command>
    <Arguments>--index-service</Arguments></Exec></Actions>
</Task>
<!-- \\Adobe Acrobat Update Task -->
<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo><Author>Adobe Systems Incorporated</Author></RegistrationInfo>
  <Settings><Enabled>false</Enabled></Settings>
  <Actions Context="Author"><Exec><Command>C:\\Program Files (x86)\\Common Files\\Adobe\\ARM\\1.0\\AdobeARM.exe</Command>
    </Exec></Actions>
</Task>
<!-- \\Microsoft\\Windows\\Defrag\\ScheduledDefrag -->
<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo><Author>Microsoft Corporation</Author></RegistrationInfo>
  <Actions Context="Author"><ComHandler><ClassId>{11111111-2222-3333-4444-555555555555}</ClassId></ComHandler>
    </Actions>
</Task>
</Tasks>
"""


@pytest.fixture
def world(tmp_path, monkeypatch):
    """A made-up Windows: a Windows folder with real files, Startup folders, an in-memory registry."""
    from pr7ar import entries, registry
    monkeypatch.setenv("PR7AR_TRASH", str(tmp_path / "trash"))
    win = tmp_path / "Windows"
    (win / "System32" / "drivers").mkdir(parents=True)
    for n in ("userinit.exe", "autochk.exe", "rundll32.exe", "SecurityHealthSystray.exe", "msv1_0.dll",
              "mspmon.dll", "ntprint.dll", "drivers/fancy.sys", "msacm32.dll", "svchost.exe", "wuaueng.dll"):
        (win / "System32" / n).write_bytes(b"MZ")
    apps = tmp_path / "Program Files" / "My App"
    apps.mkdir(parents=True)
    (apps / "app.exe").write_bytes(b"MZ")
    places = entries.Places(windir=str(win), startup_user=str(tmp_path / "Startup"),
                            startup_common=str(tmp_path / "StartUp (all)"), path=[],
                            env={"SystemRoot": str(win), "ProgramFiles": str(tmp_path / "Program Files")})
    os.makedirs(places.startup_user)
    os.makedirs(places.startup_common)
    reg = registry.MemRegistry()
    return places, reg, tmp_path


class FakeTasks:
    """schtasks.exe stand-in: recorded output for /query, every other command kept."""

    def __init__(self, xml=TASKS_XML, fail=None):
        self.xml, self.calls, self.fail = xml, [], fail

    def __call__(self, args):
        import subprocess
        self.calls.append(args)
        if args[:1] == ["/query"]:
            return subprocess.CompletedProcess(args, 0, self.xml, "")
        if self.fail:
            return subprocess.CompletedProcess(args, 1, "", self.fail)
        return subprocess.CompletedProcess(args, 0, "SUCCESS", "")


@pytest.fixture(scope="session")
def qapp(tmp_path_factory):
    from PySide6.QtCore import QSettings
    from PySide6.QtWidgets import QApplication
    QSettings.setDefaultFormat(QSettings.Format.IniFormat)           # never the real settings
    QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, str(tmp_path_factory.mktemp("settings")))
    app = QApplication.instance() or QApplication([])
    from pr7ar import theme
    theme.load_fonts()
    yield app
    app.clipboard().clear()


@pytest.fixture
def window(qapp, world):
    """The real window on the made-up Windows (reading inline), signatures from a stand-in checker."""
    from pr7ar import settings, signatures, tasks
    from pr7ar.main_window import MainWindow
    places, reg, tmp = world
    settings.set("hide_windows", True)                  # a test that unticked it doesn't carry over (it's saved)

    def fake(paths):
        return {p: signatures.Signature(True, "Microsoft Windows", True) if "Windows" in p else
                signatures.Signature(False, "") for p in paths}
    fake_tasks = FakeTasks()
    w = MainWindow(reg=reg, places=places, scheduler=tasks.Scheduler(fake_tasks),
                   checker=signatures.Checker(None, run=fake), sync=True)
    w.fake_tasks = fake_tasks
    ran, launched = [], []
    w.ran, w.launched = ran, launched
    w.answers.update({"say": lambda kind, text: None, "confirm": lambda t: True, "menu": True,
                      "run": ran.append, "launch": lambda app, args: launched.append((app, args)) or True})
    w.show()
    yield w
    w.close()
    from PySide6.QtCore import QCoreApplication, QEvent
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    del w
    import gc
    gc.collect()          # on the main thread now (PR7-U's lesson)
