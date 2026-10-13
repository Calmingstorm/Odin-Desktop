# macOS feasibility (phase 1)

Evidence harnesses for the macOS port, on the `macos/port` branch. They answer two questions before any port code
is written. Nothing here ships: phase 2 re-implements what they prove under `src/`, with the full test, coverage and
ledger gates. The Linux and Windows builds do not use these files.

## Question 1: background-job cleanup
Can a supervisor that starts each job in its own session start, observe, stop and settle jobs safely on macOS?

- `darwin_proc.py` reads process facts through public interfaces: libproc (`proc_listallpids`,
  `proc_pidinfo`), `getsid`, the kernel's process-group filter, and kqueue exit notifications.
- `session_jobs.py` is the prototype supervisor. The job's first process stays an unreaped child until the job is
  released, so its PID, and with it the session and group IDs, cannot be reused while signals are sent. Other groups
  in the session are signalled only after a live member's identity (PID plus start time) is re-checked.
- `test_session_jobs.py` uses harmless stand-ins only (`sleep`, shell background sleeps, small Python snippets that
  fork, change group or detach). Pass criteria: every case passes, a settled result always carries "escaped
  descendants are unverified", and a failed or incomplete observation is reported as unknown, never as empty.

Run: `python -m pytest -q scripts/macos-feasibility/test_session_jobs.py` (macOS only; skipped elsewhere).

## Question 2: the signed runtime
Do the bundled Python and its compiled packages work under Developer ID signing with the hardened runtime and one
exception (library validation off, for the Python executable only)?

- `runtime-lock.json` pins the python-build-standalone build for Apple Silicon and the two wheels the checks install.
- `stage_runtime.py` stages that interpreter, installs the engine's locked dependencies from `uv.lock` (hash-checked,
  binary wheels only) and the pinned search model, then audits every Mach-O file: an arm64 slice, a minimum macOS no
  newer than 26.0, and no library loads from outside the system or the bundle.
- `sign_runtime.sh` signs every Mach-O inside-out with a secure timestamp, using a disposable keychain, and can submit
  a notarization probe. `entitlements-python.plist` holds the one exception.
- `native_checks.py` runs under the staged or signed interpreter: all imports, a ctypes callback, one embedding with
  the bundled model, sqlite-vec, a compiled wheel installed after signing (the skills path), and the first-use PDF
  reader. With `--control`, the same skills-path load must fail under a copy signed without the exception.

The workflow `.github/workflows/macos-feasibility.yml` runs question 1 and the unsigned half of question 2 on GitHub's
macOS 26 machines. Signing, the signed checks and the notarization probe run on a real Mac, because no signing
material goes to GitHub before the release pipeline exists.
