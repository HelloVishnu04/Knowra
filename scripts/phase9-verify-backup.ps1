[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$BackupPath
)

$ErrorActionPreference = "Stop"
$backup = (Resolve-Path -LiteralPath $BackupPath).Path
$manifestPath = Join-Path $backup "manifest.json"
if (-not (Test-Path -LiteralPath $manifestPath)) {
    throw "Backup manifest is missing."
}
$manifest = Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json
foreach ($entry in $manifest.files) {
    $path = Join-Path $backup $entry.path
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
        throw "Backup file is missing: $($entry.path)"
    }
    $actual = (Get-FileHash -Algorithm SHA256 -LiteralPath $path).Hash.ToLowerInvariant()
    if ($actual -ne $entry.sha256) {
        throw "Checksum mismatch: $($entry.path)"
    }
}
$dumpPath = Join-Path $backup "postgres.dump"
$dumpBytes = [System.IO.File]::ReadAllBytes($dumpPath)
if ($dumpBytes.Length -lt 5) { throw "postgres.dump is truncated." }
$header = [System.Text.Encoding]::ASCII.GetString($dumpBytes[0..4])
if ($header -ne "PGDMP") {
    throw "postgres.dump is not a PostgreSQL custom-format archive."
}
Write-Host "Verified $($manifest.files.Count) files and the PostgreSQL archive header."
Write-Host "A full restore drill is still required before the backup is considered production-proven."
