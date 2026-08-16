"""test_generate - test chip_timing_analysis.report.generate

Focuses on _parse_args' blank/whitespace-only-string handling -- a real
VS Code task gotcha (CLAUDE.md): an optional input whose value ends up as ""
or a lone space must be treated as "not provided", not a literal value (a
literal " " passed to pd.Timestamp() for --gun-time would raise). Also
covers _parse_bib_list (comma/space-separated --known-drop/--exclude-bib
values, needed so a single VS Code task prompt can supply a whole group)
and the .generate-args.json sidecar used by --from-last-run.
"""

import pytest

from chip_timing_analysis.report.generate import (
    _load_args_sidecar, _parse_args, _parse_bib_list, _save_args_sidecar,
)


def test_required_race_dir_is_parsed():
    args = _parse_args(["data/2026-05-25-panda-5k"])

    assert args.race_dir == "data/2026-05-25-panda-5k"


def test_optional_fields_default_to_none():
    args = _parse_args(["race_dir"])

    assert args.race_name is None
    assert args.race_date is None
    assert args.distance is None
    assert args.gun_time is None


def test_explicit_value_is_kept():
    args = _parse_args(["race_dir", "--race-name", "Indy 5000"])

    assert args.race_name == "Indy 5000"


def test_blank_string_value_becomes_none():
    args = _parse_args(["race_dir", "--race-name", ""])

    assert args.race_name is None


def test_whitespace_only_value_becomes_none():
    # a VS Code promptString default of " " (not "", to dodge the
    # cancelled-prompt gotcha) must still resolve to "not provided"
    args = _parse_args(["race_dir", "--gun-time", " "])

    assert args.gun_time is None


def test_all_four_optional_string_fields_get_blank_handling():
    args = _parse_args([
        "race_dir",
        "--race-name", " ", "--race-date", " ", "--distance", " ", "--gun-time", " ",
    ])

    assert args.race_name is None
    assert args.race_date is None
    assert args.distance is None
    assert args.gun_time is None


def test_blank_notes_are_dropped_not_kept_as_empty_bullets():
    args = _parse_args(["race_dir", "--note", "  ", "--note", "real note"])

    assert args.notes == ["real note"]


def test_blank_detail_notes_are_dropped():
    args = _parse_args(["race_dir", "--detail-note", " ", "--detail-note", "bib 641 detail"])

    assert args.detail_notes == ["bib 641 detail"]


def test_notes_default_to_empty_list():
    args = _parse_args(["race_dir"])

    assert args.notes == []
    assert args.detail_notes == []


def test_known_drop_and_exclude_bib_are_repeatable_ints():
    args = _parse_args(["race_dir", "--known-drop", "267", "--known-drop", "303", "--exclude-bib", "375"])

    assert args.known_drops == [267, 303]
    assert args.exclude_bibs == [375]


def test_n_registered_starters_finishers_parse_as_ints():
    args = _parse_args(["race_dir", "--n-registered", "141", "--n-starters", "110", "--n-finishers", "109"])

    assert args.n_registered == 141
    assert args.n_starters == 110
    assert args.n_finishers == 109


def test_reports_dir_defaults_to_reports():
    args = _parse_args(["race_dir"])

    assert args.reports_dir == "reports"


# ----------------------------------------------------------------------
# _parse_bib_list / --known-drop, --exclude-bib comma-list handling
# ----------------------------------------------------------------------

def test_parse_bib_list_single_bib():
    assert _parse_bib_list("267") == [267]


def test_parse_bib_list_comma_separated():
    assert _parse_bib_list("267,303,333") == [267, 303, 333]


def test_parse_bib_list_space_separated():
    assert _parse_bib_list("267 303 333") == [267, 303, 333]


def test_parse_bib_list_comma_and_space_mixed_with_extra_whitespace():
    assert _parse_bib_list(" 267, 303,  333 ") == [267, 303, 333]


def test_parse_bib_list_blank_returns_empty():
    assert _parse_bib_list(" ") == []
    assert _parse_bib_list("") == []


def test_known_drop_comma_list_flattens_in_parsed_args():
    args = _parse_args(["race_dir", "--known-drop", "267,303,333"])

    assert args.known_drops == [267, 303, 333]


def test_known_drop_repeated_and_comma_list_both_flatten():
    args = _parse_args(["race_dir", "--known-drop", "267,303", "--known-drop", "333"])

    assert args.known_drops == [267, 303, 333]


def test_exclude_bib_comma_list_flattens_in_parsed_args():
    args = _parse_args(["race_dir", "--exclude-bib", "375, 400"])

    assert args.exclude_bibs == [375, 400]


def test_known_drop_blank_vscode_sentinel_flattens_to_empty_list():
    # a VS Code task's default " " for an unfilled knownDrops prompt
    args = _parse_args(["race_dir", "--known-drop", " "])

    assert args.known_drops == []


def test_known_drops_and_exclude_bibs_default_to_empty_list():
    args = _parse_args(["race_dir"])

    assert args.known_drops == []
    assert args.exclude_bibs == []


# ----------------------------------------------------------------------
# --from-last-run flag parsing
# ----------------------------------------------------------------------

def test_from_last_run_defaults_to_false():
    args = _parse_args(["race_dir"])

    assert args.from_last_run is False


def test_from_last_run_flag_is_parsed():
    args = _parse_args(["race_dir", "--from-last-run"])

    assert args.from_last_run is True


# ----------------------------------------------------------------------
# .generate-args.json sidecar (--from-last-run's data source)
# ----------------------------------------------------------------------

def test_sidecar_round_trips_saved_options(tmp_path):
    _save_args_sidecar(
        tmp_path,
        race_name="Panda 5K", race_date="2026-05-25", distance="5K", gun_time=None,
        notes=["a note"], detail_notes=[],
        n_registered=300, n_starters=None, n_finishers=None,
        known_drops=[267, 303, 333], exclude_bibs=[375],
    )

    loaded = _load_args_sidecar(tmp_path)

    assert loaded["race_name"] == "Panda 5K"
    assert loaded["known_drops"] == [267, 303, 333]
    assert loaded["exclude_bibs"] == [375]
    assert loaded["n_registered"] == 300
    assert loaded["gun_time"] is None


def test_sidecar_missing_raises_with_actionable_message(tmp_path):
    with pytest.raises(FileNotFoundError, match="--from-last-run"):
        _load_args_sidecar(tmp_path)


def test_sidecar_file_is_hidden_dotfile(tmp_path):
    _save_args_sidecar(
        tmp_path,
        race_name=None, race_date=None, distance=None, gun_time=None,
        notes=[], detail_notes=[],
        n_registered=None, n_starters=None, n_finishers=None,
        known_drops=[], exclude_bibs=[],
    )

    assert (tmp_path / ".generate-args.json").exists()
