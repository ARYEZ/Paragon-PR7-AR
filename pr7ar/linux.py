"""PR7-AR on Linux (PR7-OS): Autoruns' tabs filled with Linux's places, read from the files (no Qt):

    Logon            XDG autostart: yours (~/.config/autostart) and the system's (/etc/xdg/autostart)
    Services         systemd services: the system's (enabled = a link in a *.wants folder) and yours (systemd --user)
    Scheduled Tasks  systemd timers, /etc/crontab, /etc/cron.d, your crontab, the scripts in /etc/cron.{hourly...}
    Drivers          kernel modules loaded at boot (/etc/modules, /etc/modules-load.d)

Switching off is each place's own way, so it can be switched on again and the entry stays listed, unticked:
autostart entries get Hidden=true (a system one: your own copy of the same name saying Hidden=true, the standard
override; no root), units `systemctl [--user] disable` (PR7-AR remembers them in <data>/linux-disabled.json so they stay
listed), cron lines are commented out with Autoruns' word ("#AutorunsDisabled "), cron scripts lose their execute bit
(run-parts skips them), module lines are commented out. What belongs to the system needs administrator rights: those go
through `root_run` (pkexec; tests record them). Essential parts of the system (systemd's own units, D-Bus, the login
screen, the session) are `locked`, as Autoruns locks Windows' own.

`Linux(places)` with a made-up root in tests; `run` / `root_run` / `crontab` are injectable.
"""
from __future__ import annotations

import json
import os
import re
import shlex
import shutil
import stat
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from .entries import DISABLED, Entry

CRON_OFF = "#" + DISABLED + " "
LOCKED = re.compile(r"^(systemd-|dbus|getty@|serial-getty@|sddm|display-manager|plasma-|polkit|udisks2|upower|"
                    r"NetworkManager\.service|wpa_supplicant|accounts-daemon|rtkit|pipewire|wireplumber|kwin|cron\.)")


@dataclass
class LinuxPlaces:
    root: Path = Path("/")                 # the system's files (tests: a made-up one)
    config_home: Path = field(default_factory=lambda: Path(os.environ.get("XDG_CONFIG_HOME")
                                                           or Path.home() / ".config"))
    data: Path = field(default_factory=lambda: Path(os.environ.get("PR7AR_DATA")
                                                    or Path.home() / ".local/share/Paragon/PR7-AR"))

    def sys(self, path: str) -> Path:
        return self.root / path.lstrip("/")


def _desktop(text: str) -> dict[str, str]:
    out, inside = {}, False
    for line in text.splitlines():
        s = line.strip()
        if s.startswith("["):
            inside = s == "[Desktop Entry]"
        elif inside and "=" in s and not s.startswith("#"):
            k, v = s.split("=", 1)
            if "[" not in k:
                out[k.strip()] = v.strip()
    return out


def _unit(text: str) -> dict[str, str]:
    out = {}
    for line in text.splitlines():
        s = line.strip()
        if "=" in s and not s.startswith(("#", ";", "[")):
            k, v = s.split("=", 1)
            out.setdefault(k.strip(), v.strip())
    return out


def image_of(command: str) -> str:
    """The program a command line starts: its first word, found on PATH ("-" and "@" prefixes of systemd dropped)."""
    try:
        words = shlex.split(command)
    except ValueError:
        words = command.split()
    words = [w for w in words if not re.fullmatch(r"\w+=.*", w)]          # VAR=value before the program
    if not words:
        return ""
    first = words[0].lstrip("-@+!:")
    if first in ("env", "sh", "bash", "/bin/sh", "/usr/bin/env") and len(words) > 1:
        return image_of(" ".join(shlex.quote(w) for w in words[1:]))
    return first if first.startswith("/") else (shutil.which(first) or first)


class Linux:
    def __init__(self, places: LinuxPlaces | None = None, run=subprocess.run, root_run=None, crontab=None,
                 desktop: str = "KDE"):
        self.places = places or LinuxPlaces()
        self.run = run
        self.root_run = root_run or self._pkexec
        self.crontab = crontab or self._crontab
        self.desktop = desktop

    # ---------------------------------------------------------------- administrator rights, your crontab
    def _pkexec(self, args: list[str], input: str | None = None) -> None:
        done = self.run(["pkexec", *args], input=input, capture_output=True, text=True)
        if done.returncode in (126, 127):
            raise PermissionError(1, "administrator rights weren't given")
        if done.returncode:
            raise OSError(done.returncode, (done.stderr or done.stdout or "failed").strip())

    def _crontab(self, text: str | None = None) -> str:
        """Your crontab (text=None reads it; otherwise it's replaced by text)."""
        if text is None:
            done = self.run(["crontab", "-l"], capture_output=True, text=True)
            return done.stdout if done.returncode == 0 else ""
        self.run(["crontab", "-"], input=text, capture_output=True, text=True, check=True)
        return text

    def _write(self, path: Path, text: str, system: bool) -> None:
        if system:
            self.root_run(["tee", str(path)], input=text)
        else:
            path.write_text(text, encoding="utf-8")

    def _disabled_units(self) -> dict:
        try:
            return json.loads((self.places.data / "linux-disabled.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def _remember(self, key: str, on: bool) -> None:
        d = self._disabled_units()
        if on:
            d.pop(key, None)
        else:
            d[key] = True
        self.places.data.mkdir(parents=True, exist_ok=True)
        (self.places.data / "linux-disabled.json").write_text(json.dumps(d), encoding="utf-8")

    # ---------------------------------------------------------------- reading
    def collect(self) -> list[Entry]:
        out: list[Entry] = []
        out += self._autostart()
        out += self._units(user=False)
        out += self._units(user=True)
        out += self._cron()
        out += self._modules()
        for e in out:
            e.os_file = bool(e.image) and e.image.startswith(("/usr/", "/lib/", "/bin/", "/sbin/"))
            e.signer = "Debian package" if e.os_file else ""
        return out

    def _autostart(self) -> list[Entry]:
        system_dir = self.places.sys("/etc/xdg/autostart")
        user_dir = self.places.config_home / "autostart"
        names = set()
        for d in (system_dir, user_dir):
            if d.is_dir():
                names |= {f.name for f in d.glob("*.desktop")}
        out = []
        for name in sorted(names):
            sys_f, user_f = system_dir / name, user_dir / name
            sys_k = _desktop(sys_f.read_text(errors="replace")) if sys_f.exists() else {}
            user_k = _desktop(user_f.read_text(errors="replace")) if user_f.exists() else {}
            keys = {**sys_k, **user_k} if user_k.get("Exec") or not sys_k else {**sys_k, **user_k}
            only = [x for x in keys.get("OnlyShowIn", "").split(";") if x]
            if (only and self.desktop not in only) or self.desktop in keys.get("NotShowIn", "").split(";"):
                continue                                         # another desktop's (GNOME's ...): never runs here
            if not keys.get("Exec") and not sys_k:
                continue
            hidden = keys.get("Hidden", "").lower() == "true" or \
                keys.get("X-GNOME-Autostart-enabled", "").lower() == "false"
            where = user_dir if user_k.get("Exec") else system_dir
            out.append(Entry("Logon", str(where), keys.get("Name", name), keys.get("Exec", ""),
                             image_of(keys.get("Exec", "")), not hidden, "xdg",
                             {"name": name, "system": str(sys_f) if sys_f.exists() else "",
                              "user": str(user_f) if user_f.exists() else ""},
                             (user_f if user_f.exists() else sys_f).stat().st_mtime,
                             keys.get("Comment", "")))
        return out

    def _unit_dirs(self, user: bool) -> list[Path]:
        if user:
            return [self.places.config_home / "systemd/user", self.places.sys("/etc/systemd/user"),
                    self.places.sys("/usr/lib/systemd/user")]
        return [self.places.sys("/etc/systemd/system"), self.places.sys("/usr/lib/systemd/system"),
                self.places.sys("/lib/systemd/system")]

    def _unit_file(self, name: str, user: bool) -> Path | None:
        template = re.sub(r"@[^.]*\.", "@.", name)
        for d in self._unit_dirs(user):
            for n in (name, template):
                f = d / n
                if f.exists() and not (f.is_symlink() and os.readlink(f) == "/dev/null"):
                    return f
        return None

    def _units(self, user: bool) -> list[Entry]:
        wants = [self.places.config_home / "systemd/user"] if user else []
        wants.append(self.places.sys("/etc/systemd/user" if user else "/etc/systemd/system"))
        enabled = set()
        for d in wants:
            if d.is_dir():
                for w in d.glob("*.wants"):
                    enabled |= {f.name for f in w.iterdir() if f.name.endswith((".service", ".timer"))}
        scope = "user" if user else "system"
        off = {k.split(":", 1)[1] for k in self._disabled_units() if k.startswith(scope + ":")}
        out = []
        for name in sorted(enabled | off):
            f = self._unit_file(name, user)
            if f is None:
                continue
            k = _unit(f.read_text(errors="replace"))
            command = k.get("ExecStart", "")
            if name.endswith(".timer"):
                target = k.get("Unit") or name[:-6] + ".service"
                tf = self._unit_file(target, user)
                command = _unit(tf.read_text(errors="replace")).get("ExecStart", "") if tf else ""
            tab = "Scheduled Tasks" if name.endswith(".timer") else "Services"
            where = "systemd (you)" if user else "systemd"
            out.append(Entry(tab, where, name, command, image_of(command), name in enabled, "unit",
                             {"name": name, "user": user, "file": str(f)}, f.stat().st_mtime,
                             k.get("Description", ""), locked=bool(LOCKED.match(name)) and not user))
        return out

    def _cron_lines(self, text: str, location: str, ref: dict) -> list[Entry]:
        out = []
        for i, line in enumerate(text.splitlines()):
            s = line.strip()
            on = True
            if s.startswith(CRON_OFF):
                s, on = s[len(CRON_OFF):].strip(), False
            if not s or s.startswith("#") or re.match(r"^[A-Za-z_][A-Za-z0-9_]*\s*=", s):
                continue
            fields = s.split()
            if s.startswith("@"):
                when, rest = fields[0], fields[1:]
            else:
                when, rest = " ".join(fields[:5]), fields[5:]
            if ref.get("system"):                               # system crontabs name the user before the command
                rest = rest[1:]
            command = " ".join(rest)
            out.append(Entry("Scheduled Tasks", location, f"{when}  {command}"[:120], command, image_of(command), on,
                             "cron", {**ref, "line": line}))
        return out

    def _cron(self) -> list[Entry]:
        out = []
        files = [self.places.sys("/etc/crontab")] + sorted(self.places.sys("/etc/cron.d").glob("*")) \
            if self.places.sys("/etc/cron.d").is_dir() else [self.places.sys("/etc/crontab")]
        for f in files:
            if f.is_file() and not f.name.startswith("."):
                out += self._cron_lines(f.read_text(errors="replace"), str(f), {"file": str(f), "system": True})
        mine = self.crontab()
        if mine:
            out += self._cron_lines(mine, "crontab (you)", {"file": "", "system": False})
        for period in ("hourly", "daily", "weekly", "monthly"):
            d = self.places.sys(f"/etc/cron.{period}")
            if d.is_dir():
                for f in sorted(d.iterdir()):
                    if f.is_file() and not f.name.startswith(".") and f.name != "0anacron":
                        out.append(Entry("Scheduled Tasks", str(d), f.name, str(f), str(f),
                                         bool(f.stat().st_mode & stat.S_IXUSR), "cronscript", {"file": str(f)},
                                         f.stat().st_mtime))
        return out

    def _modules(self) -> list[Entry]:
        out = []
        files = [self.places.sys("/etc/modules")]
        d = self.places.sys("/etc/modules-load.d")
        if d.is_dir():
            files += sorted(d.glob("*.conf"))
        for f in files:
            if not f.is_file():
                continue
            for line in f.read_text(errors="replace").splitlines():
                s, on = line.strip(), True
                if s.startswith(CRON_OFF):
                    s, on = s[len(CRON_OFF):].strip(), False
                if not s or s.startswith(("#", ";")):
                    continue
                out.append(Entry("Drivers", str(f), s.split()[0], s, "", on, "module", {"file": str(f), "line": line}))
        return out

    # ---------------------------------------------------------------- switching off and on
    def set_enabled(self, e: Entry, on: bool) -> None:
        if e.enabled == on:
            return
        if e.locked and not on:
            raise PermissionError(1, f"{e.name} can't be switched off: the system needs it")
        r = e.ref
        if e.kind == "xdg":
            self._xdg(r, on)
        elif e.kind == "unit":
            args = ["systemctl"] + (["--user"] if r["user"] else []) + ["enable" if on else "disable", r["name"]]
            if r["user"]:
                self.run(args, capture_output=True, text=True, check=True)
            else:
                self.root_run(args)
            self._remember(("user:" if r["user"] else "system:") + r["name"], on)
        elif e.kind in ("cron", "module"):
            self._line(e, on)
        elif e.kind == "cronscript":
            mode = "u+x,g+x,o+x" if on else "a-x"
            self.root_run(["chmod", mode, r["file"]])
        e.enabled = on

    def _xdg(self, r: dict, on: bool) -> None:
        user = Path(r["user"]) if r["user"] else self.places.config_home / "autostart" / r["name"]
        if not on:
            if user.exists():
                lines = [l for l in user.read_text(errors="replace").splitlines() if not l.startswith("Hidden=")]
                if "[Desktop Entry]" not in lines:
                    lines.insert(0, "[Desktop Entry]")
                lines.insert(lines.index("[Desktop Entry]") + 1, "Hidden=true")
                user.write_text("\n".join(lines) + "\n", encoding="utf-8")
            else:                                     # the system's: your override of the same name
                user.parent.mkdir(parents=True, exist_ok=True)
                user.write_text("[Desktop Entry]\nType=Application\nHidden=true\n", encoding="utf-8")
            r["user"] = str(user)
            return
        keys = _desktop(user.read_text(errors="replace")) if user.exists() else {}
        if r["system"] and not keys.get("Exec"):      # only PR7-AR's override: the system's entry again
            user.unlink(missing_ok=True)
            r["user"] = ""
        elif user.exists():
            lines = [l for l in user.read_text(errors="replace").splitlines()
                     if not l.startswith("Hidden=") and not l.startswith("X-GNOME-Autostart-enabled=false")]
            user.write_text("\n".join(lines) + "\n", encoding="utf-8")

    def _line(self, e: Entry, on: bool) -> None:
        r = e.ref
        if e.kind == "cron" and not r["system"]:
            text = self.crontab()
        else:
            text = Path(r["file"]).read_text(errors="replace")
        old = r["line"]
        new = old.strip()[len(CRON_OFF):] if on and old.strip().startswith(CRON_OFF) else (old if on else CRON_OFF + old.strip())
        lines = text.splitlines()
        if old not in lines:
            raise OSError(2, f"{e.name} changed meanwhile: refresh (F5)")
        lines[lines.index(old)] = new
        text = "\n".join(lines) + "\n"
        if e.kind == "cron" and not r["system"]:
            self.crontab(text)
        else:
            self._write(Path(r["file"]), text, system=True)
        r["line"] = new

    def delete(self, e: Entry) -> None:
        if e.locked:
            raise PermissionError(1, f"{e.name} can't be deleted: the system needs it")
        r = e.ref
        if e.kind == "xdg":
            if r["system"]:
                raise PermissionError(1, f"{e.name} comes with the system: switch it off instead (it stays off), or "
                                         "remove its program with PR7-UN")
            from . import trash
            trash.send(r["user"])
        elif e.kind == "unit":
            if not r["user"] or not str(r["file"]).startswith(str(self.places.config_home)):
                raise PermissionError(1, f"{e.name} comes with a package: switch it off instead, or remove its "
                                         "program with PR7-UN")
            self.run(["systemctl", "--user", "disable", r["name"]], capture_output=True, text=True)
            from . import trash
            trash.send(r["file"])
            self._remember("user:" + r["name"], True)
        elif e.kind in ("cron", "module"):
            if e.kind == "cron" and not r["system"]:
                lines = self.crontab().splitlines()
            else:
                lines = Path(r["file"]).read_text(errors="replace").splitlines()
            if r["line"] not in lines:
                raise OSError(2, f"{e.name} changed meanwhile: refresh (F5)")
            lines.remove(r["line"])
            text = "\n".join(lines) + "\n"
            if e.kind == "cron" and not r["system"]:
                self.crontab(text)
            else:
                self._write(Path(r["file"]), text, system=True)
        elif e.kind == "cronscript":
            self.root_run(["rm", "-f", r["file"]])
