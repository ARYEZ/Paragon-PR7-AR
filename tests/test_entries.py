"""Every location, switching off / on and deleting, against an in-memory registry, real folders and a recorded
schtasks; each test checks where things really ended up."""
import os

import pytest

from conftest import FakeTasks
from pr7ar import entries, lnk, signatures, tasks
from pr7ar.entries import CV, NT
from pr7ar.registry import DISABLED, DWORD, EXPAND_SZ, MULTI_SZ, SZ


def find(es, name, tab=None):
    got = [e for e in es if e.name == name and (tab is None or e.tab == tab)]
    assert got, f"{name} not listed"
    return got[0]


def test_resolve_finds_the_program(world):
    places, _, tmp = world
    win = places.windir
    app = str(tmp / "Program Files" / "My App" / "app.exe")
    r = lambda c: entries.resolve(c, places)                       # noqa: E731
    assert r(f'"{app}" --tray') == app
    assert r(f"{app} --tray") == app                                # unquoted, with spaces
    assert r("%ProgramFiles%\\My App\\app.exe /x").replace("\\", "/") == app.replace("\\", "/")
    assert r("%SystemRoot%\\System32\\SecurityHealthSystray.exe") == win + "\\System32\\SecurityHealthSystray.exe"
    assert r("\\SystemRoot\\System32\\drivers\\fancy.sys") == win + "\\System32\\drivers\\fancy.sys"
    assert r("System32\\drivers\\fancy.sys") == win + "\\System32\\drivers\\fancy.sys"
    assert r("\\??\\C:\\Drivers\\x.sys") == "C:\\Drivers\\x.sys"
    assert r('rundll32.exe "C:\\Tools\\thing.dll",Start /q') == "C:\\Tools\\thing.dll"
    assert r("rundll32 C:\\Tools\\other.dll,Entry") == "C:\\Tools\\other.dll"
    assert r("userinit.exe") == win + "\\System32\\userinit.exe"   # a bare name: found in System32
    assert r("userinit") == win + "\\System32\\userinit.exe"


def test_run_values_off_on_and_deleted(world):
    places, reg, tmp = world
    app = str(tmp / "Program Files" / "My App" / "app.exe")
    reg.set("HKCU", CV + "\\Run", "MyApp", f'"{app}" --tray')
    reg.set("HKCU", CV + "\\Run\\" + DISABLED, "OldTool", "C:\\Gone\\old.exe")      # switched off by Autoruns
    es = entries.collect(reg, places)
    a, o = find(es, "MyApp"), find(es, "OldTool")
    assert (a.tab, a.enabled, a.image, a.missing) == ("Logon", True, app, False)
    assert a.location == "HKCU\\" + CV + "\\Run"
    assert (o.enabled, o.missing) == (False, True)
    entries.set_enabled(a, False, reg)
    assert reg.get("HKCU", CV + "\\Run", "MyApp") is None
    assert reg.get("HKCU", CV + "\\Run\\" + DISABLED, "MyApp")[0] == f'"{app}" --tray'
    entries.set_enabled(o, True, reg)
    assert reg.get("HKCU", CV + "\\Run", "OldTool")[0] == "C:\\Gone\\old.exe"
    again = {e.name: e.enabled for e in entries.collect(reg, places)}
    assert again == {"MyApp": False, "OldTool": True}
    entries.delete(find(entries.collect(reg, places), "MyApp"), reg)
    assert reg.get("HKCU", CV + "\\Run\\" + DISABLED, "MyApp") is None


def test_machine_wide_changes_need_rights(world):
    places, reg, _ = world
    reg.set("HKLM", CV + "\\Run", "SecurityHealth", "%windir%\\system32\\SecurityHealthSystray.exe", EXPAND_SZ)
    reg.denied.add(("HKLM", CV.casefold() + "\\run"))
    e = find(entries.collect(reg, places), "SecurityHealth")
    with pytest.raises(PermissionError):
        entries.set_enabled(e, False, reg)
    assert e.enabled and reg.get("HKLM", CV + "\\Run", "SecurityHealth")


def test_startup_folder_shortcuts(world):
    places, reg, tmp = world
    app = str(tmp / "Program Files" / "My App" / "app.exe")
    with open(os.path.join(places.startup_user, "My App.lnk"), "wb") as f:
        f.write(lnk.make_lnk(app))
    with open(os.path.join(places.startup_common, "notes.txt"), "w") as f:
        f.write("x")
    es = entries.collect(reg, places)
    s = find(es, "My App.lnk")
    assert (s.tab, s.kind, s.image, s.enabled) == ("Logon", "file", app, True)
    entries.set_enabled(s, False, reg)
    assert os.path.exists(os.path.join(places.startup_user, DISABLED, "My App.lnk"))
    assert not os.path.exists(os.path.join(places.startup_user, "My App.lnk"))
    s2 = find(entries.collect(reg, places), "My App.lnk")
    assert not s2.enabled
    entries.set_enabled(s2, True, reg)
    assert os.path.exists(os.path.join(places.startup_user, "My App.lnk"))
    entries.delete(find(entries.collect(reg, places), "notes.txt"), reg)
    assert (tmp / "trash" / "notes.txt").exists()


def test_services_and_drivers(world):
    places, reg, _ = world
    svc = r"SYSTEM\CurrentControlSet\Services"
    reg.set("HKLM", svc + "\\MySvc", "Type", 0x10, DWORD)
    reg.set("HKLM", svc + "\\MySvc", "Start", 2, DWORD)
    reg.set("HKLM", svc + "\\MySvc", "ImagePath", '"C:\\Program Files\\My\\svc.exe" -k')
    reg.set("HKLM", svc + "\\MySvc", "DisplayName", "My service")
    reg.set("HKLM", svc + "\\Manual", "Type", 0x10, DWORD)
    reg.set("HKLM", svc + "\\Manual", "Start", 3, DWORD)                  # started on demand: not a startup entry
    reg.set("HKLM", svc + "\\wuauserv", "Type", 0x20, DWORD)
    reg.set("HKLM", svc + "\\wuauserv", "Start", 2, DWORD)
    reg.set("HKLM", svc + "\\wuauserv", "ImagePath", "%systemroot%\\system32\\svchost.exe -k netsvcs", EXPAND_SZ)
    reg.set("HKLM", svc + "\\wuauserv\\Parameters", "ServiceDll", "%systemroot%\\system32\\wuaueng.dll", EXPAND_SZ)
    reg.set("HKLM", svc + "\\fancy", "Type", 1, DWORD)
    reg.set("HKLM", svc + "\\fancy", "Start", 1, DWORD)
    reg.set("HKLM", svc + "\\fancy", "ImagePath", "System32\\drivers\\fancy.sys", EXPAND_SZ)
    es = entries.collect(reg, places)
    names = {e.name: e.tab for e in es if e.tab in ("Services", "Drivers")}
    assert names == {"MySvc": "Services", "wuauserv": "Services", "fancy": "Drivers"}
    assert find(es, "wuauserv").image.casefold().endswith("system32\\wuaueng.dll")          # svchost's hosted DLL
    assert find(es, "MySvc").description == "My service"
    m = find(es, "MySvc")
    entries.set_enabled(m, False, reg)
    assert reg.get("HKLM", svc + "\\MySvc", "Start")[0] == 4
    assert reg.get("HKLM", svc + "\\MySvc", entries.SAVED_START)[0] == 2
    m2 = find(entries.collect(reg, places), "MySvc")                            # still listed, as switched off
    assert not m2.enabled
    entries.set_enabled(m2, True, reg)
    assert reg.get("HKLM", svc + "\\MySvc", "Start")[0] == 2 and not reg.get("HKLM", svc + "\\MySvc",
                                                                              entries.SAVED_START)
    entries.delete(find(entries.collect(reg, places), "MySvc"), reg)
    assert not reg.exists("HKLM", svc + "\\MySvc")


def test_list_values(world):
    places, reg, _ = world
    sm = r"SYSTEM\CurrentControlSet\Control\Session Manager"
    reg.set("HKLM", sm, "BootExecute", ["autocheck autochk *", "evil.exe /now"], MULTI_SZ)
    wl = NT + "\\Winlogon"
    reg.set("HKLM", wl, "Userinit", "C:\\Windows\\system32\\userinit.exe,C:\\bad\\helper.exe,")
    reg.set("HKLM", wl, "Shell", "explorer.exe")
    reg.set("HKLM", r"SYSTEM\CurrentControlSet\Control\Lsa", "Authentication Packages", ["msv1_0"], MULTI_SZ)
    reg.set("HKLM", NT + "\\Windows", "AppInit_DLLs", "C:\\a.dll C:\\b.dll")
    es = entries.collect(reg, places)
    autochk = find(es, "autocheck autochk *")
    assert autochk.locked and autochk.image.endswith("System32\\autochk.exe")
    with pytest.raises(PermissionError):
        entries.set_enabled(autochk, False, reg)
    evil = find(es, "evil.exe /now")
    entries.set_enabled(evil, False, reg)
    assert reg.get("HKLM", sm, "BootExecute")[0] == ["autocheck autochk *"]
    assert reg.get("HKLM", sm + "\\" + DISABLED, "BootExecute")[0] == ["evil.exe /now"]
    evil2 = find(entries.collect(reg, places), "evil.exe /now")
    assert not evil2.enabled
    entries.set_enabled(evil2, True, reg)
    assert reg.get("HKLM", sm, "BootExecute")[0] == ["autocheck autochk *", "evil.exe /now"]
    assert reg.get("HKLM", sm + "\\" + DISABLED, "BootExecute") is None
    helper = find(es, "C:\\bad\\helper.exe")
    assert find(es, "C:\\Windows\\system32\\userinit.exe").locked and not helper.locked
    entries.set_enabled(helper, False, reg)
    assert reg.get("HKLM", wl, "Userinit")[0] == "C:\\Windows\\system32\\userinit.exe,"     # its trailing comma kept
    assert find(es, "explorer.exe", "Winlogon").locked
    assert find(es, "msv1_0").image.endswith("System32\\msv1_0.dll")
    b = find(es, "C:\\b.dll")
    entries.delete(b, reg)
    assert reg.get("HKLM", NT + "\\Windows", "AppInit_DLLs")[0] == "C:\\a.dll"


def test_keys_handlers_monitors_and_hijacks(world):
    places, reg, _ = world
    clsid = "{AAAAAAAA-0000-0000-0000-000000000001}"
    reg.set("HKLM", f"SOFTWARE\\Classes\\CLSID\\{clsid}\\InprocServer32", "", "C:\\Tools\\menu.dll")
    reg.set("HKLM", "SOFTWARE\\Classes\\*\\ShellEx\\ContextMenuHandlers\\PR7-Z", "", clsid)
    reg.set("HKLM", r"SYSTEM\CurrentControlSet\Control\Print\Monitors\Standard TCP/IP Port", "Driver", "tcpmon.dll")
    ifeo = NT + r"\Image File Execution Options"
    reg.set("HKLM", ifeo + "\\notepad.exe", "Debugger", '"C:\\PR7-W\\PR7-W.exe" /z')
    reg.set("HKLM", ifeo + "\\calc.exe", "MitigationOptions", 1, DWORD)            # no Debugger: not a hijack
    es = entries.collect(reg, places)
    h = find(es, "PR7-Z", "Explorer")
    assert h.image == "C:\\Tools\\menu.dll" and h.command == clsid
    entries.set_enabled(h, False, reg)
    assert reg.exists("HKLM", "SOFTWARE\\Classes\\*\\ShellEx\\ContextMenuHandlers\\" + DISABLED + "\\PR7-Z")
    assert not reg.exists("HKLM", "SOFTWARE\\Classes\\*\\ShellEx\\ContextMenuHandlers\\PR7-Z")
    h2 = find(entries.collect(reg, places), "PR7-Z", "Explorer")
    entries.set_enabled(h2, True, reg)
    assert reg.get("HKLM", "SOFTWARE\\Classes\\*\\ShellEx\\ContextMenuHandlers\\PR7-Z", "")[0] == clsid
    assert find(es, "Standard TCP/IP Port").image.endswith("System32\\tcpmon.dll")
    hj = [e for e in es if e.tab == "Image Hijacks"]
    assert [e.name for e in hj] == ["notepad.exe"] and hj[0].image == "C:\\PR7-W\\PR7-W.exe"
    entries.set_enabled(hj[0], False, reg)
    assert reg.get("HKLM", ifeo + "\\notepad.exe\\" + DISABLED, "Debugger")


def test_scheduled_tasks(world):
    places, reg, _ = world
    reg.set("HKLM", "SOFTWARE\\Classes\\CLSID\\{11111111-2222-3333-4444-555555555555}\\InprocServer32", "",
            "%SystemRoot%\\System32\\defragsvc.dll", EXPAND_SZ)
    fake = FakeTasks()
    es = [e for e in entries.collect(reg, places, tasks.Scheduler(fake)) if e.tab == "Scheduled Tasks"]
    assert [e.name for e in es] == ["\\Paragon\\PR7-IS Index", "\\Adobe Acrobat Update Task",
                                    "\\Microsoft\\Windows\\Defrag\\ScheduledDefrag"]
    pr7is, adobe, defrag = es
    assert pr7is.image.endswith("PR7-IS.exe") and pr7is.command.endswith("--index-service") and pr7is.enabled
    assert pr7is.description == "Paragon PR7-IS file search" and pr7is.timestamp
    assert adobe.command.startswith('"C:\\Program Files (x86)') and not adobe.enabled
    assert defrag.image.endswith("System32\\defragsvc.dll") and defrag.windows
    entries.set_enabled(adobe, True, reg, tasks.Scheduler(fake))
    assert fake.calls[-1] == ["/change", "/tn", "\\Adobe Acrobat Update Task", "/enable"]
    entries.delete(pr7is, reg, tasks.Scheduler(fake))
    assert fake.calls[-1] == ["/delete", "/tn", "\\Paragon\\PR7-IS Index", "/f"]
    denied = tasks.Scheduler(FakeTasks(fail="ERROR: Access is denied."))
    with pytest.raises(PermissionError):
        denied.set_enabled("\\X", False)


def test_snapshots_compare(world, tmp_path):
    places, reg, _ = world
    reg.set("HKCU", CV + "\\Run", "Old", "C:\\old.exe")
    reg.set("HKCU", CV + "\\Run", "Kept", "C:\\kept.exe")
    before = entries.collect(reg, places)
    path = str(tmp_path / "before.pr7ar")
    entries.save_snapshot(before, path)
    reg.delete_value("HKCU", CV + "\\Run", "Old")
    reg.set("HKCU", CV + "\\Run", "New", "C:\\new.exe")
    reg.set("HKCU", CV + "\\Run", "Kept", "C:\\changed.exe")
    when, then = entries.load_snapshot(path)
    new, gone = entries.compare(entries.collect(reg, places), then)
    assert when > 0 and {k.split("|")[-1] for k in new} == {"new", "kept"} and [e.name for e in gone] == ["Old"]
    (tmp_path / "bad.pr7ar").write_text("[]")
    with pytest.raises(ValueError):
        entries.load_snapshot(str(tmp_path / "bad.pr7ar"))


def test_signatures_are_cached_and_windows_entries_known(world, tmp_path):
    places, reg, tmp = world
    app = str(tmp / "Program Files" / "My App" / "app.exe")
    seen = []

    def fake(paths):
        seen.append(list(paths))
        return {p: signatures.Signature(True, "Microsoft Windows", True) if "Windows" in p else
                signatures.Signature(False, "") for p in paths}
    c = signatures.Checker(str(tmp_path / "sig.json"), run=fake)
    reg.set("HKCU", CV + "\\Run", "MyApp", app)
    reg.set("HKLM", CV + "\\Run", "Sec", "%SystemRoot%\\System32\\SecurityHealthSystray.exe", EXPAND_SZ)
    es = entries.collect(reg, places)
    entries.fill_details(es, c)
    assert find(es, "Sec").windows and find(es, "Sec").verified and not find(es, "MyApp").windows
    assert find(es, "MyApp").verified is False
    entries.fill_details(entries.collect(reg, places), signatures.Checker(str(tmp_path / "sig.json"), run=fake))
    assert len(seen) == 1                                                        # the second time: from the cache
    assert find(es, "MyApp").matches("my app") and not find(es, "MyApp").matches("adobe")


def test_task_xml_parsing_details():
    ts = tasks.parse("\ufeff<Tasks>\n<!-- \\A -->\n<Task xmlns='x'><Actions><Exec><Command>C:\\x y\\z.exe</Command>"
                     "</Exec></Actions></Task>\n<!-- \\Broken -->\n<Task><oops></Task>\n</Tasks>")
    assert [(t.path, t.command, t.enabled) for t in ts] == [("\\A", '"C:\\x y\\z.exe"', True)]


def test_load_list_value_and_codecs(world):
    places, reg, _ = world
    reg.set("HKCU", "Software\\Microsoft\\Windows NT\\CurrentVersion\\Windows", "Load", "C:\\x.exe, C:\\y.exe")
    reg.set("HKLM", NT + "\\Drivers32", "msacm.imaadpcm", "imaadp32.acm")
    reg.set("HKLM", NT + "\\Drivers32", "wave", "")
    es = entries.collect(reg, places)
    assert {e.name for e in es if e.tab == "Logon"} == {"C:\\x.exe", "C:\\y.exe"}
    assert [e.name for e in es if e.tab == "Codecs"] == ["msacm.imaadpcm"]
    assert SZ and EXPAND_SZ
