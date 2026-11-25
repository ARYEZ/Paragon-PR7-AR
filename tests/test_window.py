"""The window driven like a user on a made-up Windows; every change is checked in the registry or folders."""
import json
import os

from PySide6.QtCore import Qt

from pr7ar import app, entries, registry
from pr7ar.entries import CV, NT
from pr7ar.registry import DISABLED, MULTI_SZ


def setup(world):
    places, reg, tmp = world
    reg.set("HKCU", CV + "\\Run", "MyApp", str(tmp / "Program Files" / "My App" / "app.exe"))
    reg.set("HKCU", CV + "\\Run", "Broken", "C:\\Gone\\gone.exe")
    reg.set("HKLM", CV + "\\Run", "SecurityHealth", "%SystemRoot%\\System32\\SecurityHealthSystray.exe",
            registry.EXPAND_SZ)
    reg.set("HKLM", r"SYSTEM\CurrentControlSet\Control\Session Manager", "BootExecute", ["autocheck autochk *"],
            MULTI_SZ)
    return places, reg, tmp


def rows(w):
    return [(k, (e if k == "group" else e.name)) for k, e in w.model.rows]


def test_lists_groups_and_tints(window, world):
    w = window
    setup(world)
    w.refresh()
    names = [n for k, n in rows(w) if k == "entry"]
    assert "MyApp" in names and "Broken" in names and "SecurityHealth" not in names       # Windows' own hidden
    assert rows(w)[0] == ("group", "HKCU\\" + CV + "\\Run")
    w.hide_windows.setChecked(False)
    assert "SecurityHealth" in [n for k, n in rows(w) if k == "entry"]
    i = [n for _, n in rows(w)].index("Broken")
    tint = w.model.data(w.model.index(i, 0), Qt.ItemDataRole.BackgroundRole).color()
    assert tint.red() > 200 and tint.green() > 100                                         # orange: file missing
    j = [n for _, n in rows(w)].index("MyApp")
    assert w.model.data(w.model.index(j, 2)) == "(not verified)"                            # unverified: pink
    assert w.model.data(w.model.index(j, 0), Qt.ItemDataRole.BackgroundRole).color().name().lower() == "#d6457e"
    assert "files missing" in w.status.text() and "unverified" in w.status.text()   # Broken + the tasks' programs


def test_unticking_switches_off(window, world):
    w = window
    places, reg, _ = setup(world)
    w.refresh()
    i = [n for _, n in rows(w)].index("MyApp")
    idx = w.model.index(i, 0)
    assert w.model.flags(idx) & Qt.ItemFlag.ItemIsUserCheckable
    assert w.model.setData(idx, Qt.CheckState.Unchecked.value, Qt.ItemDataRole.CheckStateRole)
    assert reg.get("HKCU", CV + "\\Run\\" + DISABLED, "MyApp") and not reg.get("HKCU", CV + "\\Run", "MyApp")
    assert w.model.data(idx, Qt.ItemDataRole.CheckStateRole) == Qt.CheckState.Unchecked
    w.model.setData(idx, Qt.CheckState.Checked.value, Qt.ItemDataRole.CheckStateRole)
    assert reg.get("HKCU", CV + "\\Run", "MyApp")


def test_rights_and_locked_entries(window, world):
    w = window
    places, reg, _ = setup(world)
    reg.denied.add(("HKLM", CV.casefold() + "\\run"))
    w.hide_windows.setChecked(False)
    w.refresh()
    i = [n for _, n in rows(w)].index("SecurityHealth")
    assert not w.model.setData(w.model.index(i, 0), Qt.CheckState.Unchecked.value, Qt.ItemDataRole.CheckStateRole)
    assert "administrator" in w.said[-1][1] and reg.get("HKLM", CV + "\\Run", "SecurityHealth")
    w.tabs.setCurrentIndex(entries.TABS.index("Boot Execute"))
    j = [n for _, n in rows(w)].index("autocheck autochk *")
    assert not (w.model.flags(w.model.index(j, 0)) & Qt.ItemFlag.ItemIsUserCheckable)    # locked: no checkbox
    w.select("autocheck autochk *")
    assert not w.keys["delete"].isEnabled()


def test_delete_asks_first(window, world):
    w = window
    places, reg, _ = setup(world)
    w.refresh()
    assert not w.keys["delete"].isEnabled()
    w.select("Broken")
    assert w.keys["delete"].isEnabled() and w.keys["jump_entry"].isEnabled()       # the keys follow the selection
    w.answers["confirm"] = False
    assert not w.delete(w.current()) and reg.get("HKCU", CV + "\\Run", "Broken")
    asked = []
    w.answers["confirm"] = lambda t: asked.append(t) or True
    assert w.delete(w.current())
    assert reg.get("HKCU", CV + "\\Run", "Broken") is None and "can't be undone" in asked[-1]
    assert "Broken" not in [n for _, n in rows(w)]


def test_tabs_and_filter(window, world):
    w = window
    places, reg, _ = setup(world)
    reg.set("HKLM", NT + r"\Image File Execution Options\notepad.exe", "Debugger", '"C:\\PR7-W\\PR7-W.exe" /z')
    w.refresh()
    w.tabs.setCurrentIndex(entries.TABS.index("Image Hijacks"))
    assert [n for k, n in rows(w) if k == "entry"] == ["notepad.exe"]
    w.tabs.setCurrentIndex(0)
    w.filter.setText("my app")
    assert [n for k, n in rows(w) if k == "entry"] == ["MyApp"]
    w.tabs.setCurrentIndex(entries.TABS.index("Scheduled Tasks"))
    w.filter.setText("")
    assert [n for k, n in rows(w) if k == "entry"] == ["\\Paragon\\PR7-IS Index", "\\Adobe Acrobat Update Task"]


def test_scheduled_task_checkbox_runs_schtasks(window, world):
    w = window
    w.refresh()
    w.tabs.setCurrentIndex(entries.TABS.index("Scheduled Tasks"))
    i = [n for _, n in rows(w)].index("\\Adobe Acrobat Update Task")
    w.model.setData(w.model.index(i, 0), Qt.CheckState.Checked.value, Qt.ItemDataRole.CheckStateRole)
    assert w.fake_tasks.calls[-1] == ["/change", "/tn", "\\Adobe Acrobat Update Task", "/enable"]


def test_snapshot_and_compare(window, world, tmp_path):
    w = window
    places, reg, _ = setup(world)
    w.refresh()
    path = tmp_path / "before.pr7ar"
    w.answers["save_file"] = str(path)
    w.save_snapshot()
    data = json.loads(path.read_text())
    assert any(e["name"] == "MyApp" for e in data["entries"])
    reg.set("HKCU", CV + "\\Run", "Sneaky", "C:\\ProgramData\\x\\upd.exe")
    reg.delete_value("HKCU", CV + "\\Run", "Broken")
    w.refresh()
    w.compare(str(path))
    shown = rows(w)
    assert ("entry", "Sneaky") in shown and ("gone", "Broken") in shown and ("entry", "MyApp") not in shown
    assert w.banner.isVisible() and "1 new" in w.banner_text.text() and "1 gone" in w.banner_text.text()
    i = [n for _, n in shown].index("Sneaky")
    assert w.model.data(w.model.index(i, 0), Qt.ItemDataRole.BackgroundRole).color().name().lower() == "#e8e8ea"
    w.stop_compare()
    assert not w.banner.isVisible() and ("entry", "MyApp") in rows(w)
    (tmp_path / "bad.pr7ar").write_text("nope")
    w.compare(str(tmp_path / "bad.pr7ar"))
    assert "isn't a PR7-AR snapshot" in w.said[-1][1]


def test_jumps(window, world):
    w = window
    places, reg, tmp = setup(world)
    w.refresh()
    w.select("MyApp")
    w.jump_entry(w.current())
    assert reg.get("HKCU", r"Software\Microsoft\Windows\CurrentVersion\Applets\Regedit", "LastKey")[0] == \
        "Computer\\HKEY_CURRENT_USER\\" + CV + "\\Run"
    assert w.ran[-1] == ["regedit.exe"]
    w.jump_file(w.current())
    assert w.launched[-1] == ("PR7-E", [str(tmp / "Program Files" / "My App")])
    w.select("Broken")
    w.jump_file(w.current())
    assert "isn't there" in w.said[-1][1]
    w.tabs.setCurrentIndex(entries.TABS.index("Scheduled Tasks"))
    w.select("\\Paragon\\PR7-IS Index")
    w.jump_entry(w.current())
    assert w.ran[-1] == ["mmc.exe", "taskschd.msc"]


def test_details_pane(window, world):
    w = window
    setup(world)
    w.hide_windows.setChecked(False)
    w.refresh()
    w.select("SecurityHealth")
    assert w.d_title.text() == "SecurityHealth" and "verified" in w.d["Publisher"].text()
    w.select("MyApp")
    assert "NOT VERIFIED" in w.d["Publisher"].text()
    w.select("Broken")
    assert w.d["Image"].text().startswith("File not found")


def test_selftest(tmp_path):
    out = tmp_path / "st.json"
    assert app.selftest(str(out)) == 0
    got = json.loads(out.read_text())
    assert got["found"] and got["switched_off"] and got["switched_on"] and got["deleted"]


def test_version(capsys):
    from pr7ar import __version__
    assert app.main(["--version"]) == 0 and capsys.readouterr().out.strip() == __version__
    assert os.environ.get("PR7AR_TRASH")
