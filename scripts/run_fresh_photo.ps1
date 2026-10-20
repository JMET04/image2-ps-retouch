param(
    [Parameter(Mandatory=$true)][string]$RecipePath,
    [Parameter(Mandatory=$true)][string]$PhotoshopPath,
    [string]$PythonPath = 'python',
    [ValidateSet('Standard','ConstrainedSmall')][string]$SessionMode = 'Standard'
)
$ErrorActionPreference = 'Stop'
function Wait-PhotoshopExit {
    $waitStarted = Get-Date
    $exitDeadline = $waitStarted.AddSeconds(120)
    $nextNotice = $waitStarted.AddSeconds(15)
    while (Get-Process -Name Photoshop -ErrorAction SilentlyContinue) {
        $now = Get-Date
        if ($now -gt $exitDeadline) { throw 'Normal zero-document quit requested, but process has not exited after 120 seconds; inspect before next launch, never repeat a saved photo' }
        if ($now -ge $nextNotice) {
            Write-Output ('Waiting for normal Photoshop exit: {0:N0}s; no photo resubmitted' -f ($now-$waitStarted).TotalSeconds)
            $nextNotice = $now.AddSeconds(15)
        }
        Start-Sleep -Milliseconds 250
    }
    Write-Output ('Photoshop exit confirmed after {0:N1}s' -f ((Get-Date)-$waitStarted).TotalSeconds)
}
$recipeFile = (Resolve-Path -LiteralPath $RecipePath).Path
$photoshopFile = (Resolve-Path -LiteralPath $PhotoshopPath).Path
$pythonFile = (Get-Command $PythonPath -ErrorAction Stop).Source
$jobScript = Join-Path $PSScriptRoot 'photoshop_job.py'
& $pythonFile -X utf8 (Join-Path $PSScriptRoot 'project_session.py') --context $recipeFile --reserve-seconds 720
if ($LASTEXITCODE -ne 0) { throw 'Project session limit prevents a new Photoshop lifecycle.' }
$photoRecipe = Get-Content -LiteralPath $recipeFile -Raw | ConvertFrom-Json
$savedReceiptPath = [string]$photoRecipe.output_base + '_execution.json'
if (Test-Path -LiteralPath $savedReceiptPath) {
    $savedReceipt = Get-Content -LiteralPath $savedReceiptPath -Raw | ConvertFrom-Json
    if ($savedReceipt.original_unchanged) {
        throw "This photo already has a persisted native success receipt: $savedReceiptPath. Inspect the saved result; use a new version path for an intentional edit. No Photoshop launch or photo resubmission."
    }
}
$nativeStatePath = Join-Path $env:LOCALAPPDATA 'CodexPhotoRetouch\native-state.json'
if (Test-Path -LiteralPath $nativeStatePath) {
    $nativeState = Get-Content -LiteralPath $nativeStatePath -Raw | ConvertFrom-Json
    if ($nativeState.status -in @('running', 'outcome_unknown', 'native_error')) {
        throw "Prior native outcome is unresolved ($($nativeState.status)): $nativeStatePath. Inspect Photoshop and saved outputs, then use the guarded zero-document recovery probe. No Photoshop launch or photo resubmission."
    }
}
& $pythonFile -X utf8 $jobScript $recipeFile --validate-only
if ($LASTEXITCODE -ne 0) { throw 'Recipe validation failed before Photoshop launch' }
$controlDriveName = [IO.Path]::GetPathRoot($env:LOCALAPPDATA).Substring(0,1)
$controlFreeBytes = (Get-PSDrive -Name $controlDriveName).Free
if ($controlFreeBytes -lt 512MB) {
    throw "Control/cache drive $controlDriveName has only $([math]::Round($controlFreeBytes / 1MB)) MiB free; reserve at least 512 MiB before launching Photoshop. No photo submitted."
}
if ($SessionMode -eq 'Standard') {
    $outputRoot = [IO.Path]::GetPathRoot([IO.Path]::GetFullPath([string]$photoRecipe.output_base))
    $outputDriveName = $outputRoot.Substring(0,1)
    if ((Get-PSDrive -Name $outputDriveName).Free -lt 16GB) {
        throw 'Standard mode requires at least 16 GiB on the output drive before Photoshop startup.'
    }
}
if (Get-Process -Name Photoshop -ErrorAction SilentlyContinue) {
    & $pythonFile -X utf8 $jobScript --quit-idle
    if ($LASTEXITCODE -ne 0) { throw 'Guarded normal idle quit failed; inspect before recovery' }
    Wait-PhotoshopExit
}
# Background launch; the editor remains available for explicit visual diagnosis.
& $pythonFile -X utf8 (Join-Path $PSScriptRoot 'project_session.py') --context $recipeFile --reserve-seconds 570
if ($LASTEXITCODE -ne 0) { throw 'Project session limit reached before Photoshop startup.' }
Start-Process -FilePath $photoshopFile -WindowStyle Hidden
& $pythonFile -X utf8 $jobScript --wait-startup-idle
if ($LASTEXITCODE -ne 0) { throw 'Bounded startup readiness failed; no photo job submitted' }
if ($SessionMode -eq 'ConstrainedSmall') {
    & $pythonFile -X utf8 $jobScript $recipeFile --fresh-small-session $photoshopFile
} else {
    & $pythonFile -X utf8 $jobScript $recipeFile
}
if ($LASTEXITCODE -ne 0) {
    if (Test-Path -LiteralPath $savedReceiptPath) {
        $savedReceipt = Get-Content -LiteralPath $savedReceiptPath -Raw | ConvertFrom-Json
        if ($savedReceipt.original_unchanged) {
            throw "Photo output was saved before the control/quit failure. Keep $savedReceiptPath; inspect the Photoshop window and recover the native guard. Do not resubmit this saved photo."
        }
    }
    throw 'Native photo job failed; no retry submitted'
}
if ($SessionMode -eq 'Standard') {
    & $pythonFile -X utf8 $jobScript --quit-idle
    if ($LASTEXITCODE -ne 0) { throw "Photo receipt is saved; normal idle quit failed. Inspect $savedReceiptPath and native state; do not resubmit." }
}
Wait-PhotoshopExit
