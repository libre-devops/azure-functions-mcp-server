"""check_cidr: validate any IPv4 CIDR against Azure's subnet rules.

Pure arithmetic, no Azure call, so this tool needs no identity and works the moment a bare
deployment lands.
"""

import json

import azure.functions as func

from lib.cidr import analyze_cidr

bp = func.Blueprint()


@bp.mcp_tool()
@bp.mcp_tool_property(
    arg_name="cidr",
    description="The CIDR to check, with an explicit prefix length, for example 10.0.0.0/29.",
)
def check_cidr(cidr: str) -> str:
    """Check an IPv4 CIDR against Azure's subnet rules: whether Azure would accept a subnet of
    that size (/2 through /29), the total and usable address counts, and the five addresses Azure
    reserves in every subnet (the network address, the default gateway, two addresses for Azure
    DNS, and the broadcast address). A CIDR Azure would refuse is still answered, with the reason
    spelled out."""
    try:
        return json.dumps(analyze_cidr(cidr), indent=2)
    except ValueError as err:
        return json.dumps({"error": str(err)}, indent=2)
