"""Scoped-KQL plumbing shared by the run_kql tool.

Pure functions only: no Azure SDK imports, no network calls, so everything here is exercised
directly by the unit tests. The guardrails live here: the workspace allow-list (defense in depth
in front of the identity's RBAC), the timespan bounds, and the result caps that keep a chatty
query from flooding the model's context.
"""

MAX_ROWS = 100
MAX_CELL_CHARS = 1000
DEFAULT_TIMESPAN_HOURS = 24
MAX_TIMESPAN_HOURS = 720


def parse_allowed_workspaces(setting):
    """Parse the ALLOWED_WORKSPACE_IDS app setting: workspace GUIDs separated by commas (or
    semicolons), case-insensitive, whitespace ignored."""
    if not setting:
        return []
    return [
        token.strip().lower()
        for token in str(setting).replace(";", ",").split(",")
        if token.strip()
    ]


def ensure_workspace_allowed(workspace_id, allowed):
    """Return the normalized workspace id, or raise ValueError when it is missing or not on the
    deployment's allow-list."""
    if workspace_id is None or not str(workspace_id).strip():
        raise ValueError("workspace_id is required")
    if not allowed:
        raise ValueError(
            "no workspaces are allow-listed on this deployment; set ALLOWED_WORKSPACE_IDS"
        )
    normalized = str(workspace_id).strip().lower()
    if normalized not in allowed:
        raise ValueError(f"workspace {workspace_id} is not on this deployment's allow-list")
    return normalized


def parse_timespan_hours(value):
    """Return the query timespan in hours: default 24, capped at 720 (30 days), positive."""
    if value is None or (isinstance(value, str) and not value.strip()):
        return DEFAULT_TIMESPAN_HOURS
    try:
        hours = float(value)
    except (TypeError, ValueError):
        raise ValueError(f"timespan_hours must be a number of hours: {value}") from None
    if hours <= 0 or hours > MAX_TIMESPAN_HOURS:
        raise ValueError(f"timespan_hours must be between 0 and {MAX_TIMESPAN_HOURS}")
    return hours


def shape_table(columns, rows, max_rows=MAX_ROWS, max_cell_chars=MAX_CELL_CHARS):
    """Shape a result table into row dicts, capping the row count and the size of any single
    cell so one query cannot flood the model's context. Numbers, booleans, and nulls pass
    through; everything else becomes a string."""
    shaped = []
    for row in list(rows)[:max_rows]:
        item = {}
        for column, cell in zip(columns, row):
            if cell is None or isinstance(cell, (int, float, bool)):
                value = cell
            else:
                value = str(cell)
                if len(value) > max_cell_chars:
                    value = value[:max_cell_chars] + "... (truncated)"
            item[str(column)] = value
        shaped.append(item)
    return {
        "rows": shaped,
        "rowCount": len(shaped),
        "truncated": len(list(rows)) > max_rows,
    }
