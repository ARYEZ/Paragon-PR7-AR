"""Screenshots of the real PR7-AR window on a made-up Windows (an in-memory registry, generated files, recorded
scheduled tasks, stand-in signatures: nothing of the user's): QT_SCALE_FACTOR=2 python tools/screenshots.py OUT_DIR

everything.png (OBSIDIAN), tasks.png (AURORA), compare.png (a saved snapshot compared)."""
import os
import subprocess
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["PR7AR_DATA"] = tempfile.mkdtemp()
_family = Path(tempfile.mkdtemp()) / "finish"
_family.write_text("obsidian")
os.environ["PARAGON_FAMILY_FILE"] = str(_family)
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tests"))

from PySide6.QtCore import QSettings  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

QSettings.setDefaultFormat(QSettings.Format.IniFormat)
QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, tempfile.mkdtemp())

from pr7ar import entries, lnk, registry, signatures, tasks, theme  # noqa: E402
from pr7ar.entries import CV  # noqa: E402
from pr7ar.main_window import MainWindow  # noqa: E402
from pr7ar.registry import DISABLED, DWORD, EXPAND_SZ  # noqa: E402

out = Path(sys.argv[1] if len(sys.argv) > 1 else "docs/screenshots")
out.mkdir(parents=True, exist_ok=True)
app = QApplication([])
theme.load_fonts()
root = Path(tempfile.mkdtemp())


def make(rel, size=200_000):
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(b"MZ" + b"\0" * size)
    return str(p)


win = root / "Windows"
places = entries.Places(windir=str(win), startup_user=str(root / "Startup"), startup_common=str(root / "StartUp2"),
                        env={"SystemRoot": str(win)})
os.makedirs(places.startup_user)
os.makedirs(places.startup_common)
reg = registry.MemRegistry()
progs = {"Discord": make("Users/Studio/AppData/Local/Discord/Update.exe"),
         "OneDrive": make("Program Files/Microsoft OneDrive/OneDrive.exe"),
         "Paragon PR7-CB": make("Users/Studio/AppData/Local/Programs/PR7-CB/PR7-CB.exe"),
         "Spotify": make("Users/Studio/AppData/Roaming/Spotify/Spotify.exe")}
for name, p in progs.items():
    reg.set("HKCU", CV + "\\Run", name, f'"{p}" --background')
reg.move_value("HKCU", CV + "\\Run", CV + "\\Run\\" + DISABLED, "Spotify")
reg.set("HKLM", CV + "\\Run", "SecurityHealth", "%SystemRoot%\\System32\\SecurityHealthSystray.exe", EXPAND_SZ)
make("Windows/System32/SecurityHealthSystray.exe")
reg.set("HKLM", CV + "\\Run", "RtkAudUService", f'"{make("Windows/System32/RtkAudUService64.exe")}" -background')
reg.set("HKLM", CV + "\\Run", "UpdaterHelper", f'"{make("ProgramData/UpdHelper/upd_helper.exe")}" /silent /startup')
with open(os.path.join(places.startup_user, "Paragon PR7-Q.lnk"), "wb") as f:
    f.write(lnk.make_lnk(make("Users/Studio/AppData/Local/Programs/PR7-Q/PR7-Q.exe")))
with open(os.path.join(places.startup_user, "OldTool.lnk"), "wb") as f:
    f.write(lnk.make_lnk(str(root / "Tools" / "OldTool" / "oldtool.exe")))
svc = r"SYSTEM\CurrentControlSet\Services"
for name, image, display in (("Blackmagic Desktop Video", make("Program Files/Blackmagic Design/DesktopVideoHelper.exe"),
                              "Blackmagic Design Desktop Video Helper"),
                             ("NVDisplay.ContainerLocalSystem", make("Windows/System32/NVDisplay.Container.exe"),
                              "NVIDIA Display Container LS")):
    reg.set("HKLM", f"{svc}\\{name}", "Type", 0x10, DWORD)
    reg.set("HKLM", f"{svc}\\{name}", "Start", 2, DWORD)
    reg.set("HKLM", f"{svc}\\{name}", "ImagePath", f'"{image}"')
    reg.set("HKLM", f"{svc}\\{name}", "DisplayName", display)
pr7is = make("Users/Studio/AppData/Local/Programs/PR7-IS/PR7-IS.exe")
xml = f"""<Tasks>
<!-- \\Paragon\\PR7-IS Index -->
<Task xmlns="x"><RegistrationInfo><Date>2026-11-25T13:11:00</Date><Description>Paragon PR7-IS file search</Description>
</RegistrationInfo><Actions><Exec><Command>{pr7is}</Command><Arguments>--index-service</Arguments></Exec></Actions></Task>
<!-- \\GoogleUpdateTaskMachineUA -->
<Task xmlns="x"><RegistrationInfo><Date>2026-09-30T17:05:00</Date><Description>Google Installer</Description>
</RegistrationInfo><Actions><Exec><Command>{make("Program Files (x86)/Google/Update/GoogleUpdate.exe")}</Command>
<Arguments>/ua /installsource scheduler</Arguments></Exec></Actions></Task>
<!-- \\Adobe Acrobat Update Task -->
<Task xmlns="x"><Settings><Enabled>false</Enabled></Settings><Actions><Exec>
<Command>{make("Program Files (x86)/Common Files/Adobe/ARM/AdobeARM.exe")}</Command></Exec></Actions></Task>
</Tasks>"""
signers = {"Discord": "Discord Inc.", "OneDrive": "Microsoft Corporation", "Spotify": "Spotify AB",
           "Google": "Google LLC", "Adobe": "Adobe Inc.", "Blackmagic": "Blackmagic Design Pty. Ltd.",
           "NVDisplay": "NVIDIA Corporation", "RtkAud": "Realtek Semiconductor Corp.",
           "SecurityHealth": "Microsoft Windows"}


def fake(paths):
    got = {}
    for p in paths:
        who = next((v for k, v in signers.items() if k in p), "")
        got[p] = signatures.Signature(bool(who), who, who == "Microsoft Windows")
    return got


def run_tasks(args):
    return subprocess.CompletedProcess(args, 0, xml if args[:1] == ["/query"] else "SUCCESS", "")


w = MainWindow(reg=reg, places=places, scheduler=tasks.Scheduler(run_tasks), checker=signatures.Checker(None, run=fake),
               sync=True)
w.answers.update({"say": lambda k, t: None, "confirm": lambda t: True})
w.resize(1320, 840)
w.show()
w.refresh()
w.select("UpdaterHelper")
app.processEvents()
w.grab().save(str(out / "everything.png"))
snap = root / "before-update.pr7ar"
entries.save_snapshot(w.all, str(snap))
w.set_finish("aurora")
w.tabs.setCurrentIndex(entries.TABS.index("Scheduled Tasks"))
w.select("\\Paragon\\PR7-IS Index")
app.processEvents()
w.grab().save(str(out / "tasks.png"))
w.set_finish("obsidian")
w.tabs.setCurrentIndex(0)
reg.set("HKLM", f"{svc}\\UpdHelperSvc", "Type", 0x10, DWORD)
reg.set("HKLM", f"{svc}\\UpdHelperSvc", "Start", 2, DWORD)
reg.set("HKLM", f"{svc}\\UpdHelperSvc", "ImagePath", make("ProgramData/UpdHelper/upd_svc.exe"))
reg.delete_value("HKCU", CV + "\\Run", "Discord")
w.refresh()
w.compare(str(snap))
app.processEvents()
w.grab().save(str(out / "compare.png"))
w.close()
print("ok", out)
