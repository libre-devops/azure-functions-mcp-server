# The infrastructure for the Libre DevOps remote MCP server: a Flex Consumption function app on
# Python, from the estate's flex-consumption-function-app module: dedicated FC1 plan, keyless
# storage with a deployment container, a user-assigned identity with identity-based host storage,
# all by module default. The MCP endpoint itself is platform-provided (/runtime/webhooks/mcp);
# nothing MCP-specific exists at the ARM layer. Blocks are ordered by dependency, top to bottom.
#
# Two deployment paths, chosen by tfvars alone:
#   Standalone (default): deploy_test_law = true seeds a small Log Analytics workspace, so the
#   run_kql tool has something real to answer the moment the deploy lands.
#   Bring your own workspaces: deploy_test_law = false, workspace_scopes = the ARM resource IDs
#   of the Log Analytics workspaces your agents may query. The server's identity is granted Log
#   Analytics Reader on exactly those, and their workspace GUIDs become the tool's allow-list.
locals {
  location  = lookup(var.regions, var.loc, "uksouth")
  rg_name   = "rg-${var.short}-${var.loc}-${var.env}-mcp-001"
  func_name = "func-${var.short}-${var.loc}-${var.env}-mcp-001"
  law_name  = "law-${var.short}-${var.loc}-${var.env}-mcp-001"

  # Both identities need the grant: the app carries a user-assigned identity for host storage, but
  # DefaultAzureCredential with no AZURE_CLIENT_ID authenticates as the system-assigned one, so
  # granting only one of them leaves the tool 403ing depending on the credential chain. The list
  # stays statically sized (no compact/distinct): its length feeds for_each keys downstream, and
  # on a fresh apply the ids are unknown, so a dynamic length fails the plan. The flex module
  # attaches both identity kinds by default, so both entries are always real.
  function_principal_ids = [
    module.flex_function_app.identity_principal_ids[local.func_name].system_assigned,
    module.flex_function_app.identity_principal_ids[local.func_name].user_assigned,
  ]

  # The tool-facing allow-list: workspace GUIDs (customer ids), one per workspace the identity is
  # granted on. Values are apply-time-known, which is fine; only for_each keys must be plan-known.
  allowed_workspace_guids = concat(
    var.deploy_test_law ? [module.log_analytics[0].workspace_guids[local.law_name]] : [],
    data.azurerm_log_analytics_workspace.byon[*].workspace_id,
  )
}

module "tags" {
  source  = "libre-devops/tags/azurerm"
  version = "~> 4.0"

  cost_centre     = var.cost_centre
  owner           = var.owner
  additional_tags = { Application = "AzureFunctionsMcpServer" }
}

module "rg" {
  source  = "libre-devops/rg/azurerm"
  version = "~> 4.0"

  resource_groups = [{ name = local.rg_name, location = local.location, tags = module.tags.tags }]
}

# A small test workspace so run_kql has something real to answer; module defaults throughout
# (PerGB2018, 90 day retention). Even an empty workspace answers KQL like `print`.
module "log_analytics" {
  count = var.deploy_test_law ? 1 : 0

  source  = "libre-devops/log-analytics-workspace/azurerm"
  version = "~> 4.0"

  resource_group_id = module.rg.ids[local.rg_name]
  location          = local.location
  tags              = module.tags.tags

  log_analytics_workspaces = {
    (local.law_name) = {}
  }
}

# Bring-your-own workspaces are read back to translate ARM resource IDs (what the caller has, and
# what the role grants need) into workspace GUIDs (what the query API and the allow-list need).
data "azurerm_log_analytics_workspace" "byon" {
  count = length(var.workspace_scopes)

  name                = provider::azurerm::parse_resource_id(var.workspace_scopes[count.index]).resource_name
  resource_group_name = provider::azurerm::parse_resource_id(var.workspace_scopes[count.index]).resource_group_name
}

module "flex_function_app" {
  source  = "libre-devops/flex-consumption-function-app/azurerm"
  version = "~> 4.0"

  resource_group_id = module.rg.ids[local.rg_name]
  location          = local.location
  tags              = module.tags.tags

  function_apps = {
    (local.func_name) = {
      runtime_name    = "python"
      runtime_version = var.python_version

      # The run_kql tool refuses any workspace not on this list, before RBAC even gets a say.
      app_settings = {
        ALLOWED_WORKSPACE_IDS = join(",", local.allowed_workspace_guids)
      }
    }
  }
}

# Log Analytics Reader is exactly what run_kql needs, nothing more. The standalone path grants it
# on the test workspace; the bring-your-own path grants it on each workspace in
# var.workspace_scopes. Keys index into the caller's literal list, so they stay plan-known.
module "role_assignment" {
  source  = "libre-devops/role-assignment/azurerm"
  version = "~> 4.1"

  role_assignments = merge(
    var.deploy_test_law ? {
      test-law-reader = {
        scope                            = module.log_analytics[0].workspace_ids[local.law_name]
        principal_ids                    = local.function_principal_ids
        role_names                       = ["Log Analytics Reader"]
        principal_type                   = "ServicePrincipal"
        skip_service_principal_aad_check = true
      }
    } : {},
    {
      for idx, scope in var.workspace_scopes : "byon-law-reader-${idx}" => {
        scope                            = scope
        principal_ids                    = local.function_principal_ids
        role_names                       = ["Log Analytics Reader"]
        principal_type                   = "ServicePrincipal"
        skip_service_principal_aad_check = true
      }
    }
  )
}
