"""Mock-up pictures of PR7-AR, drawn offscreen with real Qt widgets in the family theme (every entry is made up):
QT_SCALE_FACTOR=2 python tools/mockup.py OUT_DIR

1_everything.png   the Everything tab: every place Windows starts things from, grouped by registry key / folder, each
                   entry with its checkbox (unticked = switched off, not deleted), publisher and file; unverified
                   publishers pink, missing files orange; the selected entry's details below (OBSIDIAN)
2_tasks.png        the Scheduled Tasks tab, Windows' own entries hidden, a filter typed (AURORA)
3_compare.png      Compare with a saved snapshot: what's new since then (pearl) and what's gone (OBSIDIAN)
"""
import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from PySide6.QtCore import QSize, Qt  # noqa: E402
from PySide6.QtGui import QBrush, QColor, QFont  # noqa: E402
from PySide6.QtWidgets import (QApplication, QCheckBox, QFrame, QGridLayout, QHBoxLayout, QHeaderView,  # noqa: E402
                               QLabel, QLineEdit, QStyledItemDelegate, QTabBar, QTreeWidget, QTreeWidgetItem,
                               QVBoxLayout, QWidget)


class Tint(QStyledItemDelegate):
    """Paints a row's tint itself: the theme's ::item rules make Qt ignore item backgrounds (PR7-SM's lesson)."""

    def paint(self, painter, option, index):
        b = index.data(Qt.ItemDataRole.BackgroundRole)
        if isinstance(b, QBrush) and b.style() != Qt.BrushStyle.NoBrush:
            painter.fillRect(option.rect, b)
        super().paint(painter, option, index)

from pr7ar import theme, widgets  # noqa: E402

out = Path(sys.argv[1] if len(sys.argv) > 1 else "docs/mockup")
out.mkdir(parents=True, exist_ok=True)
app = QApplication([])
theme.load_fonts()
app.setFont(QFont("Inter", 10))

TABS = ["EVERYTHING", "LOGON", "EXPLORER", "SCHEDULED TASKS", "SERVICES", "DRIVERS", "CODECS", "BOOT EXECUTE",
        "IMAGE HIJACKS", "WINLOGON", "WINSOCK", "PRINT MONITORS", "LSA", "WMI", "OFFICE"]


def style():
    app.setPalette(theme.palette())
    app.setStyleSheet(theme.stylesheet())


def field(text):
    lab = QLabel(text.upper())
    lab.setProperty("role", "field")
    return lab


def dim(text):
    lab = QLabel(text)
    lab.setProperty("role", "dim")
    return lab


def toolbar(groups, right=None):
    bar = QWidget()
    lay = QHBoxLayout(bar)
    lay.setContentsMargins(16, 10, 16, 6)
    lay.setSpacing(6)
    for i, group in enumerate(groups):
        if i:
            sep = QLabel()
            sep.setFixedSize(1, 40)
            sep.setStyleSheet(f"background: {theme.PANEL_EDGE};")
            lay.addSpacing(8)
            lay.addWidget(sep)
            lay.addSpacing(8)
        for icon, label in group:
            k = widgets.KeyButton(icon, label)
            k.setFixedSize(QSize(100, 62))
            lay.addWidget(k)
    lay.addStretch(1)
    if right is not None:
        lay.addWidget(right)
    return bar


def search_box(text=""):
    w = QWidget()
    lay = QHBoxLayout(w)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.addWidget(field("Filter"))
    e = QLineEdit(text)
    e.setPlaceholderText("names, publishers, paths")
    e.setFixedWidth(280)
    lay.addWidget(e)
    hide = QCheckBox("Hide Windows entries")
    hide.setChecked(True)
    lay.addWidget(hide)
    return w


def tabbar(current):
    t = QTabBar()
    t.setExpanding(False)
    t.setDrawBase(False)
    for name in TABS:
        t.addTab(name)
    t.setCurrentIndex(TABS.index(current))
    t.setStyleSheet("QTabBar::tab { padding: 6px 11px; font-size: 10.5px; }")
    holder = QWidget()
    lay = QHBoxLayout(holder)
    lay.setContentsMargins(16, 0, 16, 0)
    lay.addWidget(t)
    lay.addStretch(1)
    return holder


UNSIGNED = "#D6457E"          # family pink: the publisher can't be verified
MISSING = theme.LED_ORANGE    # the file the entry starts isn't there
NEW = "#E8E8EA"               # pearl: new since the snapshot


def tint(item, colour, cols=6, alpha=0.18):
    c = QColor(colour)
    c.setAlphaF(alpha)
    for i in range(cols):
        item.setBackground(i, QBrush(c))


def entries_tree(groups, columns=("AUTORUN ENTRY", "DESCRIPTION", "PUBLISHER", "IMAGE PATH", "TIMESTAMP")):
    t = QTreeWidget()
    t.setColumnCount(len(columns))
    t.setHeaderLabels(list(columns))
    t.setRootIsDecorated(False)
    t.setIndentation(0)
    t.setIconSize(QSize(18, 18))
    t.setUniformRowHeights(True)
    t.setItemDelegate(Tint(t))
    h = t.header()
    h.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
    h.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
    h.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
    h.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
    h.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
    selected = None
    for location, rows in groups:
        g = QTreeWidgetItem([location])
        g.setFirstColumnSpanned(True)
        f = QFont("Inter", 10)
        f.setWeight(QFont.Weight.DemiBold)
        g.setFont(0, f)
        g.setForeground(0, QColor(theme.TEXT_DIM))
        g.setIcon(0, widgets.line_icon("registry" if location.startswith("HK") else "open", theme.TEXT_DIM))
        c = QColor(theme.PANEL_EDGE)
        c.setAlphaF(.55)
        for i in range(len(columns)):
            g.setBackground(i, QBrush(c))
        t.addTopLevelItem(g)
        g.setFirstColumnSpanned(True)
        for row in rows:
            name, desc, pub, path, when, state = row[:6]
            it = QTreeWidgetItem(["     " + name, desc, pub, path, when])
            it.setFlags(it.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            it.setCheckState(0, Qt.CheckState.Unchecked if "off" in state else Qt.CheckState.Checked)
            it.setIcon(0, widgets.file_icon("file", 18))
            if "unsigned" in state:
                tint(it, UNSIGNED, len(columns))
            if "missing" in state:
                tint(it, MISSING, len(columns), .22)
                it.setText(3, "File not found: " + path)
            if "new" in state:
                tint(it, NEW, len(columns), .14)
            if "gone" in state:
                for i in range(len(columns)):
                    it.setForeground(i, QColor(theme.TEXT_DIM))
                    fn = it.font(i)
                    fn.setStrikeOut(True)
                    it.setFont(i, fn)
            t.addTopLevelItem(it)
            if "selected" in state:
                selected = it
    if selected is not None:
        t.setCurrentItem(selected)
    return t


def details(name, desc, pub, ver, size, when, path, cmd, verified):
    f = QFrame()
    f.setObjectName("details")
    f.setStyleSheet(f"QFrame#details {{ background: {theme.DOCK_TOP}; border-top: 1px solid {theme.PANEL_EDGE}; }}")
    g = QGridLayout(f)
    g.setContentsMargins(18, 12, 18, 12)
    g.setHorizontalSpacing(16)
    g.setVerticalSpacing(6)
    title = QLabel(name)
    title.setStyleSheet("font-size: 14px; font-weight: 600;")
    g.addWidget(title, 0, 0, 1, 2)
    g.addWidget(dim(desc), 0, 2, 1, 2)
    rows = [("Publisher", pub + ("   ·   verified" if verified else "   ·   NOT VERIFIED")), ("Version", ver),
            ("Size", size), ("Time", when), ("Image", path), ("Command", cmd)]
    for i, (k, v) in enumerate(rows):
        g.addWidget(field(k), 1 + i % 3, (i // 3) * 2)
        lab = QLabel(v)
        if k == "Publisher" and not verified:
            lab.setStyleSheet(f"color: {UNSIGNED}; font-weight: 600;")
        g.addWidget(lab, 1 + i % 3, (i // 3) * 2 + 1)
    g.setColumnStretch(3, 1)
    return f


def window(subtitle, tab, tree, bottom=None, search="", extra=None, status="Ready  ·  318 entries, 41 shown "
           "(Windows entries hidden)  ·  2 unverified  ·  1 file missing"):
    w = QWidget()
    w.setObjectName("win")
    w.setStyleSheet(f"QWidget#win {{ background: {theme.BACKGROUND}; }}")
    lay = QVBoxLayout(w)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(0)
    lay.addWidget(widgets.Header(subtitle))
    lay.addWidget(toolbar([[("refresh", "Refresh"), ("file", "Save"), ("compare", "Compare")],
                           [("registry", "Jump to Entry"), ("jump", "Jump to File"), ("trash", "Delete")],
                           [("shield", "As Admin")]], search_box(search)))
    if extra is not None:
        lay.addWidget(extra)
    lay.addWidget(tabbar(tab))
    holder = QWidget()
    hl = QVBoxLayout(holder)
    hl.setContentsMargins(16, 0, 16, 0)
    hl.addWidget(tree)
    lay.addWidget(holder, 1)
    if bottom is not None:
        lay.addWidget(bottom)
    bar = QFrame()
    bar.setStyleSheet(f"QFrame {{ background: {theme.TAB_FRAME}; border-top: 1px solid {theme.PANEL_EDGE}; }}")
    sl = QHBoxLayout(bar)
    sl.setContentsMargins(16, 6, 16, 6)
    sl.addWidget(dim(status))
    sl.addStretch(1)
    key = QLabel(f"<span style='color:{UNSIGNED}'>■</span> unverified publisher     "
                 f"<span style='color:{MISSING}'>■</span> file not found     "
                 f"<span style='color:{theme.TEXT_DIM}'>☐</span> switched off")
    key.setStyleSheet(f"color: {theme.TEXT_DIM}; font-size: 11px;")
    sl.addWidget(key)
    lay.addWidget(bar)
    w.resize(1320, 840)
    return w


EVERYTHING = [
    ("HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Run", [
        ("Discord", "Discord", "Discord Inc.", r"C:\Users\Studio\AppData\Local\Discord\Update.exe", "2026-11-02 21:14", ""),
        ("OneDrive", "Microsoft OneDrive", "Microsoft Corporation", r"C:\Program Files\Microsoft OneDrive\OneDrive.exe",
         "2026-10-28 09:02", ""),
        ("Paragon PR7-CB", "Paragon PR7-CB clipboard history", "Paragon",
         r"C:\Users\Studio\AppData\Local\Programs\PR7-CB\PR7-CB.exe", "2026-11-25 13:10", "unsigned"),
        ("Spotify", "Spotify", "Spotify AB", r"C:\Users\Studio\AppData\Roaming\Spotify\Spotify.exe", "2026-11-19 18:40",
         "off")]),
    ("HKLM\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\Run", [
        ("RtkAudUService", "Realtek HD Audio Universal Service", "Realtek Semiconductor Corp.",
         r"C:\Windows\System32\DriverStore\FileRepository\realtekservice.inf_amd64\RtkAudUService64.exe",
         "2026-06-14 11:20", ""),
        ("SecurityHealth", "Windows Security notification icon", "Microsoft Corporation",
         r"C:\Windows\System32\SecurityHealthSystray.exe", "2026-10-09 03:12", ""),
        ("UpdaterHelper", "", "", r"C:\ProgramData\UpdHelper\upd_helper.exe", "2026-11-24 23:51",
         "unsigned selected")]),
    ("C:\\Users\\Studio\\AppData\\Roaming\\Microsoft\\Windows\\Start Menu\\Programs\\Startup", [
        ("Paragon PR7-Q.lnk", "Paragon PR7-Q screenshots", "Paragon",
         r"C:\Users\Studio\AppData\Local\Programs\PR7-Q\PR7-Q.exe", "2026-11-25 13:09", "unsigned"),
        ("OldTool.lnk", "", "", r"D:\Tools\OldTool\oldtool.exe", "", "missing")]),
    ("Task Scheduler", [
        ("\\Paragon\\PR7-IS Index", "Paragon PR7-IS file search", "Paragon",
         r"C:\Users\Studio\AppData\Local\Programs\PR7-IS\PR7-IS.exe", "2026-11-25 13:11", "unsigned"),
        ("\\GoogleUpdateTaskMachineUA", "Google Installer", "Google LLC",
         r"C:\Program Files (x86)\Google\Update\GoogleUpdate.exe", "2026-09-30 17:05", "")]),
    ("HKLM\\System\\CurrentControlSet\\Services", [
        ("Blackmagic Desktop Video", "Blackmagic Design Desktop Video Helper", "Blackmagic Design Pty. Ltd.",
         r"C:\Program Files\Blackmagic Design\Desktop Video\DesktopVideoHelper.exe", "2026-08-11 10:44", ""),
        ("NVDisplay.ContainerLocalSystem", "NVIDIA Display Container LS", "NVIDIA Corporation",
         r"C:\Windows\System32\DriverStore\FileRepository\nv_dispi.inf_amd64\Display.NvContainer\NVDisplay.Container.exe",
         "2026-11-12 22:30", "")]),
]

TASKS = [
    ("Task Scheduler", [
        ("\\Paragon\\PR7-IS Index", "Paragon PR7-IS file search", "Paragon",
         r"C:\Users\Studio\AppData\Local\Programs\PR7-IS\PR7-IS.exe --index-service", "2026-11-25 13:11", "unsigned"),
        ("\\Paragon\\PR7-FS Nightly", "Paragon PR7-FS folder sync", "Paragon",
         r"C:\Users\Studio\AppData\Local\Programs\PR7-FS\PR7-FS.exe --batch D:\Backup.pr7fs", "2026-11-25 17:30",
         "unsigned selected"),
        ("\\GoogleUpdateTaskMachineCore", "Google Installer", "Google LLC",
         r"C:\Program Files (x86)\Google\Update\GoogleUpdate.exe /c", "2026-09-30 17:05", ""),
        ("\\GoogleUpdateTaskMachineUA", "Google Installer", "Google LLC",
         r"C:\Program Files (x86)\Google\Update\GoogleUpdate.exe /ua /installsource scheduler", "2026-09-30 17:05", ""),
        ("\\Adobe Acrobat Update Task", "Adobe Acrobat Update Service", "Adobe Inc.",
         r"C:\Program Files (x86)\Common Files\Adobe\ARM\1.0\AdobeARM.exe", "2026-07-21 08:12", "off"),
        ("\\OneDrive Reporting Task", "Microsoft OneDrive", "Microsoft Corporation",
         r"C:\Users\Studio\AppData\Local\Microsoft\OneDrive\OneDriveStandaloneUpdater.exe /reporting",
         "2026-10-28 09:02", "")]),
]

COMPARE = [
    ("HKLM\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\Run", [
        ("UpdaterHelper", "", "", r"C:\ProgramData\UpdHelper\upd_helper.exe", "2026-11-24 23:51", "unsigned new selected"),
        ("SecurityHealth", "Windows Security notification icon", "Microsoft Corporation",
         r"C:\Windows\System32\SecurityHealthSystray.exe", "2026-10-09 03:12", "")]),
    ("HKLM\\System\\CurrentControlSet\\Services", [
        ("UpdHelperSvc", "", "", r"C:\ProgramData\UpdHelper\upd_svc.exe", "2026-11-24 23:51", "unsigned new"),
        ("TeamViewer", "TeamViewer", "TeamViewer Germany GmbH", r"C:\Program Files\TeamViewer\TeamViewer_Service.exe",
         "2026-05-02 14:20", "gone")]),
    ("Task Scheduler", [
        ("\\Paragon\\PR7-FS Nightly", "Paragon PR7-FS folder sync", "Paragon",
         r"C:\Users\Studio\AppData\Local\Programs\PR7-FS\PR7-FS.exe --batch D:\Backup.pr7fs", "2026-11-25 17:30",
         "unsigned new")]),
]


def compare_banner():
    f = QFrame()
    f.setObjectName("banner")
    f.setStyleSheet(f"QFrame#banner {{ background: {theme.DOCK_TOP}; border-top: 1px solid {theme.PANEL_EDGE}; "
                    f"border-bottom: 1px solid {theme.PANEL_EDGE}; }}")
    lay = QHBoxLayout(f)
    lay.setContentsMargins(18, 8, 18, 8)
    lay.addWidget(field("Comparing with"))
    lay.addWidget(QLabel("before-update.pr7ar  ·  saved 2026-11-20 19:02"))
    lay.addSpacing(20)
    lay.addWidget(QLabel(f"<span style='color:{theme.TEXT}'>3 new</span>   ·   "
                         f"<span style='color:{theme.TEXT_DIM}'>1 gone</span>   ·   only changes shown"))
    lay.addStretch(1)
    lay.addWidget(dim("Esc stops comparing"))
    return f


def shoot(widget, name):
    widget.show()
    app.processEvents()
    widget.grab().save(str(out / name))
    widget.close()


theme.set_finish("obsidian")
style()
shoot(window("STARTUP", "EVERYTHING", entries_tree(EVERYTHING),
             details("UpdaterHelper", "(no description)", "(no publisher)", "(none)", "1.2 MB",
                     "2026-11-24 23:51 (yesterday)", r"C:\ProgramData\UpdHelper\upd_helper.exe",
                     r'"C:\ProgramData\UpdHelper\upd_helper.exe" /silent /startup', False)), "1_everything.png")
theme.set_finish("aurora")
style()
google = [(loc, [r for r in rows if "google" in " ".join(r[:4]).lower()]) for loc, rows in TASKS]
shoot(window("STARTUP", "SCHEDULED TASKS", entries_tree(google), search="google",
             status="Ready  ·  47 scheduled tasks, 2 match \"google\" (Windows entries hidden)"), "2_tasks.png")
theme.set_finish("obsidian")
style()
shoot(window("STARTUP", "EVERYTHING", entries_tree(COMPARE), extra=compare_banner()), "3_compare.png")
print("ok", out)
