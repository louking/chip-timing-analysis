"""CLI: generate a race's detailed + sanitized reports and append it to the
running cross-race summary.

Usage:
    python -m chip_timing_analysis.report.generate \\
        <race_dir> \\
        [--race-name NAME] [--race-date YYYY-MM-DD] [--distance 5K|10K|10M] \\
        [--gun-time "YYYY-MM-DD HH:MM:SS"] \\
        [--note TEXT ...] [--detail-note TEXT ...] \\
        [--n-registered N] [--n-starters N] [--n-finishers N] \\
        [--known-drop BIB[,BIB...] ...] [--exclude-bib BIB[,BIB...] ...] \\
        [--reports-dir DIR] [--from-last-run]

--race-name/--race-date/--distance/--gun-time are only required when race_dir
has no RDS full-database-export zip (see CLAUDE.md / parsers/rdgo_export.py)
-- when one is present, any left unset are derived from it (race_name from
the export's own race name, race_date from the gun time's date, distance
from each scored_event's Gap Factor, gun_time from its GUNTIME marker). Pass
any of them explicitly to override the derived value.

--note is a free-text note about an unusual occurrence at the race (e.g.
equipment trouble that didn't affect results) -- included verbatim in the
detailed report, the sanitized report, AND the summary row, so keep these
bib/name-free. Repeat --note for multiple. --detail-note can name specific
bibs/individuals and is shown ONLY in the private detailed report (repeat
for multiple).

--known-drop / --exclude-bib each take a bib number, or a comma/space-
separated list of bibs in one flag (e.g. --known-drop "267,303,333") --
and may also be repeated for multiple bibs/groups. See RaceReport/
build_race_report() docstrings for the distinction: a known drop started
but didn't finish (real DNF); an excluded bib is removed from the
participant universe entirely (e.g. a chip cross-reference that was a
data-entry error, never really issued).

--from-last-run replays race_name/race_date/distance/gun_time/notes/
detail_notes/n_registered/n_starters/n_finishers/known_drops/exclude_bibs
saved from this race_dir's last successful run (see .generate-args.json,
written there after every run) -- any of those flags also passed alongside
--from-last-run are ignored. Useful for re-running a race after a
software update, without having to retype every override by hand.

Example (zip present -- race_name/race_date/distance/gun_time all derived):
    python -m chip_timing_analysis.report.generate "data/2026-05-25-panda-5k" \\
        --n-registered 300 --known-drop 267 --known-drop 303 --known-drop 333

Example (no zip -- CSV path, everything explicit):
    python -m chip_timing_analysis.report.generate \\
        "data/2026-07-04-indy-5000" \\
        --race-name "Indy 5000" --race-date "2026-07-04" --distance "5K" \\
        --gun-time "2026-07-04 08:30:02" \\
        --note "Brief live-network interruption ~09:05-09:07; did not affect final results, all recovered via backup timing." \\
        --n-registered 141 --n-starters 110 --n-finishers 109

Writes:
    <race_dir>/report.md    -- detailed, bib-level (gitignored with the rest of data/)
    reports/<race_date>.md  -- sanitized, aggregate-only, no race name anywhere
                                (not in the filename either -- it's going into git/GitHub)
    reports/SUMMARY.md      -- one row appended for this race
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from chip_timing_analysis.report.build import build_race_report
from chip_timing_analysis.report.render import render_detailed_report, render_sanitized_report, append_summary_row
from chip_timing_analysis.wslpath import to_wsl_path

# Sidecar written next to report.md in race_dir after every successful run,
# recording the options used -- lets --from-last-run replay them verbatim
# (e.g. after a software update) without retyping known_drops/exclude_bibs/etc.
_ARGS_SIDECAR_NAME = ".generate-args.json"


def _save_args_sidecar(race_dir_path: Path, **kwargs) -> None:
    (race_dir_path / _ARGS_SIDECAR_NAME).write_text(
        json.dumps(kwargs, indent=2) + "\n", encoding="utf-8",
    )


def _load_args_sidecar(race_dir_path: Path) -> dict:
    path = race_dir_path / _ARGS_SIDECAR_NAME
    if not path.exists():
        raise FileNotFoundError(
            f"{path} not found -- this race has no prior successful generate() run to replay "
            "(--from-last-run needs one)"
        )
    return json.loads(path.read_text(encoding="utf-8"))


def generate(
    race_dir: str,
    race_name: str | None = None,
    race_date: str | None = None,
    distance: str | None = None,
    gun_time: str | None = None,
    notes: list[str] | None = None,
    detail_notes: list[str] | None = None,
    reports_dir: str = "reports",
    n_registered: int | None = None,
    n_starters: int | None = None,
    n_finishers: int | None = None,
    known_drops: list[int] | None = None,
    exclude_bibs: list[int] | None = None,
    from_last_run: bool = False,
) -> None:
    race_dir_path = Path(to_wsl_path(race_dir))

    if from_last_run:
        saved = _load_args_sidecar(race_dir_path)
        print(f"replaying options saved from a prior run ({_ARGS_SIDECAR_NAME}): {saved}")
        race_name, race_date, distance, gun_time = (
            saved["race_name"], saved["race_date"], saved["distance"], saved["gun_time"]
        )
        notes, detail_notes = saved["notes"], saved["detail_notes"]
        n_registered, n_starters, n_finishers = (
            saved["n_registered"], saved["n_starters"], saved["n_finishers"]
        )
        known_drops, exclude_bibs = saved["known_drops"], saved["exclude_bibs"]

    report = build_race_report(
        race_dir_path, race_name, race_date, distance, gun_time,
        notes=notes, detail_notes=detail_notes,
        n_registered=n_registered, n_starters=n_starters, n_finishers=n_finishers,
        known_drops=known_drops, exclude_bibs=exclude_bibs,
    )

    detailed_path = race_dir_path / "report.md"
    detailed_path.write_text(render_detailed_report(report), encoding="utf-8")
    print(f"wrote {detailed_path}")

    reports_dir_path = Path(reports_dir)
    reports_dir_path.mkdir(parents=True, exist_ok=True)
    # filename is date-only, not the race slug -- this file is git-tracked
    # (going into GitHub), and the race name shouldn't be discoverable just
    # from browsing the repo's file listing. Uses report.race_date (the
    # resolved value) rather than the race_date argument, which may have
    # been None and derived from the RDS export inside build_race_report().
    sanitized_path = reports_dir_path / f"{report.race_date}.md"
    sanitized_path.write_text(render_sanitized_report(report), encoding="utf-8")
    print(f"wrote {sanitized_path}")

    summary_path = reports_dir_path / "SUMMARY.md"
    append_summary_row(report, summary_path)
    print(f"appended row to {summary_path}")

    _save_args_sidecar(
        race_dir_path,
        race_name=race_name, race_date=race_date, distance=distance,
        gun_time=str(gun_time) if gun_time is not None else None,
        notes=notes or [], detail_notes=detail_notes or [],
        n_registered=n_registered, n_starters=n_starters, n_finishers=n_finishers,
        known_drops=known_drops or [], exclude_bibs=exclude_bibs or [],
    )


def _parse_bib_list(value: str) -> list[int]:
    """Parses one --known-drop/--exclude-bib occurrence, which may be a
    single bib or a comma/space-separated list (e.g. "267,303,333") -- lets
    one VS Code task prompt supply a whole group in a single flag.
    """
    return [int(tok) for tok in re.split(r"[,\s]+", value.strip()) if tok]


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate a race's detailed + sanitized reports and append it to the running cross-race summary.",
    )
    parser.add_argument("race_dir")
    parser.add_argument(
        "--race-name", default=None,
        help="Required only when race_dir has no RDS export zip (otherwise derived from it).",
    )
    parser.add_argument(
        "--race-date", default=None,
        help="Required only when race_dir has no RDS export zip (otherwise derived from gun_time's date).",
    )
    parser.add_argument(
        "--distance", default=None,
        help="Required only when race_dir has no RDS export zip (otherwise derived from the export's Gap Factor).",
    )
    parser.add_argument(
        "--gun-time", default=None,
        help="Required only when race_dir has no RDS export zip.",
    )
    parser.add_argument(
        "--note", dest="notes", action="append", default=[],
        help="Bib/name-free note, shown in all three outputs. Repeatable.",
    )
    parser.add_argument(
        "--detail-note", dest="detail_notes", action="append", default=[],
        help="Note that may name bibs/individuals, shown only in the private detailed report. Repeatable.",
    )
    parser.add_argument("--reports-dir", default="reports")
    parser.add_argument("--n-registered", type=int, default=None)
    parser.add_argument("--n-starters", type=int, default=None)
    parser.add_argument("--n-finishers", type=int, default=None)
    parser.add_argument(
        "--known-drop", dest="known_drops", type=_parse_bib_list, action="append", default=[],
        help="Bib(s) confirmed as a legitimate DNF (started, didn't finish) -- a single bib, or a "
             "comma/space-separated list in one flag. Repeatable.",
    )
    parser.add_argument(
        "--exclude-bib", dest="exclude_bibs", type=_parse_bib_list, action="append", default=[],
        help="Bib(s) to remove from the participant universe entirely (e.g. data-entry error) -- a "
             "single bib, or a comma/space-separated list in one flag. Repeatable.",
    )
    parser.add_argument(
        "--from-last-run", action="store_true",
        help="Replay options saved from this race_dir's last successful run instead of the flags above "
             "(see .generate-args.json in race_dir).",
    )
    args = parser.parse_args(argv)
    # Blank/whitespace-only strings (e.g. an unfilled VS Code task input,
    # which passes "" or -- for these optional fields -- a literal single
    # space, see .vscode/tasks.json's comment on why a bare "" default isn't
    # used -- rather than omitting the flag) mean "not provided" here, not a
    # literal value -- gun_time=" " would fail pd.Timestamp(), and a blank
    # note would show up as an empty bullet in the reports. race_name/
    # race_date/distance similarly fall through to build_race_report()'s own
    # None-means-derive-from-the-RDS-export handling.
    for attr in ("race_name", "race_date", "distance", "gun_time"):
        val = getattr(args, attr)
        if val is not None and val.strip() == "":
            setattr(args, attr, None)
    args.notes = [n for n in args.notes if n.strip()]
    args.detail_notes = [n for n in args.detail_notes if n.strip()]
    # each --known-drop/--exclude-bib occurrence parses to a list (possibly
    # empty, for a blank VS Code task input) -- flatten to one list of bibs.
    args.known_drops = [bib for group in args.known_drops for bib in group]
    args.exclude_bibs = [bib for group in args.exclude_bibs for bib in group]
    return args


if __name__ == "__main__":
    args = _parse_args()
    generate(
        args.race_dir, args.race_name, args.race_date, args.distance,
        gun_time=args.gun_time,
        notes=args.notes,
        detail_notes=args.detail_notes,
        reports_dir=args.reports_dir,
        n_registered=args.n_registered,
        n_starters=args.n_starters,
        n_finishers=args.n_finishers,
        known_drops=args.known_drops,
        exclude_bibs=args.exclude_bibs,
        from_last_run=args.from_last_run,
    )
