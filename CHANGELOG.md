# Changelog

## 0.2.0

PR7-AR runs on Linux (PR7-OS), with Autoruns' tabs filled from Linux's places:
- **Logon**: autostart entries, yours and the system's (another desktop's, like GNOME's, left out: they never run here).
- **Services**: systemd services, the system's and your own; **Scheduled Tasks**: systemd timers, /etc/crontab,
  /etc/cron.d, your crontab and the scripts in /etc/cron.daily and the like; **Drivers**: kernel modules loaded at boot.
- **Switching off is each place's own way**, so switching back on restores it and the entry stays listed, unticked:
  autostart entries get Hidden=true (a system one through your own copy of the same name: no password needed), units are
  disabled with systemctl, cron lines are commented out with Autoruns' AutorunsDisabled mark, cron scripts stop being
  executable. What belongs to the system asks for your password (pkexec). The system's essential parts (systemd's own,
  D-Bus, the login screen, the session) can't be switched off; package-owned entries can't be deleted (switch them off,
  or remove the program with PR7-UN).
- Jump to Entry opens the file in PR7-W; "Hide Windows entries" is "Hide system entries" there.
Nothing changes on Windows.

## 0.1.3

- The family list (`family.py`) knows the three newest Paragon apps: PR7-HW (hardware information), PR7-BK
  (backups) and PR7-TM (terminal), so links between the apps and the PR7-U offer find them.

## 0.1.2

- The family list (`family.py`) knows the four newest Paragon apps: PR7-HX (hex editor), PR7-DB (SQLite browser),
  PR7-UN (uninstaller) and PR7-LN (launcher), so links between the apps and the PR7-U offer find them.

## 0.1.1

- The family's list knows the newest apps (PR7-HB, PR7-FS, PR7-AR, PR7-WM), so links between apps and Check for Updates find them.

## 0.1.0

- First release: a startup manager that works the way Autoruns works.
- Fifteen tabs of startup locations; every entry's program, description, publisher (signatures checked by Windows,
  catalogs included) and time; unverified publishers pink, missing files orange; Hide Windows entries.
- Switch entries off and on the Autoruns way (shared with Autoruns), delete them, jump to the key or the file.
- Snapshots: save, and compare later (what's new, what's gone).
- As Admin for machine-wide entries; one finish for the whole family (OBSIDIAN / AURORA), Check for updates, and
  PR7-U knows it.
