"""Scheduled tasks (no Qt) through schtasks.exe. The list is `schtasks /query /xml ONE`: every task's own XML, each after
a `<!-- \\Folder\\Name -->` comment. XML element names don't change with Windows' display language, where the CSV
listing's columns and words do. Switching off / on is `/change /disable|/enable`, deleting `/delete /f`. The runner is
injectable: tests give recorded output and keep the commands."""

from __future__ import annotations

import re
import subprocess
import sys
import xml.etree.ElementTree as ET
from dataclasses import dataclass

NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0


@dataclass
class Task:
    path: str               # "\Paragon\PR7-IS Index"
    command: str            # the program and its arguments, as written
    enabled: bool
    author: str = ""
    description: str = ""
    date: str = ""          # RegistrationInfo/Date (ISO), may be ""
    com_class: str = ""     # a COM handler action instead of a program: its CLSID


def _run(args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(["schtasks.exe", *args], capture_output=True, text=True, encoding="utf-8",
                          errors="replace", timeout=60, creationflags=NO_WINDOW, stdin=subprocess.DEVNULL)


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _find(el, *names):
    for child in el:
        if _local(child.tag) == names[0]:
            return _find(child, *names[1:]) if len(names) > 1 else child
    return None


def parse(xml_text: str) -> list[Task]:
    """`schtasks /query /xml ONE`: <Tasks> holding <!-- \\name --> comments, each followed by its <Task>."""
    out: list[Task] = []
    text = xml_text.lstrip("﻿")
    # ElementTree drops comments by default; keep the names by pairing each comment with the next <Task>
    pieces = re.split(r"<!--\s*(.*?)\s*-->", text, flags=re.S)
    name = None
    for i, piece in enumerate(pieces):
        if i % 2 == 1:
            name = piece.strip()
            continue
        if name is None:
            continue
        m = re.search(r"<Task\b.*?</Task>", piece, flags=re.S)
        if not m:
            continue
        try:
            task = ET.fromstring(m.group(0))
        except ET.ParseError:
            name = None
            continue
        reg = _find(task, "RegistrationInfo")
        settings = _find(task, "Settings")
        enabled_el = _find(settings, "Enabled") if settings is not None else None
        enabled = (enabled_el is None) or (enabled_el.text or "").strip().lower() != "false"
        command, com = "", ""
        actions = _find(task, "Actions")
        if actions is not None:
            for act in actions:
                kind = _local(act.tag)
                if kind == "Exec":
                    c = _find(act, "Command")
                    a = _find(act, "Arguments")
                    prog = (c.text or "").strip() if c is not None else ""
                    if prog and " " in prog and not prog.startswith('"'):
                        prog = f'"{prog}"'
                    command = (prog + (" " + (a.text or "").strip() if a is not None and a.text else "")).strip()
                    break
                if kind == "ComHandler":
                    cid = _find(act, "ClassId")
                    com = (cid.text or "").strip() if cid is not None else ""
                    break
        def text(el, tag):
            x = _find(el, tag) if el is not None else None
            return (x.text or "").strip() if x is not None else ""
        out.append(Task(name, command, enabled, text(reg, "Author"), text(reg, "Description"), text(reg, "Date"),
                        com))
        name = None
    return out


class Scheduler:
    def __init__(self, run=None):
        self.run = run or _run

    def list(self) -> list[Task]:
        r = self.run(["/query", "/xml", "ONE"])
        if r.returncode != 0:
            return []
        return parse(r.stdout)

    def _do(self, args: list[str]) -> None:
        r = self.run(args)
        if r.returncode != 0:
            msg = (r.stderr or r.stdout or "").strip().splitlines()
            text = msg[-1] if msg else f"schtasks ended with code {r.returncode}"
            if "denied" in text.lower() or r.returncode == 5:
                raise PermissionError(13, text)
            raise OSError(r.returncode, text)

    def set_enabled(self, path: str, on: bool) -> None:
        self._do(["/change", "/tn", path, "/enable" if on else "/disable"])

    def delete(self, path: str) -> None:
        self._do(["/delete", "/tn", path, "/f"])
