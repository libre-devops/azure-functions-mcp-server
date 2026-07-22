output "allowed_workspace_ids" {
  description = "The workspace GUIDs on the run_kql allow-list (the ALLOWED_WORKSPACE_IDS app setting)."
  value       = local.allowed_workspace_guids
}

output "function_app_name" {
  description = "The function app name, for az deployments and key retrieval."
  value       = local.func_name
}

output "function_hostname" {
  description = "The function app's default hostname."
  value       = module.flex_function_app.default_hostnames[local.func_name]
}

output "mcp_endpoint" {
  description = "The MCP server endpoint (Streamable HTTP). Clients also need the mcp_extension system key in the x-functions-key header; retrieve it with: just mcp-key"
  value       = "https://${module.flex_function_app.default_hostnames[local.func_name]}/runtime/webhooks/mcp"
}

output "resource_group_name" {
  description = "The resource group holding the stack."
  value       = local.rg_name
}

output "test_law_query" {
  description = "Ready-made run_kql tool arguments against the test workspace; the query answers even on an empty workspace."
  value = var.deploy_test_law ? jsonencode({
    workspace_id = module.log_analytics[0].workspace_guids[local.law_name]
    query        = "print greeting='hello from run_kql'"
  }) : "test law disabled"
}
