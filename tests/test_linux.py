"""PR7-AR on Linux (PR7-OS): Autoruns' tabs from a made-up Linux (autostart entries, systemd units, cron, modules),
switched off and on the way each place does it, checked on disk. Root's commands go through a stand-in for pkexec
that runs them (`as_root`), so the result is real."""
import os
import subprocess
from pathlib import Path

import pytest

from pr7ar.linux import CRON_OFF, Linux, LinuxPlaces

# cron.* scripts are on / off by their executable bit (run-parts' rule); Windows has none (every file is X_OK there)
needs_exec_bit = pytest.mark.skipif(os.name == "nt", reason="Windows has no executable bit")


def write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


@pytest.fixture
def pc(tmp_path):
    root, home = tmp_path / "root", tmp_path / "home/.config"
    write(root / "etc/xdg/autostart/org.kde.kdeconnect.daemon.desktop",
          "[Desktop Entry]\nName=KDE Connect\nExec=/usr/lib/x86_64-linux-gnu/libexec/kdeconnectd\nComment=Phones\n")
    write(root / "etc/xdg/autostart/gnome-thing.desktop", "[Desktop Entry]\nName=GNOME thing\nExec=gthing\nOnlyShowIn=GNOME;\n")
    write(home / "autostart/myapp.desktop", "[Desktop Entry]\nName=My app\nExec=/home/ari/bin/myapp --tray\n")
    lib = root / "usr/lib/systemd/system"
    write(lib / "cups.service", "[Unit]\nDescription=CUPS Scheduler\n[Service]\nExecStart=/usr/sbin/cupsd -l\n")
    write(lib / "ssh.service", "[Unit]\nDescription=OpenBSD Secure Shell server\n[Service]\nExecStart=/usr/sbin/sshd -D\n")
    write(lib / "systemd-journald.service", "[Unit]\nDescription=Journal\n[Service]\nExecStart=/usr/lib/systemd/systemd-journald\n")
    write(lib / "apt-daily.timer", "[Unit]\nDescription=Daily apt download activities\n[Timer]\nOnCalendar=daily\n")
    write(lib / "apt-daily.service", "[Unit]\nDescription=apt\n[Service]\nExecStart=/usr/lib/apt/apt.systemd.daily update\n")
    wants = root / "etc/systemd/system"
    for target, unit in (("multi-user.target.wants", "cups.service"), ("multi-user.target.wants", "ssh.service"),
                         ("sysinit.target.wants", "systemd-journald.service"), ("timers.target.wants", "apt-daily.timer")):
        (wants / target).mkdir(parents=True, exist_ok=True)
        (wants / target / unit).symlink_to(lib / unit)
    write(home / "systemd/user/syncthing.service", "[Unit]\nDescription=Syncthing\n[Service]\nExecStart=/usr/bin/syncthing serve\n")
    (home / "systemd/user/default.target.wants").mkdir(parents=True)
    (home / "systemd/user/default.target.wants/syncthing.service").symlink_to(home / "systemd/user/syncthing.service")
    write(root / "etc/crontab", "SHELL=/bin/sh\n# m h dom mon dow user command\n17 * * * * root cd / && run-parts --report /etc/cron.hourly\n")
    write(root / "etc/cron.d/backup", "30 2 * * * root /usr/local/bin/backup.sh --quiet\n")
    script = write(root / "etc/cron.daily/logrotate", "#!/bin/sh\n")
    script.chmod(0o755)
    write(root / "etc/modules-load.d/vfio.conf", "# for the GPU\nvfio-pci\n")
    mine = {"text": "@reboot /home/ari/bin/sync-notes\n"}
    root_calls = []

    def as_root(args, input=None):          # pkexec, given the password: runs it
        root_calls.append(args)
        if args[0] == "tee":
            Path(args[1]).write_text(input)
        elif args[:2] == ["systemctl", "disable"]:
            for link in wants.glob(f"*.wants/{args[2]}"):
                link.unlink()
        elif args[:2] == ["systemctl", "enable"]:
            (wants / "multi-user.target.wants").mkdir(exist_ok=True)
            (wants / "multi-user.target.wants" / args[2]).symlink_to(lib / args[2])
        else:
            subprocess.run(args, check=True)

    def crontab(text=None):
        if text is not None:
            mine["text"] = text
        return mine["text"]

    def run(args, **kw):                    # systemctl --user, as the user
        if args[:3] == ["systemctl", "--user", "disable"]:
            (home / "systemd/user/default.target.wants" / args[3]).unlink()
        elif args[:3] == ["systemctl", "--user", "enable"]:
            (home / "systemd/user/default.target.wants" / args[3]).symlink_to(home / "systemd/user" / args[3])
        return subprocess.CompletedProcess(args, 0, "", "")
    lx = Linux(LinuxPlaces(root, home, tmp_path / "data"), run=run, root_run=as_root, crontab=crontab)
    return lx, root, home, root_calls, mine


def by_name(entries):
    return {e.name: e for e in entries}


@needs_exec_bit
def test_every_place_is_read(pc):
    lx, root, home, _, _ = pc
    got = by_name(lx.collect())
    assert "GNOME thing" not in got                                  # another desktop's: never runs on Plasma
    kde = got["KDE Connect"]
    assert (kde.tab, kde.enabled, kde.os_file, kde.description) == ("Logon", True, True, "Phones")
    assert got["My app"].image == "/home/ari/bin/myapp" and not got["My app"].os_file
    assert got["cups.service"].tab == "Services" and got["cups.service"].image == "/usr/sbin/cupsd"
    assert got["systemd-journald.service"].locked and not got["cups.service"].locked
    assert got["apt-daily.timer"].tab == "Scheduled Tasks" and got["apt-daily.timer"].image == "/usr/lib/apt/apt.systemd.daily"
    assert got["syncthing.service"].location == "systemd (you)"
    crons = {e.command for e in got.values() if e.kind == "cron"}
    assert crons == {"cd / && run-parts --report /etc/cron.hourly", "/usr/local/bin/backup.sh --quiet",
                     "/home/ari/bin/sync-notes"}                    # the user field of system crontabs left out
    assert got["logrotate"].enabled and got["vfio-pci"].tab == "Drivers"


def test_autostart_off_and_on(pc):
    lx, root, home, calls, _ = pc
    kde = by_name(lx.collect())["KDE Connect"]
    lx.set_enabled(kde, False)                                       # the system's: your Hidden=true copy, no root
    override = home / "autostart/org.kde.kdeconnect.daemon.desktop"
    assert "Hidden=true" in override.read_text() and calls == []
    assert not by_name(lx.collect())["KDE Connect"].enabled           # still listed, unticked
    lx.set_enabled(by_name(lx.collect())["KDE Connect"], True)
    assert not override.exists() and by_name(lx.collect())["KDE Connect"].enabled
    mine = by_name(lx.collect())["My app"]
    lx.set_enabled(mine, False)
    assert "Hidden=true" in (home / "autostart/myapp.desktop").read_text()
    lx.set_enabled(by_name(lx.collect())["My app"], True)
    assert "Hidden" not in (home / "autostart/myapp.desktop").read_text()
    assert "Exec=/home/ari/bin/myapp --tray" in (home / "autostart/myapp.desktop").read_text()


def test_services_and_timers(pc):
    lx, root, home, calls, _ = pc
    lx.set_enabled(by_name(lx.collect())["cups.service"], False)
    assert calls[-1] == ["systemctl", "disable", "cups.service"]       # with your password
    cups = by_name(lx.collect())["cups.service"]
    assert not cups.enabled                                          # remembered: still listed, unticked
    lx.set_enabled(cups, True)
    assert calls[-1] == ["systemctl", "enable", "cups.service"] and by_name(lx.collect())["cups.service"].enabled
    lx.set_enabled(by_name(lx.collect())["syncthing.service"], False)  # yours: no password
    assert not by_name(lx.collect())["syncthing.service"].enabled and calls[-1][1] == "enable"
    with pytest.raises(PermissionError):
        lx.set_enabled(by_name(lx.collect())["systemd-journald.service"], False)
    with pytest.raises(PermissionError, match="comes with a package"):
        lx.delete(by_name(lx.collect())["cups.service"])


@needs_exec_bit
def test_cron_lines_scripts_and_modules(pc):
    lx, root, home, calls, mine = pc
    got = by_name(lx.collect())
    backup = next(e for e in got.values() if e.command.startswith("/usr/local/bin/backup.sh"))
    lx.set_enabled(backup, False)
    assert (root / "etc/cron.d/backup").read_text() == CRON_OFF + "30 2 * * * root /usr/local/bin/backup.sh --quiet\n"
    back = next(e for e in lx.collect() if e.command.startswith("/usr/local/bin/backup.sh"))
    assert not back.enabled
    lx.set_enabled(back, True)
    assert (root / "etc/cron.d/backup").read_text() == "30 2 * * * root /usr/local/bin/backup.sh --quiet\n"
    notes = next(e for e in lx.collect() if e.command == "/home/ari/bin/sync-notes")
    lx.set_enabled(notes, False)
    assert mine["text"].startswith(CRON_OFF + "@reboot")              # your crontab, through crontab(1)
    lx.delete(next(e for e in lx.collect() if e.command == "/home/ari/bin/sync-notes"))
    assert "sync-notes" not in mine["text"]
    lx.set_enabled(by_name(lx.collect())["logrotate"], False)
    assert not os.access(root / "etc/cron.daily/logrotate", os.X_OK)  # run-parts skips it
    lx.set_enabled(by_name(lx.collect())["vfio-pci"], False)
    assert CRON_OFF + "vfio-pci" in (root / "etc/modules-load.d/vfio.conf").read_text()
    assert not by_name(lx.collect())["vfio-pci"].enabled


def test_deleting_your_own_and_refusing_the_systems(pc, monkeypatch, tmp_path):
    lx, root, home, calls, _ = pc
    monkeypatch.setenv("PR7AR_TRASH", str(tmp_path / "trash"))
    lx.delete(by_name(lx.collect())["My app"])
    assert not (home / "autostart/myapp.desktop").exists() and (tmp_path / "trash/myapp.desktop").exists()
    with pytest.raises(PermissionError, match="comes with the system"):
        lx.delete(by_name(lx.collect())["KDE Connect"])


def test_the_window_shows_linux(pc, qapp):
    from pr7ar.main_window import LINUX_TABS, MainWindow
    lx = pc[0]
    w = MainWindow(sync=True, linux=lx)
    w.refresh()
    assert [w.tabs.tabText(i) for i in range(w.tabs.count())] == [t.upper() for t in LINUX_TABS]
    assert w.hide_windows.text() == "Hide system entries" and not w.keys["admin"].isVisibleTo(w)
    names = {e.name for e in w.all}
    assert {"KDE Connect", "cups.service", "vfio-pci"} <= names
    kde = next(e for e in w.all if e.name == "KDE Connect")
    assert w.toggle(kde, False) and not kde.enabled
    opened = []
    w.answers["launch"] = lambda app, args: opened.append((app, args)) or True
    w.jump_entry(kde)
    assert opened == [("PR7-W", [str(pc[2] / "autostart/org.kde.kdeconnect.daemon.desktop")])]
    w.close()
