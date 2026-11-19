[CmdletBinding()]
param(
    [string]$Destination = ""
)

$ErrorActionPreference = "Stop"
$workspaceRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
if (-not $Destination) {
    $stamp = Get-Date -Format "yyyyMMdd-HHmmss"
    $Destination = Join-Path $workspaceRoot "backups/phase9-$stamp"
}
$Destination = [System.IO.Path]::GetFullPath($Destination)
$allowedRoot = [System.IO.Path]::GetFullPath((Join-Path $workspaceRoot "backups"))
if (-not $Destination.StartsWith($allowedRoot, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw "Backup destination must remain inside $allowedRoot"
}
New-Item -ItemType Directory -Force -Path $Destination | Out-Null

Push-Location $workspaceRoot
try {
    $postgresId = (docker compose ps -q postgres).Trim()
    $apiId = (docker compose ps -q api).Trim()
    if (-not $postgresId -or -not $apiId) {
        throw "The postgres and api services must be running."
    }

    $containerDump = "/tmp/knowra-phase9-$([guid]::NewGuid().ToString('N')).dump"
    docker exec $postgresId pg_dump -Fc -U user -d omnirag -f $containerDump
    if ($LASTEXITCODE -ne 0) { throw "PostgreSQL backup failed." }
    docker cp "$($postgresId):$containerDump" (Join-Path $Destination "postgres.dump")
    if ($LASTEXITCODE -ne 0) { throw "Could not copy PostgreSQL backup." }

    New-Item -ItemType Directory -Force -Path (Join-Path $Destination "objects") | Out-Null
    New-Item -ItemType Directory -Force -Path (Join-Path $Destination "repositories") | Out-Null
    docker cp "$($apiId):/data/objects/." (Join-Path $Destination "objects")
    if ($LASTEXITCODE -ne 0) { throw "Could not copy object storage." }
    docker cp "$($apiId):/data/repositories/." (Join-Path $Destination "repositories")
    if ($LASTEXITCODE -ne 0) { throw "Could not copy repository storage." }

    $files = @(Get-ChildItem -LiteralPath $Destination -File -Recurse |
        Sort-Object FullName |
        ForEach-Object {
            [ordered]@{
                path = [System.IO.Path]::GetRelativePath($Destination, $_.FullName)
                bytes = $_.Length
                sha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $_.FullName).Hash.ToLowerInvariant()
            }
        })
    $manifest = [ordered]@{
        schema_version = 1
        created_at_utc = (Get-Date).ToUniversalTime().ToString("o")
        git_commit = (git rev-parse HEAD).Trim()
        includes = @("postgres", "objects", "repositories")
        excludes = @("provider secret plaintext", "environment files", "derived Qdrant index", "Redis")
        files = $files
    }
    $manifest | ConvertTo-Json -Depth 8 |
        Set-Content -LiteralPath (Join-Path $Destination "manifest.json") -Encoding utf8
    Write-Host "Created baseline backup at $Destination"
    Write-Host "Keep encryption/signing secrets in a separate approved secret backup."
} finally {
    Pop-Location
}
