[CmdletBinding()]
param(
    [string]$OutputPath = ""
)

$ErrorActionPreference = "Stop"
$workspaceRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
if (-not $OutputPath) {
    $stamp = Get-Date -Format "yyyyMMdd-HHmmss"
    $OutputPath = Join-Path $workspaceRoot "artifacts/phase9/baseline-$stamp.json"
}
$resolvedParent = Split-Path -Parent $OutputPath
New-Item -ItemType Directory -Force -Path $resolvedParent | Out-Null

Push-Location $workspaceRoot
try {
    $trackedChanges = @(git status --short)
    $migrations = @(Get-ChildItem "backend/alembic/versions" -File |
        Sort-Object Name |
        ForEach-Object { $_.Name })
    $locks = @{}
    foreach ($path in @("backend/uv.lock", "frontend/package-lock.json")) {
        if (Test-Path -LiteralPath $path) {
            $locks[$path] = (Get-FileHash -Algorithm SHA256 -LiteralPath $path).Hash.ToLowerInvariant()
        }
    }

    $docker = @{
        available = $false
        services = @()
        images = @()
        volumes = @()
        runtime = $null
    }
    if (Get-Command docker -ErrorAction SilentlyContinue) {
        try {
            $null = docker info --format "{{.ServerVersion}}" 2>$null
            if ($LASTEXITCODE -eq 0) {
                $docker.available = $true
                $docker.services = @(docker compose ps --format json 2>$null |
                    ForEach-Object { $_ | ConvertFrom-Json })
                $docker.images = @(docker compose images --format json 2>$null |
                    ForEach-Object { $_ | ConvertFrom-Json })
                $docker.volumes = @(docker volume ls --filter "label=com.docker.compose.project=knowra" --format "{{.Name}}" 2>$null)
                $runtimeJson = docker compose exec -T api python -c @"
import importlib.util, json
from importlib.metadata import PackageNotFoundError, version
from app.core.config import settings
def package(name):
    try:
        return version(name)
    except PackageNotFoundError:
        return None
print(json.dumps({
    "app_version": settings.VERSION,
    "auth_required": settings.AUTH_REQUIRED,
    "sandbox_enabled": settings.SANDBOX_EXECUTION_ENABLED,
    "reranker_enabled": settings.RERANKER_ENABLED,
    "embedding_model_configured": bool(settings.EMBEDDING_MODEL),
    "docling_installed": importlib.util.find_spec("docling") is not None,
    "fastembed_installed": importlib.util.find_spec("fastembed") is not None,
    "tree_sitter": package("tree-sitter"),
    "tree_sitter_language_pack": package("tree-sitter-language-pack"),
}))
"@ 2>$null
                if ($LASTEXITCODE -eq 0 -and $runtimeJson) {
                    $docker.runtime = $runtimeJson | ConvertFrom-Json
                }
            }
        } catch {
            $docker.error = $_.Exception.GetType().Name
        }
    }

    $inventory = [ordered]@{
        schema_version = 1
        created_at_utc = (Get-Date).ToUniversalTime().ToString("o")
        workspace = $workspaceRoot
        git = @{
            commit = (git rev-parse HEAD).Trim()
            branch = (git branch --show-current).Trim()
            changes = $trackedChanges
        }
        dependency_locks_sha256 = $locks
        migrations = $migrations
        docker = $docker
        secrets = @{
            included = $false
            note = "Environment values and provider credentials are intentionally excluded."
        }
    }
    $inventory | ConvertTo-Json -Depth 10 |
        Set-Content -LiteralPath $OutputPath -Encoding utf8
    Write-Host "Wrote sanitized baseline inventory to $OutputPath"
} finally {
    Pop-Location
}
