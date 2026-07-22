<div align="center">
  <a href="https://libredevops.org">
    <picture>
      <source media="(prefers-color-scheme: dark)" srcset="https://libredevops.org/assets/libre-devops-white.png">
      <img alt="Libre DevOps" src="https://libredevops.org/assets/libre-devops-black.png" width="300">
    </picture>
  </a>
</div>

# azure-functions-mcp-server

A remote MCP server hosted on Azure Functions: Azure network tools your AI agents can call, built
basic but extensible, so wiring in your own tool is dropping one Python file into a folder.

[![CI](https://github.com/libre-devops/azure-functions-mcp-server/actions/workflows/ci.yml/badge.svg)](https://github.com/libre-devops/azure-functions-mcp-server/actions/workflows/ci.yml)
[![License](https://img.shields.io/github/license/libre-devops/azure-functions-mcp-server)](./LICENSE)

## Overview

Azure Functions hosts remote [MCP](https://modelcontextprotocol.io) servers natively: the GA MCP
extension handles the protocol (JSON-RPC framing, tool discovery, the Streamable HTTP transport)
and your functions become the tools. This repo is the Libre DevOps take on that: a Python
function app on a Flex Consumption plan, deployed by Terraform composed entirely from the
published estate modules, with the same treatment as
[FindNextCIDRRange](https://github.com/libre-devops/FindNextCIDRRange): unit tests, a pwsh
justfile, CI with tflint and a gated trivy scan, CodeQL, dependabot, and a smoke that speaks real
MCP against the deployed server.

The server starts with two tools from the same domain as FindNextCIDRRange:

| Tool | Needs | Answers |
| --- | --- | --- |
| `check_cidr` | Nothing (pure arithmetic) | Whether Azure would accept a subnet of that size (/2 through /29), the total and usable counts, and the five addresses Azure reserves in every subnet (network, default gateway, two for Azure DNS, broadcast). A /30 is answered, not errored: `validAzureSubnet: false` with the reason. |
| `get_next_cidr` | Reader on the vnet's scope | The next free subnet of a requested size in an Azure virtual network: the first candidate that fits without overlapping anything already there. Nothing is created or reserved. |

## Wiring in your own tool

The whole mechanism is one convention: every module in `src/tools/` that exposes a module-level
`bp` (an `azure.functions.Blueprint`) is discovered and registered by `src/function_app.py`.
Adding a tool is adding a file:

```python
# src/tools/my_tool.py
import azure.functions as func

bp = func.Blueprint()

@bp.mcp_tool()
@bp.mcp_tool_property(arg_name="thing", description="What to frob.")
def my_tool(thing: str) -> str:
    """One or two sentences describing the tool; the model reads this to decide when to call it."""
    return f"frobbed {thing}"
```

Nothing else needs touching: no registry, no config, no edits to existing files. The function
name is the tool name, the docstring is the tool description, and `mcp_tool_property` declares
the arguments. Keep business logic in `src/lib/` as pure functions so the unit tests can drive it
without Azure; the tool discovery test will insist your tool carries a real description.

## Deploy

Two paths, chosen entirely by tfvars.

**Standalone** (the default) seeds a small test vnet with two subnets already carved, so
`get_next_cidr` has a real question to answer the moment the deploy lands:

```bash
az login
export ARM_SUBSCRIPTION_ID=$(az account show --query id -o tsv)
cp terraform/terraform.tfvars.example terraform/terraform.tfvars   # then make it yours (owner tag etc.)
just apply       # the stack: function app, identity, Reader grant, test vnet
just package     # zip the source (dependencies build remotely on deploy)
just deploy      # push the zip to the app
just smoke       # a real MCP session: initialize, tools/list, and a call of each tool
```

**Bring your own network** deploys nothing but the function and points Reader at the networks you
already have: start from `terraform/terraform.tfvars.byon.example` instead, which sets
`deploy_test_vnet = false` and lists your `reader_scopes` (subscription, resource group, or single
vnet IDs; narrower is better). Same `just` steps afterwards.

State is local and gitignored; this is a deploy-into-your-tenant tool, not a shared pipeline.

## Connect a client

The server speaks Streamable HTTP at `/runtime/webhooks/mcp`. Run `just mcp-key` for the endpoint
and the `mcp_extension` system key, then give any MCP client the pair; the key travels in the
`x-functions-key` header. For GitHub Copilot in VS Code, a `.vscode/mcp.json` like this prompts
for the key rather than committing it:

```json
{
    "inputs": [
        {
            "type": "promptString",
            "id": "functions-mcp-key",
            "description": "The mcp_extension system key (just mcp-key)",
            "password": true
        }
    ],
    "servers": {
        "libre-devops-azure-tools": {
            "type": "http",
            "url": "https://<functionapp>.azurewebsites.net/runtime/webhooks/mcp",
            "headers": {
                "x-functions-key": "${input:functions-mcp-key}"
            }
        }
    }
}
```

## Notes

- The MCP endpoint is platform-provided; nothing MCP-specific exists at the ARM layer, which is
  why the Terraform is nothing but the estate's standard flex function app composition. The one
  provider gap worth knowing: the azurerm host-keys data source does not expose the
  `mcp_extension` system key, so `just mcp-key` and `just smoke` read it with the az CLI instead
  (keeping it out of Terraform state is no bad thing).
- `get_next_cidr` authenticates outward with `DefaultAzureCredential`, so the app's managed
  identity is the credential in Azure. The stack grants Reader to both of the app's identities
  (system-assigned and user-assigned), because the credential chain picks the system-assigned one
  unless told otherwise.
- Key auth is the access control here. The platform also supports built-in MCP authorization
  (Entra ID OAuth via App Service authentication) for spec-compliant sign-in; it is deliberately
  not wired in yet, to keep the reference basic. The `auth_settings_v2` surface it needs is
  already exposed by the flex module when the time comes.
- Flex Consumption zip deploys flake: `just deploy` pushes with a spaced retry and a remote
  dependency build, and the only verdict that counts is `just smoke` completing a real MCP
  session.

## Security scan exceptions

CI runs a trivy config scan that gates on HIGH and CRITICAL findings. Waivers live in
[`.trivyignore.yaml`](./.trivyignore.yaml), and every waiver is recorded here.

| ID | Where | Justification |
| --- | --- | --- |
| AVD-AZU-0012 | The function's host storage account, inside the composed flex-consumption-function-app module | The host storage must stay reachable: zip deploys arrive from wherever the operator runs `just deploy` (no knowable IP to allow-list) and the Functions platform itself needs the account. Data-plane access is Entra ID via the app's managed identity, the account holds only the function package and host state, and the stack is disposable by design. |
