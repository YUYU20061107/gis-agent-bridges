# gis-agent-bridges quickstart wrapper for Windows PowerShell.
# Usage examples:
#   .\scripts\quickstart.ps1 -List
#   .\scripts\quickstart.ps1 -Package qgis -Selftest
#   .\scripts\quickstart.ps1 -SampleQgis
param(
    [switch]$List,
    [string]$Package,
    [switch]$Selftest,
    [switch]$PrintConfig,
    [switch]$SampleQgis
)

$Root = Split-Path -Parent $PSScriptRoot
$ArgsList = @()
if ($List) { $ArgsList += "--list" }
if ($Package) { $ArgsList += @("--package", $Package) }
if ($Selftest) { $ArgsList += "--selftest" }
if ($PrintConfig) { $ArgsList += "--print-config" }
if ($SampleQgis) { $ArgsList += "--sample-qgis" }

$Python = Get-Command python -ErrorAction SilentlyContinue
if (-not $Python) {
    $Python = Get-Command py -ErrorAction SilentlyContinue
    if (-not $Python) { throw "Python 3.11+ was not found in PATH." }
    & $Python.Source -3 "$Root\scripts\quickstart.py" @ArgsList
} else {
    & $Python.Source "$Root\scripts\quickstart.py" @ArgsList
}
exit $LASTEXITCODE
