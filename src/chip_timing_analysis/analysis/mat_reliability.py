"""Per-mat raw-read diagnostics: whether one or more antennas are reading at
a low level or being missed entirely, which could point to a cabling/power
problem worth a physical check.

Uses r_*.log (RR, every individual antenna ping) rather than f_*.log (BS/LS,
one representative read per crossing) -- filtering collapses exactly the
density/signal-strength this needs: a weak mat might yield 1 raw read per
tag vs. 15 for a strong one, but both look identical once reduced to a
single BS/LS record (see CLAUDE.md).

Per Lou (race director, knows the physical setup): comparing a specific
missed-read bib's raw pings against their own filtered-file miss isn't a
useful diagnostic -- if raw reads existed but didn't produce a scored BS/LS
record, that would mean Trident's own onboard filtering silently dropped a
good read, which would be a device software bug and is vanishingly
unlikely. The actual information raw reads carry is purely per-mat: is a
given antenna reading weakly (low signal strength) or being missed
completely (near-zero reads), which are the two things a bad cable/connector
would produce. Read counts and coverage also naturally taper from the
middle of the mat run toward the edges (fewer runners take the outermost
lanes), so a real cabling problem shows up as a LOCAL dip relative to a
mat's immediate neighbors, not a deviation from the race-wide average.
"""

from __future__ import annotations

import pandas as pd


def mat_summary(raw_reads: pd.DataFrame) -> pd.DataFrame:
    """One row per mat_id: total raw reads, unique tags seen, reads-per-tag
    (density), and mean signal strength (RSSI) -- the direct "reading at a
    low level" indicator.
    """
    columns = ["mat_id", "n_reads", "n_unique_tags", "reads_per_tag", "mean_signal_strength"]
    if raw_reads.empty:
        return pd.DataFrame(columns=columns)
    summary = raw_reads.groupby("mat_id").agg(
        n_reads=("tag_id", "size"),
        n_unique_tags=("tag_id", "nunique"),
        mean_signal_strength=("signal_strength", "mean"),
    ).reset_index()
    summary["reads_per_tag"] = summary["n_reads"] / summary["n_unique_tags"]
    return summary.sort_values("mat_id").reset_index(drop=True)[columns]


def flag_weak_mats(summary: pd.DataFrame, drop_ratio: float = 0.5) -> pd.DataFrame:
    """Mats whose unique-tag coverage or mean signal strength is well below
    (less than `drop_ratio` of) the average of their immediate neighbors
    (adjacent mat_id) -- a local, neighbor-relative comparison rather than a
    race-wide one, so an expected smooth taper toward the edges of the mat
    run isn't misflagged as a problem. Also sidesteps needing to know which
    end of the run (if either) is nearer the reader cabling -- mat_id 1
    isn't assumed to be either edge or middle.
    """
    columns = list(summary.columns)
    if summary.empty or len(summary) < 2:
        return summary.iloc[0:0]

    ordered = summary.sort_values("mat_id").reset_index(drop=True)
    flagged_ids = []
    for i in range(len(ordered)):
        neighbor_idx = [j for j in (i - 1, i + 1) if 0 <= j < len(ordered)]
        neighbors = ordered.loc[neighbor_idx]
        row = ordered.iloc[i]

        neighbor_coverage = neighbors["n_unique_tags"].mean()
        weak_coverage = neighbor_coverage > 0 and row["n_unique_tags"] < drop_ratio * neighbor_coverage

        neighbor_signal = neighbors["mean_signal_strength"].mean()
        weak_signal = (
            pd.notna(neighbor_signal) and pd.notna(row["mean_signal_strength"])
            and row["mean_signal_strength"] < drop_ratio * neighbor_signal
        )

        if weak_coverage or weak_signal:
            flagged_ids.append(row["mat_id"])

    return ordered[ordered["mat_id"].isin(flagged_ids)][columns]


def mat_reliability_verdict(summary: pd.DataFrame, weak_mats: pd.DataFrame) -> dict:
    """Roll mat_summary() + flag_weak_mats() up into a single verdict for the
    report: does any mat look like it has a local coverage/signal-strength
    problem worth a physical check?
    """
    return {
        "n_mats": len(summary),
        "weak_mats": sorted(weak_mats["mat_id"].tolist()) if not weak_mats.empty else [],
        "systemic_signal": not weak_mats.empty,
    }
