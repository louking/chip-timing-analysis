"""Translate Windows-style paths to their WSL-mounted form.

Race data lives in Windows-side folders (Dropbox, etc.) and race_dir/
fsrc_tech_dir are often pasted in as `C:\\...` from Windows Explorer or a
VS Code task prompt. Since this repo now runs under WSL bash (see
.vscode/tasks.json), a path like that doesn't resolve on its own -- it
needs the `/mnt/c/...` form. Shells out to the `wslpath` utility (part of
WSL, not this repo) rather than hand-rolling the drive-letter/UNC/escaping
rules, which `wslpath` already gets right.
"""

from __future__ import annotations

import re
import subprocess

_WINDOWS_PATH_RE = re.compile(r"^[A-Za-z]:[\\/]")


def to_wsl_path(path: str) -> str:
    """Return path unchanged unless it looks like a Windows path (`C:\\...`
    or `C:/...`), in which case it's converted via `wslpath -u`. Falls back
    to the original path if `wslpath` isn't available (e.g. running outside
    WSL) or fails on it.
    """
    if not _WINDOWS_PATH_RE.match(path):
        return path
    try:
        result = subprocess.run(
            ["wslpath", "-u", path], capture_output=True, text=True, check=True,
        )
    except (FileNotFoundError, subprocess.CalledProcessError):
        return path
    return result.stdout.strip()
