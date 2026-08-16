"""test_wslpath - test chip_timing_analysis.wslpath

Covers the exit-127/unresolvable-path failure mode hit running the VS Code
tasks under WSL bash: a race_dir or fsrc_tech_dir pasted in as a Windows
path (e.g. from Explorer/Dropbox) needs translating to its /mnt/<drive>
form before Path()/open() can resolve it.
"""

import subprocess

import pytest

from chip_timing_analysis.wslpath import to_wsl_path


def test_posix_path_is_returned_unchanged():
    assert to_wsl_path("data/2026-07-04-indy-5000") == "data/2026-07-04-indy-5000"


def test_relative_dotted_path_is_returned_unchanged():
    assert to_wsl_path("../../fsrc-tech/fsrc-tech") == "../../fsrc-tech/fsrc-tech"


def test_windows_path_with_backslashes_is_converted(monkeypatch):
    def fake_run(cmd, capture_output, text, check):
        assert cmd == ["wslpath", "-u", r"C:\Users\lking\Dropbox\race"]
        return subprocess.CompletedProcess(cmd, 0, stdout="/mnt/c/Users/lking/Dropbox/race\n", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)

    assert to_wsl_path(r"C:\Users\lking\Dropbox\race") == "/mnt/c/Users/lking/Dropbox/race"


def test_windows_path_with_forward_slashes_is_converted(monkeypatch):
    monkeypatch.setattr(
        subprocess, "run",
        lambda cmd, capture_output, text, check: subprocess.CompletedProcess(
            cmd, 0, stdout="/mnt/c/Users/lking/race\n", stderr=""
        ),
    )

    assert to_wsl_path("C:/Users/lking/race") == "/mnt/c/Users/lking/race"


def test_falls_back_to_original_path_when_wslpath_missing(monkeypatch):
    def fake_run(cmd, capture_output, text, check):
        raise FileNotFoundError("wslpath not found")

    monkeypatch.setattr(subprocess, "run", fake_run)

    assert to_wsl_path(r"C:\Users\lking\race") == r"C:\Users\lking\race"


def test_falls_back_to_original_path_when_wslpath_fails(monkeypatch):
    def fake_run(cmd, capture_output, text, check):
        raise subprocess.CalledProcessError(1, cmd)

    monkeypatch.setattr(subprocess, "run", fake_run)

    assert to_wsl_path(r"C:\bad\path") == r"C:\bad\path"


def test_real_wslpath_translates_drive_letter():
    # exercises the real binary (not mocked) -- confirms the assumption
    # the mocked tests above are built on actually holds on this machine
    result = to_wsl_path(r"C:\Users\lking\race")

    assert result == "/mnt/c/Users/lking/race"
