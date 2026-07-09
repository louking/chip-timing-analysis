"""Parser for the bib<->chip assignment list (bib-chip.csv)."""

from __future__ import annotations

from pathlib import Path

import pandas as pd


def parse_bib_chip(file_path: str | Path) -> pd.DataFrame:
    """Parse a bib-chip.csv (header: bib,chip) into a DataFrame.

    tag_id is lowercased to match the case used by parse_trident_raw's tag_id
    (the raw log's chip field is uppercase; the reader logs it lowercase).
    """
    df = pd.read_csv(file_path, dtype={"bib": "int64", "chip": "string"})
    df["chip"] = df["chip"].str.lower()
    df = df.rename(columns={"chip": "tag_id"})
    return df[["bib", "tag_id"]]


def sanity_check(df: pd.DataFrame) -> None:
    print(f"records: {len(df)}")
    if df.empty:
        return
    print(f"unique bibs: {df['bib'].nunique()}")
    print(f"unique tags: {df['tag_id'].nunique()}")
    dupes = df[df.duplicated("tag_id", keep=False)]
    if not dupes.empty:
        print(f"WARNING: {len(dupes)} rows share a tag_id with another bib")


if __name__ == "__main__":
    import sys

    df = parse_bib_chip(sys.argv[1])
    sanity_check(df)
