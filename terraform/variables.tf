variable "cost_centre" {
  description = "Cost centre tag applied to everything. Replace the placeholder with yours."
  type        = string
  default     = "1888/67"
}

variable "deploy_test_law" {
  description = "Deploy a small Log Analytics workspace alongside the function, so the run_kql tool has something real to answer against. Turn off for a production deployment."
  type        = bool
  default     = true
}

variable "env" {
  description = "Environment code used in resource names."
  type        = string
  default     = "dev"
}

variable "loc" {
  description = "Outfix: short Azure region code used in resource names."
  type        = string
  default     = "uks"
}

variable "python_version" {
  description = "The Python runtime version for the function app. Check what Flex Consumption offers in your region with: az functionapp list-flexconsumption-runtimes --location <region> --runtime python"
  type        = string
  default     = "3.14"
}

variable "workspace_scopes" {
  description = "Bring-your-own-workspaces path: ARM resource IDs of the Log Analytics workspaces your agents may query. The server's identity is granted Log Analytics Reader on exactly these, and their workspace GUIDs become the run_kql allow-list. Leave empty on the standalone path."
  type        = list(string)
  default     = []
}

variable "owner" {
  description = "Owner tag applied to everything: the person or team accountable for the deployment. Replace the placeholder with yours."
  type        = string
  default     = "craig@craigthacker.dev"
}

variable "regions" {
  description = "Map of short region codes to Azure region slugs."
  type        = map(string)
  default = {
    uks = "uksouth"
    ukw = "ukwest"
    eus = "eastus"
    euw = "westeurope"
  }
}

variable "short" {
  description = "Infix: short product code used in resource names."
  type        = string
  default     = "ldo"
}
