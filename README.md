<div align="center">
  <a href="https://libredevops.org">
    <picture>
      <source media="(prefers-color-scheme: dark)" srcset="https://libredevops.org/assets/libre-devops-white.png">
      <img alt="Libre DevOps" src="https://libredevops.org/assets/libre-devops-black.png" width="300">
    </picture>
  </a>
</div>

# azure-functions-mcp-server

A remote MCP server hosted on Azure Functions: scoped, read-only Azure estate tools that AI
agents (Security Copilot among them) can reach over MCP, built basic but extensible, so wiring in
your own tool is dropping one Python file into a folder.

[![CI](https://github.com/libre-devops/azure-functions-mcp-server/actions/workflows/ci.yml/badge.svg)](https://github.com/libre-devops/azure-functions-mcp-server/actions/workflows/ci.yml)
[![License](https://img.shields.io/github/license/libre-devops/azure-functions-mcp-server)](./LICENSE)

## Overview

Azure Functions hosts remote [MCP](https://modelcontextprotocol.io) servers natively: the GA MCP
extension handles the protocol (JSON-RPC framing, tool discovery, the Streamable HTTP transport
at `/runtime/webhooks/mcp`) and your functions become the tools. This repo is the Libre DevOps
take on that: a Python function app on a Flex Consumption plan, deployed by Terraform composed
entirely from the published estate modules, with unit tests, a pwsh justfile, CI with tflint and
a gated trivy scan, CodeQL, dependabot, and a smoke that speaks real MCP against the deployed
server.

The launch tool:

| Tool | Needs | Answers |
| --- | --- | --- |
| `run_kql` | Log Analytics Reader on allow-listed workspaces | A read-only KQL query against an Azure Log Analytics workspace. Two gates in front of every query: the deployment's workspace allow-list (an app setting the Terraform manages), then the identity's own RBAC. Results are capped (100 rows, long cells truncated) so one query cannot flood a model's context. |

The Log Analytics query API is read-only by design, so the tool cannot mutate anything no matter
what it is asked.

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
without Azure; the tool discovery test will insist your tool carries a real description. Keep
tool inputs to primitive types (Security Copilot imports nothing else), and keep tools
non-destructive: read tools compose safely, and Security Copilot refuses tools marked
destructive anyway.

## Deploy

Two paths, chosen entirely by tfvars.

**Standalone** (the default) seeds a small Log Analytics workspace, so `run_kql` has something
real to answer the moment the deploy lands:

```bash
az login
export ARM_SUBSCRIPTION_ID=$(az account show --query id -o tsv)
cp terraform/terraform.tfvars.example terraform/terraform.tfvars   # then make it yours (owner tag etc.)
just apply       # the stack: function app, identity, test workspace, Log Analytics Reader grant
just package     # zip the source (dependencies build remotely on deploy)
just deploy      # push the zip to the app
just smoke       # a real MCP session: initialize, tools/list, the allow-list refusal, a live query
```

**Bring your own workspaces** deploys nothing but the function and points it at the Log Analytics
workspaces you already have: start from `terraform/terraform.tfvars.byon.example` instead, which
sets `deploy_test_law = false` and lists your `workspace_scopes` (LAW ARM resource IDs). The
server's identity gets Log Analytics Reader on exactly those, and their workspace GUIDs become
the tool's allow-list. Same `just` steps afterwards.

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

### Security Copilot

Security Copilot consumes MCP servers as custom plugins (Preview) via a YAML manifest;
[`manifests/security-copilot.yaml`](./manifests/security-copilot.yaml) is this server's manifest,
ready to fill in and upload. One hard requirement to know: the manifest can only express OAuth or
Entra delegated auth, so the default key-auth deployment cannot be registered there. The path to
Copilot is the built-in Entra authorization milestone (App Service authentication on the app, an
Entra app registration exposing a `user_impersonation` scope, and the key requirement switched
off in host.json); the manifest documents that target shape. Every header-capable MCP client
works today with the key.

## Notes

- The MCP endpoint is platform-provided; nothing MCP-specific exists at the ARM layer, which is
  why the Terraform is nothing but the estate's standard flex function app composition plus a
  workspace and a role grant. The one provider gap worth knowing: the azurerm host-keys data
  source does not expose the `mcp_extension` system key, so `just mcp-key` and `just smoke` read
  it with the az CLI instead (keeping it out of Terraform state is no bad thing).
- `run_kql` authenticates outward with `DefaultAzureCredential`, so the app's managed identity is
  the credential in Azure. The stack grants Log Analytics Reader to both of the app's identities
  (system-assigned and user-assigned), because the credential chain picks the system-assigned one
  unless told otherwise.
- Flex Consumption zip deploys flake: `just deploy` pushes with a spaced retry and a remote
  dependency build, and the only verdict that counts is `just smoke` completing a real MCP
  session.

## Security scan exceptions

CI runs a trivy config scan that gates on HIGH and CRITICAL findings. Waivers live in
[`.trivyignore.yaml`](./.trivyignore.yaml), and every waiver is recorded here.

| ID | Where | Justification |
| --- | --- | --- |
| AVD-AZU-0012 | The function's host storage account, inside the composed flex-consumption-function-app module | The host storage must stay reachable: zip deploys arrive from wherever the operator runs `just deploy` (no knowable IP to allow-list) and the Functions platform itself needs the account. Data-plane access is Entra ID via the app's managed identity, the account holds only the function package and host state, and the stack is disposable by design. |
