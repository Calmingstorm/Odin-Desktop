# Linux v1 release checklist

**P4.4 updated user docs. No release authorization.** Documentation watermark:
Desktop main `aa3d61b3043ea47805686c185133a53c54b127fc`, 2026-10-07.
This checklist does not assert that P4.5 or P4.6 has passed, authorize a tag,
install/run on the active desktop, or approve publication. Leave items open until
the reviewer records evidence and the required owner approvals. Earlier candidate
passes do not transfer to different bytes.

Authority: [approved work order P4.4/P4.5/P4.6 and section 6](../work/phase-3-app-v1.md#4-phase-4-steps).
Aaron's work-order approval permits the early isolated candidate lane, **not
publication**. `CONTRIBUTING.md` remains binding. The repository stays private
unless Aaron explicitly approves a visibility change.

## Candidate identity and source review

- [ ] Record final Desktop source SHA, workflow SHA, product version, dependency
  locks, build environment and candidate run identity. Do not reuse this draft's
  watermark as the final build identity.
- [ ] Record both x86-64 `.deb` and AppImage names, sizes, SHA-256 hashes,
  resource-manifest digest and build/provenance receipt. Distinguish download,
  extracted resource and installed sizes; measure disk/memory requirements and
  actual supported glibc/CPU/sandbox/helper floors rather than publishing estimates.
- [ ] Reconcile the reviewed upstream watermark through a pinned Odin commit.
  Current [baseline record](../../maintenance/baseline.md) is `v4.13.0`,
  `cd7530906e9cfa10a0fa900247d7ce2a8bb33e25`, **baseline only**. Review ports,
  outstanding critical fixes, safety drift, exact model-facing D19 approvals and
  corpus accounting. Test totals are not an identical-engine claim.
- [ ] Independently review source/resource/reference/catalog scans, removed-feature
  closure, dependency findings and license/provenance notices. Resolve or explicitly
  disposition the recorded locked npm findings (ten high, one critical) against
  the exact release candidate; this unresolved triage blocks the release gate.
  Do not hide it behind a green smoke test or run a blind audit fix. Product
  distribution license remains Aaron's decision.

Sources: [maintenance policy](../design/maintenance.md),
[builder/resource layout](../../app/packaging/README.md),
[existing candidate evidence](../../maintenance/p41-packaging.md).

## Prerequisite closure and P4.4 procedure validation

- [ ] Phase 2 exit, P3.1 to P3.5 and P3.6/D11 closure are evidenced, with exact
  inherited-case accounting, D19/host parity and no unexplained safety divergence.
  Pending integrations are not shipped just because this guide mentions them.
- [ ] D11 rows use identified x86-64 candidates in isolated Mint 22 Cinnamon/X11,
  Ubuntu 24.04-base GNOME/Wayland, KDE/Wayland and Hyprland environments. Record
  distro/kernel/compositor/portal/GPU/driver/helper versions and limitations.
  One heavy VM at a time; Xvfb/container tests do not substitute for native rows.
- [ ] Prove stock Ubuntu restricted-user-namespace startup and actual FUSE-mounted
  AppImage behavior, retaining the sandbox. No `--no-sandbox`, policy weakening or
  active-desktop input to fill missing evidence.
- [ ] Have a tester follow the user docs on the exact isolated candidates: fresh
  install, first run/provider sign-in and keyring Retry, no-tray reopen/Exit,
  opt-in startup, keyboard/Orca, conversations/results, privacy, unknown/recovery,
  updates and uninstall retention. Record outcomes and limits, not prose-wording
  assertions. Real provider acceptance requires a separately authorized test account.
- [ ] Check links and generated metadata as data. Do not take screenshots containing
  credentials, login codes or private history. Evidence must include source/artifact
  identities, commands/environment, cases/results, logs and cleanup receipts.

Source: [P3.6, P4.4 and R4/CC inventory](../work/phase-3-app-v1.md#p36-d11-matrix-and-phase-3-closure).

### Ready-to-run user procedures, not newly executed

**pending: #59 / #97**: the P4.4 walkthrough needs identified isolated candidates.
At the 2026-10-07 documentation update, `/run/odq-lab.lock/owner` was
`p33 2026-10-07T16:26:57Z GNOME missing rows req-7747a619` and only
`odq-gnome` was running. No lock acquisition, VM changes or native tests by
this documentation lane. Acquire the shared lock only when free and confirm
all other lab VMs are stopped before testing one guest.

For each procedure record candidate SHA-256, source/workflow identity, desktop,
versions, actual outcomes and sanitized logs; stop only owned resources and
retain cleanup receipts. Keep these unchecked until a tester follows them:

- [ ] **Install/first run:** follow [Install](../user/install.md) and
  [First run](../user/first-run.md) as an ordinary guest user. Inspect actual
  provider readiness and keyring failure/Retry. Do not invent a provider response;
  a real login needs a separately authorized account, and no code/key screenshots.
- [ ] **Manual/no-tray/login launch:** confirm manual first-window visibility,
  Close then launcher reopen, window/menu/Ctrl+Q/launcher Exit and opt-in hidden
  start at login with one core. GNOME no-tray controls/notice remain **pending: #59**.
- [ ] **Session end:** shutdown, reboot and logout request bounded Exit; cancelling
  a logout query keeps the app alive. Query/cancel native acceptance remains
  **pending: #59**. Exit during initial core startup is merged (#96): it waits up to
  five seconds for a starting core; record any remaining unknown truthfully.
- [ ] **Work/D12/results:** follow [Background work](../user/background-work.md)
  and [Chat/results](../user/chat-and-results.md). Read original-owner controls,
  paged stored reports and retained output; suspend/wake for one catch-up reminder
  and no automatic missed check/workflow, then Exit and verify no local scheduling.
- [ ] **Keyboard/privacy** (Orca optional, Decision G): follow [Accessibility](../user/accessibility.md)
  with harmless content, native Attach/Save, notification preview settings and
  explicit destinations. Raven evidence is Cinnamon 7/7, GNOME 7/7, KDE 6/7;
  KDE chooser accessibility still needs Aaron's disposition, not a silent pass.
- [ ] **Recovery/update/remove:** follow [Recovery](../user/recovery.md),
  [Updates](../user/updates.md) and [Uninstall](../user/install.md#uninstall-without-losing-recovery-records).
  In disposable guest state, verify refusal while running leaves the package
  installed, unclean-end refusal gives the restart message, and valid older-boot
  ownership permits replacement after restart without erasing evidence/quarantine.
  Different-version upgrade remains **pending: #59**.
- [ ] **Notifications:** real desktop appearance and click opens the right
  conversation/message; daemon acceptance alone is insufficient. **pending: #59**.

**pending: #97**: complete D11/Phase 3 matrix and closure on immutable bytes.
**pending: #98**: P3.5 native receiver/loss,
release, quarantine and helper qualification. Never substitute the historical
sleep/wake or Orca candidate observations for these final-candidate rows.

### Ownership and upgrade evidence

The ownership/compatibility implementation (#36) is merged. Its earlier evidence
does not substitute for final-candidate acceptance below.

- [ ] Repeat fresh install/ordinary-user launch,
  clean Exit, package-manager `.deb` replacement/removal and user-managed AppImage
  same-path replacement on final hashes.
- [ ] Include busy/surviving-core and interrupted-transaction fences, incompatible
  protocol/storage/checkpoint refusal before writes, durable backups/migrations,
  pending/failed startup, and older-reader refusal. No blind old executable over
  an upgraded profile, automatic state rollback or receipt/quarantine deletion.
- [ ] Keep the legacy P4.1 direct-upgrade refusal visible. Its externally fenced
  disposable-guest transition is not a workstation chmod recipe.
- [ ] Recheck alongside isolation with a disposable second installation's data,
  credential fixtures, locks, endpoints and harmless process sentinels, never the
  real standalone install. Verify remove/purge keeps per-user state/keyring and
  retained package ownership evidence. Package hooks must not signal services.
- [ ] Recheck FUSE/native AppImage lifetime, stable autostart path and relocation
  stale-command behavior. Container and old-inode tests are not FUSE qualification.

Sources in the integrated main tree: [P4.2 evidence/open gates](../../maintenance/phase4-packaging.md),
[compatibility/backup implementation](../../src/desktop/package_state.py),
[manual AppImage helper boundaries](../../app/packaging/APPIMAGE-REPLACEMENT.md).
Exact source identities are recorded in [P4.4 validation](../../maintenance/p44-user-docs-validation.md).

### Notice and non-publishing release rehearsal

The notice/workflow implementation (#39) is merged. The remaining items are
external protections, non-publishing rehearsal and exact-candidate acceptance,
not a pending manual-check feature.

- [ ] Independently review the integrated notice/workflow implementation. Rehearse
  both real formats with the reviewed non-publishing entrypoint; identify local
  rehearsal separately from actual Actions evidence. No fabricated run/artifact IDs.
- [ ] Test manual opt-in checking, initial Not checked, private-repo Can't check,
  denied/offline/rate-limited/malformed/incomplete responses, stable comparison,
  draft/prerelease filtering and validated fixed-repository links. Prove checks
  and opening a page do not download/install/write executables, restart work,
  replay effects or clear quarantine. No app token/browser-cookie import.
- [ ] Match curated release notes, product/tag/package/ASAR versions and provenance
  to exact candidate hashes. Hashes are integrity/provenance data, not signatures;
  assets remain unsigned. No custom feed, signing-key custody or in-app apply gate.
- [ ] Independently configure/audit required external tag/runner restrictions and
  protected `odin-desktop-release` environment before enabling publication. Pending
  evidence says protection is not installed by this lane. YAML/approval-link shape
  alone does not prove owner authorization or actual gate completion.
- [ ] Verify prospective publication uses the **same retained bytes** approved at
  P4.5/P4.6, not a rebuild. Check source/workflow/run/artifact provenance and current
  trusted workflow identity. Moving main or rebuilding reopens affected approvals.

Integrated sources: [workflow record and missing external protection](https://github.com/Calmingstorm/Odin-Desktop/blob/aa3d61b3043ea47805686c185133a53c54b127fc/maintenance/phase4-releases.md),
[workflow](https://github.com/Calmingstorm/Odin-Desktop/blob/aa3d61b3043ea47805686c185133a53c54b127fc/.github/workflows/release.yml),
[notice UI](https://github.com/Calmingstorm/Odin-Desktop/blob/aa3d61b3043ea47805686c185133a53c54b127fc/app/src/renderer/src/components/ReleaseNotice.vue).

## P4.5 gate: full R4 on final candidates

- [ ] Record reviewed `maintenance/r4-acceptance.json` and human evidence with
  case IDs, source assertions/corpus mapping, environments, final hashes, outcomes,
  evidence and unresolved dispositions. Those files are required gate outputs,
  not asserted to exist or pass by this draft.
- [ ] Complete applicable Linux R4 and CC cases through real Electron/core and
  both formats. Include attachments/results, concurrent conversations/controls,
  renderer loss/core interruption, durable history/evidence expiry, schedule
  sleep/exited policies, lost-ack identity/no replay, ownership/update paths,
  disabled/unqualified catalog refusal and ingress settings/lifecycle. Future
  Windows/macOS disposition is deferred, not relabeled a Linux pass.
- [ ] Close inherited suites, D19/host parity, current upstream review, safety/source
  drift, dependency/provenance and bundle/reference/catalog scans. No missing
  required row, hidden skip, unqualified promised backend or unresolved critical port.
- [ ] Include real native/receiver/containment/quarantine evidence, rendering,
  sandbox/security, keyboard/Orca and notification/login/no-tray evidence. CI,
  screenshots, provider readiness and OS notification acceptance are distinct
  facts and do not prove human visibility or receiver release.
- [ ] Reuse evidence only for identical artifact/environment identities. Record
  rebuilds and rerun affected cases. Independent reviewer records P4.5 acceptance.

**P4.5 never publishes.** Source:
[P4.5 gate](../work/phase-3-app-v1.md#p45-full-r4-and-final-release-candidate-qualification).

## P4.6 gate: Aaron's supervised exact-build acceptance

- [ ] After P4.5, present Aaron the exact build/hashes, proposed tasks, paths and
  session resources, duration and cleanup/rollback plan.
- [ ] Obtain and record **Aaron's immediate explicit authorization before any
  active-desktop install/run**. Prior work-order approval and isolated passes do
  not satisfy this. No daily-use trial or start-at-login permission is implied.
- [ ] Perform only the supervised tasks he authorized: launch/first-run/chat/results/
  notifications/tray/startup/Exit as scoped. Fault injection, guardian/controller/
  parent killing, locking, suspension, logout, session teardown and destructive
  tests remain isolated, never workstation acceptance tasks.
- [ ] Record Aaron's acceptance of the **exact candidate** on Mint 22/Cinnamon/X11,
  its outcomes/cleanup and remaining support/rollback limitations in the reviewed
  handoff. Do not call earlier isolated candidate logs his live acceptance.

Source: [P4.6 and decision B](../work/phase-3-app-v1.md#p46-explicitly-authorized-live-acceptance-then-release-handoff).

## Separate publication authorization and handoff

- [ ] Obtain **Aaron's separate explicit approval for publication, version,
  distribution license and release audience**. Obtain distinct explicit approval
  for any visibility change; D16 remains private otherwise.
- [ ] Claude reviews the release handoff PR containing hashes/watermark/approvals/
  evidence/support/rollback, not unreviewed implementation changes. Do not merge,
  tag, publish or change visibility merely because this checklist or tests are green.
- [ ] Authorized publication attaches only the same exact approved `.deb` and
  AppImage bytes. Verify matching release metadata and attached identities/hashes.
  Partial publication failures require owner reconciliation, never clobber or
  automatic replay. The pending workflow details above require their own acceptance.
- [ ] Release notes disclose unsigned assets, supported qualified environments,
  known backend/rollback/data-retention limits, dependency/security disposition
  and pinned upstream review watermark. No feed/key provisioning or in-app
  download/apply instructions are added.

**Draft status at this watermark:** release approval, exact final R4/D11 native
closure, product/license handoff, externally configured publication protection
and actual publication are not established by these documents. The open Ubuntu
sandbox/FUSE rows remain blockers for their promised qualification. This docs-only
task ran no installer, GUI, live service or system changes.
