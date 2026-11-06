param(
    [string]$OutputPath = "",
    [switch]$WhatIf
)

$ErrorActionPreference = "Stop"
$Source = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$SpecCandidates = @(
    Get-ChildItem -LiteralPath (Join-Path $Source "docs") -File -Filter "*v1.4.md"
)
if ($SpecCandidates.Count -ne 1 -or $SpecCandidates[0].Length -eq 0) {
    throw "The mandatory v1.4 specification is missing, ambiguous, or empty"
}
$Spec = $SpecCandidates[0].FullName

if (-not $OutputPath) {
    $OutputPath = Join-Path $Source ("dist\photocheck-" + (Get-Date -Format "yyyyMMdd-HHmm") + ".zip")
}
$OutputPath = [System.IO.Path]::GetFullPath($OutputPath)
$Staging = Join-Path $env:TEMP ("photocheck-release-" + [guid]::NewGuid())

try {
    New-Item -ItemType Directory -Path $Staging | Out-Null
    robocopy $Source $Staging /E `
        /XD .git __pycache__ .pytest_cache .venv venv dist `
            photocheck-output e2e-photocheck-output test-output `
        /XF *.pyc *.log /NFL /NDL /NJH /NJS /NP
    if ($LASTEXITCODE -gt 7) {
        throw "robocopy failed with exit code $LASTEXITCODE"
    }

    $StagedSpec = @(
        Get-ChildItem -LiteralPath (Join-Path $Staging "docs") -File -Filter "*v1.4.md"
    )
    if ($StagedSpec.Count -ne 1 -or $StagedSpec[0].Length -eq 0) {
        throw "The staged release is missing the mandatory v1.4 specification"
    }
    if (Test-Path -LiteralPath (Join-Path $Staging ".git")) {
        throw "The staged release still contains .git"
    }

    if ($WhatIf) {
        Write-Output "Release staging validation passed: $Staging"
        Write-Output "Would write: $OutputPath"
        return
    }

    $OutputDir = Split-Path -Parent $OutputPath
    New-Item -ItemType Directory -Force -Path $OutputDir | Out-Null
    Remove-Item -LiteralPath $OutputPath -Force -ErrorAction SilentlyContinue
    Compress-Archive -Path (Join-Path $Staging "*") -DestinationPath $OutputPath

    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $archive = [System.IO.Compression.ZipFile]::OpenRead($OutputPath)
    try {
        $entries = @($archive.Entries | ForEach-Object { $_.FullName -replace '\\', '/' })
        if (-not ($entries | Where-Object { $_ -match '^docs/.*v1\.4\.md$' })) {
            throw "The release archive is missing the mandatory v1.4 specification"
        }
        if ($entries | Where-Object { $_ -match '(^|/)\.git(/|$)' }) {
            throw "The release archive contains .git"
        }
    }
    finally {
        $archive.Dispose()
    }

    Write-Output $OutputPath
}
finally {
    if (Test-Path -LiteralPath $Staging) {
        Remove-Item -LiteralPath $Staging -Recurse -Force
    }
}
