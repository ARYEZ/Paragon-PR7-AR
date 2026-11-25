"""Everything Windows starts by itself (no Qt), the way Autoruns lists it: each tab's locations, each entry's program
file, and switching entries off / on / deleting them.

Switching off works as Autoruns does, so entries Autoruns switched off show as off here and the other way round:
- a registry value (Run keys, codecs, image hijacks) moves into the key's "AutorunsDisabled" sub-key;
- a registry key (Explorer menu handlers, print monitors, Office add-ins) moves under "<parent>\\AutorunsDisabled";
- a Startup folder item moves into "<folder>\\AutorunsDisabled";
- an item of a list value (Boot Execute, LSA packages, Winlogon, AppInit, network providers) leaves the list and is
  kept in the "AutorunsDisabled" sub-key's value of the same name;
- a scheduled task is disabled (schtasks); a service or driver gets Start = 4 (disabled), its old Start kept in
  "PR7-AR Start" to put back.
Windows' own must-haves (Winlogon's userinit.exe and explorer.exe, Boot Execute's autocheck) can't be switched off.

Machine-wide locations need administrator rights to change: a refused write is a PermissionError, said in the window
(As Admin restarts PR7-AR elevated)."""

from __future__ import annotations

import json
import os
import re
import time
from dataclasses import asdict, dataclass, field

from . import lnk, trash
from .registry import DISABLED, DWORD, MULTI_SZ, SZ, Registry
from .tasks import Scheduler

TABS = ["Everything", "Logon", "Explorer", "Scheduled Tasks", "Services", "Drivers", "Codecs", "Boot Execute",
        "Image Hijacks", "AppInit", "Winlogon", "Print Monitors", "LSA", "Network Providers", "Office"]
SAVED_START = "PR7-AR Start"
EXTS = (".exe", ".dll", ".sys", ".com", ".bat", ".cmd", ".ocx", ".cpl", ".scr", ".acm", ".ax", ".drv", ".vbs", ".js",
        ".ps1", ".lnk", ".msc", ".tlb")
CV = r"SOFTWARE\Microsoft\Windows\CurrentVersion"
NT = r"SOFTWARE\Microsoft\Windows NT\CurrentVersion"


# --------------------------------------------------------------------------- where things are
@dataclass
class Places:
    windir: str = "C:\\Windows"
    startup_user: str = ""
    startup_common: str = ""
    path: list = field(default_factory=list)
    env: dict = field(default_factory=dict)

    @staticmethod
    def here() -> "Places":
        env = dict(os.environ)
        win = env.get("SystemRoot") or env.get("windir") or "C:\\Windows"
        appdata, progdata = env.get("APPDATA", ""), env.get("ProgramData", "C:\\ProgramData")
        return Places(win, os.path.join(appdata, "Microsoft", "Windows", "Start Menu", "Programs", "Startup"),
                      os.path.join(progdata, "Microsoft", "Windows", "Start Menu", "Programs", "StartUp"),
                      [p for p in env.get("PATH", "").split(os.pathsep) if p], env)

    @property
    def system32(self) -> str:
        return self.windir.rstrip("\\/") + "\\System32"


def _join(*parts: str) -> str:
    out = parts[0].rstrip("\\/")
    for p in parts[1:]:
        out += "\\" + p.strip("\\/")
    return out


def _exists(path: str) -> bool:
    return bool(path) and os.path.exists(path.replace("\\", os.sep) if os.sep != "\\" else path)


def expand(text: str, places: Places) -> str:
    """%VAR% the Windows way (os.path.expandvars only does that on Windows), with SystemRoot / windir from places."""
    env = {k.casefold(): v for k, v in places.env.items()}
    env.setdefault("systemroot", places.windir)
    env.setdefault("windir", places.windir)
    return re.sub(r"%([^%]+)%", lambda m: env.get(m.group(1).casefold(), m.group(0)), text)


def resolve(command: str, places: Places) -> str:
    """The program file a command line starts: quotes, %VARS%, \\SystemRoot\\ and \\??\\ prefixes, unquoted paths
    with spaces, rundll32's DLL, and bare names looked up in System32, Windows and PATH (as Windows finds them)."""
    cmd = expand(command.strip(), places).strip()
    if not cmd:
        return ""
    if cmd.startswith("@"):
        cmd = cmd[1:]
    if cmd.startswith('"'):
        end = cmd.find('"', 1)
        image, rest = (cmd[1:end], cmd[end + 1:]) if end > 0 else (cmd[1:], "")
    else:
        tokens = cmd.split(" ")
        image, rest = tokens[0], " ".join(tokens[1:])
        for i in range(1, len(tokens) + 1):               # "C:\Program Files\App\app.exe /x" without quotes
            cand = " ".join(tokens[:i])
            if cand.lower().endswith(EXTS) or (i > 1 and _exists(cand)):
                image, rest = cand, " ".join(tokens[i:])
                break
        image = image.rstrip(",")
    image = image.strip()
    low = image.lower()
    if low.startswith("\\??\\"):
        image = image[4:]
    elif low.startswith("\\systemroot\\"):
        image = _join(places.windir, image[12:])
    elif low.startswith("system32\\") or low.startswith("syswow64\\"):
        image = _join(places.windir, image)
    base = os.path.basename(image.replace("\\", "/")).lower()
    if base in ("rundll32.exe", "rundll32") and rest.strip():        # the DLL rundll32 is asked to run
        arg = rest.strip()
        arg = arg[1:arg.find('"', 1)] if arg.startswith('"') else arg.split(",")[0].split(" ")[0]
        return resolve(arg.split(",")[0], places)
    if "\\" not in image and "/" not in image:
        names = [image] if "." in image else [image + ".exe", image + ".dll", image]
        for d in [places.system32, places.windir, *places.path]:
            for n in names:
                p = _join(d, n)
                if _exists(p):
                    return p
        return _join(places.system32, names[0])
    if "." not in os.path.basename(image.replace("\\", "/")) and _exists(image + ".exe"):
        image += ".exe"
    return image


# --------------------------------------------------------------------------- entries
@dataclass
class Entry:
    tab: str
    location: str           # what the window shows as the group: "HKLM\...\Run", a folder, "Task Scheduler"
    name: str
    command: str
    image: str
    enabled: bool
    kind: str               # value | key | file | task | service | list
    ref: dict               # how to find it again (hive, path, name, item, ...)
    timestamp: float | None = None
    description: str = ""
    company: str = ""
    version: str = ""
    signer: str = ""
    verified: bool | None = None
    os_file: bool = False
    locked: bool = False    # can't be switched off (Windows needs it)

    @property
    def missing(self) -> bool:
        return bool(self.image) and not _exists(self.image)

    @property
    def windows(self) -> bool:
        """Windows' own, for Hide Windows entries: signed as part of Windows (its OS files), or by Microsoft Windows."""
        if self.os_file or self.signer.startswith("Microsoft Windows"):
            return True
        # Windows' own scheduled tasks live under \Microsoft\Windows\ (their programs are often shared ones)
        return self.kind == "task" and self.name.casefold().startswith("\\microsoft\\windows\\") and \
            self.verified is not False

    @property
    def publisher(self) -> str:
        return self.signer or self.company

    def key(self) -> str:
        return f"{self.tab}|{self.location}|{self.name}".casefold()

    def matches(self, text: str) -> bool:
        hay = " ".join((self.name, self.description, self.publisher, self.image, self.command, self.location)).casefold()
        return all(w in hay for w in text.casefold().split())


def _when(reg: Registry, hive: str, path: str) -> float | None:
    try:
        return reg.key_time(hive, path)
    except OSError:
        return None


def _value_entries(reg: Registry, tab: str, hive: str, path: str, places: Places, image_of=None,
                   skip=("",)) -> list[Entry]:
    out = []
    for where, enabled in ((path, True), (path + "\\" + DISABLED, False)):
        for name, data, kind in reg.values(hive, where):
            if name in skip or not isinstance(data, str):
                continue
            cmd = data
            out.append(Entry(tab, f"{hive}\\{path}", name, cmd, image_of(cmd) if image_of else resolve(cmd, places),
                             enabled, "value", {"hive": hive, "path": path, "name": name},
                             _when(reg, hive, where)))
    return out


def _clsid_dll(reg: Registry, clsid: str, places: Places) -> str:
    for hive, base in (("HKLM", "SOFTWARE\\Classes\\CLSID"), ("HKCU", "Software\\Classes\\CLSID"),
                       ("HKLM", "SOFTWARE\\WOW6432Node\\Classes\\CLSID")):
        got = reg.get(hive, f"{base}\\{clsid}\\InprocServer32", "")
        if got and got[0]:
            return resolve(str(got[0]), places)
    return ""


def _key_entries(reg: Registry, tab: str, hive: str, parent: str, places: Places, image_of) -> list[Entry]:
    out = []
    for where, enabled in ((parent, True), (parent + "\\" + DISABLED, False)):
        for sub in reg.subkeys(hive, where):
            if sub == DISABLED:
                continue
            image, cmd, name = image_of(hive, f"{where}\\{sub}", sub)
            if image is None:
                continue
            out.append(Entry(tab, f"{hive}\\{parent}", name, cmd, image, enabled, "key",
                             {"hive": hive, "path": parent, "name": sub}, _when(reg, hive, f"{where}\\{sub}")))
    return out


def _split(data, sep):
    if sep is None:
        return [s for s in (data or []) if s and s.strip()]
    parts = re.split(sep, data or "")
    return [p.strip() for p in parts if p.strip()]


def _list_entries(reg: Registry, tab: str, hive: str, path: str, name: str, sep, places: Places, image_of=None,
                  locked=()) -> list[Entry]:
    """Each item of a list value (MULTI_SZ, or a string split by `sep`), and the switched-off ones kept in the
    AutorunsDisabled sub-key (always MULTI_SZ)."""
    out = []
    for where, enabled in ((path, True), (path + "\\" + DISABLED, False)):
        items, _, _ = _list_get(reg, hive, where, name, sep)
        for item in items:
            image = image_of(item) if image_of else resolve(item, places)
            out.append(Entry(tab, f"{hive}\\{path}\\{name}", item, item, image, enabled, "list",
                             {"hive": hive, "path": path, "name": name, "item": item, "sep": sep},
                             _when(reg, hive, path), locked=item.casefold() in locked))
    return out


def _resource_text(text: str) -> str:
    """Service names like "@%SystemRoot%\\system32\\x.dll,-100" are resource references: no text without loading."""
    return "" if (text or "").startswith("@") else (text or "")


def collect(reg: Registry, places: Places, scheduler: Scheduler | None = None) -> list[Entry]:
    out: list[Entry] = []
    # ---- Logon
    for hive, path in (("HKCU", CV + "\\Run"), ("HKCU", CV + "\\RunOnce"), ("HKLM", CV + "\\Run"),
                       ("HKLM", CV + "\\RunOnce"), ("HKLM", r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Run"),
                       ("HKLM", r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\RunOnce"),
                       ("HKCU", CV + r"\Policies\Explorer\Run"), ("HKLM", CV + r"\Policies\Explorer\Run")):
        out += _value_entries(reg, "Logon", hive, path, places)
    out += _list_entries(reg, "Logon", "HKCU", NT.replace("SOFTWARE", "Software") + "\\Windows", "Load", r"[ ,]+",
                         places)
    for folder in (places.startup_user, places.startup_common):
        out += _startup(folder, places)
    # ---- Explorer
    for hive, classes in (("HKLM", "SOFTWARE\\Classes"), ("HKCU", "Software\\Classes")):
        for kind in ("*", "Directory", "Directory\\Background", "Folder", "Drive"):
            parent = f"{classes}\\{kind}\\ShellEx\\ContextMenuHandlers"

            def handler(h, path, sub):
                got = reg.get(h, path, "")
                clsid = sub if sub.startswith("{") else (str(got[0]) if got and got[0] else "")
                return (_clsid_dll(reg, clsid, places) if clsid else ""), clsid, sub
            out += _key_entries(reg, "Explorer", hive, parent, places, handler)
    def overlay(h, path, sub):
        got = reg.get(h, path, "")
        clsid = str(got[0]) if got and got[0] else ""
        return (_clsid_dll(reg, clsid, places) if clsid else ""), clsid, sub.strip()
    out += _key_entries(reg, "Explorer", "HKLM", CV + r"\Explorer\ShellIconOverlayIdentifiers", places, overlay)
    # ---- Scheduled Tasks
    if scheduler is not None:
        for t in scheduler.list():
            image = _clsid_dll(reg, t.com_class, places) if t.com_class else resolve(t.command, places)
            when = None
            if t.date:
                try:
                    when = time.mktime(time.strptime(t.date[:19], "%Y-%m-%dT%H:%M:%S"))
                except ValueError:
                    when = None
            e = Entry("Scheduled Tasks", "Task Scheduler", t.path, t.command or t.com_class, image, t.enabled, "task",
                      {"path": t.path}, when, description=t.description)
            out.append(e)
    # ---- Services and drivers
    svc_root = r"SYSTEM\CurrentControlSet\Services"
    for name in reg.subkeys("HKLM", svc_root):
        path = f"{svc_root}\\{name}"
        vals = {n.casefold(): d for n, d, _ in reg.values("HKLM", path)}
        typ, start = vals.get("type"), vals.get("start")
        if not isinstance(typ, int) or not isinstance(start, int):
            continue
        if not (start in (0, 1, 2) or (start == 4 and SAVED_START.casefold() in vals)):
            continue
        tab = "Drivers" if typ in (1, 2, 8) else "Services" if typ & 0x30 else None
        if tab is None:
            continue
        cmd = str(vals.get("imagepath") or "")
        image = resolve(cmd, places) if cmd else (_join(places.system32, "drivers", name + ".sys") if tab == "Drivers"
                                                  else "")
        dll = reg.get("HKLM", path + "\\Parameters", "ServiceDll")
        if dll and dll[0] and "svchost" in cmd.lower():
            image = resolve(str(dll[0]), places)
        display = _resource_text(str(vals.get("displayname") or ""))
        out.append(Entry(tab, f"HKLM\\{svc_root}", name, cmd, image, start != 4, "service", {"name": name},
                         _when(reg, "HKLM", path), description=_resource_text(str(vals.get("description") or "")) or
                         display))
    # ---- Codecs
    for hive, path in (("HKLM", NT + "\\Drivers32"), ("HKLM", r"SOFTWARE\WOW6432Node\Microsoft\Windows NT\CurrentVersion"
                                                       r"\Drivers32")):
        out += [e for e in _value_entries(reg, "Codecs", hive, path, places) if e.command.strip()]
    # ---- Boot Execute
    sm = r"SYSTEM\CurrentControlSet\Control\Session Manager"
    out += _list_entries(reg, "Boot Execute", "HKLM", sm, "BootExecute", None, places,
                         image_of=lambda item: resolve(item.split(" ")[1] if item.lower().startswith("autocheck ")
                                                       else item.split(" ")[0], places),
                         locked=("autocheck autochk *",))
    # ---- Image Hijacks
    for root in (NT + r"\Image File Execution Options",
                 r"SOFTWARE\WOW6432Node\Microsoft\Windows NT\CurrentVersion\Image File Execution Options"):
        for exe in reg.subkeys("HKLM", root):
            for where, enabled in ((f"{root}\\{exe}", True), (f"{root}\\{exe}\\{DISABLED}", False)):
                got = reg.get("HKLM", where, "Debugger")
                if got and isinstance(got[0], str) and got[0].strip():
                    out.append(Entry("Image Hijacks", f"HKLM\\{root}", exe, got[0], resolve(got[0], places), enabled,
                                     "value", {"hive": "HKLM", "path": f"{root}\\{exe}", "name": "Debugger"},
                                     _when(reg, "HKLM", where)))
    # ---- AppInit
    for path in (NT + "\\Windows", r"SOFTWARE\WOW6432Node\Microsoft\Windows NT\CurrentVersion\Windows"):
        out += _list_entries(reg, "AppInit", "HKLM", path, "AppInit_DLLs", r"[ ,]+", places)
    # ---- Winlogon
    wl = NT + "\\Winlogon"
    out += _list_entries(reg, "Winlogon", "HKLM", wl, "Userinit", r",", places,
                         locked=(_join(places.system32, "userinit.exe").casefold(), "userinit.exe",
                                 "c:\\windows\\system32\\userinit.exe"))
    out += _list_entries(reg, "Winlogon", "HKLM", wl, "Shell", r",", places, locked=("explorer.exe",))
    out += _list_entries(reg, "Winlogon", "HKCU", NT.replace("SOFTWARE", "Software") + "\\Winlogon", "Shell", r",",
                         places)
    # ---- Print monitors
    def monitor(h, path, sub):
        got = reg.get(h, path, "Driver")
        if not got or not got[0]:
            return None, "", sub
        return resolve(str(got[0]), places), str(got[0]), sub
    out += _key_entries(reg, "Print Monitors", "HKLM", r"SYSTEM\CurrentControlSet\Control\Print\Monitors", places,
                        monitor)
    # ---- LSA
    lsa = r"SYSTEM\CurrentControlSet\Control\Lsa"
    for name in ("Authentication Packages", "Notification Packages", "Security Packages"):
        out += _list_entries(reg, "LSA", "HKLM", lsa, name, None, places,
                             image_of=lambda item: resolve(item if item.lower().endswith(".dll") else item + ".dll",
                                                           places))
    out += _list_entries(reg, "LSA", "HKLM", lsa + "\\OSConfig", "Security Packages", None, places,
                         image_of=lambda item: resolve(item if item.lower().endswith(".dll") else item + ".dll", places))
    # ---- Network providers
    def provider(item):
        got = reg.get("HKLM", f"{svc_root}\\{item}\\NetworkProvider", "ProviderPath")
        return resolve(str(got[0]), places) if got and got[0] else ""
    out += _list_entries(reg, "Network Providers", "HKLM", r"SYSTEM\CurrentControlSet\Control\NetworkProvider\Order",
                         "ProviderOrder", r",", places, image_of=provider)
    # ---- Office add-ins
    for hive, base in (("HKCU", "Software\\Microsoft\\Office"), ("HKLM", "SOFTWARE\\Microsoft\\Office"),
                       ("HKLM", "SOFTWARE\\WOW6432Node\\Microsoft\\Office")):
        for app in ("Word", "Excel", "PowerPoint", "Outlook", "Access", "OneNote", "Visio", "Publisher"):
            def addin(h, path, sub):
                man = reg.get(h, path, "Manifest")
                if man and man[0]:
                    m = str(man[0]).split("|")[0]
                    return (m[8:] if m.lower().startswith("file:///") else m).replace("/", "\\"), str(man[0]), sub
                clsid = reg.get("HKLM", f"SOFTWARE\\Classes\\{sub}\\CLSID", "") or \
                    reg.get("HKCU", f"Software\\Classes\\{sub}\\CLSID", "")
                return (_clsid_dll(reg, str(clsid[0]), places) if clsid and clsid[0] else ""), sub, sub
            out += _key_entries(reg, "Office", hive, f"{base}\\{app}\\Addins", places, addin)
    return out


def _startup(folder: str, places: Places) -> list[Entry]:
    out = []
    if not folder:
        return out
    for where, enabled in ((folder, True), (os.path.join(folder, DISABLED), False)):
        try:
            names = sorted(os.listdir(where), key=str.casefold)
        except OSError:
            continue
        for n in names:
            p = os.path.join(where, n)
            if not os.path.isfile(p) or n.lower() == "desktop.ini":
                continue
            target = ""
            if n.lower().endswith(".lnk"):
                try:
                    with open(p, "rb") as f:
                        target = lnk.lnk_target(f.read()) or ""
                except OSError:
                    target = ""
            cmd = target or p
            out.append(Entry("Logon", folder, n, cmd, resolve(cmd, places) if target else p, enabled, "file",
                             {"folder": folder, "name": n}, os.path.getmtime(p)))
    return out


# --------------------------------------------------------------------------- switching off / on, deleting
def set_enabled(e: Entry, on: bool, reg: Registry, scheduler: Scheduler | None = None) -> None:
    if e.enabled == on:
        return
    if e.locked and not on:
        raise PermissionError(1, f"{e.name} can't be switched off: Windows needs it")
    r = e.ref
    if e.kind == "value":
        src, dst = (r["path"] + "\\" + DISABLED, r["path"]) if on else (r["path"], r["path"] + "\\" + DISABLED)
        reg.move_value(r["hive"], src, dst, r["name"])
    elif e.kind == "key":
        dis = f"{r['path']}\\{DISABLED}\\{r['name']}"
        live = f"{r['path']}\\{r['name']}"
        reg.move_key(r["hive"], dis if on else live, live if on else dis)
    elif e.kind == "file":
        live = os.path.join(r["folder"], r["name"])
        dis = os.path.join(r["folder"], DISABLED, r["name"])
        os.makedirs(os.path.dirname(dis if not on else live), exist_ok=True)
        os.replace(dis if on else live, live if on else dis)
    elif e.kind == "task":
        (scheduler or Scheduler()).set_enabled(r["path"], on)
    elif e.kind == "service":
        path = rf"SYSTEM\CurrentControlSet\Services\{r['name']}"
        if on:
            saved = reg.get("HKLM", path, SAVED_START)
            reg.set("HKLM", path, "Start", int(saved[0]) if saved else 3, DWORD)
            if saved:
                reg.delete_value("HKLM", path, SAVED_START)
        else:
            cur = reg.get("HKLM", path, "Start")
            reg.set("HKLM", path, SAVED_START, int(cur[0]) if cur else 2, DWORD)
            reg.set("HKLM", path, "Start", 4, DWORD)
    elif e.kind == "list":
        _list_move(e, on, reg)
    e.enabled = on


def _list_get(reg, hive, path, name, sep):
    """(items, value kind, the raw text): MULTI_SZ is a list already; a string is split by `sep`."""
    got = reg.get(hive, path, name)
    if not got:
        return [], (MULTI_SZ if sep is None else SZ), ""
    data, kind = got
    if kind == MULTI_SZ or isinstance(data, list):
        return [x for x in (data or []) if x and x.strip()], MULTI_SZ, ""
    return _split(str(data), sep or r"[ ,]+"), kind, str(data)


def _list_put(reg, hive, path, name, items, kind, sep, raw=""):
    """Write a list back in its own form: Winlogon's "userinit.exe," keeps its trailing comma, AppInit and Load are
    space-separated, network providers comma-separated."""
    if kind == MULTI_SZ:
        reg.set(hive, path, name, items, MULTI_SZ)
        return
    if sep == r",":
        text = ",".join(items) + ("," if raw.rstrip().endswith(",") and items else "")
    else:
        text = " ".join(items)
    reg.set(hive, path, name, text, kind)


def _list_move(e: Entry, on: bool, reg: Registry) -> None:
    r = e.ref
    hive, path, name, item, sep = r["hive"], r["path"], r["name"], r["item"], r["sep"]
    live, kind, raw = _list_get(reg, hive, path, name, sep)
    dis, _, _ = _list_get(reg, hive, path + "\\" + DISABLED, name, None)
    if on:
        dis = [x for x in dis if x != item]
        live.append(item)
    else:
        live = [x for x in live if x != item]
        dis.append(item)
    _list_put(reg, hive, path, name, live, kind, sep, raw)
    if dis:
        reg.set(hive, path + "\\" + DISABLED, name, dis, MULTI_SZ)
    elif reg.get(hive, path + "\\" + DISABLED, name):
        reg.delete_value(hive, path + "\\" + DISABLED, name)


def delete(e: Entry, reg: Registry, scheduler: Scheduler | None = None) -> None:
    """Gone for good (a Startup file to the Recycle Bin). Services: the service's registry key goes, as Autoruns
    does: Windows forgets the service after a restart."""
    if e.locked:
        raise PermissionError(1, f"{e.name} can't be deleted: Windows needs it")
    r = e.ref
    if e.kind == "value":
        reg.delete_value(r["hive"], r["path"] if e.enabled else r["path"] + "\\" + DISABLED, r["name"])
    elif e.kind == "key":
        reg.delete_key(r["hive"], f"{r['path']}\\{r['name']}" if e.enabled else
                       f"{r['path']}\\{DISABLED}\\{r['name']}")
    elif e.kind == "file":
        trash.send(os.path.join(r["folder"], r["name"]) if e.enabled else os.path.join(r["folder"], DISABLED, r["name"]))
    elif e.kind == "task":
        (scheduler or Scheduler()).delete(r["path"])
    elif e.kind == "service":
        reg.delete_key("HKLM", rf"SYSTEM\CurrentControlSet\Services\{r['name']}")
    elif e.kind == "list":
        if e.enabled:
            live, kind, raw = _list_get(reg, r["hive"], r["path"], r["name"], r["sep"])
            _list_put(reg, r["hive"], r["path"], r["name"], [x for x in live if x != r["item"]], kind, r["sep"], raw)
        else:
            dis, _, _ = _list_get(reg, r["hive"], r["path"] + "\\" + DISABLED, r["name"], None)
            rest = [x for x in dis if x != r["item"]]
            if rest:
                reg.set(r["hive"], r["path"] + "\\" + DISABLED, r["name"], rest, MULTI_SZ)
            else:
                reg.delete_value(r["hive"], r["path"] + "\\" + DISABLED, r["name"])


# --------------------------------------------------------------------------- file details, signatures
def fill_details(entries: list[Entry], checker=None) -> None:
    from . import winver
    for e in entries:
        d = winver.details(e.image) if e.image else {}
        e.description = e.description or d.get("description", "")
        e.company = d.get("company", "")
        e.version = d.get("version", "")
    if checker is not None:
        sigs = checker.check([e.image for e in entries if e.image])
        for e in entries:
            s = sigs.get(e.image)
            if s is not None:
                e.verified, e.signer, e.os_file = s.verified, s.signer, s.os_file


# --------------------------------------------------------------------------- snapshots
SNAPSHOT_EXT = ".pr7ar"


def save_snapshot(entries: list[Entry], path: str) -> None:
    data = {"pr7ar": 1, "saved": time.time(), "entries": [
        {k: v for k, v in asdict(e).items() if k not in ("ref",)} for e in entries]}
    tmp = path + ".part"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f)
    os.replace(tmp, path)


def load_snapshot(path: str) -> tuple[float, list[Entry]]:
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict) or "entries" not in data:
        raise ValueError("not a PR7-AR snapshot")
    known = Entry.__dataclass_fields__
    out = [Entry(**{k: v for k, v in d.items() if k in known}, ref={}) for d in data["entries"]]
    return float(data.get("saved", 0)), out


def compare(now: list[Entry], then: list[Entry]) -> tuple[set[str], list[Entry]]:
    """(keys of entries new since the snapshot or with another command, entries the snapshot had that are gone)."""
    old = {e.key(): e for e in then}
    new = {e.key() for e in now if e.key() not in old or old[e.key()].command != e.command}
    have = {e.key() for e in now}
    return new, [e for k, e in old.items() if k not in have]
