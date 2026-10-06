# Task 1 Ubuntu restricted-userns result

Overall gate **OPEN**. Do not merge this as a claim that the installed GUI passed.
See `maintenance/p41-packaging.md` for the exact policy restoration and row results.

Run root: `/mnt/storage/odin-desktop-evidence/lane7-userns-20261006/`.
Candidate source: `d142968a3533c9a930f7e3147ef8cca6c79183e7`.
Base: `ed0069674533c23e70a0302652a2fb76901ff385`.
Both formats freshly built; first build was replaced before any launch to fix
missing postinst AppArmor installation. Exactly one final launch per case.

| Row | Result | Retained evidence |
|---|---|---|
| Installed deb GUI | FAIL timeout/UnknownVizError; sandbox unproven | `guest-proof/deb/` |
| Installed bundled browser | PASS actual sandboxed renderer and screenshot | `guest-proof/browser/` |
| FUSE AppImage | PASS plain refusal, exit 78, actual FUSE and Zenity | `guest-proof/appimage/` |
| App check | PASS 747 | `app-check-final.log` |
| Fixture / real-core smoke | PASS private display | `app-smoke.log`, `app-real-core-smoke.log` |
| Real-core/onboarding | PASS including 6 onboarding rows | `app-real-core-test.log` |
| Accessibility | PASS 15 | `app-a11y.log` |
| Lifecycle E2E | FAIL 1, PASS 28; core connecting timeout | `app-e2e.log` |
| Packaging ordinary owner | PASS 109 run, 22 skips | `packaging-tests-final-nonroot.log` |
| Root-only profile hooks / preflight fixtures | PASS 21 / 9 | `deb-hooks-tests-root.log`, `preflight-tests-root.log` |
| Applicable engine resources | PASS 21, isolated PID namespace | `engine-targeted-final.log` |

Preliminary failures remain: `engine-targeted.log` cannot import inherited
`src.config.package_migrations`; `engine-targeted-applicable.log` has four inherited
computer-packaging failures because upstream nfpm files/extras are absent. Those
tests were not edited. `packaging-tests-final.log` was incorrectly run as real root:
21 ordinary-owner replacement rows rightly refused root. Correct final ordinary-
owner gate and separately selected root-only fixtures are reported above.
Initial candidate validation failed absent profile. Final exact profiles and
actual unprofiled namespace denial passed validation. One dpkg validation command
had a show-format expansion error, corrected without package or case replay.
Guest service/config/install validation was performed after each change.

Initial guest state was not stock restricted-policy state: sysctl 0, no AppArmor
tools, service inactive. Distro AppArmor packages installed in guest only, both
restrictions set 1, enforcing `unprivileged_userns` confirmed. Installed exception
profiles are intentionally unconfined plus userns, not application-confinement
profiles. No sandbox-off switches or host-policy changes.

Failed GUI row did not save its collected process witnesses before asserting;
no Electron proof is reconstructed. Probe now persists observations before final
assertions for future operators, but was **not rerun**. GUI handshake/core log alone
does not qualify rendering/sandbox success. Browser screenshot and renderer proof
are genuine. Zenity command/text is evidence of native dialog invocation, not
pixel/readability/Orca speech proof. AppImage is conservatively refused, not tried
unsafely and then recovered.

No host install, live service action, active desktop input, other VM start,
Task 2 run, release, or merge. Host `/` remained above 60 GB free (120 GB at final
VM stop). Own disposable checkout is removed only after push; candidates and raw
evidence remain. `post-stop-vms.csv` confirms all odq VMs stopped.
