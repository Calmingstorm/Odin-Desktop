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
# a cleanup step to fail after its work. -Publisher names the signer of a signed build: the installer, then the
# installed Odin.exe and its uninstaller, must each carry that publisher's valid, timestamped signature, and the report
# records the publisher and the installer's certificate.
param(
  [Parameter(Mandatory = $true)] [string] $Installer,
  [Parameter(Mandatory = $true)] [string] $Report,
  [Parameter(Mandatory = $true)] [string] $Packaging,
  [string] $Python = '',
  [string] $Mode = 'orchestrate',
  [string] $FailAt = '',
  [string] $FailCleanup = '',
  [string] $CoreScript = '',
  [string] $Publisher = ''
)
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
# Beside this script by default; Windows PowerShell 5.1 leaves $PSScriptRoot empty in parameter defaults.
if (-not $CoreScript) { $CoreScript = Join-Path $PSScriptRoot 'windows-installed-core-acceptance.py' }
$AppId = 'net.calmingstorm.odin.desktop'
$Guid = '824e65ca-c164-5739-ae3c-52ce54902f24'  # electron-builder's uuid of the appId: the registry key names
$checks = New-Object System.Collections.Generic.List[object]
# Every check also lands here as it's made: a run cut short still says how far it got.
$Progress = "$Report.progress"
Remove-Item -LiteralPath $Progress -ErrorAction SilentlyContinue

function Check([string] $name, [bool] $ok, $detail) {
  $checks.Add([ordered]@{ check = $name; ok = $ok; detail = "$detail" })
  if ($Progress) { Add-Content -LiteralPath $Progress -Value "$ok $name" -Encoding utf8 }
  if ($FailAt -and $name -eq $FailAt) { throw "intentional failure after '$name' (-FailAt)" }
}
# A signed build's signature as Windows reads it: valid, by -Publisher, timestamped (the certificates last three days;
# the timestamp keeps a signature valid after that).
if ($Publisher -and $Publisher -notmatch "^[A-Za-z0-9 .,'-]+$") { throw "an unexpected publisher name: $Publisher" }
$SignerThumbprint = ''
function SignedBy([string] $path) {
  $signature = Get-AuthenticodeSignature -LiteralPath $path
  $certificate = $signature.SignerCertificate
  $name = if ($certificate) { $certificate.GetNameInfo('SimpleName', $false) } else { '' }
  $stamped = $null -ne $signature.TimeStamperCertificate
  [ordered]@{ ok = ($signature.Status -eq 'Valid' -and $name -eq $Publisher -and $stamped)
    thumbprint = $(if ($certificate) { $certificate.Thumbprint } else { '' })
    detail = "$($signature.Status), signer '$name', $(if ($stamped) { 'timestamped' } else { 'no timestamp' })" }
}
# Every process this test waits for is bounded, and only the process itself is waited for (Start-Process -Wait also
# waits for every descendant, so one that lingers stalls the run with no report). One that doesn't exit in time ends
# the run as a failure naming it. The process object keeps its exit code only if its handle was taken while it ran.
function Run([string] $file, [string[]] $arguments, [int] $minutes, [hashtable] $more = @{}) {
  $run = Start-Process -FilePath $file -ArgumentList $arguments -PassThru @more
  $null = $run.Handle
  if (-not $run.WaitForExit($minutes * 60000)) {
    & taskkill.exe /PID $run.Id /T /F | Out-Null
    throw "$(Split-Path -Leaf $file) $($arguments -join ' ') didn't exit within $minutes minutes"
  }
  $run.ExitCode
}
# Ends these processes, then waits (bounded) until they're gone: Stop-Process returns before Windows has torn a
# process down, and an installer started at once still finds it running and refuses.
function StopAndWait($processes, [int] $seconds = 30) {
  $ids = @($processes | Where-Object { $_ } | ForEach-Object { $_.ProcessId } | Where-Object { $_ })
  if (-not $ids.Count) { return }
  $ids | ForEach-Object { Stop-Process -Id $_ -Force -ErrorAction SilentlyContinue }
  $deadline = (Get-Date).AddSeconds($seconds)
  while ((Get-Date) -lt $deadline -and @(Get-Process -Id $ids -ErrorAction SilentlyContinue).Count) {
    Start-Sleep -Milliseconds 500
  }
}
function Install([string[]] $arguments) {
  Run $Installer $arguments 10
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
# The installed core's report, judged at this boundary by type, never by coercion. Each row needs a nonempty string
# name and a boolean ok; a malformed row is imported as a failed check. The report counts as complete only with exit 0,
# a boolean completed that is true, an array of well-formed rows holding every required check, and a nonnegative
# integer failed equal to the false rows. The required list comes from the core script (--list-checks), never from the
# report: an interrupted, partial, empty, malformed or inconsistent report fails here.
function Import-CoreReport([string] $report, [int] $exitCode, [string[]] $required, [string] $errorLog) {
  $core = $null
  try { $core = Get-Content -LiteralPath $report -Raw | ConvertFrom-Json } catch { }
  $rows = $null -ne $core -and $core.checks -is [array]
  $items = @()
  if ($rows) { $items = @($core.checks) }
  $names = @()
  $failures = 0
  $malformed = 0
  foreach ($item in $items) {
    $name = $item.check
    $ok = $item.ok
    if ($name -is [string] -and $name.Length -gt 0 -and $ok -is [bool]) {
      $names += $name
      if (-not $ok) { $failures++ }
      Check "core: $name" $ok $item.detail
    } else {
      $malformed++
      $kind = if ($null -eq $ok) { 'null' } else { $ok.GetType().Name }
      Check "core: $name" $false "malformed row: ok is $kind, not a boolean (or the name isn't a string)"
    }
  }
  $missing = @($required | Where-Object { $names -notcontains $_ })
  $count = $core.failed
  $wellFormed = $rows -and $items.Count -gt 0 -and $malformed -eq 0 -and
    $core.completed -is [bool] -and $core.completed -and
    ($count -is [int] -or $count -is [long]) -and $count -ge 0 -and $count -eq $failures
  $tail = (Get-Content -LiteralPath $errorLog -Tail 4 -ErrorAction SilentlyContinue) -join ' / '
  Check 'the installed core''s run completed with every required check' (
    $exitCode -eq 0 -and $wellFormed -and @($required).Count -gt 0 -and $missing.Count -eq 0) (
    "exit $exitCode; completed $($core.completed); failed $count against $failures false rows; " +
    "$malformed malformed rows; missing: $($missing -join '; '); $tail")
}
function Finish([string] $outcome = '') {
  if ($outcome) { $checks.Add([ordered]@{ check = 'the run reached its end'; ok = $false; detail = $outcome }) }
  $failed = @($checks | Where-Object { -not $_.ok })
  # The tested bytes, so a release receipt can require the retained installer to be exactly these.
  $digest = try { (Get-FileHash -LiteralPath $Installer -Algorithm SHA256).Hash.ToLowerInvariant() } catch { '' }
  # The signer this run checked, for the receipt: none for an unsigned build, or the user's part of a signed one.
  $signature = if ($Publisher -and $SignerThumbprint) { [ordered]@{ publisher = $Publisher; thumbprint = $SignerThumbprint } }
  [ordered]@{ mode = $Mode; user = [Security.Principal.WindowsIdentity]::GetCurrent().Name; failed = $failed.Count
    installer_sha256 = $digest; signature = $signature; checks = $checks } | ConvertTo-Json -Depth 4 |
    Set-Content -LiteralPath $Report -Encoding utf8
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
  # An uninstall leaves its marker for the next install to take over (with no tree nothing can start), so a kept
  # profile can carry one from an earlier run. The first complete install must take it over and clear it.
  $pending = Join-Path $env:LOCALAPPDATA 'odin-desktop\install-ownership\nsis\transaction.json'
  $earlier = Test-Path -LiteralPath $pending

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
  Check 'it completes its transaction, leaving no marker' (-not (Test-Path -LiteralPath $pending)) (
    "a marker from an earlier run: $earlier")
  $owner = (Get-Acl -LiteralPath $inst).GetOwner([Security.Principal.SecurityIdentifier]).Value
  Check 'the install folder is the user''s' ($owner -eq $me) $owner
  $missing = @('Uninstall Odin.exe', 'resources\ownership.py', 'resources\bundle-manifest.json',
    'resources\runtime\python\python.exe' | Where-Object { -not (Test-Path (Join-Path $inst $_)) })
  Check 'the installed layout' ($missing.Count -eq 0) ($missing -join ', ')
  if ($Publisher) {
    foreach ($file in 'Odin.exe', 'Uninstall Odin.exe') {
      $signed = SignedBy (Join-Path $inst $file)
      Check "the installed $file is validly signed by the expected publisher, with a timestamp" $signed.ok $signed.detail
    }
  }
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
  # This install's Odin only: another account's Odin on the same machine has a name but no readable path.
  $launched = @(Get-Process Odin -ErrorAction SilentlyContinue | Where-Object {
    $_.Path -and $_.Path.StartsWith($inst, [StringComparison]::OrdinalIgnoreCase) })
  Check 'nothing launched' ($launched.Count -eq 0) (($launched | ForEach-Object { "$($_.Id) $($_.Path)" }) -join ', ')
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
  # Lifetime receipts not marked clean: each fences every later install until a restart. A publication's leftover
  # (".<name>.<32 hex>.tmp") is never a receipt.
  $receiptsDir = Join-Path $env:LOCALAPPDATA 'odin-desktop\install-ownership\nsis\receipts'
  function UnresolvedLifetimes() {
    @(Get-ChildItem -LiteralPath $receiptsDir -Force -ErrorAction SilentlyContinue |
      Where-Object { $_.Name -notmatch '^\..+\.[0-9a-f]{32}\.tmp$' } | ForEach-Object {
        $record = try { Get-Content -LiteralPath $_.FullName -Raw | ConvertFrom-Json } catch { $null }
        if (-not $record -or $record.state -ne 'clean') {
          "$($_.Name): $(if ($record) { "$($record.role) $($record.state)" } else { 'unreadable' })" } })
  }
  # After an Exit: the guardian writes the lifetime's clean receipt once the app has exited, then exits itself, and a
  # process listing taken as it finishes can miss it. So the receipts get a few seconds to settle; one still unconfirmed
  # after that has stayed so.
  function SettledLifetimes() {
    $deadline = (Get-Date).AddSeconds(15)
    while ($true) {
      $unresolved = @(UnresolvedLifetimes)
      if (-not $unresolved.Count -or (Get-Date) -ge $deadline) { return $unresolved }
      Start-Sleep -Milliseconds 500
    }
  }
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
    if ($start -eq 'first') {
      # UTF-8 mode: the engine's text files are UTF-8, as on Linux, not the ANSI code page.
      $cores = @((& $installed) | Where-Object { $_.Name -eq 'python.exe' -and $_.CommandLine -match '\s-m\s+src(\s|$)' })
      Check 'the installed app starts its core in UTF-8 mode' (
        $cores.Count -eq 1 -and $cores[0].CommandLine -match '\s-X\s+utf8\s') (
        ($cores | ForEach-Object { $_.CommandLine }) -join ' | ')
    }
    Run $exe @('--exit') 2 | Out-Null
    $deadline = (Get-Date).AddSeconds(120)
    while ((Get-Date) -lt $deadline -and ((& $installed).Count -or (& $serving))) { Start-Sleep -Seconds 2 }
    $left = (& $installed)
    Check "Exit ends the app, its core, its guardian and their bundled processes ($start start)" (
      $left.Count -eq 0 -and -not (& $serving)) (
      ($left | ForEach-Object { "$($_.Name) $($_.ProcessId)" }) -join ', ')
    # The app's guardian records its clean Exit after the app's real exit, so it has to outlive the app.
    $unresolved = @(SettledLifetimes)
    Check "Exit leaves every lifetime clean ($start start)" ($unresolved.Count -eq 0) ($unresolved -join ', ')
    StopAndWait $left
  }
  Check 'the starts made a profile' (Test-Path (Join-Path $profileRoot 'config\ipc.token')) $profileRoot

  # The installed real core: the installed runtime runs the engine's own client against it (a scripted tool turn, a
  # relaunch, an incompatible client). Its output goes to files: a native child's stderr must not stop this script.
  $coreReport = Join-Path $env:TEMP 'odin-installed-core.json'
  $coreLog = Join-Path $env:TEMP 'odin-installed-core.log'
  $coreList = Join-Path $env:TEMP 'odin-installed-core-checks.json'
  Remove-Item -LiteralPath $coreReport, $coreLog, "$coreLog.err", $coreList, "$coreList.err" -ErrorAction SilentlyContinue
  $corePython = Join-Path $inst 'resources\runtime\python\python.exe'
  $listCode = Run $corePython @('-I', '-B', "`"$CoreScript`"", '--list-checks') 5 @{
    NoNewWindow = $true; RedirectStandardOutput = $coreList; RedirectStandardError = "$coreList.err" }
  $required = @()
  if ($listCode -eq 0) {
    # Windows PowerShell 5.1 emits a top-level JSON array as one object: assign, then wrap.
    try { $parsed = Get-Content -LiteralPath $coreList -Raw | ConvertFrom-Json; $required = @($parsed) } catch { }
  }
  $coreCode = Run $corePython @('-I', '-B', "`"$CoreScript`"", '--report', "`"$coreReport`"") 30 @{
    NoNewWindow = $true; RedirectStandardOutput = $coreLog; RedirectStandardError = "$coreLog.err" }
  Import-CoreReport $coreReport $coreCode $required "$coreLog.err"

  # Install safety (phase 5): the installer and uninstaller hold the app's lease, never end Odin.
  $ownership = Join-Path $env:LOCALAPPDATA 'odin-desktop\install-ownership\nsis'
  $marker = Join-Path $ownership 'transaction.json'
  $uninstaller = Join-Path $inst 'Uninstall Odin.exe'
  function Serve() {
    Start-Process -FilePath $exe -ArgumentList '--hidden' | Out-Null
    $deadline = (Get-Date).AddSeconds(180)
    while ((Get-Date) -lt $deadline -and -not (& $serving)) { Start-Sleep -Seconds 2 }
    & $serving
  }
  function ExitOdin() {
    Run $exe @('--exit') 2 | Out-Null
    $deadline = (Get-Date).AddSeconds(120)
    while ((Get-Date) -lt $deadline -and ((& $installed).Count -or (& $serving))) { Start-Sleep -Seconds 2 }
  }
  # What the installer's own gates see, for a refused install's detail (its refusal box answers itself when silent):
  # processes under the install folder as .NET reads them, the marker and each receipt's state; with -Verdict, the
  # installed guardian's receipt verdict and a lease probe. Facts only, never a check of their own, and nothing here
  # throws: what can't be captured becomes text. Native output goes to files, never 2>&1, because under 'Stop'
  # Windows PowerShell 5.1 raises a redirected stderr line, and these diagnostics write to stderr by design.
  function InstallFacts([switch] $Verdict) {
    $facts = @()
    try {
      $running = @([System.Diagnostics.Process]::GetProcesses() | Where-Object {
        $_.Path -and $_.Path.StartsWith($inst, [StringComparison]::OrdinalIgnoreCase) } |
        ForEach-Object { "$($_.ProcessName) $($_.Id)" })
      $facts += 'running: ' + $(if ($running.Count) { $running -join ', ' } else { 'none' })
      $facts += "marker: $(Test-Path $marker)"
      $receipts = @(Get-ChildItem -LiteralPath (Join-Path $ownership 'receipts') -Force -ErrorAction SilentlyContinue)
      foreach ($file in $receipts) {
        $record = try { Get-Content -LiteralPath $file.FullName -Raw | ConvertFrom-Json } catch { $null }
        $state = if ($record) { "$($record.role) $($record.state) boot $($record.boot_id)" } else { 'unreadable' }
        $facts += "receipt $($file.Name): $state"
      }
    } catch { $facts += "facts not captured: $($_.Exception.Message)" }
    if ($Verdict) {
      $resources = Join-Path $inst 'resources'
      $probe = "import sys; sys.path.insert(0, sys.argv[1]); import ownership as o; " +
        "p = o.ownership_paths('nsis'); fd = o._open(p); o._lock(fd, exclusive=True); o._close(fd); print('lease free')"
      $captures = @(
        @('receipts verdict', @('-I', '-B', "`"$(Join-Path $resources 'ownership.py')`"", 'receipts', '--kind', 'nsis')),
        @('lease', @('-I', '-B', '-c', "`"$probe`"", "`"$resources`"")))
      foreach ($capture in $captures) {
        $log = Join-Path $env:TEMP "odin-install-facts-$([guid]::NewGuid().ToString('N'))"
        try {
          $code = Run $python $capture[1] 1 @{
            NoNewWindow = $true; RedirectStandardOutput = "$log.out"; RedirectStandardError = "$log.err" }
          # stdout whole, and stderr's last line: a refusal's message, or a traceback's exception.
          $lines = @(Get-Content -LiteralPath "$log.out" -ErrorAction SilentlyContinue) +
            @(Get-Content -LiteralPath "$log.err" -ErrorAction SilentlyContinue | Select-Object -Last 1)
          $facts += ("$($capture[0]): exit $code " + (($lines -join ' ') -replace '\s+', ' ')).Trim()
        } catch {
          $facts += "$($capture[0]): not captured ($($_.Exception.Message))"
        } finally {
          Remove-Item -LiteralPath "$log.out", "$log.err" -ErrorAction SilentlyContinue
        }
      }
    }
    $facts -join '; '
  }
  $up = Serve
  $running = (& $installed).Count
  $code = Install @('/S')
  Check 'an install over the running app is refused, and Odin keeps running' ($up -and $code -eq 2 -and
    (& $serving) -and (& $installed).Count -ge $running -and -not (Test-Path $marker)) "exit $code"
  # In place (_?=) so the exit code is the uninstaller's own, not its relaunching copy's.
  $code = Run $uninstaller @('/S', "_?=$inst") 10
  Check 'an uninstall while Odin runs is refused, and Odin keeps running' ($code -eq 2 -and (& $serving) -and
    (Test-Path $exe)) "exit $code"
  ExitOdin
  # The lifetime the refusals ran beside must end clean too. The guardian finishes a lifetime only when the app's and
  # the core's cleanup journals were both written during it and both say clean, and it keeps no record of a refusal.
  # So a failure carries both journals and their write times beside the receipts', which says which condition failed,
  # and the installed guardian's verdict, which says what a replacement would meet.
  $unresolved = @(SettledLifetimes)
  $exitDetail = $unresolved -join ', '
  if ($unresolved.Count) {
    $lifetimeFacts = @(Get-ChildItem -LiteralPath $receiptsDir -Force -ErrorAction SilentlyContinue | ForEach-Object {
      "$($_.Name) written $($_.LastWriteTimeUtc.ToString('o'))" })
    foreach ($journal in (Join-Path $profileRoot 'default-cleanup-state.json'),
        (Join-Path $profileRoot 'data\resource-cleanup.json')) {
      $item = Get-Item -LiteralPath $journal -Force -ErrorAction SilentlyContinue
      $written = if ($item) { $item.LastWriteTimeUtc.ToString('o') } else { 'absent' }
      $text = Get-Content -LiteralPath $journal -Raw -ErrorAction SilentlyContinue
      $lifetimeFacts += "$(Split-Path $journal -Leaf) written ${written}: $text"
    }
    $exitDetail += " | $($lifetimeFacts -join ' | ') | $(InstallFacts -Verdict)"
  }
  Check 'Exit after the refused install and uninstall leaves every lifetime clean' ($unresolved.Count -eq 0) $exitDetail

  # A process from this installation that holds no lease (an app started outside it): refused too, never ended.
  $stray = Start-Process -FilePath (Join-Path $inst 'resources\runtime\python\python.exe') -PassThru `
    -ArgumentList '-I', '-S', '-c', "__import__('time').sleep(300)" -WindowStyle Hidden
  Start-Sleep -Seconds 2
  $code = Install @('/S')
  Check 'an install while a process from this installation runs without the lease is refused, ending nothing' (
    $code -eq 2 -and -not $stray.HasExited -and -not (Test-Path $marker)) "exit $code"
  # A damaged installation without Odin.exe, its runtime still running: found all the same.
  $moved = "$exe.acceptance-moved"
  Move-Item -LiteralPath $exe -Destination $moved
  $code = Install @('/S')
  $absent = -not (Test-Path $exe)
  Move-Item -LiteralPath $moved -Destination $exe -Force
  Check 'with Odin.exe missing, a process still running from the installation refuses the install' (
    $code -eq 2 -and $absent -and -not $stray.HasExited -and -not (Test-Path $marker)) "exit $code"
  $code = Run $uninstaller @('/S', "_?=$inst") 10
  Check 'an uninstall while that process runs is refused, ending nothing' ($code -eq 2 -and -not $stray.HasExited -and
    (Test-Path $exe) -and -not (Test-Path $marker)) "exit $code"
  Stop-Process -Id $stray.Id -Force -ErrorAction SilentlyContinue
  $stray.WaitForExit(10000) | Out-Null

  # An installer run that never finished leaves its fence: Odin refuses to start until a run completes.
  $beforeFence = InstallFacts
  Set-Content -LiteralPath $marker -Value '{"operation": "install", "version": 1}' -Encoding ascii
  Start-Process -FilePath $exe -ArgumentList '--hidden' | Out-Null
  $deadline = (Get-Date).AddSeconds(45)
  while ((Get-Date) -lt $deadline -and -not (& $serving)) { Start-Sleep -Seconds 2 }
  $guardians = @(Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like '*ownership.py*hold*' })
  Check 'an unfinished installer run fences the start' (-not (& $serving) -and $guardians.Count -eq 0) (
    "guardians left: $($guardians.Count)")
  # The refused app waits on its error box; it's this test's own process. The installer runs next, so it waits
  # until the app is gone: a process still being torn down counts as Odin running (exit 2).
  StopAndWait (& $installed)
  $beforeInstall = InstallFacts
  $code = Install @('/S')
  Check 'running the installer again completes the transaction' ($code -eq 0 -and -not (Test-Path $marker)) (
    "exit $code" + $(if ($code -ne 0) { " | before the fence: $beforeFence | before this install: $beforeInstall" +
      " | after it: $(InstallFacts -Verdict)" } else { '' }))
  Check 'and Odin starts again' (Serve) ''
  ExitOdin

  # This boot's lifetimes must have ended clean; an earlier boot's no longer fence.
  $boot = & $python -I -B -c 'from src.desktop.platform import win32; print(win32.boot_identifier())'
  $crashed = Join-Path $ownership 'receipts\acceptance-crashed-core.json'
  foreach ($case in @(@($boot, 2, 'this boot''s unconfirmed lifetime refuses the install'),
                      @('00000000-0000-4000-8000-000000000001', 0, 'an earlier boot''s no longer fences it'))) {
    Set-Content -LiteralPath $crashed -Encoding ascii -Value ('{"boot_id": "' + $case[0] +
      '", "role": "core", "state": "running", "uid": "' + $me + '", "version": 1}')
    $code = Install @('/S')
    Check "receipts: $($case[2])" ($code -eq $case[1] -and -not (Test-Path $marker)) "exit $code, boot $($case[0])"
  }
  Remove-Item -LiteralPath $crashed -ErrorAction SilentlyContinue
  # An interrupted receipt write's leftover (the publish primitive's ".<name>.<32 hex>.tmp", cut off mid-write) was
  # never a receipt, so it doesn't fence. A damaged receipt does: a restart wouldn't change it.
  $leftover = Join-Path $ownership "receipts\.acceptance-app.json.$([guid]::NewGuid().ToString('N')).tmp"
  $damaged = Join-Path $ownership 'receipts\acceptance-damaged.json'
  foreach ($case in @(@($leftover, 0, 'an interrupted write''s leftover doesn''t fence the install'),
                      @($damaged, 2, 'a damaged receipt refuses the install'))) {
    Set-Content -LiteralPath $case[0] -Encoding ascii -Value '{"boot_id": "'
    $code = Install @('/S')
    Check "receipts: $($case[2])" ($code -eq $case[1] -and -not (Test-Path $marker)) "exit $code"
    Remove-Item -LiteralPath $case[0] -ErrorAction SilentlyContinue
  }

  # The lease must be an ordinary file of its own: a hard link (as any link or redirect) is refused, changing nothing.
  # The next run creates a real one again.
  $lease = Join-Path $ownership 'lease'
  $linked = Join-Path $ownership 'acceptance-link-target'
  Remove-Item -LiteralPath $lease -Force
  Set-Content -LiteralPath $linked -Value 'not the lease' -Encoding ascii
  New-Item -ItemType HardLink -Path $lease -Target $linked | Out-Null
  $code = Install @('/S')
  Check 'a lease that is a link is refused, changing nothing' ($code -eq 2 -and -not (Test-Path $marker) -and
    (Test-Path $exe)) "exit $code"
  Remove-Item -LiteralPath $lease, $linked -Force

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
  # A fence the installer can't remove (here a handle that refuses deletion, after the uninstall above left its
  # marker) fails the run instead of reporting success, since Odin wouldn't start. Released, the next run clears it.
  $hold = [System.IO.File]::Open($marker, 'OpenOrCreate', 'Read', 'ReadWrite')
  try {
    $code = Install @('/S')
    $kept = Test-Path $marker
  } finally {
    $hold.Dispose()
  }
  Check 'a fence the installer can''t remove fails the install instead of reporting success' (
    $code -eq 2 -and $kept -and (Test-Path $exe)) "exit $code"
  $code = Install @('/S')
  Check 'released, the next install completes and clears it' ($code -eq 0 -and -not (Test-Path $marker)) "exit $code"
  Uninstall
  # In place (_?=), as an upgrade runs the old uninstaller: its own image isn't Odin running.
  $code = Install @('/S')
  $removed = Run $uninstaller @('/S', "_?=$inst") 10
  Check 'an uninstall in place does not count itself as Odin running' ($code -eq 0 -and $removed -eq 0 -and
    -not (Test-Path $exe) -and -not (Test-Path $installKey)) "install $code, uninstall $removed"
  # In place it can't delete its own file.
  Remove-Item -LiteralPath $inst -Recurse -Force -ErrorAction SilentlyContinue
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
if ($Publisher) {
  $signed = SignedBy $Installer
  Check 'the installer is validly signed by the expected publisher, with a timestamp' $signed.ok (
    "$($signed.detail), certificate $($signed.thumbprint)")
  if ($signed.ok) { $SignerThumbprint = $signed.thumbprint }
}
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
if ($Publisher) { $arguments += " -Publisher `"$Publisher`"" }
$process = Start-Process powershell.exe -Credential $credential -LoadUserProfile -ArgumentList $arguments `
  -WorkingDirectory $work -PassThru
$null = $process.Handle
# Bounded, well inside the job's own limit, so a run that hangs still ends in a report: its progress file names
# the last checks it made. Then nothing of the disposable user may still run: a process left behind is named, then
# ended, before the account goes.
$finished = $process.WaitForExit(40 * 60000)
# A process that is just ending (its console host) gets a few seconds; one still there after that has stayed.
$deadline = (Get-Date).AddSeconds(15)
do {
  $left = @(Get-CimInstance Win32_Process | Where-Object {
    $owner = Invoke-CimMethod -InputObject $_ -MethodName GetOwner -ErrorAction SilentlyContinue
    $owner -and $owner.User -eq $name })
  if (-not $left.Count -or -not $finished) { break }
  Start-Sleep -Seconds 1
} while ((Get-Date) -lt $deadline)
if (-not $finished) {
  $last = (Get-Content -LiteralPath "$userReport.progress" -Tail 3 -ErrorAction SilentlyContinue) -join ' / '
  Check 'the standard user''s run finished within 40 minutes' $false "its last checks: $last"
}
Check 'no process of the disposable user outlives its run' ($left.Count -eq 0) (
  ($left | ForEach-Object { "$($_.Name) $($_.ProcessId): $($_.CommandLine)" }) -join ' | ')
StopAndWait $left
$result = Get-Content -LiteralPath $userReport -Raw -ErrorAction SilentlyContinue | ConvertFrom-Json
if ($null -eq $result) {
  Check 'the standard user''s cases ran' $false "exit $(if ($finished) { $process.ExitCode } else { 'none' }), no report"
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
