# macOS feasibility (phase 1)

Evidence harnesses for the macOS port, on the `macos/port` branch. They answer two questions before any port code
is written. Nothing here ships: phase 2 re-implements what they prove under `src/`, with the full test, coverage and
ledger gates. The Linux and Windows builds do not use these files.

## Question 1: background-job cleanup
Can a supervisor that starts each job in its own session stop it and say truthfully what is left?

- `darwin_proc.py` reads process facts. Membership comes first: `getsid` over libproc's PID list (Darwin has no
  kernel session filter), then the group from the short BSD info, which also works for other users' processes. A
  process's identity is its unique ID plus its PID version, which changes on exec. Each record is bracketed by two
  identity reads and kept only when both name the same process, so a reused PID never inherits a member's session.
  A member whose identity cannot be read stays a member, never a missing one.
- Signals go to identities, not numbers: `proc_signal_with_audittoken` signals only the process whose PID version
  still matches and refuses a stale one. The one numeric signal is to the leader's own group, whose number is pinned
  because the leader is kept as an unreaped child until the job is released.
- `session_jobs.py` reports convergence, not proof. "settled" means two consecutive rounds in which no member was
  observed, the watched members reported no fork (kqueue), the leader's group had no signallable member, and every
  other group seen in the session was empty under signal 0 (which harms no one). Anything else, including an
  unreadable identity, a refused signal, a failed check or a passed deadline, ends as unknown with the evidence
  kept. After release the job has no authority and refuses to observe or signal.
- Limits: nothing on macOS shows a session's members atomically. The PID list is a snapshot inspected later, and
  the kernel's group signal also snapshots member PIDs before looking each one up, so a process that forks and
  exits faster than these checks, in any group including the leader's, or in a group never observed, can survive a
  settled result. macOS offers no unprivileged way to rule that out. A process that detaches into a new session is
  outside the scope; a settled result carries "escaped descendants are unverified".
- `test_session_jobs.py` uses harmless stand-ins only (`sleep`, shell background sleeps, small Python snippets that
  fork, change group, detach or hand off a group). It signals only its own processes, by identity.

Run: `python -m pytest -q scripts/macos-feasibility/test_session_jobs.py` (macOS only; skipped elsewhere).

## Question 2: the signed runtime
Do the bundled Python and its compiled packages work under Developer ID signing with the hardened runtime and one
exception (library validation off, for the Python executable only)?

- `runtime-lock.json` pins the python-build-standalone build for Apple Silicon and the two wheels the checks install.
- `stage_runtime.py` stages that interpreter, installs the engine's locked dependencies from `uv.lock` (hash-checked,
  binary wheels only) and the pinned search model, then audits every Mach-O file found by content: each arm64 slice
  must be built for macOS with a known minimum no newer than 26.0, and for each library load outside `/usr/lib` and
  `/System/Library` the first existing candidate in search order (the binary's run paths, then the interpreter's,
  each expanded against the image that declared it) must be inside the bundle. That approximates dyld's loader
  chain; it is not a full dependency-closure proof, which belongs to the packaged-app checks.
- `sign_runtime.sh` signs every Mach-O inside-out with a secure timestamp from a disposable keychain. codesign needs
  that keychain in the user search list, and setting the list replaces it, so the script is for an isolated signing
  environment (a hosted runner or a dedicated account), not an owner's everyday session. It reports every cleanup
  failure. Its notarization probe reports accepted, rejected or pending only from Apple's explicit status; anything
  else is reported as unknown or failed. `entitlements-python.plist` holds the one exception.
- `native_checks.py` runs under the staged or signed interpreter: all imports, a ctypes callback, one embedding with
  the bundled model, sqlite-vec, a compiled wheel installed after signing (the skills path), and the first-use PDF
  reader. With `--control`, a copy of the same build signed without the exception must run, and must refuse that
  wheel for code signing (different Team IDs).

The workflow `.github/workflows/macos-feasibility.yml` runs question 1 and the unsigned half of question 2 on GitHub's
macOS 26 machines. Signing, the signed checks and the notarization probe run on a real Mac, because no signing
material goes to GitHub before the release pipeline exists.
