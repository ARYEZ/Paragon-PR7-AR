# Paragon PR7-AR: notes for Claude

**Paragon PR7-AR** is the owner's personal startup manager: Python (**PySide6**) that **works the way Autoruns works**,
in the Paragon family look (PR7-Z ... PR7-HB, PR7-FS `ARYEZ/Paragon-PR7-FS`). Windows 10/11 x64 is the target; it runs
on Linux for tests. The owner writes Python; explain the why.

## How it's built

- `pr7ar/registry.py` (no Qt): one interface (`subkeys`, `values`, `get`, `set`, `delete_value`, `delete_key`,
  `key_time`, `move_value`, `move_key`): `WinRegistry` (winreg, 64-bit view) and `MemRegistry` (tests; `denied`
  simulates missing admin rights). `DISABLED` = "AutorunsDisabled".
- `pr7ar/tasks.py` (no Qt): schtasks.exe; the list is `/query /xml ONE` (XML names don't change with Windows'
  language, the CSV's do), `parse` pairs each `<!-- \name -->` with its `<Task>`; `/change /enable|/disable`,
  `/delete /f`; the runner is injectable (tests: recorded XML, commands kept).
- `pr7ar/entries.py` (no Qt): `Places` (Windows folder, Startup folders, PATH, env; tests use a made-up Windows),
  `resolve` (command line -> program file: quotes, %VARS%, \SystemRoot\, \??\, unquoted spaces, rundll32's DLL, bare
  names via System32 / Windows / PATH), `collect` (every tab's locations: Run keys, Load, Startup folders with
  `lnk.py` (PR7-E's .lnk reader), ContextMenuHandlers / overlay icons via CLSID -> InprocServer32, tasks (ComHandler
  -> CLSID DLL), services / drivers (Start 0-2, or 4 with our saved start; svchost's ServiceDll), Drivers32, BootExecute,
  IFEO Debugger, AppInit_DLLs, Winlogon Userinit / Shell, print monitors, LSA packages, network providers, Office
  add-ins). Kinds and **Autoruns' switch-off places**: value -> `<key>\AutorunsDisabled`, key -> `<parent>\AutorunsDisabled\
  <key>`, file -> `<folder>\AutorunsDisabled`, list item -> removed and kept in `<key>\AutorunsDisabled` (MULTI_SZ),
  task -> schtasks, service -> Start 4 + "PR7-AR Start". `locked`: userinit / explorer / autocheck. `delete` (services:
  the key; files: `trash.send`). `Entry.windows` = OS file / signed "Microsoft Windows" (tasks under \Microsoft\Windows\
  unless unverified). Snapshots: `save_snapshot` / `load_snapshot` (.pr7ar JSON), `compare` -> (new keys, gone).
- `pr7ar/signatures.py` (no Qt): one PowerShell Get-AuthenticodeSignature run per refresh (catalog signatures too),
  cached by path + size + time in <data>/signatures.json; `run=` injectable. `winver.py` (PR7-SM's) for descriptions.
  <data> = %APPDATA%\Paragon\PR7-AR (**PR7AR_DATA** in tests); **PR7AR_TRASH** points the Recycle Bin at a folder.
- `pr7ar/main_window.py`: `EntryModel` (plain list of group / entry / gone rows; checkboxes via CheckStateRole ->
  `toggle`), `Tint` delegate (the theme's ::item rules hide item backgrounds; the selected row keeps the band), tabs,
  filter, Hide Windows entries (saved), compare banner, details, jump to entry (Regedit's LastKey) / file (PR7-E),
  Properties (ShellExecuteEx "properties"), As Admin (ShellExecuteW runas). Loading in two steps on threads (entries,
  then signatures; inline when `sync`). `_ask` / `answers` / `said`; `answers["run"]`, `["launch"]`, `["elevate"]`.
- `pr7ar/app.py`: one window per user (QLocalSocket, PR7-R's Windows fix); command-line modes never let an error escape
  (PR7-IS's lesson); `--selftest OUT.json` (the real entries, then its own HKCU Run entry off / on / deleted; CI).
- Tests: `tests/test_windows.py` runs only on Windows CI: a real HKCU Run entry, a real scheduled task (schtasks
  /create), real signatures; each cleans up in `finally`.
- Installer `installer/pr7ar.iss` (per user, AppId {5DD7DA56-83DC-421E-8D0F-E7FB868B3860} permanent); CI installs it,
  `tools/verify_install.py installed|uninstalled`. Spec: file details, no UPX, PyInstaller's bootloader built in CI,
  Defender scan.
- Updates: `pr7ar/updates.py` / `update_ui.py` (the family's files, keep them in step; with PR7-U installed,
  update_ui offers it); `family.py`: the family's AppIds (PR7-AR included).
- `pr7ar/finish.py` (no Qt): the family's finish (OBSIDIAN / AURORA), one choice for every app:
  HKCU\Software\Paragon\Family "Finish" (a file elsewhere; PARAGON_FAMILY_FILE in tests, conftest). `finish.start`
  at start-up, `set_finish` saves it, app.py's 2 s timer `finish.follow`s another app's switch. The same file in every
  family app: keep them in step.

## The look (family rules)

- Theme is PR7-FS's (OBSIDIAN + AURORA). Colours: the family's only (Autoruns' yellow / pink / green are orange /
  pink / pearl here); Inter; labels UPPER CASE.
- The PR7-AR mark: PR7 `Logo.cpp` geometry plus A (new, the P's bowl with legs) and R (PR7's); icon "7AR" by
  `tools/make_icon.py`, wizard art by `tools/make_installer_art.py`. Mock-up: `tools/mockup.py`. Check visuals with
  `QT_SCALE_FACTOR=2 python tools/screenshots.py OUT` (a made-up Windows).

## Rules

- Behaviour questions: do what Autoruns does (tabs, colours, switch-off places, jumps, compare).
- Tests: `python -m pytest` (offscreen) on an in-memory registry, real folders and recorded schtasks; Windows CI adds
  the real registry / tasks / signatures. Never the real settings, data folder or Recycle Bin (conftest), or, outside
  CI, the real registry.
- Releases: bump `__version__` in `pr7ar/__init__.py` and add a `## x.y.z` section to CHANGELOG.md, then push: CI
  publishes that version by itself once every check has passed. Run workflow / `v*` tags still work.
