param(
    [Parameter(Mandatory=$true)][string]$PsdPath,
    [Parameter(Mandatory=$true)][string]$ProofPath,
    [Parameter(Mandatory=$true)][string]$PhotoshopPath,
    [string]$PythonPath = 'python'
)
$ErrorActionPreference = 'Stop'
$psdFile = (Resolve-Path -LiteralPath $PsdPath).Path
$photoshopFile = (Resolve-Path -LiteralPath $PhotoshopPath).Path
$pythonFile = (Get-Command $PythonPath -ErrorAction Stop).Source
$jobScript = Join-Path $PSScriptRoot 'photoshop_job.py'
& $pythonFile -X utf8 (Join-Path $PSScriptRoot 'project_session.py') --context $psdFile --reserve-seconds 600
if ($LASTEXITCODE -ne 0) { throw 'Project session limit prevents a new PSD inspection lifecycle.' }
if (Test-Path -LiteralPath $ProofPath) { throw 'Inspection proof already exists; inspect it instead of opening the PSD again.' }
$statePath = Join-Path $env:LOCALAPPDATA 'CodexPhotoRetouch\native-state.json'
if (Test-Path -LiteralPath $statePath) {
    $state = Get-Content -LiteralPath $statePath -Raw | ConvertFrom-Json
    if ($state.status -in @('running','outcome_unknown','native_error')) { throw 'Unresolved native outcome; inspect before guarded recovery.' }
}
$controlDrive = [IO.Path]::GetPathRoot($env:LOCALAPPDATA).Substring(0,1)
if ((Get-PSDrive -Name $controlDrive).Free -lt 512MB) { throw 'Control/cache drive needs at least 512 MiB before startup.' }
$outputDrive = [IO.Path]::GetPathRoot($psdFile).Substring(0,1)
if ((Get-PSDrive -Name $outputDrive).Free -lt 16GB) { throw 'PSD inspection drive needs at least 16 GiB free.' }
function Wait-InspectionExit {
    $started = Get-Date
    $nextNotice = $started.AddSeconds(15)
    while (Get-Process -Name Photoshop -ErrorAction SilentlyContinue) {
        $now = Get-Date
        if ($now -gt $started.AddSeconds(120)) { throw 'Normal quit requested; Photoshop exit not confirmed. Keep saved inspection proof.' }
        if ($now -ge $nextNotice) {
            Write-Output ('Waiting for normal inspection exit: {0:N0}s' -f ($now-$started).TotalSeconds)
            $nextNotice = $now.AddSeconds(15)
        }
        Start-Sleep -Milliseconds 250
    }
    Write-Output 'Photoshop inspection exit confirmed'
}
if (Get-Process -Name Photoshop -ErrorAction SilentlyContinue) {
    & $pythonFile -X utf8 $jobScript --quit-idle
    if ($LASTEXITCODE -ne 0) { throw 'Guarded idle quit failed; no inspection submitted.' }
    Wait-InspectionExit
}
# Show the actual editor so any blocking Photoshop dialog remains observable.
& $pythonFile -X utf8 (Join-Path $PSScriptRoot 'project_session.py') --context $psdFile --reserve-seconds 450
if ($LASTEXITCODE -ne 0) { throw 'Project session limit reached before inspection startup.' }
Start-Process -FilePath $photoshopFile -WindowStyle Normal
& $pythonFile -X utf8 $jobScript --wait-startup-idle
if ($LASTEXITCODE -ne 0) { throw 'Bounded startup failed; no inspection submitted.' }
& $pythonFile -X utf8 (Join-Path $PSScriptRoot 'inspect_psd_native.py') $psdFile $ProofPath
if ($LASTEXITCODE -ne 0) { throw 'Native PSD inspection failed; inspect state and existing proof before retry.' }
& $pythonFile -X utf8 $jobScript --quit-idle
if ($LASTEXITCODE -ne 0) { throw 'Inspection was saved, but normal quit failed. Keep the proof; do not repeat inspection.' }
Wait-InspectionExit
