"""PR7-AR's window, Autoruns' way: tabs of startup locations, each entry with its checkbox (unticked = switched off, not
deleted), publisher, file and time; unverified publishers pink, missing files orange; the details below. The list is
a plain Python list model of group rows and entry rows (never QStandardItemModel: PR7-Z's crash), tints painted by a
delegate (the theme's ::item rules make Qt ignore item backgrounds: PR7-SM's lesson).

Loading runs on a worker thread in two steps (the entries, then their signatures) unless `sync` is True (tests);
everything that asks goes through `_ask` / `answers`."""

from __future__ import annotations

import os
import subprocess
import sys
import threading
import time

from PySide6.QtCore import QAbstractTableModel, QModelIndex, QObject, QSize, Qt, QUrl, Signal
from PySide6.QtGui import QAction, QActionGroup, QBrush, QColor, QDesktopServices, QFont, QKeySequence
from PySide6.QtWidgets import (QApplication, QCheckBox, QFileDialog, QFrame, QGridLayout, QHBoxLayout, QHeaderView,
                               QLabel, QLineEdit, QMainWindow, QMenu, QMessageBox, QStyledItemDelegate, QTabBar,
                               QTreeView, QVBoxLayout, QWidget)

from . import __version__, entries, family, finish, registry, settings, signatures, tasks, theme, widgets
from .entries import Entry

UNSIGNED = "#D6457E"          # family pink: the publisher can't be verified
NEW = "#E8E8EA"               # pearl: new since the snapshot
REGEDIT_KEY = r"Software\Microsoft\Windows\CurrentVersion\Applets\Regedit"
HIVE_NAMES = {"HKCU": "HKEY_CURRENT_USER", "HKLM": "HKEY_LOCAL_MACHINE"}


def data_dir() -> str:
    d = os.environ.get("PR7AR_DATA") or (
        os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")), "Paragon", "PR7-AR") if sys.platform == "win32"
        else os.path.join(os.path.expanduser("~"), ".local", "share", "paragon", "pr7-ar"))
    os.makedirs(d, exist_ok=True)
    return d


def is_admin() -> bool:
    if sys.platform != "win32":
        return hasattr(os, "geteuid") and os.geteuid() == 0
    try:
        import ctypes
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:  # noqa: BLE001
        return False


def when(t: float | None) -> str:
    return time.strftime("%Y-%m-%d %H:%M", time.localtime(t)) if t else ""


# --------------------------------------------------------------------------- the list
class EntryModel(QAbstractTableModel):
    HEADERS = ["AUTORUN ENTRY", "DESCRIPTION", "PUBLISHER", "IMAGE PATH", "TIMESTAMP"]

    def __init__(self, win):
        super().__init__()
        self.win = win
        self.rows: list[tuple[str, object]] = []      # ("group", location) | ("entry", Entry) | ("gone", Entry)

    def set_rows(self, rows):
        self.beginResetModel()
        self.rows = rows
        self.endResetModel()

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.rows)

    def columnCount(self, parent=QModelIndex()):
        return 5

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole:
            return self.HEADERS[section]
        return None

    def entry(self, row: int) -> Entry | None:
        if 0 <= row < len(self.rows) and self.rows[row][0] in ("entry", "gone"):
            return self.rows[row][1]
        return None

    def flags(self, index):
        f = Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
        kind, e = self.rows[index.row()]
        if kind == "entry" and index.column() == 0 and not e.locked:
            f |= Qt.ItemFlag.ItemIsUserCheckable
        return f

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        kind, obj = self.rows[index.row()]
        col = index.column()
        if kind == "group":
            if role == Qt.ItemDataRole.DisplayRole and col == 0:
                return obj
            if role == Qt.ItemDataRole.DecorationRole and col == 0:
                return widgets.line_icon("registry" if str(obj).startswith("HK") else "open", theme.TEXT_DIM)
            if role == Qt.ItemDataRole.FontRole:
                f = QFont("Inter", 10)
                f.setWeight(QFont.Weight.DemiBold)
                return f
            if role == Qt.ItemDataRole.ForegroundRole:
                return QColor(theme.TEXT_DIM)
            if role == Qt.ItemDataRole.BackgroundRole:
                c = QColor(theme.PANEL_EDGE)
                c.setAlphaF(.55)
                return QBrush(c)
            return None
        e: Entry = obj
        if role == Qt.ItemDataRole.DisplayRole:
            if col == 0:
                return e.name
            if col == 1:
                return e.description
            if col == 2:
                if e.verified is True:
                    return f"(Verified) {e.signer}"
                return e.publisher if e.verified is None else (e.company or "(not verified)")
            if col == 3:
                return ("File not found: " if e.missing else "") + e.image
            if col == 4:
                return when(e.timestamp)
        if role == Qt.ItemDataRole.CheckStateRole and col == 0 and kind == "entry":
            return Qt.CheckState.Checked if e.enabled else Qt.CheckState.Unchecked
        if role == Qt.ItemDataRole.DecorationRole and col == 0:
            return widgets.file_icon(widgets.kind_of(os.path.basename(e.image.replace("\\", "/"))) if e.image
                                     else "file", 18)
        if role == Qt.ItemDataRole.BackgroundRole:
            if e.key() in self.win.new_keys and kind == "entry":
                c = QColor(NEW); c.setAlphaF(.14)
                return QBrush(c)
            if e.missing:
                c = QColor(theme.LED_ORANGE); c.setAlphaF(.22)
                return QBrush(c)
            if e.verified is False:
                c = QColor(UNSIGNED); c.setAlphaF(.18)
                return QBrush(c)
        if role == Qt.ItemDataRole.FontRole and kind == "gone":
            f = QFont("Inter", 10)
            f.setStrikeOut(True)
            return f
        if role == Qt.ItemDataRole.ForegroundRole and (kind == "gone" or not e.enabled):
            return QColor(theme.TEXT_DIM)
        if role == Qt.ItemDataRole.ToolTipRole:
            bits = [e.command]
            if e.locked:
                bits.append("Windows needs this: it can't be switched off.")
            if e.missing:
                bits.append("The file it starts isn't there.")
            return "\n".join(bits)
        return None

    def setData(self, index, value, role=Qt.ItemDataRole.EditRole):
        if role != Qt.ItemDataRole.CheckStateRole or index.column() != 0:
            return False
        e = self.entry(index.row())
        if e is None:
            return False
        on = Qt.CheckState(value) == Qt.CheckState.Checked if not isinstance(value, bool) else value
        if self.win.toggle(e, on):
            self.dataChanged.emit(self.index(index.row(), 0), self.index(index.row(), 4))
            return True
        return False


class Tint(QStyledItemDelegate):
    """Paints a row's tint itself: the theme's ::item rules make Qt ignore item backgrounds (PR7-SM's lesson)."""

    def paint(self, painter, option, index):
        from PySide6.QtWidgets import QStyle
        b = index.data(Qt.ItemDataRole.BackgroundRole)
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        if not selected and isinstance(b, QBrush) and b.style() != Qt.BrushStyle.NoBrush:
            painter.fillRect(option.rect, b)          # the selected row keeps the family's selection band
        super().paint(painter, option, index)


class _Bridge(QObject):
    listed = Signal(object, object)          # entries, error
    signed = Signal(object)                  # entries with details


def _field(text):
    lab = QLabel(text.upper())
    lab.setProperty("role", "field")
    return lab


def _dim(text):
    lab = QLabel(text)
    lab.setProperty("role", "dim")
    return lab


class MainWindow(QMainWindow):
    def __init__(self, reg: registry.Registry | None = None, places: entries.Places | None = None,
                 scheduler: tasks.Scheduler | None = None, checker: signatures.Checker | None = None,
                 sync: bool = False):
        super().__init__()
        self.sync = sync
        self.answers: dict = {}
        self.said: list = []
        self.reg = reg or registry.default()
        self.places = places or entries.Places.here()
        self.scheduler = scheduler if scheduler is not None else (tasks.Scheduler() if sys.platform == "win32"
                                                                  else None)
        self.checker = checker if checker is not None else signatures.Checker(os.path.join(data_dir(),
                                                                                          "signatures.json"))
        self.all: list[Entry] = []
        self.new_keys: set[str] = set()
        self.gone: list[Entry] = []
        self.comparing = ""                          # the snapshot's name while comparing
        self.loading = False
        self.bridge = _Bridge()
        self.bridge.listed.connect(self._listed)
        self.bridge.signed.connect(self._signed)
        self.setWindowTitle("Paragon PR7-AR" + ("  (Administrator)" if is_admin() else ""))
        self.resize(1320, 860)
        self._build()
        self.restyle()

    # ================================================================ building
    def _build(self):
        central = QWidget()
        central.setObjectName("central")
        self.setCentralWidget(central)
        lay = QVBoxLayout(central)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        self.header = widgets.Header("STARTUP")
        lay.addWidget(self.header)
        bar = QWidget()
        bl = QHBoxLayout(bar)
        bl.setContentsMargins(16, 10, 16, 6)
        bl.setSpacing(6)
        self.keys = {}
        for i, group in enumerate([[("refresh", "refresh", "Refresh"), ("save", "file", "Save"),
                                    ("compare", "compare", "Compare")],
                                   [("jump_entry", "registry", "Jump to Entry"), ("jump_file", "jump", "Jump to File"),
                                    ("delete", "trash", "Delete")],
                                   [("admin", "shield", "As Admin")]]):
            if i:
                sep = QLabel()
                sep.setObjectName("sep")
                sep.setFixedSize(1, 40)
                bl.addSpacing(8)
                bl.addWidget(sep)
                bl.addSpacing(8)
            for name, icon, label in group:
                k = widgets.KeyButton(icon, label)
                k.setFixedSize(QSize(100, 62))
                self.keys[name] = k
                bl.addWidget(k)
        bl.addStretch(1)
        bl.addWidget(_field("Filter"))
        self.filter = QLineEdit()
        self.filter.setPlaceholderText("names, publishers, paths")
        self.filter.setFixedWidth(280)
        self.filter.textChanged.connect(lambda _: self.show_rows())
        bl.addWidget(self.filter)
        self.hide_windows = QCheckBox("Hide Windows entries")
        self.hide_windows.setChecked(settings.get_bool("hide_windows", True))
        self.hide_windows.toggled.connect(self._hide_windows)
        bl.addWidget(self.hide_windows)
        lay.addWidget(bar)
        self.keys["refresh"].clicked.connect(self.refresh)
        self.keys["save"].clicked.connect(self.save_snapshot)
        self.keys["compare"].clicked.connect(self.compare)
        self.keys["jump_entry"].clicked.connect(lambda: self.jump_entry(self.current()))
        self.keys["jump_file"].clicked.connect(lambda: self.jump_file(self.current()))
        self.keys["delete"].clicked.connect(lambda: self.delete(self.current()))
        self.keys["admin"].clicked.connect(self.as_admin)
        self.keys["admin"].setEnabled(sys.platform == "win32" and not is_admin())

        self.banner = QFrame()
        self.banner.setObjectName("banner")
        bnl = QHBoxLayout(self.banner)
        bnl.setContentsMargins(18, 8, 18, 8)
        bnl.addWidget(_field("Comparing with"))
        self.banner_text = QLabel("")
        bnl.addWidget(self.banner_text)
        bnl.addStretch(1)
        bnl.addWidget(_dim("Esc stops comparing"))
        self.banner.hide()
        lay.addWidget(self.banner)

        self.tabs = QTabBar()
        self.tabs.setExpanding(False)
        self.tabs.setDrawBase(False)
        for name in entries.TABS:
            self.tabs.addTab(name.upper())
        self.tabs.currentChanged.connect(lambda _: self.show_rows())
        th = QWidget()
        thl = QHBoxLayout(th)
        thl.setContentsMargins(16, 0, 16, 0)
        thl.addWidget(self.tabs)
        thl.addStretch(1)
        lay.addWidget(th)

        self.model = EntryModel(self)
        self.tree = QTreeView()
        self.tree.setModel(self.model)
        self.tree.setRootIsDecorated(False)
        self.tree.setIndentation(0)
        self.tree.setUniformRowHeights(True)
        self.tree.setIconSize(QSize(18, 18))
        self.tree.setItemDelegate(Tint(self.tree))
        self.tree.setSelectionBehavior(QTreeView.SelectionBehavior.SelectRows)
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._menu)
        self.tree.doubleClicked.connect(lambda i: self.jump_entry(self.model.entry(i.row())))
        h = self.tree.header()
        for c, mode in enumerate([QHeaderView.ResizeMode.Interactive, QHeaderView.ResizeMode.Interactive,
                                  QHeaderView.ResizeMode.Interactive, QHeaderView.ResizeMode.Stretch,
                                  QHeaderView.ResizeMode.ResizeToContents]):
            h.setSectionResizeMode(c, mode)
        for c, w in enumerate((300, 280, 230)):
            self.tree.setColumnWidth(c, w)
        self.tree.selectionModel().currentRowChanged.connect(lambda *_: (self.show_details(), self._enable()))
        holder = QWidget()
        hl = QVBoxLayout(holder)
        hl.setContentsMargins(16, 0, 16, 0)
        hl.addWidget(self.tree)
        lay.addWidget(holder, 1)

        self.details = QFrame()
        self.details.setObjectName("details")
        g = QGridLayout(self.details)
        g.setContentsMargins(18, 10, 18, 10)
        g.setHorizontalSpacing(16)
        g.setVerticalSpacing(5)
        self.d_title = QLabel("")
        self.d_title.setStyleSheet("font-size: 14px; font-weight: 600;")
        g.addWidget(self.d_title, 0, 0, 1, 2)
        self.d_desc = _dim("")
        g.addWidget(self.d_desc, 0, 2, 1, 2)
        self.d = {}
        for i, k in enumerate(("Publisher", "Version", "Size", "Time", "Image", "Command")):
            g.addWidget(_field(k), 1 + i % 3, (i // 3) * 2)
            v = QLabel("")
            v.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            g.addWidget(v, 1 + i % 3, (i // 3) * 2 + 1)
            self.d[k] = v
        g.setColumnStretch(3, 1)
        lay.addWidget(self.details)

        foot = QFrame()
        foot.setObjectName("foot")
        fl = QHBoxLayout(foot)
        fl.setContentsMargins(16, 6, 16, 6)
        self.status = _dim("")
        fl.addWidget(self.status)
        fl.addStretch(1)
        self.legend = QLabel("")
        fl.addWidget(self.legend)
        lay.addWidget(foot)
        self._menus()

    def _act(self, menu, text, slot, keys=None, key=None, checkable=False):
        a = QAction(text, self)
        if keys:
            a.setShortcut(QKeySequence(keys))
        a.setCheckable(checkable)
        a.triggered.connect(lambda *_: slot())
        menu.addAction(a)
        if key:
            self.acts[key] = a
        return a

    def _menus(self):
        self.acts: dict[str, QAction] = {}
        mb = self.menuBar()
        m = mb.addMenu("&File")
        self._act(m, "Save…", self.save_snapshot, "Ctrl+S", "save")
        self._act(m, "Compare…", self.compare, "Ctrl+M", "compare")
        self._act(m, "Stop Comparing", self.stop_compare, "Esc", "stop_compare")
        m.addSeparator()
        self._act(m, "Run as Administrator", self.as_admin, None, "admin")
        m.addSeparator()
        self._act(m, "Exit", self.close, "Alt+F4")
        m = mb.addMenu("&Entry")
        self._act(m, "Jump to Entry", lambda: self.jump_entry(self.current()), "Ctrl+J", "jump_entry")
        self._act(m, "Jump to File", lambda: self.jump_file(self.current()), "Ctrl+Shift+J", "jump_file")
        self._act(m, "Copy", lambda: self.copy(self.current()), "Ctrl+C", "copy")
        self._act(m, "Delete", lambda: self.delete(self.current()), "Del", "delete")
        self._act(m, "Properties", lambda: self.properties(self.current()), "Alt+Return", "properties")
        m = mb.addMenu("&View")
        self._act(m, "Refresh", self.refresh, "F5", "refresh")
        self._act(m, "Find", lambda: self.filter.setFocus(), "Ctrl+F", "find")
        m.addSeparator()
        fm = m.addMenu("Finish")
        group = QActionGroup(self)
        self.finish_acts = {}
        for name in ("obsidian", "aurora"):
            a = self._act(fm, name.upper(), lambda n=name: self.set_finish(n), checkable=True)
            group.addAction(a)
            self.finish_acts[name] = a
        self.finish_acts[theme.FINISH].setChecked(True)
        m = mb.addMenu("&Help")
        self._act(m, "Check for Updates…", self.check_updates, None, "updates")
        self._act(m, "About PR7-AR", self.about, None, "about")

    # ================================================================ look
    def restyle(self):
        app = QApplication.instance()
        if app is not None:
            app.setPalette(theme.palette())
            app.setStyleSheet(theme.stylesheet())
        self.centralWidget().setStyleSheet(
            f"QWidget#central {{ background: {theme.BACKGROUND}; }} QLabel#sep {{ background: {theme.PANEL_EDGE}; }} "
            f"QFrame#foot {{ background: {theme.TAB_FRAME}; border-top: 1px solid {theme.PANEL_EDGE}; }} "
            f"QFrame#details {{ background: {theme.DOCK_TOP}; border-top: 1px solid {theme.PANEL_EDGE}; }} "
            f"QFrame#banner {{ background: {theme.DOCK_TOP}; border-top: 1px solid {theme.PANEL_EDGE}; "
            f"border-bottom: 1px solid {theme.PANEL_EDGE}; }} "
            "QTabBar::tab { padding: 6px 11px; font-size: 10.5px; }")
        self.legend.setText(f"<span style='color:{UNSIGNED}'>■</span> unverified publisher     "
                            f"<span style='color:{theme.LED_ORANGE}'>■</span> file not found     "
                            f"<span style='color:{theme.TEXT_DIM}'>☐</span> switched off")
        self.legend.setStyleSheet(f"color: {theme.TEXT_DIM}; font-size: 11px;")
        self.header.update()
        for a_name, a in getattr(self, "finish_acts", {}).items():
            a.setChecked(a_name == theme.FINISH)
        if self.model.rows:
            self.show_rows()

    def set_finish(self, name: str):
        theme.set_finish(name)
        finish.set(theme.FINISH)                 # every family app follows (finish.py)
        settings.set("finish", theme.FINISH)
        self.restyle()

    # ================================================================ asking
    def _ask(self, kind: str, payload=None):
        if kind in self.answers:
            a = self.answers[kind]
            return a(payload) if callable(a) else a
        if kind == "confirm":
            return QMessageBox.question(self, "PR7-AR", payload) == QMessageBox.StandardButton.Yes
        if kind == "save_file":
            return QFileDialog.getSaveFileName(self, "Save", payload, f"PR7-AR snapshots (*{entries.SNAPSHOT_EXT})")[0]
        if kind == "open_file":
            return QFileDialog.getOpenFileName(self, "Compare with", payload or "",
                                               f"PR7-AR snapshots (*{entries.SNAPSHOT_EXT})")[0]
        return None

    def _say(self, kind: str, text: str):
        self.said.append((kind, text))
        if "say" in self.answers:
            self.answers["say"](kind, text)
            return
        icon = QMessageBox.Icon.Warning if kind == "error" else QMessageBox.Icon.Information
        QMessageBox(icon, "PR7-AR", text, parent=self).exec()

    def _run(self, args: list[str]):
        run = self.answers.get("run", lambda a: subprocess.Popen(a, creationflags=0x08000000
                                                                  if sys.platform == "win32" else 0))
        return run(args)

    # ================================================================ loading
    def refresh(self):
        if self.loading:
            return
        self.loading = True
        self.status.setText("Reading…")

        def work():
            try:
                return entries.collect(self.reg, self.places, self.scheduler), None
            except Exception as e:      # noqa: BLE001 - shown to the user
                return [], str(e)
        if self.sync:
            self.bridge.listed.emit(*work())
        else:
            threading.Thread(target=lambda: self.bridge.listed.emit(*work()), daemon=True).start()

    def _listed(self, got, error):
        self.all = got
        self.show_rows()
        if error:
            self.loading = False
            self._say("error", f"Reading the startup entries failed: {error}")
            return
        self.status.setText(self._status_text() + "  ·  checking publishers…")

        def work():
            entries.fill_details(got, self.checker)
            return got
        if self.sync:
            self.bridge.signed.emit(work())
        else:
            threading.Thread(target=lambda: self.bridge.signed.emit(work()), daemon=True).start()

    def _signed(self, got):
        self.loading = False
        if got is self.all:
            self.show_rows()

    def tab(self) -> str:
        return entries.TABS[self.tabs.currentIndex()]

    def shown(self) -> list[Entry]:
        tab, text = self.tab(), self.filter.text().strip()
        hide = self.hide_windows.isChecked()
        out = []
        for e in self.all:
            if tab != "Everything" and e.tab != tab:
                continue
            if hide and e.windows:
                continue
            if text and not e.matches(text):
                continue
            if self.comparing and e.key() not in self.new_keys:
                continue
            out.append(e)
        return out

    def show_rows(self):
        keep = self.current()
        rows, last = [], None
        shown = self.shown()
        gone = [e for e in self.gone if self.tab() in ("Everything", e.tab)] if self.comparing else []
        for kind, e in [("entry", e) for e in shown] + [("gone", e) for e in gone]:
            if e.location != last:
                rows.append(("group", e.location))
                last = e.location
            rows.append((kind, e))
        self.model.set_rows(rows)
        for i, (kind, _) in enumerate(rows):
            if kind == "group":
                self.tree.setFirstColumnSpanned(i, QModelIndex(), True)
        if keep is not None:
            for i, (kind, e) in enumerate(rows):
                if kind == "entry" and e.key() == keep.key():
                    self.tree.setCurrentIndex(self.model.index(i, 0))
                    break
        self.status.setText(self._status_text())
        self.show_details()
        self._enable()

    def _status_text(self) -> str:
        es = self.all
        tab = self.tab()
        in_tab = [e for e in es if tab == "Everything" or e.tab == tab]
        shown = len(self.shown())
        unv = sum(1 for e in in_tab if e.verified is False)
        miss = sum(1 for e in in_tab if e.missing)
        bits = [f"{len(in_tab)} entries" + (f", {shown} shown" if shown != len(in_tab) else "")
                + (" (Windows entries hidden)" if self.hide_windows.isChecked() else "")]
        if unv:
            bits.append(f"{unv} unverified")
        if miss:
            bits.append(f"{miss} file{'s' if miss != 1 else ''} missing")
        if self.loading:
            bits.append("checking publishers…")
        return "  ·  ".join(bits)

    def _hide_windows(self, on: bool):
        settings.set("hide_windows", on)
        self.show_rows()

    def current(self) -> Entry | None:
        idx = self.tree.currentIndex()
        return self.model.entry(idx.row()) if idx.isValid() else None

    def select(self, name: str) -> bool:
        for i, (kind, e) in enumerate(self.model.rows):
            if kind in ("entry", "gone") and e.name == name:
                self.tree.setCurrentIndex(self.model.index(i, 0))
                return True
        return False

    def show_details(self):
        e = self.current()
        self.details.setVisible(e is not None)
        if e is None:
            return
        self.d_title.setText(e.name)
        self.d_desc.setText(e.description or "(no description)")
        pub = self.d["Publisher"]
        if e.verified is True:
            pub.setText(f"{e.signer}   ·   verified")
            pub.setStyleSheet("")
        elif e.verified is False:
            pub.setText(f"{e.company or '(no publisher)'}   ·   NOT VERIFIED")
            pub.setStyleSheet(f"color: {UNSIGNED}; font-weight: 600;")
        else:
            pub.setText(e.company or "(not checked)")
            pub.setStyleSheet("")
        self.d["Version"].setText(e.version or "(none)")
        try:
            size = os.path.getsize(e.image) if e.image and not e.missing else None
        except OSError:
            size = None
        self.d["Size"].setText(f"{size / 1e6:.1f} MB" if size and size >= 1e5 else f"{size} bytes" if size else "")
        self.d["Time"].setText(when(e.timestamp))
        self.d["Image"].setText(("File not found: " if e.missing else "") + e.image)
        self.d["Command"].setText(e.command)

    def _enable(self):
        e = self.current()
        live = e is not None and e in self.all
        for k in ("jump_entry", "jump_file", "delete"):
            self.keys[k].setEnabled(live)
        self.keys["delete"].setEnabled(live and not e.locked)
        self.banner.setVisible(bool(self.comparing))

    # ================================================================ changing things
    def toggle(self, e: Entry, on: bool) -> bool:
        try:
            entries.set_enabled(e, on, self.reg, self.scheduler)
        except PermissionError as err:
            if e.locked:
                self._say("error", str(err.strerror or err))
            else:
                self._say("error", f"{e.name} is machine-wide: changing it needs administrator rights. "
                                   "As Admin restarts PR7-AR as administrator.")
            return False
        except OSError as err:
            self._say("error", f"{e.name} couldn't be changed: {err.strerror or err}")
            return False
        self.status.setText(self._status_text())
        return True

    def delete(self, e: Entry | None):
        if e is None or e not in self.all:
            return False
        if e.locked:
            self._say("error", f"{e.name} can't be deleted: Windows needs it.")
            return False
        warn = {"service": f"Delete the service {e.name}? Windows forgets it after a restart; its files stay. "
                           "Switching it off (unticking) can be undone; deleting can't.",
                "task": f"Delete the scheduled task {e.name}? This can't be undone."}.get(
            e.kind, f"Delete {e.name}? This can't be undone (switching it off can).")
        if not self._ask("confirm", warn):
            return False
        try:
            entries.delete(e, self.reg, self.scheduler)
        except PermissionError:
            self._say("error", f"{e.name} is machine-wide: deleting it needs administrator rights (As Admin).")
            return False
        except OSError as err:
            self._say("error", f"{e.name} couldn't be deleted: {err.strerror or err}")
            return False
        self.all = [x for x in self.all if x is not e]
        self.show_rows()
        return True

    # ================================================================ jumping
    def jump_entry(self, e: Entry | None):
        """Autoruns' Jump to Entry: the registry key in Regedit, the Startup folder, Task Scheduler or Services."""
        if e is None:
            return
        if e.kind in ("value", "key", "list", "service"):
            r = e.ref
            if e.kind == "service":
                hive, path = "HKLM", rf"SYSTEM\CurrentControlSet\Services\{r['name']}"
            elif e.kind == "key":
                hive = r["hive"]
                path = f"{r['path']}\\{r['name']}" if e.enabled else f"{r['path']}\\{registry.DISABLED}\\{r['name']}"
            else:
                hive = r["hive"]
                path = r["path"] if e.enabled else f"{r['path']}\\{registry.DISABLED}"
            target = f"Computer\\{HIVE_NAMES[hive]}\\{path}"
            try:                    # Regedit opens at the key it last showed: tell it this one (Autoruns' way)
                self.reg.set("HKCU", REGEDIT_KEY, "LastKey", target)
            except OSError:
                pass
            self.last_jump = target
            self._run(["regedit.exe"])
        elif e.kind == "file":
            self.show_in_folder(os.path.join(e.ref["folder"], e.ref["name"]) if e.enabled else
                                os.path.join(e.ref["folder"], registry.DISABLED, e.ref["name"]))
        elif e.kind == "task":
            self.last_jump = e.name
            self._run(["mmc.exe", "taskschd.msc"])

    def jump_file(self, e: Entry | None):
        if e is None or not e.image:
            return
        if e.missing:
            self._say("info", f"{e.image} isn't there.")
            return
        self.show_in_folder(e.image)

    def show_in_folder(self, path: str):
        folder = os.path.dirname(path)
        self.last_jump = path
        launch = self.answers.get("launch", family.launch)
        if launch("PR7-E", [folder]):
            return
        if sys.platform == "win32":
            self._run(["explorer.exe", "/select,", path])
        else:
            opener = self.answers.get("url", QDesktopServices.openUrl)
            opener(QUrl.fromLocalFile(folder))

    def copy(self, e: Entry | None):
        if e is not None:
            QApplication.clipboard().setText("\t".join((e.name, e.description, e.publisher, e.image, e.command)))

    def properties(self, e: Entry | None):
        """Windows' own Properties window for the file (its Digital Signatures tab included)."""
        if e is None or not e.image or e.missing or sys.platform != "win32":
            return
        import ctypes
        from ctypes import wintypes

        class SHELLEXECUTEINFOW(ctypes.Structure):
            _fields_ = [("cbSize", wintypes.DWORD), ("fMask", ctypes.c_ulong), ("hwnd", wintypes.HWND),
                        ("lpVerb", wintypes.LPCWSTR), ("lpFile", wintypes.LPCWSTR),
                        ("lpParameters", wintypes.LPCWSTR), ("lpDirectory", wintypes.LPCWSTR),
                        ("nShow", ctypes.c_int), ("hInstApp", wintypes.HINSTANCE), ("lpIDList", ctypes.c_void_p),
                        ("lpClass", wintypes.LPCWSTR), ("hkeyClass", wintypes.HKEY), ("dwHotKey", wintypes.DWORD),
                        ("hIcon", wintypes.HANDLE), ("hProcess", wintypes.HANDLE)]
        info = SHELLEXECUTEINFOW(ctypes.sizeof(SHELLEXECUTEINFOW), 0x0000000C, int(self.winId()), "properties",
                                 e.image, None, None, 1)
        ctypes.windll.shell32.ShellExecuteExW(ctypes.byref(info))

    def _menu(self, pos):
        e = self.current()
        if e is None:
            return
        m = QMenu(self)
        m.addAction("Jump to Entry", lambda: self.jump_entry(e))
        m.addAction("Jump to File", lambda: self.jump_file(e))
        m.addSeparator()
        m.addAction("Copy", lambda: self.copy(e))
        d = m.addAction("Delete", lambda: self.delete(e))
        d.setEnabled(not e.locked and e in self.all)
        m.addAction("Properties", lambda: self.properties(e)).setEnabled(sys.platform == "win32" and not e.missing)
        self.last_menu = m
        if "menu" not in self.answers:
            m.exec(self.tree.viewport().mapToGlobal(pos))

    # ================================================================ snapshots
    def save_snapshot(self):
        path = self._ask("save_file", time.strftime("startup %Y-%m-%d") + entries.SNAPSHOT_EXT)
        if not path:
            return
        if not path.endswith(entries.SNAPSHOT_EXT):
            path += entries.SNAPSHOT_EXT
        entries.save_snapshot(self.all, path)
        self.status.setText(f"Saved {os.path.basename(path)}")

    def compare(self, path: str | None = None):
        path = path or self._ask("open_file", "")
        if not path:
            return
        try:
            saved, then = entries.load_snapshot(path)
        except (OSError, ValueError) as e:
            self._say("error", f"{os.path.basename(path)} isn't a PR7-AR snapshot ({e}).")
            return
        self.new_keys, self.gone = entries.compare(self.all, then)
        self.comparing = os.path.basename(path)
        self.banner_text.setText(f"{self.comparing}  ·  saved {when(saved)}      {len(self.new_keys)} new  ·  "
                                 f"{len(self.gone)} gone  ·  only changes shown")
        self.show_rows()

    def stop_compare(self):
        if self.comparing:
            self.comparing = ""
            self.new_keys, self.gone = set(), []
            self.show_rows()

    # ================================================================ elevation, help
    def as_admin(self):
        """Restart elevated (Windows asks for permission): machine-wide entries can then be changed."""
        elevate = self.answers.get("elevate")
        if elevate is not None:
            elevate()
            return
        if sys.platform != "win32":
            return
        import ctypes
        exe = sys.executable
        args = "" if getattr(sys, "frozen", False) else "-m pr7ar"
        res = ctypes.windll.shell32.ShellExecuteW(None, "runas", exe, args, None, 1)
        if res > 32:
            self.close()

    def check_updates(self):
        from . import update_ui
        update_ui.check(self, manual=True)

    def about(self):
        self._say("info", f"Paragon PR7-AR {__version__}\nA startup manager that works the way Autoruns works.")
