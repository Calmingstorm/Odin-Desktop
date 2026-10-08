# Slice 5: setup invitation and compact chat status

Implemented on `campaign/v1.0-ui` after corrective commit
`db994421cfc06f42d43c7c7431f1a649c6bc5720`. No commit or push by this worker.

## Behavior

- Setup invitation renders only in chat for a current fresh/incomplete core
  projection and an undismissed profile preference. Effective-ready renders no
  success banner or generation/connection-test sentence.
- Main/preload expose strict named reminder get/set routes, trusted-frame and
  shutdown admission checked, with only a boolean payload. The window never
  uses localStorage. Window-state owner integrated the callbacks in index.ts
  and the single latest-state profile writer; this worker did not edit index.ts.
- Saved/degraded, credential and keyring action notices remain independent of
  invitation dismissal. Independently read settings keyring diagnostics carry
  epoch/core-instance qualification, including when first_run is absent.
- Retry is explicit, bounded, never replays secret/config writes or device login.
  Recovery fences surround unlock and metadata/account rehydration. A focused
  review identified and fixed loadCodex's missing epoch/core-instance adoption
  fence, with an old-core-account Retry regression.
- Status bar always names the connection, offers Status/Usage report links,
  shows actionable provider failures rather than normal/disabled/unknown badges,
  and retains awaiting receipts, unknown effects and cleanup attention.
- Chat header hides only absent Context; zero context, quota and tokens remain.
  Current independent usage remains visible if status.get fails. Review caught
  and corrected coupling usage to a successful core status projection.
- General About was inspected, not modified: Desktop release and engine build
  are separate facts, with MIT licence and redacted diagnostics.

## Tests and observed receipts

All Node test execution used launchIsolated as nonprivileged odin with sanitized
HOME/XDG, a private PID namespace and no live display/session credentials.

- Focused initial final selection: 181 passed; typecheck passed.
- After review fixes: six focused files, 82 passed; typecheck passed.
- Full intermediate app selection: 148 files, 1,563 passed. This precedes the
  last two review regressions; parent owns final combined 1,565-test gate and
  coverage qualification.
- Final actual Electron/preload/Vue plus real core onboarding: six passed in
  39 seconds, including fresh dismissal, later incomplete state, restart with
  dismissal persisted, ready without banner, saved/degraded recovery, locked
  and missing keyring recovery, cancellation/expiry, revision/connection retry,
  write-only credential and no transcript/secret readback invariants.
- Final source build passed. Onboarding receipt:
  `/home/odin/reviews/desktop-ui-v1/D-onboarding-real-sealed.log`.
  Focused receipt: `D-onboarding-focused-final.log`; earlier app receipt:
  `D-app-suite-final.log`, under the same report directory.

## Retained failed runs

Earlier focused runs exposed old smoke fixture expectations and the actual
schema error name `bad_request`, then passed after faithful fixture adaptation.
First actual onboarding run failed all scenarios due to outdated corrective-C
selectors. Add-account is now a named data-testid outside the account section;
main model Save is scoped to its dirty action row. Direct settings mutation
request IDs were corrected. Later fresh-case attempts exposed dedicated-owner
rejection and the legitimate inability to re-enable an unauthenticated provider.
The final scenario uses rendered Disable and retains the actual incomplete
configuration across restart, rather than inventing a successful restore.
All six final scenarios passed without deleting old retries or invariants.

No VM, live desktop, service, system installation, engine/Python source change,
or package/platform qualification was performed. Source is quiescent for the
parent's final combined release/capture/coverage gates.
