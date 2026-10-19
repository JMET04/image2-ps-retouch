param(
    [Parameter(Mandatory=$true)][string]$PhotoshopPath,
    [Parameter(Mandatory=$true)][string]$PythonPath
)
$ErrorActionPreference = 'Stop'
if (-not (Test-Path -LiteralPath $PhotoshopPath -PathType Leaf)) { throw 'Verified Photoshop executable required' }
if (-not (Test-Path -LiteralPath $PythonPath -PathType Leaf)) { throw 'Verified Python executable required' }
& $PythonPath -X utf8 (Join-Path $PSScriptRoot 'photoshop_job.py') --quit-idle
if ($LASTEXITCODE -ne 0) { throw 'Idle quit refused; inspect application; no automatic retry' }
$exitDeadline = [DateTime]::UtcNow.AddSeconds(20)
while (Get-Process -Name Photoshop -ErrorAction SilentlyContinue) {
    if ([DateTime]::UtcNow -gt $exitDeadline) { throw 'Photoshop has not exited; will not launch a second instance' }
    Start-Sleep -Milliseconds 250
}
Start-Process -FilePath $PhotoshopPath -WindowStyle Hidden
Write-Output 'Normal exit confirmed; verified Photoshop launched. Confirm startup is ready before submitting jobs.'
