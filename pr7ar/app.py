"""Start PR7-AR.

    PR7-AR.exe                      the window (one per user: a later start brings it to the front)
    PR7-AR.exe --version
    PR7-AR.exe --selftest OUT.json  read the real startup entries, then add a Run entry of its own (HKCU), find it,
                                    switch it off and on (Autoruns' AutorunsDisabled key) and delete it; check a
                                    signature; write what happened (CI runs the installed exe)
"""

from __future__ import annotations

import getpass
import hashlib
import json
import os
import sys

TIMEOUT_MS = 1500
SELFTEST_NAME = "Paragon PR7-AR self-test"


def server_name() -> str:
    try:
        user = getpass.getuser()
    except Exception:  # noqa: BLE001
        user = "user"
    return "Paragon-PR7-AR-" + hashlib.sha1(user.encode()).hexdigest()[:12]


def hand_over() -> bool:
    from PySide6.QtNetwork import QLocalSocket
    s = QLocalSocket()
    s.connectToServer(server_name())
    if not s.waitForConnected(TIMEOUT_MS):
        return False
    s.write(b'{"show": true}\n')
    s.flush()
    s.waitForBytesWritten(TIMEOUT_MS)
    if not s.waitForDisconnected(TIMEOUT_MS):
        s.disconnectFromServer()
    return True


def listen(window):
    """Later starts bring this window to the front (PR7-R's hand-off, with its Windows fix)."""
    from PySide6.QtNetwork import QLocalServer
    server = QLocalServer(window)
    QLocalServer.removeServer(server_name())
    if not server.listen(server_name()):
        return None

    def connection():
        sock = server.nextPendingConnection()
        if sock is None:
            return
        done = []

        def read():
            if not done and bytes(sock.readAll()).strip():
                done.append(True)
                window.showNormal()
                window.raise_()
                window.activateWindow()
                sock.disconnectFromServer()
        sock.readyRead.connect(read)
        if sock.bytesAvailable():
            read()
    server.newConnection.connect(connection)
    window.instance_server = server
    return server


def selftest(out: str) -> int:
    import tempfile
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    os.environ["PR7AR_DATA"] = tempfile.mkdtemp()
    from PySide6.QtCore import QSettings
    from PySide6.QtGui import QFontDatabase
    from PySide6.QtWidgets import QApplication
    QSettings.setDefaultFormat(QSettings.Format.IniFormat)
    QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, tempfile.mkdtemp())
    app = QApplication.instance() or QApplication(sys.argv[:1])
    result: dict = {}
    from . import entries, registry
    reg = registry.default()
    run_key = entries.CV + "\\Run"
    try:
        from . import __version__, theme
        from .main_window import MainWindow
        theme.load_fonts()
        cmd = f'"{sys.executable}" --version'
        reg.set("HKCU", run_key, SELFTEST_NAME, cmd)
        w = MainWindow(reg=reg, sync=True)
        w.answers.update({"say": lambda k, t: None, "confirm": lambda t: True, "run": lambda a: None,
                          "launch": lambda *a: True})
        w.hide_windows.setChecked(False)
        w.refresh()
        tabs = sorted({e.tab for e in w.all})
        mine = next((e for e in w.all if e.name == SELFTEST_NAME), None)
        off = on = False
        if mine is not None:
            w.toggle(mine, False)
            off = reg.get("HKCU", run_key + "\\" + registry.DISABLED, SELFTEST_NAME) is not None and \
                reg.get("HKCU", run_key, SELFTEST_NAME) is None
            w.toggle(mine, True)
            on = reg.get("HKCU", run_key, SELFTEST_NAME) is not None
            w.delete(mine)
        gone = reg.get("HKCU", run_key, SELFTEST_NAME) is None
        verified = [e for e in w.all if e.verified is True]
        result = {"version": __version__, "entries": len(w.all), "tabs": tabs, "found": mine is not None,
                  "switched_off": off, "switched_on": on, "deleted": gone, "verified": len(verified),
                  "windows": sum(1 for e in w.all if e.windows), "tasks": sum(1 for e in w.all if e.kind == "task"),
                  "services": sum(1 for e in w.all if e.tab == "Services"),
                  "fonts": "Inter" in QFontDatabase.families()}
        result["ok"] = bool(mine) and off and on and gone
        w.close()
    except Exception as e:  # noqa: BLE001 - reported in the output
        import traceback
        result = {"error": f"{type(e).__name__}: {e}", "trace": traceback.format_exc()}
    finally:
        for where in (run_key, run_key + "\\" + registry.DISABLED):
            try:
                reg.delete_value("HKCU", where, SELFTEST_NAME)
            except OSError:
                pass
    with open(out, "w", encoding="utf-8") as fh:
        json.dump(result, fh, indent=1)
    app.clipboard().clear()
    return 0 if result.get("ok") else 1


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or not argv[0].startswith("--"):
        return _window(argv)
    # a command-line mode (CI): an unexpected error must end the process with a code; in the windowed exe it would
    # otherwise open an error box that waits for a click nobody gives
    try:
        return _command(argv)
    except SystemExit:
        raise
    except BaseException:  # noqa: BLE001 - reported, then a failing exit code
        import traceback
        if sys.stderr is not None:
            sys.stderr.write(traceback.format_exc())
        return 2


def _command(argv: list[str]) -> int:
    if argv[:1] == ["--version"]:
        from . import __version__
        print(__version__)
        return 0
    if argv[:1] == ["--selftest"] and len(argv) == 2:
        return selftest(argv[1])
    print(__doc__)
    return 1


def _window(argv: list[str]) -> int:
    from PySide6.QtWidgets import QApplication

    from . import settings, theme
    app = QApplication.instance() or QApplication(sys.argv[:1])
    app.setOrganizationName("Paragon")
    app.setApplicationName("PR7-AR")
    if hand_over():
        return 0
    from . import finish
    theme.set_finish(finish.start(settings.get("finish", "obsidian")))
    theme.load_fonts()
    app.setPalette(theme.palette())
    from PySide6.QtGui import QIcon
    icon = os.path.join(os.path.dirname(__file__), "icons", "app.ico")
    if os.path.exists(icon):
        app.setWindowIcon(QIcon(icon))
    from .main_window import MainWindow
    w = MainWindow()
    from PySide6.QtCore import QTimer
    _follow = QTimer(w)                      # one finish for the family: follow another app's switch (finish.py)
    _follow.timeout.connect(lambda: finish.follow(theme.FINISH, w.set_finish))
    _follow.start(2000)
    listen(w)
    w.show()
    QTimer.singleShot(0, w.refresh)
    from . import update_ui
    update_ui.start(w)
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
