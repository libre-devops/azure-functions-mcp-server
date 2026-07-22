"""get_next_cidr: propose the next free subnet of a requested size in an Azure virtual network.

The server's identity (DefaultAzureCredential: the app's managed identity in Azure, your az login
locally) reads the vnet directly by resource id, so Reader on the vnet's scope is genuinely
enough; there is no subscription-level lookup.
"""

import json

import azure.functions as func

from lib.cidr import MAX_PREFIX, MIN_PREFIX, first_free_subnet

bp = func.Blueprint()


@bp.mcp_tool()
@bp.mcp_tool_property(
    arg_name="subscription_id",
    description="The Azure subscription id holding the virtual network.",
)
@bp.mcp_tool_property(
    arg_name="resource_group_name",
    description="The resource group holding the virtual network.",
)
@bp.mcp_tool_property(
    arg_name="virtual_network_name",
    description="The virtual network to search.",
)
@bp.mcp_tool_property(
    arg_name="cidr",
    description="The requested subnet size as a CIDR prefix length, 2 through 29.",
)
@bp.mcp_tool_property(
    arg_name="address_space",
    description=(
        "Optional: narrows the search to one of the vnet's address spaces, in exact normalized "
        "form, for example 10.30.0.0/24. Omitted, the first space that fits wins."
    ),
    is_required=False,
)
def get_next_cidr(
    subscription_id: str,
    resource_group_name: str,
    virtual_network_name: str,
    cidr: str,
    address_space: str = None,
) -> str:
    """Propose the next free CIDR of the requested size in an Azure virtual network: the first
    candidate subnet that fits without overlapping anything already there. The server's identity
    needs Reader on the scope holding the virtual network. Nothing is created or reserved."""
    try:
        size = int(cidr)
    except (TypeError, ValueError):
        return _error(f"Invalid CIDR size requested: {cidr}")
    if not MIN_PREFIX <= size <= MAX_PREFIX:
        return _error(f"Invalid CIDR size requested: {cidr}")

    # Imported lazily so the module (and tool discovery, and the unit tests) never needs Azure.
    from azure.core.exceptions import HttpResponseError, ResourceNotFoundError
    from azure.identity import DefaultAzureCredential
    from azure.mgmt.network import NetworkManagementClient

    try:
        client = NetworkManagementClient(DefaultAzureCredential(), subscription_id)
        vnet = client.virtual_networks.get(resource_group_name, virtual_network_name)
    except ResourceNotFoundError as err:
        return _error(f"NotFound, {err.message}")
    except HttpResponseError as err:
        return _error(f"{err.reason}, {err.message}")

    used = []
    for subnet in vnet.subnets or []:
        prefixes = list(subnet.address_prefixes or [])
        if subnet.address_prefix and subnet.address_prefix not in prefixes:
            prefixes.append(subnet.address_prefix)
        used.extend(prefixes)

    spaces = list(vnet.address_space.address_prefixes or [])
    proposed, found_space = first_free_subnet(spaces, used, size, address_space)

    if proposed is None:
        if address_space is None:
            return _error(
                f"VNet {resource_group_name}/{virtual_network_name} cannot accept a subnet of size {size}"
            )
        return _error(
            f"Requested address space ({address_space}) not found in VNet "
            f"{resource_group_name}/{virtual_network_name}"
        )

    return json.dumps(
        {
            "name": virtual_network_name,
            "id": vnet.id,
            "type": vnet.type,
            "location": vnet.location,
            "addressSpace": found_space,
            "proposedCIDR": proposed,
        },
        indent=2,
    )


def _error(message: str) -> str:
    return json.dumps({"error": message}, indent=2)
