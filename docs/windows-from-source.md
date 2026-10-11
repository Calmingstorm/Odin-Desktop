# Odin Desktop on Windows, from source

This runs the app and its engine straight from a checkout on Windows 11. It is the private test build of the Windows
port: there is no installer, no bundled runtime and no signing yet. Those come with the packaged app.

## What you need
- Windows 11 x64. Windows PowerShell 5.1, the OpenSSH client and `curl.exe` are already part of it.
- [uv](https://docs.astral.sh/uv/) and Node.js 22.
- A normal (not elevated) PowerShell. Odin Desktop runs as you. Running it elevated, even once, leaves files in your
  temporary folder that Administrators own, and a normal run then can't save settings.

## Set up the checkout
In PowerShell, from the checkout's root:

```powershell
uv sync --locked              # the engine and its dependencies, installed into .venv
cd app
npm.cmd ci                    # npm.cmd: PowerShell's default policy blocks npm's .ps1 shim
npm.cmd run build
```

## Run it
Still in `app`, name the checkout's own engine (Windows has no development stand-in for it), then start Electron:

```powershell
$env:ODIN_DESKTOP_CORE_CMD = '["C:\\path\\to\\checkout\\.venv\\Scripts\\python.exe","-I","-B","-m","src"]'
.\node_modules\electron\dist\electron.exe .
```

The value is a JSON array, so each backslash is doubled. Without it the app stops with a message naming this
variable.

Your profile lives in `%LOCALAPPDATA%\odin-desktop\default`, and the window's own data in
`%LOCALAPPDATA%\odin-desktop\electron`. Exit Odin from the tray icon's menu; closing the window keeps it running in
the tray.

## What works, what needs preparing, what isn't there yet
- **Works:** chat, files and editing (`apply_patch`, `read_file`), commands in Windows PowerShell, background
  processes, scripts, validation checks, MCP servers, SSH to your Linux machines, schedules, knowledge and memory.
- **Needs preparing in a source checkout:**
  - Skills that need extra Python packages: the uv environment has no pip, so add it with
    `.venv\Scripts\python.exe -m ensurepip`.
  - The browser tools: `.venv\Scripts\python.exe -m playwright install chromium`.
  - Search by meaning downloads its model the first time it's used.
- **Not there yet:** computer use (off on Windows), start at login (comes with the installed app), the installer,
  updates and signing.

## If settings won't save
If Odin was ever started elevated, a normal run can't use the lock folder that the elevated run left behind. Exit
Odin, delete `%TEMP%\odin-config-locks-*`, and start it again normally.

## Automated checks
`app\scripts\windows-real-core-smoke.mjs` runs the built app with this checkout's engine and a scripted local model in
a throwaway profile:
- a reply, a harmless local tool turn, and a draft that survives a relaunch;
- then it checks that the app, the engine and anything they started have ended.

It opens the Odin window, so run it in your own desktop session.
