# P3.1 slice 6: real webhook trigger setup and ingress

PR #55 targets `phase-2/step8-part6-webhook-suites` (Task 1, #58).
Task 1 head `f9d06c2fa8e178377b01e2f3e2ae3b2a94cc7537` was merged locally,
without rebase or force push. Fresh app source gate:
`79c9082126adbb196d0f38d6a44c324cdcf59b56`.

## Delivered and observed

- Schedule trigger CRUD preserves the real core's native source/event/repository
  rules. Listener setup is separately opt-in; numeric explicit addresses are
  validated by the core, without a stricter renderer address policy (D17).
- The Settings inspector reads actual ingress state, eligible-trigger count and
  observed socket address. Disabled/no-eligible/not-bound states do not advertise
  an accepting endpoint. Per-trigger secrets are write-only, never prefilled or
  read back. Unsupported ingress sources remain honest rather than fixture-backed.
- The real smoke created a reminder through the named preload bridge, saved its
  source/secret, and bound only isolated loopback `127.0.0.1:42393` with configured
  port zero. A wrong credential returned 403 with no scheduler history; an
  authenticated nonmatching event returned 200, published one notice and ran no
  trigger. Two matching HTTP deliveries returned 200, produced two successful
  history entries and exactly two reminder messages. Clearing the secret closed
  the listener; subsequent connection failed and history stayed unchanged.
- Schema, rendered inspector and delivered transcript contain no fixture secret.
  Unknown deliveries remained zero. Existing real task/report effect counters
  stayed `background=1, report=1` through all navigation and delivery.

## Fresh five-gate qualification

Independent clone: `/home/odin/desktop-lane5-step8p6-s6-20261006/task2-fresh`.
Parent and root permissions were 0775. Dependencies were provisioned independently
with `uv sync --frozen --extra dev` and `npm ci`, without system-package installs.

| Gate | Observed result | Authoritative log |
| --- | --- | --- |
| `npm run check` | Typecheck/build and 803 tests in 85 files passed | `fresh-check.log` |
| `npm run smoke` | Fixture smoke passed, exit 0 | `fresh-fixture-smoke.log` |
| `npm run test:real-core` | 34 real Broker/core tests and 6 onboarding tests passed | `fresh-real-core.log` |
| `npm run smoke:real-core` | Passed, 41 screen observations | `fresh-real-smoke.log` |
| `npm run test:a11y` | 16 tests passed | `fresh-a11y.log` |

Also ran only the touched engine status suite with the official isolated launcher:
`tests/test_desktop_webhook_status.py`, 2 passed (`fresh-targeted-engine.log`).
No full engine qualification was repeated by Task 2; Task 1 owns that run.
Inventory report returned no errors, `byte-drift-clean-review-pending`; existing
exact records for the runtime/status change remained current. Independent review
and safety approval are not manufactured by a clean byte report.

## Bugs and retained failed evidence

The production bug was Vue's numeric-input coercion: `port.value` became a number
and `.trim()` threw. Listener submission now checks `String(port.value).trim()`.
Three DOM-coercion regressions cover 0, 8081 and 65535; all 29 targeted inspector
tests passed in `numeric-port-regression.log`, and the fresh full app suite passed.

The first-conversation smoke incorrectly treated ancestor `innerText` as the full
transcript while Chromium's `content-visibility: auto` skipped offscreen bodies.
It now first asserts exactly one durable catch-up message plus its D12 provenance,
scrolls that exact message into view, and proves the same visible rendered text.
Report paging remains a real UI action with unchanged effect counters. A retained
Work inspector also consumed the chat viewport; the smoke closes it through its
real control before scrolling/proving the committed user message. No assertion
was removed, no content-visibility production behavior changed, no deadline or
native/isolation guard was relaxed. Vue field settlement and explicit schedule
refresh precede trigger selection rather than assuming pending UI updates landed.

Exploratory failures are retained externally, including `smoke-development.log`,
`smoke-fixed.log`, `smoke-visible.log`, `smoke-diagnostic.log`,
`smoke-development-final.log`, and `development-real-core.log`. One exploratory
real-core test exceeded its unchanged 30-second socket-start deadline; the other
33 passed. One smoke delivery exceeded its unchanged 5-second HTTP deadline.
These are observed failures under concurrent host activity, not proven root causes
or hidden automatic retries. Later explicitly invoked fresh gates all passed.

## Evidence and limits

Raw logs, screenshots, 1.4 MB real-smoke JSON and 26.8 MB accessibility output are
outside Git in `/mnt/storage/odin-desktop-evidence/lane5-step8p6-s6-20261006/task2/`.
`p31-slice6-artifacts.json` records authoritative paths/digests and anchors the full
external 120-file SHA-256 inventory, including failed-run artifacts. The fixture
smoke's temporary screenshot was verified by its official runner, not retained.

All engine execution used official sanitized non-root PID helpers; graphical
proofs used private Xvfb/D-Bus. No active desktop, LAN/tailnet listener, provider
account, live profile/service or `/opt/odin` was used. This is not LAN reachability,
native desktop qualification, full P3.1 completion or release acceptance.
Locked dependencies report 11 inherited npm advisories (10 high, 1 critical).
Disk remained above 60 GB free (120 GB at the final gates).
