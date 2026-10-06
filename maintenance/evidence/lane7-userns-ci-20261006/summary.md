# PR54 deterministic short-gates repair

Original PR head: `7d38f9317cd0d46e52045a4bae0df7c774c7b774`.
GitHub reports the actual PR branch as `lane7/ubuntu24-userns`, not the
`fix/ubuntu-userns-sandbox-gate` name supplied in the follow-up request.
This repair stays on the actual PR54 branch, without force or merging main.

Both short-gates jobs in run `37442307845` failed at the same first step:
`Offline lineage and safety drift`. The only reported errors were unledgered
additions `scripts/packaging/ubuntu_userns_driver.py` and
`scripts/packaging/ubuntu_userns_probe.py`. Lint and fixtures had not run.

Added exact-byte pending ledger entries for both unchanged helper files, with
named/hash-pinned offline regression evidence. No checker exemption, test
weakening, disposition change, independent approval, or shipped code change.
New packaging tests verify exact accounting, fail closed on byte drift, keep
review pending, and mock a failed GUI checkpoint to prove collected observations
are retained with one Popen call and no relaunch. No actual native case executes.

Local checks in an isolated fresh checkout with Python 3.12 and locked dev extras:

- Inventory: no errors, `byte-drift-clean-review-pending`, not qualification.
- Lint gate: 7 inherited findings, 0 new findings.
- Phase 2 ownership plan: pass, `planned-not-implemented`.
- Hermetic Cinnamon/GNOME fixtures plus maintenance accounting: **52 passed**,
  restricted PID isolation helper, non-root UID 1003.
- New offline evidence regression: **2 passed**; standalone Ruff check passed.
- Git diff whitespace check passed.

GitHub CI will run on the pushed repair; final result is collected separately in
the external run directory. The original queued full-suites job is not evidence
of either success or failure.

Task1's Ubuntu gate remains **OPEN**. Installed `.deb` GUI sandbox is unproven
after its one-shot timeout/UnknownVizError. Bundled browser enforcing-AppArmor
case passed; FUSE AppImage plain safe-refusal case passed. Native source lifecycle
remains 28 passed and 1 readiness timeout. None was retried here.

Candidate identity remains `d142968a3533c9a930f7e3147ef8cca6c79183e7`, with original
package hashes unchanged in the original manifest. This CI repair changes only
accounting, offline tests, and summaries. Existing candidate evidence is not a
claim that packages were built from the repaired PR head, nor does it close the
unproven installed GUI row.

Raw logs, including artifacts over 100 KB, remain outside Git at
`/mnt/storage/odin-desktop-evidence/lane7-userns-ci-20261006/`; see `artifacts.sha256`.
No VM, desktop/native run, active session change, service operation, or `/opt/odin`
write. Root filesystem free space was 119 GB before the local tests, above 60 GB.
Only this lane's fresh checkout and its venv are cleanup candidates after push.
