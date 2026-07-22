"""The pure guardrail logic in front of run_kql: the allow-list, the timespan bounds, and the
result caps that protect the model's context."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from lib.kql import (
    ensure_workspace_allowed,
    parse_allowed_workspaces,
    parse_timespan_hours,
    shape_table,
)


class TestAllowList:
    def test_the_setting_parses_commas_semicolons_and_whitespace(self):
        assert parse_allowed_workspaces(" AAA , bbb ;CCC,, ") == ["aaa", "bbb", "ccc"]

    @pytest.mark.parametrize("setting", [None, "", "   "])
    def test_an_absent_setting_means_nothing_is_allowed(self, setting):
        assert parse_allowed_workspaces(setting) == []

    def test_an_allowed_workspace_passes_case_insensitively(self):
        assert ensure_workspace_allowed("ABC-123", ["abc-123"]) == "abc-123"

    def test_a_workspace_off_the_list_is_refused(self):
        with pytest.raises(ValueError, match="not on this deployment's allow-list"):
            ensure_workspace_allowed("abc", ["def"])

    def test_an_empty_allow_list_refuses_everything(self):
        with pytest.raises(ValueError, match="no workspaces are allow-listed"):
            ensure_workspace_allowed("abc", [])

    @pytest.mark.parametrize("workspace", [None, "", "  "])
    def test_a_missing_workspace_id_is_refused(self, workspace):
        with pytest.raises(ValueError, match="workspace_id is required"):
            ensure_workspace_allowed(workspace, ["abc"])


class TestTimespan:
    @pytest.mark.parametrize(("value", "expected"), [(None, 24), ("", 24), ("  ", 24), ("6", 6.0), (12, 12.0), ("0.5", 0.5)])
    def test_defaults_and_numeric_values(self, value, expected):
        assert parse_timespan_hours(value) == expected

    @pytest.mark.parametrize("value", ["abc", "0", "-1", "9999", 721])
    def test_out_of_bounds_or_garbage_is_refused(self, value):
        with pytest.raises(ValueError):
            parse_timespan_hours(value)


class TestShapeTable:
    def test_rows_become_dicts_keyed_by_column(self):
        shaped = shape_table(["name", "count"], [["a", 1], ["b", 2]])

        assert shaped["rows"] == [{"name": "a", "count": 1}, {"name": "b", "count": 2}]
        assert shaped["rowCount"] == 2
        assert shaped["truncated"] is False

    def test_the_row_cap_truncates_and_says_so(self):
        shaped = shape_table(["n"], [[i] for i in range(150)], max_rows=100)

        assert shaped["rowCount"] == 100
        assert shaped["truncated"] is True

    def test_long_cells_are_truncated_with_a_marker(self):
        shaped = shape_table(["blob"], [["x" * 2000]], max_cell_chars=100)

        cell = shaped["rows"][0]["blob"]
        assert cell.endswith("... (truncated)")
        assert len(cell) == 100 + len("... (truncated)")

    def test_numbers_booleans_and_nulls_pass_through_untouched(self):
        shaped = shape_table(["a", "b", "c", "d"], [[1, 2.5, True, None]])

        assert shaped["rows"][0] == {"a": 1, "b": 2.5, "c": True, "d": None}

    def test_non_primitive_cells_become_strings(self):
        shaped = shape_table(["when"], [[__import__("datetime").datetime(2026, 7, 22, 12, 0)]])

        assert isinstance(shaped["rows"][0]["when"], str)
        assert "2026" in shaped["rows"][0]["when"]
