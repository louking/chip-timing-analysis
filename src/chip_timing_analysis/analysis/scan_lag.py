"""Time Machine-to-scan lag: how far the barcode scanner trails the finish line.

For each Time Machine result entered with a keypad bib, find that runner's
own scan in barcode-scanner.log and take the time from the TM press to the
scan. Results without a keypad bib can't be matched this way.

This complements queue_lag.py, which measures chip finish to scan. Both
times here come from the tmtility laptop's own logs (tm-reader.log and
barcode-scanner.log), so no clock-offset correction is needed and no chip
data is used: it works the same on a race with no chip timing. Each time is
a "sending to backend" line, so each includes up to ~0.3s of client
queueing. A bib scanned more than once is matched to its scan nearest the
result. A match more than max_lag away is treated as no match (a warm-up
result, or a bib keyed wrong on the TM).

Written for tm-csv-connector #159 (louking/tm-csv-connector#159). On the
2026-10-25 Headless Horseman 5K (tmtility race id 6, whole race day): 135
keypad results, 88 matched, lag median 4.0s, 5th-95th percentile 2.2-10.2s,
min 1.7s, max 23.6s. That spread, with correctly scanned runners up to 23.6s
behind their TM press, is why tmtility decided against a lag-based scan
drift indicator.

Run from the command line on a folder holding both logs:

    python -m chip_timing_analysis.analysis.scan_lag LOGDIR --date 2026-10-25 [--raceid 6] [--max-lag 60] [--slow 10] [--all]
"""

from __future__ import annotations

from statistics import median, quantiles

import pandas as pd

DEFAULT_MAX_LAG = pd.Timedelta(seconds=60)

_COLUMNS = ["pos", "bib", "tm_time", "scan_time", "lag_sec", "matched"]


def tm_scan_lag(
    tm_sends: pd.DataFrame,
    scans: pd.DataFrame,
    max_lag: pd.Timedelta = DEFAULT_MAX_LAG,
) -> pd.DataFrame:
    """One row per TM result with a keypad bib (columns: pos, bib, tm_time,
    scan_time, lag_sec, matched). tm_sends is parse_tm_sends() output and
    scans is parse_scanner_sends() output. lag_sec is scan_time - tm_time
    for the bib's scan nearest the TM result (NaN if the bib was never
    scanned); matched is whether |lag| <= max_lag. Rows are in TM order."""
    keyed = tm_sends[tm_sends["bib"] != 0]
    scans_by_bib = scans.groupby("bib")["send_time"].apply(list).to_dict()
    limit = max_lag.total_seconds()

    rows = []
    for _, r in keyed.iterrows():
        scan_time, lag = pd.NaT, None
        for s in scans_by_bib.get(r["bib"], []):
            d = (s - r["send_time"]).total_seconds()
            if lag is None or abs(d) < abs(lag):
                scan_time, lag = s, d
        rows.append({
            "pos": r["pos"],
            "bib": r["bib"],
            "tm_time": r["send_time"],
            "scan_time": scan_time,
            "lag_sec": lag if lag is not None else float("nan"),
            "matched": lag is not None and abs(lag) <= limit,
        })
    return pd.DataFrame(rows, columns=_COLUMNS).astype({"matched": bool})


def scan_lag_summary(lag: pd.DataFrame) -> dict:
    """{n_results, n_matched, median, p5, p95, min, max} over matched rows,
    in seconds. The statistics are None with fewer than 2 matches. p5/p95
    use statistics.quantiles (exclusive method), as the original script
    did, so the 2026-10-25 check numbers still hold."""
    lags = lag.loc[lag["matched"], "lag_sec"].tolist()
    out = {"n_results": len(lag), "n_matched": len(lags),
           "median": None, "p5": None, "p95": None, "min": None, "max": None}
    if len(lags) >= 2:
        pct = quantiles(lags, n=20)
        out.update(median=median(lags), p5=pct[0], p95=pct[-1], min=min(lags), max=max(lags))
    return out


def _fmt_row(row) -> str:
    lag = f"{row['lag_sec']:6.1f}s" if pd.notna(row["lag_sec"]) else "  no scan"
    return f"  {row['pos']:4} {row['bib']:>6} {lag}"


def format_text(lag: pd.DataFrame, slow: float = 10, show_all: bool = False) -> str:
    """The original script's plain-text output."""
    s = scan_lag_summary(lag)
    lines = [f"{s['n_results']} keypad results, {s['n_matched']} matched to their own scan, "
             f"{s['n_results'] - s['n_matched']} not"]
    if s["median"] is not None:
        lines.append(f"lag median {s['median']:.1f}s, 5th-95th percentile {s['p5']:.1f}s-{s['p95']:.1f}s, "
                     f"min {s['min']:.1f}s, max {s['max']:.1f}s")
    matched = lag[lag["matched"]]
    slow_rows = matched[matched["lag_sec"] > slow]
    if not slow_rows.empty:
        lines += ["", f"matched lags above {slow:g}s (TM pos, bib, lag):"]
        lines += [_fmt_row(r) for _, r in slow_rows.iterrows()]
    unmatched = lag[~lag["matched"]]
    if not unmatched.empty:
        lines += ["", "not matched (TM pos, bib, nearest scan):"]
        lines += [_fmt_row(r) for _, r in unmatched.iterrows()]
    if show_all:
        lines += ["", "all keypad results (TM pos, bib, lag):"]
        lines += [_fmt_row(r) for _, r in lag.sort_values("pos", kind="stable").iterrows()]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> None:
    from argparse import ArgumentParser
    from pathlib import Path

    from chip_timing_analysis.parsers.barcode_scanner import parse_scanner_sends
    from chip_timing_analysis.parsers.tm_reader import parse_tm_sends

    parser = ArgumentParser(description="Time Machine-to-scan lag per runner, from tmtility race-day client logs")
    parser.add_argument("logdir", help="folder with tm-reader.log and barcode-scanner.log")
    parser.add_argument("--date", required=True, help="race date, yyyy-mm-dd")
    parser.add_argument("--raceid", help="tmtility race id, to skip other races' messages on that date")
    parser.add_argument("--max-lag", type=float, default=DEFAULT_MAX_LAG.total_seconds(),
                        help="largest |lag| counted as a match, seconds (default 60)")
    parser.add_argument("--slow", type=float, default=10, help="list matched lags above this, seconds (default 10)")
    parser.add_argument("--all", action="store_true", help="list every keypad result")
    args = parser.parse_args(argv)

    from chip_timing_analysis.wslpath import to_wsl_path
    logdir = Path(to_wsl_path(args.logdir))
    day = pd.Timestamp(args.date)
    window = dict(start=day, end=day + pd.Timedelta(days=1), raceid=args.raceid)
    tm_sends = parse_tm_sends(logdir / "tm-reader.log", **window)
    scans = parse_scanner_sends(logdir / "barcode-scanner.log", **window)
    lag = tm_scan_lag(tm_sends, scans, max_lag=pd.Timedelta(seconds=args.max_lag))
    print(format_text(lag, slow=args.slow, show_all=args.all))


if __name__ == "__main__":
    main()
