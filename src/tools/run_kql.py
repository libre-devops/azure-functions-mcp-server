"""run_kql: a scoped, read-only KQL query against an allow-listed Log Analytics workspace.

Two gates in front of every query: the deployment's workspace allow-list (the
ALLOWED_WORKSPACE_IDS app setting, managed by the Terraform), then the identity's own RBAC (the
server needs Log Analytics Reader on the workspace, granted only where the stack points it). The
Log Analytics query API is read-only by design, and results are capped before they reach the
model.
"""

import json
import os

import azure.functions as func

from lib.kql import (
    ensure_workspace_allowed,
    parse_allowed_workspaces,
    parse_timespan_hours,
    shape_table,
)

bp = func.Blueprint()


@bp.mcp_tool()
@bp.mcp_tool_property(
    arg_name="workspace_id",
    description=(
        "The Log Analytics workspace to query: the workspace GUID (customer id), not the ARM "
        "resource id. Must be on the deployment's allow-list."
    ),
)
@bp.mcp_tool_property(
    arg_name="query",
    description="The KQL query to run. The Log Analytics query API is read-only by design.",
)
@bp.mcp_tool_property(
    arg_name="timespan_hours",
    description="Optional: how far back to query, in hours. Defaults to 24, capped at 720.",
    is_required=False,
)
def run_kql(workspace_id: str, query: str, timespan_hours: str = None) -> str:
    """Run a read-only KQL query against an allow-listed Azure Log Analytics workspace and return
    the rows as JSON. The workspace must be on this deployment's allow-list and the server's
    identity needs Log Analytics Reader on it. Results are capped at 100 rows and long cells are
    truncated, so ask precise questions (project the columns you need, summarize where you can)."""
    try:
        allowed = parse_allowed_workspaces(os.environ.get("ALLOWED_WORKSPACE_IDS"))
        workspace = ensure_workspace_allowed(workspace_id, allowed)
        hours = parse_timespan_hours(timespan_hours)
    except ValueError as err:
        return _error(str(err))
    if query is None or not str(query).strip():
        return _error("query is required")

    # Imported lazily so the module (and tool discovery, and the unit tests) never needs Azure.
    from datetime import timedelta

    from azure.core.exceptions import HttpResponseError
    from azure.identity import DefaultAzureCredential
    from azure.monitor.query import LogsQueryClient, LogsQueryStatus

    client = LogsQueryClient(DefaultAzureCredential())
    try:
        result = client.query_workspace(workspace, query, timespan=timedelta(hours=hours))
    except HttpResponseError as err:
        return _error(f"{err.reason}, {err.message}")

    partial = result.status == LogsQueryStatus.PARTIAL
    tables = result.partial_data if partial else result.tables
    table = tables[0] if tables else None
    shaped = (
        shape_table([str(column) for column in table.columns], table.rows)
        if table is not None
        else {"rows": [], "rowCount": 0, "truncated": False}
    )

    body = {"workspaceId": workspace, "timespanHours": hours}
    body.update(shaped)
    if partial:
        body["partial"] = True
        body["partialError"] = str(result.partial_error)

    return json.dumps(body, indent=2, default=str)


def _error(message: str) -> str:
    return json.dumps({"error": message}, indent=2)
