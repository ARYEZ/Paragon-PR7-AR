"""Who signed a file (no Qt), the way Autoruns' "Verify code signatures" checks: Windows' own Authenticode check,
which also finds catalog signatures (most of Windows' own files are signed only in a catalog). One PowerShell run checks
every file of a refresh (Get-AuthenticodeSignature: the file list goes in through a temp file, one JSON line per file
comes out); results are cached by path + size + time in <data>/signatures.json. Nothing is sent anywhere.

Elsewhere (tests on Linux) nothing can be checked: `verified` is None ("not checked")."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from dataclasses import dataclass

NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0
SCRIPT = r"""
[Console]::OutputEncoding = [Text.Encoding]::UTF8
Get-Content -LiteralPath $args[0] -Encoding UTF8 | ForEach-Object {
  $p = $_
  try {
    $s = Get-AuthenticodeSignature -LiteralPath $p -ErrorAction Stop
    $n = ''
    if ($s.SignerCertificate) { $n = $s.SignerCertificate.GetNameInfo('SimpleName', $false) }
    [pscustomobject]@{ p = $p; s = [string]$s.Status; n = $n; o = [bool]$s.IsOSBinary } | ConvertTo-Json -Compress
  } catch {
    [pscustomobject]@{ p = $p; s = 'Error'; n = ''; o = $false } | ConvertTo-Json -Compress
  }
}
"""


@dataclass
class Signature:
    verified: bool | None       # None: not checked (no file, or not Windows)
    signer: str = ""
    os_file: bool = False       # Windows' own (IsOSBinary)


def _key(path: str) -> str | None:
    try:
        st = os.stat(path.replace("\\", os.sep) if os.sep != "\\" else path)   # tests on Linux use \ paths
    except OSError:
        return None
    return f"{path.casefold()}|{st.st_size}|{int(st.st_mtime)}"


class Checker:
    def __init__(self, cache_path: str | None = None, run=None):
        self.cache_path = cache_path
        self.run = run                  # tests: a function(paths) -> {path: Signature}
        self.cache: dict[str, dict] = {}
        if cache_path:
            try:
                with open(cache_path, encoding="utf-8") as f:
                    self.cache = json.load(f)
            except (OSError, ValueError):
                self.cache = {}

    def check(self, paths: list[str]) -> dict[str, Signature]:
        out: dict[str, Signature] = {}
        todo = []
        for p in dict.fromkeys(paths):
            k = _key(p) if p else None
            if k is None:
                continue
            if k in self.cache:
                c = self.cache[k]
                out[p] = Signature(c["v"], c["n"], c["o"])
            else:
                todo.append(p)
        if todo:
            got = self.run(todo) if self.run else (_powershell(todo) if sys.platform == "win32" else {})
            for p, sig in got.items():
                out[p] = sig
                k = _key(p)
                if k and sig.verified is not None:
                    self.cache[k] = {"v": sig.verified, "n": sig.signer, "o": sig.os_file}
            self._save()
        return out

    def _save(self):
        if not self.cache_path:
            return
        try:
            tmp = self.cache_path + ".part"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self.cache, f)
            os.replace(tmp, self.cache_path)
        except OSError:
            pass


def _powershell(paths: list[str]) -> dict[str, Signature]:
    fd, lst = tempfile.mkstemp(suffix=".txt", prefix="pr7ar-")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write("\n".join(paths))
    script = os.path.join(tempfile.gettempdir(), "pr7ar-verify.ps1")
    with open(script, "w", encoding="utf-8-sig") as f:
        f.write(SCRIPT)
    out: dict[str, Signature] = {}
    try:
        r = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File",
                            script, lst], capture_output=True, text=True, encoding="utf-8", errors="replace",
                           timeout=600, creationflags=NO_WINDOW, stdin=subprocess.DEVNULL)
        for line in r.stdout.splitlines():
            try:
                d = json.loads(line)
            except ValueError:
                continue
            status = d.get("s", "")
            out[d.get("p", "")] = Signature(status == "Valid", d.get("n") or "", bool(d.get("o")))
    except (OSError, subprocess.SubprocessError):
        pass
    finally:
        try:
            os.remove(lst)
        except OSError:
            pass
    return out
