# macOS feasibility (phase 1)

Evidence harnesses for the macOS port, on the `macos/port` branch. They answer two questions before any port code
is written. Nothing here ships: phase 2 re-implements what they prove under `src/`, with the full test, coverage and
ledger gates. The Linux and Windows builds do not use these files.

## Question 1: background-job cleanup
Can a supervisor that starts each job in its own session stop it and say truthfully what is left?

- `darwin_proc.py` reads process facts. Membership comes first: `getsid` over libproc's PID list (Darwin has no
  kernel session filter), then the group from the short BSD info, which also works for other users' processes. A
  process's identity is its unique ID plus its PID version, which changes on exec. A member whose identity cannot be
  read stays a member, never a missing one.
- Signals go to identities, not numbers: `proc_signal_with_audittoken` signals only the process whose PID version
  still matches and refuses a stale one. The one numeric signal is to the leader's own group, whose number is pinned
  because the leader is kept as an unreaped child until the job is released.
- `session_jobs.py` settles a job only after two consecutive rounds in which no member was observed, the watched
  members reported no fork (kqueue), the leader's group had no signallable member, and every other group seen in
  the session was empty. Groups are checked with signal 0, which the kernel answers atomically and which harms no
  one. Anything else, including an unreadable identity or a refused signal, ends as unknown at the deadline, with
  the evidence kept. After release the job has no authority and refuses to observe or signal.
- Limits: a process that detaches into a new session is outside the scope, so a settled result carries "escaped
  descendants are unverified". A process that keeps moving to new groups while forking and exiting faster than the
  scan can also stay unobserved; that is the same "not verified" class. Enumeration is not atomic, so a scan alone
  is never treated as proof of an empty session.
- `test_session_jobs.py` uses harmless stand-ins only (`sleep`, shell background sleeps, small Python snippets that
  fork, change group, detach or hand off a group). It signals only its own processes, by identity.

Run: `python -m pytest -q scripts/macos-feasibility/test_session_jobs.py` (macOS only; skipped elsewhere).

## Question 2: the signed runtime
Do the bundled Python and its compiled packages work under Developer ID signing with the hardened runtime and one
exception (library validation off, for the Python executable only)?

- `runtime-lock.json` pins the python-build-standalone build for Apple Silicon and the two wheels the checks install.
- `stage_runtime.py` stages that interpreter, installs the engine's locked dependencies from `uv.lock` (hash-checked,
  binary wheels only) and the pinned search model, then audits every Mach-O file found by content: each arm64 slice
  must be built for macOS with a known minimum no newer than 26.0, and every library load outside `/usr/lib` and
  `/System/Library` must resolve to a file inside the bundle (run paths come from the binary and the interpreter, an
  approximation of dyld's loader chain).
- `sign_runtime.sh` signs every Mach-O inside-out with a secure timestamp from a disposable keychain, restores the
  keychain search list path for path (a concurrent change is reported, not overwritten), and can submit a
  notarization probe whose result is reported as accepted, rejected, pending or failed, never assumed.
  `entitlements-python.plist` holds the one exception.
- `native_checks.py` runs under the staged or signed interpreter: all imports, a ctypes callback, one embedding with
  the bundled model, sqlite-vec, a compiled wheel installed after signing (the skills path), and the first-use PDF
  reader. With `--control`, a copy of the same build signed without the exception must run, and must refuse that
  wheel for code signing (different Team IDs).

The workflow `.github/workflows/macos-feasibility.yml` runs question 1 and the unsigned half of question 2 on GitHub's
macOS 26 machines. Signing, the signed checks and the notarization probe run on a real Mac, because no signing
material goes to GitHub before the release pipeline exists.
