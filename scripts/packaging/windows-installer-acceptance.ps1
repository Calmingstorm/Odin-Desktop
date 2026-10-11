# The Windows installer's behaviour (phase 4, P7), for a disposable Windows machine only. It creates a standard
# local user, installs and uninstalls as that user, and then deletes the user and its profile. CI runs it on a hosted
# runner. Never run it on a machine where someone has a real account.
#
# As the (elevated) runner it checks that an elevated token is refused. As the standard user (Mode user) it checks:
# /allusers, /D (nothing created, not even its folders), a location recorded elsewhere, --force-run and an unwritable
# folder are refused; then it runs a default install and checks it (owner, HKCU only, shortcut identity, nothing
# launched, the sealed bundle verifying in place, the installed guardian's token check); starts the installed app twice
# (hidden, as at login: its core opens its pipe, then Exit ends the app, the core, the guardian and the bundled
# processes they started); runs the installed real core through windows-installed-core-acceptance.py with the installed
# runtime (a scripted tool turn, a relaunch, an incompatible client); then a reinstall, an uninstall that keeps the
# profile, and three fresh cycles. Every install is silent (/S). The report is JSON and is written however the run
# ends: an exception is recorded as a failed check, and so is each cleanup step that fails (every step is still
# tried). Any failed check makes the exit code 1. Test hooks: -FailAt names a check to fail right after; -FailCleanup
# a cleanup step to fail after its work.
param(
  [Parameter(Mandatory = $true)] [string] $Installer,
  [Parameter(Mandatory = $true)] [string] $Report,
  [Parameter(Mandatory = $true)] [string] $Packaging,
  [string] $Python = '',
  [string] $Mode = 'orchestrate',
  [string] $FailAt = '',
  [string] $FailCleanup = '',
  [string] $CoreScript = ''
)
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
# Beside this script by default; Windows PowerShell 5.1 leaves $PSScriptRoot empty in parameter defaults.
if (-not $CoreScript) { $CoreScript = Join-Path $PSScriptRoot 'windows-installed-core-acceptance.py' }
$AppId = 'net.calmingstorm.odin.desktop'
$Guid = '824e65ca-c164-5739-ae3c-52ce54902f24'  # electron-builder's uuid of the appId: the registry key names
$checks = New-Object System.Collections.Generic.List[object]

function Check([string] $name, [bool] $ok, $detail) {
  $checks.Add([ordered]@{ check = $name; ok = $ok; detail = "$detail" })
  if ($FailAt -and $name -eq $FailAt) { throw "intentional failure after '$name' (-FailAt)" }
}
function Install([string[]] $arguments) {
  (Start-Process -FilePath $Installer -ArgumentList $arguments -Wait -PassThru).ExitCode
}
function OdinUninstallKeys([string] $root) {
  @(Get-ChildItem $root -ErrorAction SilentlyContinue |
    Where-Object { (Get-ItemProperty $_.PSPath -ErrorAction SilentlyContinue).DisplayName -like 'Odin*' })
}
# An exception as a failed check: its type, message and script line, nothing more.
function Outcome($record) {
  "$($record.Exception.GetType().Name): $($record.Exception.Message) (line $($record.InvocationInfo.ScriptLineNumber))"
}
# One cleanup step: tried whatever happened before it, its failure recorded (sanitized) without ending the cleanup.
# The step runs in this function's scope, so its parameters must not reuse a name a step reads ($name is the user's).
function Cleanup([string] $cleanupStep, [scriptblock] $cleanupBlock) {
  try {
    & $cleanupBlock
    if ($FailCleanup -and $cleanupStep -eq $FailCleanup) {
      throw "intentional cleanup failure in '$cleanupStep' (-FailCleanup)" }
    $checks.Add([ordered]@{ check = "cleanup: $cleanupStep"; ok = $true; detail = '' })
  } catch {
    $detail = Outcome $_
    if ($plain) { $detail = $detail.Replace($plain, '<password>') }
    $checks.Add([ordered]@{ check = "cleanup: $cleanupStep"; ok = $false; detail = $detail })
  }
}
function Finish([string] $outcome = '') {
  if ($outcome) { $checks.Add([ordered]@{ check = 'the run reached its end'; ok = $false; detail = $outcome }) }
  $failed = @($checks | Where-Object { -not $_.ok })
  [ordered]@{ mode = $Mode; user = [Security.Principal.WindowsIdentity]::GetCurrent().Name; failed = $failed.Count
    checks = $checks } | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath $Report -Encoding utf8
  [int]($failed.Count -gt 0)
}

if ($Mode -eq 'user') {
 $outcome = ''
 try {
  $inst = Join-Path $env:LOCALAPPDATA 'Programs\Odin'
  $userKeys = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall'
  $installKey = "HKCU:\Software\$Guid"
  $machineKeys = { (OdinUninstallKeys 'HKLM:\Software\Microsoft\Windows\CurrentVersion\Uninstall').Count +
    (OdinUninstallKeys 'HKLM:\Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall').Count }
  $nothing = { -not (Test-Path $inst) -and (OdinUninstallKeys $userKeys).Count -eq 0 -and (& $machineKeys) -eq 0 }
  $lnk = Join-Path $env:APPDATA 'Microsoft\Windows\Start Menu\Programs\Odin.lnk'
  $me = [Security.Principal.WindowsIdentity]::GetCurrent().User.Value
  function Uninstall() {
    # NSIS's uninstaller relaunches itself from TEMP: wait for its effects, the folder included.
    Start-Process -FilePath (Join-Path $inst 'Uninstall Odin.exe') -ArgumentList '/S' | Out-Null
    $deadline = (Get-Date).AddSeconds(180)
    while ((Get-Date) -lt $deadline -and ((Test-Path $inst) -or (OdinUninstallKeys $userKeys).Count)) {
      Start-Sleep -Seconds 2
    }
  }
  Check 'nothing installed before' (& $nothing) $inst
  # The guardian refuses every start while an installer transaction is unfinished: a leftover would fail the starts.
  $pending = Join-Path $env:LOCALAPPDATA 'odin-desktop\install-ownership\nsis\transaction.json'
  Check 'no unfinished installer transaction from an earlier run' (-not (Test-Path -LiteralPath $pending)) $pending

  $code = Install @('/S', '/allusers')
  Check '/allusers is refused' ($code -eq 2 -and (& $nothing)) "exit $code"
  # Refused before .onInit's SetOutPath, which would create the folder and its parents.
  $elsewhere = Join-Path $env:LOCALAPPDATA 'odin-acceptance-d'
  $code = Install @('/S', "/D=$elsewhere\nested\deeper")
  Check '/D is refused before anything is created' ($code -eq 2 -and (& $nothing) -and -not (Test-Path $elsewhere)) (
    "exit $code")
  Remove-Item $elsewhere -Recurse -Force -ErrorAction SilentlyContinue
  # A location recorded elsewhere (no installed app) is refused, never followed.
  $recorded = Join-Path $env:LOCALAPPDATA 'odin-acceptance-elsewhere'
  New-Item -Path $installKey -Force | Out-Null
  Set-ItemProperty -Path $installKey -Name InstallLocation -Value $recorded
  $code = Install @('/S')
  Check 'a location recorded elsewhere is refused' ($code -eq 2 -and (& $nothing) -and -not (Test-Path $recorded)) (
    "exit $code")
  Remove-Item -Path $installKey -Recurse -Force
  $code = Install @('/S', '--force-run')
  Check '--force-run is refused' ($code -eq 2 -and (& $nothing)) "exit $code"
  New-Item -ItemType Directory -Force (Split-Path $inst) | Out-Null
  Set-Content -LiteralPath $inst -Value 'a file where the install folder would be'
  $code = Install @('/S')
  $recorded = Test-Path $installKey
  Remove-Item -LiteralPath $inst -Force
  Check 'an unwritable folder is refused, leaving no record' ($code -eq 2 -and -not $recorded -and (& $nothing)) "exit $code"

  $code = Install @('/S')
  Check 'the default install succeeds' ($code -eq 0 -and (Test-Path (Join-Path $inst 'Odin.exe'))) "exit $code"
  $owner = (Get-Acl -LiteralPath $inst).GetOwner([Security.Principal.SecurityIdentifier]).Value
  Check 'the install folder is the user''s' ($owner -eq $me) $owner
  $missing = @('Uninstall Odin.exe', 'resources\ownership.py', 'resources\bundle-manifest.json',
    'resources\runtime\python\python.exe' | Where-Object { -not (Test-Path (Join-Path $inst $_)) })
  Check 'the installed layout' ($missing.Count -eq 0) ($missing -join ', ')
  $keys = OdinUninstallKeys $userKeys
  $quiet = if ($keys.Count -eq 1) { (Get-ItemProperty $keys[0].PSPath).QuietUninstallString } else { '' }
  Check 'one HKCU entry, current user only' ($keys.Count -eq 1 -and $keys[0].PSChildName -eq $Guid -and
    $quiet -like '*/currentuser*') "$($keys.Count) entries: $quiet"
  Check 'no machine-wide entry' ((& $machineKeys) -eq 0) ''
  $target = if (Test-Path $lnk) { (New-Object -ComObject WScript.Shell).CreateShortcut($lnk).TargetPath } else { '' }
  $aumid = if (Test-Path $lnk) {
    (New-Object -ComObject Shell.Application).NameSpace((Split-Path $lnk)).ParseName('Odin.lnk').ExtendedProperty(
      'System.AppUserModel.ID') } else { '' }
  Check 'the Start menu shortcut and its app ID' ($target -eq (Join-Path $inst 'Odin.exe') -and $aumid -eq $AppId) "$target $aumid"
  $desktop = Join-Path ([Environment]::GetFolderPath('Desktop')) 'Odin.lnk'
  Check 'no desktop shortcut' (-not (Test-Path $desktop)) ''
  Check 'nothing launched' (@(Get-Process Odin -ErrorAction SilentlyContinue).Count -eq 0) ''
  $python = Join-Path $inst 'resources\runtime\python\python.exe'
  $verify = & $python -I -B (Join-Path $Packaging 'verify-bundle.py') (Join-Path $inst 'resources') 2>&1
  Check 'the sealed bundle verifies in place' ($LASTEXITCODE -eq 0) (($verify | Select-Object -First 4) -join ' ')
  $token = & $python -I -B (Join-Path $inst 'resources\ownership.py') token 2>&1
  $facts = $null
  try { $facts = $token | ConvertFrom-Json } catch { }
  Check 'the installed guardian reads a normal token' ($null -ne $facts -and -not $facts.elevated -and
    $facts.owner -eq $me -and $facts.user -eq $me) "$token"

  # The installed app: started hidden, as at login, until its core serves its pipe; then Exit. The second start runs
  # on the profile the first one made.
  $sha = [Security.Cryptography.SHA256]::Create()
  $hash = -join ($sha.ComputeHash([Text.Encoding]::UTF8.GetBytes($me)) | ForEach-Object { $_.ToString('x2') })
  $pipe = "\\.\pipe\odin-desktop-$($hash.Substring(0, 16))-default"
  $exe = Join-Path $inst 'Odin.exe'
  $profileRoot = Join-Path $env:LOCALAPPDATA 'odin-desktop\default'
  $installed = { @(Get-CimInstance Win32_Process | Where-Object {
    $_.ExecutablePath -and $_.ExecutablePath.StartsWith($inst, [StringComparison]::OrdinalIgnoreCase) }) }
  $serving = { [IO.Directory]::GetFiles('\\.\pipe\') -contains $pipe }
  foreach ($start in 'first', 'second') {
    Start-Process -FilePath $exe -ArgumentList '--hidden' | Out-Null
    $deadline = (Get-Date).AddSeconds(180)
    while ((Get-Date) -lt $deadline -and -not (& $serving)) { Start-Sleep -Seconds 2 }
    $up = & $serving
    $detail = ((& $installed) | ForEach-Object { $_.Name } | Sort-Object -Unique) -join ', '
    if (-not $up) {
      $log = Join-Path $profileRoot 'data\logs\core.log'
      $detail += ' | ' + ((Get-Content $log -Tail 8 -ErrorAction SilentlyContinue) -join ' / ')
    }
    Check "the installed app's $start start opens its core's pipe" $up $detail
    Start-Process -FilePath $exe -ArgumentList '--exit' -Wait | Out-Null
    $deadline = (Get-Date).AddSeconds(120)
    while ((Get-Date) -lt $deadline -and ((& $installed).Count -or (& $serving))) { Start-Sleep -Seconds 2 }
    $left = (& $installed)
    Check "Exit ends the app, its core, its guardian and their bundled processes ($start start)" (
      $left.Count -eq 0 -and -not (& $serving)) (
      ($left | ForEach-Object { "$($_.Name) $($_.ProcessId)" }) -join ', ')
    $left | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
  }
  Check 'the starts made a profile' (Test-Path (Join-Path $profileRoot 'config\ipc.token')) $profileRoot

  # The installed real core: the installed runtime runs the engine's own client against it (a scripted tool turn, a
  # relaunch, an incompatible client). Its output goes to files: a native child's stderr must not stop this script.
  $coreReport = Join-Path $env:TEMP 'odin-installed-core.json'
  $coreLog = Join-Path $env:TEMP 'odin-installed-core.log'
  Remove-Item -LiteralPath $coreReport, $coreLog, "$coreLog.err" -ErrorAction SilentlyContinue
  $coreRun = Start-Process -FilePath (Join-Path $inst 'resources\runtime\python\python.exe') -NoNewWindow -Wait `
    -PassThru -ArgumentList '-I', '-B', "`"$CoreScript`"", '--report', "`"$coreReport`"" `
    -RedirectStandardOutput $coreLog -RedirectStandardError "$coreLog.err"
  $core = $null
  try { $core = Get-Content -LiteralPath $coreReport -Raw | ConvertFrom-Json } catch { }
  if ($null -eq $core) {
    Check 'the installed core''s checks ran' $false ("exit $($coreRun.ExitCode), no report: " +
      ((Get-Content -LiteralPath "$coreLog.err" -Tail 6 -ErrorAction SilentlyContinue) -join ' / '))
  } else {
    foreach ($item in $core.checks) { Check "core: $($item.check)" ([bool]$item.ok) $item.detail }
  }

  $code = Install @('/S')
  Check 'a reinstall succeeds' ($code -eq 0 -and (Test-Path (Join-Path $inst 'Odin.exe'))) "exit $code"
  Uninstall
  Check 'uninstall removes the folder, entries and shortcut' ((& $nothing) -and -not (Test-Path $lnk) -and
    -not (Test-Path $installKey)) ''
  Check 'uninstall keeps the profile' (Test-Path (Join-Path $profileRoot 'config\ipc.token')) $profileRoot
  foreach ($cycle in 1..3) {
    $code = Install @('/S')
    $installed = Test-Path (Join-Path $inst 'Odin.exe')
    Uninstall
    Check "fresh install cycle $cycle" ($code -eq 0 -and $installed -and (& $nothing)) "exit $code"
  }
 } catch {
  $outcome = Outcome $_
 }
 exit (Finish $outcome)
}

# The runner: an elevated token must be refused before anything is written.
$outcome = ''
$name = 'odin-acceptance'
$plain = ''
$exitCode = 1
try {
try {
$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
if (-not (New-Object Security.Principal.WindowsPrincipal $identity).IsInRole(
    [Security.Principal.WindowsBuiltInRole]::Administrator)) {
  throw 'The orchestrator creates a local user, so it runs elevated, on a disposable machine'
}
$runnerProgram = Join-Path $env:LOCALAPPDATA 'Programs\Odin'
# The runner's token as the app's own check reads it (the guardian's token action), for the record.
$facts = if ($Python) { & $Python -I -B (Join-Path $Packaging 'ownership.py') token 2>&1 } else { 'not read' }
$before = Test-Path $runnerProgram
$code = Install @('/S')
Check 'an elevated token is refused' ($code -eq 2 -and -not $before -and -not (Test-Path $runnerProgram) -and
  (OdinUninstallKeys 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall').Count -eq 0) "exit $code; $facts"

# A disposable standard user, its work folder, then the user's cases.
$bytes = New-Object byte[] 24
[Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($bytes)
$plain = 'Oa-' + [Convert]::ToBase64String($bytes) + '!7'
$secret = ConvertTo-SecureString $plain -AsPlainText -Force
New-LocalUser -Name $name -Password $secret -PasswordNeverExpires -AccountNeverExpires | Out-Null
Check 'a disposable user was created' ($null -ne (Get-LocalUser -Name $name -ErrorAction SilentlyContinue)) $name
$work = Join-Path $env:RUNNER_TEMP 'odin-installer-acceptance'
New-Item -ItemType Directory -Force $work | Out-Null
Copy-Item $Installer (Join-Path $work 'setup.exe')
Copy-Item $PSCommandPath (Join-Path $work 'acceptance.ps1')
Copy-Item $CoreScript (Join-Path $work 'windows-installed-core-acceptance.py')
Copy-Item -Recurse $Packaging (Join-Path $work 'packaging')
& icacls.exe $work /grant "${name}:(OI)(CI)M" /T /Q | Out-Null
$userReport = Join-Path $work 'user-report.json'
$credential = New-Object Management.Automation.PSCredential ($name, $secret)
$arguments = "-NoProfile -NonInteractive -ExecutionPolicy Bypass -File `"$work\acceptance.ps1`" -Mode user " +
  "-Installer `"$work\setup.exe`" -Report `"$userReport`" -Packaging `"$work\packaging`""
if ($FailAt) { $arguments += " -FailAt `"$FailAt`"" }
$process = Start-Process powershell.exe -Credential $credential -LoadUserProfile -ArgumentList $arguments `
  -WorkingDirectory $work -Wait -PassThru
$result = Get-Content -LiteralPath $userReport -Raw -ErrorAction SilentlyContinue | ConvertFrom-Json
if ($null -eq $result) {
  Check 'the standard user''s cases ran' $false "exit $($process.ExitCode), no report"
} else {
  foreach ($item in $result.checks) { Check "user: $($item.check)" ([bool]$item.ok) $item.detail }
}
} catch {
  $outcome = Outcome $_
  if ($plain) { $outcome = $outcome.Replace($plain, '<password>') }
} finally {
  Cleanup 'remove the account' {
    if (Get-LocalUser -Name $name -ErrorAction SilentlyContinue) { Remove-LocalUser -Name $name }
  }
  Cleanup 'remove its profile' {
    # Windows may still be unloading the profile just after its last process: a few tries, then a recorded failure.
    foreach ($try in 1..5) {
      $left = @(Get-CimInstance Win32_UserProfile | Where-Object { $_.LocalPath -like "*\$name" })
      if (-not $left.Count) { return }
      try { $left | Remove-CimInstance } catch { if ($try -eq 5) { throw } }
      Start-Sleep -Seconds 3
    }
    if (@(Get-CimInstance Win32_UserProfile | Where-Object { $_.LocalPath -like "*\$name" }).Count) {
      throw "the profile of $name is still there"
    }
  }
}
} finally {
  $exitCode = Finish $outcome
}
exit $exitCode
