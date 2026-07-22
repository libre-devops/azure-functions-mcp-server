"""Azure CIDR arithmetic shared by the MCP tools.

Pure functions only: no Azure SDK imports, no network calls, so everything here is exercised
directly by the unit tests. The rules encoded are Azure's subnet rules: five addresses are
reserved in every subnet (the network address, the default gateway, two addresses for Azure DNS,
and the broadcast address), so subnets run from /2 through /29 and a /30 cannot exist.
"""

import ipaddress

AZURE_RESERVED = 5
MIN_PREFIX = 2
MAX_PREFIX = 29


def analyze_cidr(cidr_input):
    """Check an IPv4 CIDR against Azure's subnet rules.

    Returns a dict shaped like FindNextCIDRRange's /api/CheckCidr response, so the two projects
    answer identically. Raises ValueError for input that cannot be parsed; a CIDR Azure would
    refuse is still a successful answer (validAzureSubnet false with the reason spelled out).
    """
    if cidr_input is None or not str(cidr_input).strip():
        raise ValueError("cidr is null")

    cidr_input = str(cidr_input).strip()

    # Without an explicit prefix the parser would assume a host address, which is never what an
    # Azure subnet question means.
    if "/" not in cidr_input:
        raise ValueError("cidr must include a prefix length, for example 10.0.0.0/24")

    try:
        network = ipaddress.ip_network(cidr_input, strict=False)
    except ValueError:
        raise ValueError("not a valid CIDR: " + cidr_input) from None

    if network.version != 4:
        raise ValueError("only IPv4 CIDRs are supported; Azure IPv6 subnets are always /64")

    prefix = network.prefixlen
    total = network.num_addresses

    response = {
        "cidr": cidr_input,
        "normalized": str(network),
        "validAzureSubnet": False,
        "prefixLength": prefix,
        "totalAddresses": total,
        "azureReservedAddresses": AZURE_RESERVED,
        "usableAddresses": 0,
        "reserved": None,
        "firstUsable": None,
        "lastUsable": None,
        "reason": None,
    }

    if prefix > MAX_PREFIX:
        response["reason"] = (
            "An Azure subnet cannot be smaller than /29: Azure reserves "
            f"{AZURE_RESERVED} addresses in every subnet (the network address, the default "
            "gateway, two addresses for Azure DNS, and the broadcast address), so a "
            f"/{prefix} with {total} address{'' if total == 1 else 'es'} cannot fit them."
        )
    elif prefix < MIN_PREFIX:
        response["reason"] = "An Azure subnet cannot be larger than /2."
    else:
        base = int(network.network_address)
        response["validAzureSubnet"] = True
        response["usableAddresses"] = total - AZURE_RESERVED
        response["reserved"] = {
            "networkAddress": str(network.network_address),
            "defaultGateway": str(ipaddress.ip_address(base + 1)),
            "azureDns": [str(ipaddress.ip_address(base + 2)), str(ipaddress.ip_address(base + 3))],
            "broadcast": str(network.broadcast_address),
        }
        response["firstUsable"] = str(ipaddress.ip_address(base + 4))
        response["lastUsable"] = str(ipaddress.ip_address(int(network.broadcast_address) - 1))

    return response


def first_free_subnet(address_spaces, used_prefixes, cidr, desired_space=None):
    """Walk the vnet's address spaces in order and return the first candidate subnet of the
    requested size that does not overlap any existing subnet.

    Mirrors FindNextCIDRRange's GetCidr search exactly: spaces too small for the request are
    skipped, desired_space (already normalized) filters to a single space, and within a space
    candidates are tried in address order, first fit wins. Returns (proposed, address_space) as
    strings, or (None, None) when nothing fits.
    """
    used = [ipaddress.ip_network(prefix) for prefix in used_prefixes]

    for space_input in address_spaces:
        space = ipaddress.ip_network(space_input)
        if cidr < space.prefixlen:
            continue
        if desired_space is not None and str(space) != desired_space:
            continue

        # A request for the space's own size is answered with the whole space (subnets() only
        # yields strictly smaller networks, but the original API treats equal as a valid ask).
        candidates = [space] if cidr == space.prefixlen else space.subnets(new_prefix=cidr)

        for candidate in candidates:
            if not any(candidate.overlaps(existing) for existing in used):
                return str(candidate), str(space)

    return None, None
