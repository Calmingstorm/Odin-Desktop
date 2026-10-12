# Windows phase 3c: PR #135 review round 2

Base: `b111735897b1f1d06ef6f4c5885dc0d92bbb0142`, branch
`windows/phase3c-safety`. Changes await independent review.

## Counterparts and regression coverage

- Winget `remove` and `rm` rate HIGH like `uninstall`, only in the command's
  first verb slot. Search/show/list arguments and similarly named verbs do not
  become removal operations.
- Start-Service, native Service Control `start` (including a remote server),
  and `net`/`net1 start <service>` rate MEDIUM. Bare `net start` lists services
  and stays LOW. Bare PowerShell `sc` remains Set-Content; a regression asserts
  its file/registry reason, not merely the coincidentally equal MEDIUM level.
- Set-, Disable-, Enable-, Rename-LocalUser, Remove-LocalGroupMember, and
  Set-/Rename-LocalGroup rate MEDIUM. Named `net user` mutation switches rate
  MEDIUM. Password/deletion rules still win at HIGH; `/add` retains MEDIUM;
  listing, named queries, `/domain`, `/help` and `/?` alone remain LOW.
- Msiexec accepts the dash counterpart of the slash uninstall recognizer:
  short `x` with a separate or attached operand, and exact `uninstall`.
  MSI properties, logging `x`, install operands, quoted output and comments do
  not become removal. This remains a bounded offline recognizer, not a complete
  Windows Installer argv parser or proof that an installation would succeed.

All 76 new cases only classify strings. The native Windows test module imports
the same five parametrized groups. No dangerous fixture was executed.

## Msiexec syntax evidence

Knowledge search was performed first and produced no useful Installer evidence.
Retained research is in
`/home/odin/reviews/desktop-windows/phase3c-r2-research/`.

1. Microsoft Learn, [Command-Line Options](https://learn.microsoft.com/en-us/windows/win32/msi/command-line-options):
   the `/m` entry explicitly names “install (-i), remove (-x), administrative
   installation (-a), or reinstall (-f) options.” Thus `-x` has direct official
   documentation, not an inference from PowerShell conventions. The option table
   defines `/x` as uninstall and says options are case-insensitive.
2. Microsoft Learn, [Standard Installer options](https://learn.microsoft.com/en-us/windows/win32/msi/standard-installer-command-line-options):
   `/uninstall` is equivalent to `/x` for products. This document itself does not
   explicitly promise `-uninstall`.
3. Substantive compatibility evidence for `-uninstall`:
   [Wine msiexec.c at 6265f77003e2d501a83e8a1780b5e78ad55b230f](https://github.com/wine-mirror/wine/blob/6265f77003e2d501a83e8a1780b5e78ad55b230f/programs/msiexec/msiexec.c).
   `msi_option_equal` and `msi_option_prefix` both accept `/` or `-`; the uninstall
   branch uses prefix `x` or exact `uninstall`, then appends `REMOVE=ALL`.
   This is inspected compatibility implementation evidence, not native Windows
   execution qualification. No Installer executable was launched.

Research SHA-256:

| Retained file | SHA-256 |
|---|---|
| msiexec-command-line-options.md | `60ec687754e8ea0c0c7ae394be3291490cdc2113320ca2f30027c899fc95d489` |
| msiexec-standard-options.md | `4e629a9598e67d3f420b38d0e3821ebdc8ed6e75d48cd99eaae99021fae9069c` |
| wine-msiexec.c | `d2efd8f64d11b5fdf0989845add8d445b87883de5685593cbe1ffeca478e09f8` |

## Observed validation

All pytest invocations used `scripts/run-phase1-tests.py` as unprivileged `odin`,
the restricted PID-isolation helper, and throwaway HOME/XDG state.

- Final focused classifier/platform/owner/D17/policy-floor selection: **804
  passed** in 19.82 seconds. Classifier coverage: **392/402 statements, 97.5124%**,
  ten missing. Retained `phase3c-r2-focused-clean.log`,
  `phase3c-r2-final-coverage.json` under `/home/odin/reviews/desktop-windows/`;
  focused JUnit XML (over 100KB) is retained outside Git at
  `/mnt/storage/odin-desktop-evidence/phase3c-review-r2-20261011/focused.xml`.
- Maintenance/inventory/lint/D19/closure/fresh-profile checker tests: **190
  passed** in 130.08 seconds, retained `phase3c-r2-record-tests.log` and XML.
- Native module collection on Linux: **76 skipped, 393 deselected**, with the
  explicit native-Windows routing reason, retained `phase3c-r2-native-collection.log`
  and XML. This verifies registration only; no fresh native pass is claimed.
- Focused Ruff and `git diff --check` passed.
- An expanded raw historical safety selection was also attempted: **1162 passed,
  65 failed**. All failures were in unchanged `test_risk_classifier.py` (8) and
  `test_git_force_push_governor.py` (57). An isolated clean-base reproduction
  returned **358 passed, the same 65 failed node IDs**. They include removed
  historical web/handler surfaces. No test/source was edited to conceal them.
  The expanded attempt is not claimed green. Its raw logs, each over 100KB, are
  outside Git at `/mnt/storage/odin-desktop-evidence/phase3c-review-r2-20261011/`.

## Invariants and limits

The shared Linux classifier, executor, platform variant route and variant-source
pin are byte-unchanged against the base. The exact lifted governor test passed.
No governor semantics, session/archive code, PR #137 fix, app launch, installed
profile, active desktop, service or `/opt` installation was changed. No full heavy
suite, native Windows run, packaged-release
qualification or hardware acceptance is claimed. Root disk remained above 159GB
free, well beyond the requested 60GB floor.

Final static report gates: D19 errors `[]`; lint has 7 inherited findings and no
new findings; fresh-profile parity is valid/pass with 43 deltas and no errors;
closure reports errors `[]` and `ready: true`. Final inventory has errors `[]`
and gate `byte-drift-clean-review-pending`. Initial hand-transcribed byte-patch
records failed validation; the two malformed fields were regenerated using the
repository inventory generator, with source hashes and byte reconstruction
verified before a fresh inventory pass. Complete prior rows remain preserved
under `previous_review_record`. Native-test record, parity hash and current-only
executor/variant test seals were verified. Independent approval remains pending.
The inventory and
closure reports are retained as `phase3c-r2-inventory.json` and
`phase3c-r2-closure.json` under `/home/odin/reviews/desktop-windows/`.
