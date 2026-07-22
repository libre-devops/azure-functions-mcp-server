data "azurerm_subscription" "current" {}

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

output "test_vnet_query" {
  description = "Ready-made get_next_cidr tool arguments against the test vnet; with its two /26s used, the answer should propose 10.30.0.128/26."
  value = var.deploy_test_vnet ? jsonencode({
    subscription_id      = data.azurerm_subscription.current.subscription_id
    resource_group_name  = local.rg_name
    virtual_network_name = local.vnet_name
    cidr                 = "26"
  }) : "test vnet disabled"
}
