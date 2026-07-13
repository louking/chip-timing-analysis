"""CLI: copy a race's sanitized report and the running summary into a local
fsrc-tech checkout, per the manual publishing workflow documented in
CLAUDE.md ("Publishing sanitized reports to fsrc-tech").

This only copies files -- it does not touch fsrc-tech's own CHANGELOG.md,
and does not commit or push there. Both stay a deliberate manual step (per
Lou's call, not run proactively) -- see the printed reminder at the end.

Usage:
    python -m chip_timing_analysis.report.publish <race_date> <fsrc_tech_dir>
    python -m chip_timing_analysis.report.publish --new <fsrc_tech_dir>

Example:
    python -m chip_timing_analysis.report.publish 2026-07-04 "../../fsrc-tech/fsrc-tech"
    python -m chip_timing_analysis.report.publish --new "../../fsrc-tech/fsrc-tech"

Copies:
    reports/<race_date>.md    -> <fsrc_tech_dir>/docs/race-services/reports/<race_date>.md
                                  (with --new: every reports/<date>.md missing from the
                                  destination, or present there but text-different from
                                  the source -- i.e. edited since it was last published --
                                  instead of a single race_date)
    reports/SUMMARY.md        -> <fsrc_tech_dir>/docs/race-services/reports/README.md
                                  (overwrite -- SUMMARY.md already accumulates every
                                  race, so this fully replaces the fsrc-tech index)
    reports/SUMMARY-LEGEND.md -> <fsrc_tech_dir>/docs/race-services/reports/SUMMARY-LEGEND.md
                                  (overwrite -- kept under the same filename so
                                  README.md's link to it still resolves)
"""

from __future__ import annotations

import argparse
import shutil
from pathlib import Path

_NON_RACE_STEMS = {"SUMMARY", "SUMMARY-LEGEND"}


def _find_changed_race_dates(reports_dir_path: Path, dest_dir: Path) -> list[str]:
    """Race dates whose sanitized report is missing from dest_dir, or present but
    text-different from reports_dir_path's copy (edited since last published).
    Content-compared rather than mtime-compared -- both repos are git checkouts,
    where mtimes can change without the content actually changing. Compared as
    text (which normalizes line endings on read), not raw bytes -- fsrc-tech has
    core.autocrlf=true, so a file checked out there can differ byte-for-byte from
    this repo's LF copy (CRLF vs LF) with genuinely identical content; a raw byte
    comparison flags that as "changed" on every run.
    """
    available = sorted(p for p in reports_dir_path.glob("*.md") if p.stem not in _NON_RACE_STEMS)
    changed = []
    for src_path in available:
        dest_path = dest_dir / src_path.name
        if not dest_path.exists() or src_path.read_text(encoding="utf-8") != dest_path.read_text(encoding="utf-8"):
            changed.append(src_path.stem)
    return changed


def publish(
    race_date: str | None,
    fsrc_tech_dir: str,
    reports_dir: str = "reports",
    new: bool = False,
) -> None:
    reports_dir_path = Path(reports_dir)
    src_summary = reports_dir_path / "SUMMARY.md"
    if not src_summary.exists():
        raise FileNotFoundError(f"{src_summary} not found")
    src_legend = reports_dir_path / "SUMMARY-LEGEND.md"
    if not src_legend.exists():
        raise FileNotFoundError(f"{src_legend} not found")

    dest_dir = Path(fsrc_tech_dir) / "docs" / "race-services" / "reports"
    if not dest_dir.is_dir():
        raise FileNotFoundError(
            f"{dest_dir} not found -- is fsrc_tech_dir ({fsrc_tech_dir}) a valid fsrc-tech checkout?"
        )

    if new:
        race_dates = _find_changed_race_dates(reports_dir_path, dest_dir)
        if not race_dates:
            print("no new or changed race reports to publish -- fsrc-tech is already up to date")
        else:
            print(f"found {len(race_dates)} new or changed race report(s): {', '.join(race_dates)}")
    else:
        race_dates = [race_date]

    for date in race_dates:
        src_report = reports_dir_path / f"{date}.md"
        if not src_report.exists():
            raise FileNotFoundError(
                f"{src_report} not found -- run report/generate.py for this race first"
            )
        dest_report = dest_dir / f"{date}.md"
        shutil.copyfile(src_report, dest_report)
        print(f"copied {src_report} -> {dest_report}")

    dest_summary = dest_dir / "README.md"
    shutil.copyfile(src_summary, dest_summary)
    print(f"copied {src_summary} -> {dest_summary} (overwritten)")

    dest_legend = dest_dir / "SUMMARY-LEGEND.md"
    shutil.copyfile(src_legend, dest_legend)
    print(f"copied {src_legend} -> {dest_legend} (overwritten)")

    print()
    print("Remaining manual steps (per CLAUDE.md), not done by this script:")
    print("  - first publish only: link docs/race-services/reports/README.md from docs/race-services/README.md")
    print("  - add a dated entry to fsrc-tech/CHANGELOG.md")
    print("  - review, commit, and push in fsrc-tech")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "race_date",
        nargs="?",
        default=None,
        help="e.g. 2026-07-04 -- must match an existing reports/<race_date>.md. Omit when using --new.",
    )
    parser.add_argument("fsrc_tech_dir", help="path to a local fsrc-tech checkout")
    parser.add_argument(
        "--new",
        action="store_true",
        help="publish every reports/<date>.md that's missing or changed in fsrc_tech_dir, instead of a single race_date",
    )
    parser.add_argument("--reports-dir", default="reports")
    args = parser.parse_args()

    if args.new and args.race_date:
        parser.error("race_date and --new are mutually exclusive")
    if not args.new and not args.race_date:
        parser.error("race_date is required unless --new is given")

    publish(args.race_date, args.fsrc_tech_dir, args.reports_dir, new=args.new)
