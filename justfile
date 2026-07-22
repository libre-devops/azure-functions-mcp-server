# Recipes for the Libre DevOps remote MCP server, run in PowerShell (the estate convention).
# `just` on its own lists them. Set ARM_SUBSCRIPTION_ID for the terraform recipes:
#   export ARM_SUBSCRIPTION_ID=$(az account show --query id -o tsv)
# The usual flow: just init, apply, package, deploy, then smoke to judge the deploy (it speaks
# real MCP: initialize, tools/list, and a tools/call of each tool).

set shell := ["pwsh", "-NoProfile", "-Command"]

# Shebang recipes execute from a temp file, and just's default location (XDG_RUNTIME_DIR) is
# mounted noexec on some systems (WSL2 among them), which fails every such recipe with
# "Permission denied". /tmp is executable close to everywhere.
set tempdir := '/tmp'

default:
    @just --list

# Run the unit tests (the pure CIDR logic and the tool-discovery mechanism)
test:
    python3 -m pytest tests -q

# Zip the function ready for deployment. Dependencies are resolved by the remote build during
# deploy, so the package is source only. The stale zip is removed first: zip updates an existing
# archive in place, so deleted files would otherwise linger in the package.
package:
    if (Test-Path function.zip) { Remove-Item function.zip }
    cd src && zip -qr ../function.zip . -x 'local.settings.json' -x '*__pycache__*'
    @echo "function.zip ready"

# Deploy the packaged function to the app the stack created, with a remote build for the Python
# dependencies. Pushed with a spaced retry because flex zip deploys flake transiently, and the
# CLI's exit code is untrustworthy either way, so success is only ever judged by `just smoke`.
deploy:
    #!/usr/bin/env pwsh
    Set-StrictMode -Version Latest
    $ErrorActionPreference = 'Stop'
    $rg = terraform -chdir=terraform output -raw resource_group_name
    $app = terraform -chdir=terraform output -raw function_app_name
    # terraform output exits 0 with empty stdout when the state holds no outputs at all (a
    # destroyed stack), so emptiness is the reliable "no stack" signal, not the exit code.
    if ($LASTEXITCODE -ne 0 -or -not $rg -or -not $app) { throw 'no deployed stack in the terraform outputs; run: just apply' }
    foreach ($attempt in 1, 2, 3) {
        az functionapp deployment source config-zip -g $rg -n $app --src function.zip --build-remote true
        if ($LASTEXITCODE -eq 0) { break }
        if ($attempt -lt 3) { Write-Host 'retrying in 20s'; Start-Sleep -Seconds 20 }
    }
    Write-Host 'pushed; judge success with: just smoke'

# Package and deploy in one go
ship: package deploy

# Terraform lifecycle against the stack
init *args:
    terraform -chdir=terraform init {{ args }}

plan *args:
    terraform -chdir=terraform plan {{ args }}

apply *args:
    terraform -chdir=terraform apply -auto-approve {{ args }}

destroy *args:
    terraform -chdir=terraform destroy -auto-approve {{ args }}

# Trivy config scan over the repo, gating on HIGH and CRITICAL like CI. Waivers live in
# .trivyignore.yaml, and every waiver has a row in the README's security scan exceptions table.
scan:
    trivy config --ignorefile .trivyignore.yaml --severity CRITICAL,HIGH --exit-code 1 .

# Everything CI runs: unit tests, then terraform fmt, validate, and the trivy gate
check:
    python3 -m pytest tests -q
    terraform -chdir=terraform fmt -check -recursive
    terraform -chdir=terraform init -backend=false -input=false > $null
    terraform -chdir=terraform validate
    trivy config --ignorefile .trivyignore.yaml --severity CRITICAL,HIGH --exit-code 1 .

# Print the MCP endpoint and the mcp_extension system key for wiring a client (VS Code, Claude,
# any MCP client: the key travels in the x-functions-key header)
mcp-key:
    #!/usr/bin/env pwsh
    Set-StrictMode -Version Latest
    $ErrorActionPreference = 'Stop'
    $rg = terraform -chdir=terraform output -raw resource_group_name
    $app = terraform -chdir=terraform output -raw function_app_name
    if ($LASTEXITCODE -ne 0 -or -not $rg -or -not $app) { throw 'no deployed stack in the terraform outputs; run: just apply' }
    $endpoint = terraform -chdir=terraform output -raw mcp_endpoint
    $key = az functionapp keys list -g $rg -n $app --query systemKeys.mcp_extension -o tsv
    Write-Host "endpoint: $endpoint"
    Write-Host "x-functions-key: $key"

# Exercise the deployed MCP server end to end as a real client: initialize the session, list the
# tools, call check_cidr (expecting the /30 rejection), and call get_next_cidr against the test
# vnet (skipped on the bring-your-own-network path, expecting 10.30.0.128/26)
smoke:
    #!/usr/bin/env pwsh
    Set-StrictMode -Version Latest
    $ErrorActionPreference = 'Stop'
    $rg = terraform -chdir=terraform output -raw resource_group_name
    $app = terraform -chdir=terraform output -raw function_app_name
    if ($LASTEXITCODE -ne 0 -or -not $rg -or -not $app) { throw 'no deployed stack in the terraform outputs; run: just apply' }
    $endpoint = terraform -chdir=terraform output -raw mcp_endpoint
    $key = az functionapp keys list -g $rg -n $app --query systemKeys.mcp_extension -o tsv
    if ($LASTEXITCODE -ne 0 -or -not $key) { throw 'could not read the mcp_extension system key' }
    $session = $null
    function Invoke-Mcp([hashtable] $rpc) {
        $headers = @{ 'x-functions-key' = $key; 'Accept' = 'application/json, text/event-stream' }
        if ($session) { $headers['Mcp-Session-Id'] = $session }
        $resp = Invoke-WebRequest -Uri $endpoint -Method Post -ContentType 'application/json' -Headers $headers -Body ($rpc | ConvertTo-Json -Depth 8 -Compress) -TimeoutSec 60
        if ($resp.Headers.ContainsKey('Mcp-Session-Id')) { $script:session = @($resp.Headers['Mcp-Session-Id'])[0] }
        # Streamable HTTP may answer as an SSE stream; the payload rides the data: lines.
        $payload = (($resp.Content -split "`n") | Where-Object { $_ -like 'data:*' } | ForEach-Object { $_.Substring(5).Trim() }) -join ''
        if (-not $payload) { $payload = $resp.Content }
        if ($payload) { return $payload | ConvertFrom-Json }
    }
    $init = Invoke-Mcp @{ jsonrpc = '2.0'; id = 1; method = 'initialize'; params = @{ protocolVersion = '2025-06-18'; capabilities = @{}; clientInfo = @{ name = 'just-smoke'; version = '1.0' } } }
    Write-Host "initialize -> $($init.result.serverInfo.name) $($init.result.serverInfo.version)"
    Invoke-Mcp @{ jsonrpc = '2.0'; method = 'notifications/initialized' } | Out-Null
    $tools = (Invoke-Mcp @{ jsonrpc = '2.0'; id = 2; method = 'tools/list'; params = @{} }).result.tools.name
    Write-Host "tools/list -> $($tools -join ', ')"
    foreach ($required in 'check_cidr', 'get_next_cidr') {
        if ($tools -notcontains $required) { throw "tool $required is missing from the server" }
    }
    $verdict = (Invoke-Mcp @{ jsonrpc = '2.0'; id = 3; method = 'tools/call'; params = @{ name = 'check_cidr'; arguments = @{ cidr = '10.0.0.0/30' } } }).result.content[0].text | ConvertFrom-Json
    if ($verdict.validAzureSubnet) { throw 'a /30 must not be a valid Azure subnet' }
    Write-Host 'tools/call check_cidr (/30) -> correctly rejected'
    $query = terraform -chdir=terraform output -raw test_vnet_query
    if ($query -ne 'test vnet disabled') {
        $arguments = @{}
        ($query | ConvertFrom-Json).psobject.Properties | ForEach-Object { $arguments[$_.Name] = $_.Value }
        $answer = (Invoke-Mcp @{ jsonrpc = '2.0'; id = 4; method = 'tools/call'; params = @{ name = 'get_next_cidr'; arguments = $arguments } }).result.content[0].text | ConvertFrom-Json
        if (-not $answer.proposedCIDR) { throw "get_next_cidr answered without a proposedCIDR: $answer" }
        Write-Host "tools/call get_next_cidr (test vnet) -> $($answer.proposedCIDR)"
    } else {
        Write-Host 'test vnet disabled; skipping the get_next_cidr call'
    }
    Write-Host 'smoke: the MCP server is answering'
