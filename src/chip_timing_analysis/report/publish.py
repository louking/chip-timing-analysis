"""CLI: copy a race's sanitized report and the running summary into a local
fsrc-tech checkout, per the manual publishing workflow documented in
CLAUDE.md ("Publishing sanitized reports to fsrc-tech").

This only copies files -- it does not touch fsrc-tech's own CHANGELOG.md,
and does not commit or push there. Both stay a deliberate manual step (per
Lou's call, not run proactively) -- see the printed reminder at the end.

Usage:
    python -m chip_timing_analysis.report.publish <race_date> <fsrc_tech_dir>

Example:
    python -m chip_timing_analysis.report.publish 2026-07-04 "../../fsrc-tech/fsrc-tech"

Copies:
    reports/<race_date>.md -> <fsrc_tech_dir>/docs/race-services/reports/<race_date>.md
    reports/SUMMARY.md     -> <fsrc_tech_dir>/docs/race-services/reports/README.md
                               (overwrite -- SUMMARY.md already accumulates every
                               race, so this fully replaces the fsrc-tech index)
"""

from __future__ import annotations

import argparse
import shutil
from pathlib import Path


def publish(race_date: str, fsrc_tech_dir: str, reports_dir: str = "reports") -> None:
    reports_dir_path = Path(reports_dir)
    src_report = reports_dir_path / f"{race_date}.md"
    if not src_report.exists():
        raise FileNotFoundError(
            f"{src_report} not found -- run report/generate.py for this race first"
        )
    src_summary = reports_dir_path / "SUMMARY.md"
    if not src_summary.exists():
        raise FileNotFoundError(f"{src_summary} not found")

    dest_dir = Path(fsrc_tech_dir) / "docs" / "race-services" / "reports"
    if not dest_dir.is_dir():
        raise FileNotFoundError(
            f"{dest_dir} not found -- is fsrc_tech_dir ({fsrc_tech_dir}) a valid fsrc-tech checkout?"
        )

    dest_report = dest_dir / f"{race_date}.md"
    shutil.copyfile(src_report, dest_report)
    print(f"copied {src_report} -> {dest_report}")

    dest_summary = dest_dir / "README.md"
    shutil.copyfile(src_summary, dest_summary)
    print(f"copied {src_summary} -> {dest_summary} (overwritten)")

    print()
    print("Remaining manual steps (per CLAUDE.md), not done by this script:")
    print("  - first publish only: link docs/race-services/reports/README.md from docs/race-services/README.md")
    print("  - add a dated entry to fsrc-tech/CHANGELOG.md")
    print("  - review, commit, and push in fsrc-tech")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("race_date", help="e.g. 2026-07-04 -- must match an existing reports/<race_date>.md")
    parser.add_argument("fsrc_tech_dir", help="path to a local fsrc-tech checkout")
    parser.add_argument("--reports-dir", default="reports")
    args = parser.parse_args()
    publish(args.race_date, args.fsrc_tech_dir, args.reports_dir)
