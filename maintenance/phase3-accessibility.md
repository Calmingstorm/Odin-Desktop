# P3.4 part 1: keyboard, DOM and Chromium accessibility tree

Scope: the existing app on pulled `main@2acdbc7`, not the future first-run flow and not Orca qualification.
No engine/protocol/security-policy changes, new confirmation, command restriction, deployment or active-desktop
input. D9 committed-only replies and D17 execution behavior remain unchanged.

## Runner and reproducible evidence

`app/test/e2e/accessibility.spec.ts` uses `@playwright/test@1.63.0` Electron and `axe-core@4.14.0`, pinned exactly in
the app lock. `npm run test:a11y` uses the existing real-core PID-isolation runner, then Xvfb 1440x1000 and a private
session bus. Caller uid/gid, sanitized environment, disposable HOME/XDG, no inherited workstation display/bus,
no `--no-sandbox`, real renderer sandbox/contextIsolation on and nodeIntegration off are checked. Direct E2E
invocation outside this owned PID namespace fails closed. Axe is evaluated by the debugger, without changing CSP.

Keyboard scenarios use Tab/Shift+Tab, arrows, Home/End, Escape and native accelerators. No locator click/focus/fill
is used to complete tasks. Xdotool sends only keyboard input to native dialogs on the private Xvfb display;
native Attach cancel/selection and Save complete without dialog mocks. Actual saved bytes and clipboard data are
checked. CDP `Accessibility.getFullAXTree` checks nonignored named controls, modal background exclusion, secrets,
unpublished drafts, offscreen history and provider codes. Mutation observations verify structural announcements,
not screen-reader speech. A delayed/adversarial E2E-only core subclasses the fixture without changing normal
fixture or product behavior.

Development gates: `npm run check` (580 tests), 15 Electron E2E scenarios and 49 axe checkpoints passed.
The final fresh-checkout gate, source SHA and report hashes are recorded below after execution.
Logs/reports are retained locally under `/home/odin/desktop-p34-evidence/`; generated reports/traces are ignored,
not committed. No production credential is used. Cleanup attachments record Electron exit and profile removal;
owned PID namespace teardown terminates any remaining core/private-bus children. Namespace/display/bus cleanup
is isolation evidence, not native lifecycle acceptance.

## Measured automated findings and dispositions

Every rule observed during the baseline or integration audits is listed here, including integration regressions.
All final **violation** arrays are empty; incomplete checks are explicitly separate below.

| Finding | Evidence | Disposition |
|---|---|---|
| `landmark-one-main`, moderate | All 11 baseline Settings sections replaced main with a div | Settings is a named main landmark |
| `page-has-heading-one`, moderate | All baseline Settings sections | Settings h1 plus section h2 |
| `region`, moderate | Settings content outside landmarks | Main now contains section contents |
| `color-contrast`, serious | Records Period/Level native select 4.38:1; inactive schedule detail 3.84:1 | Explicit dark select background; remove opacity on inactive work row |
| `heading-order`, moderate | Integration h1-to-h3 Settings/work and tool-detail h4 | Settings h1/h2/h3; inline Work h2; tool-detail h2 |
| `landmark-unique`, moderate | Integration named outer section duplicated Personality/Skills/MCP panels | Unique `SECTION settings content` region |
| `aria-allowed-role`, minor | Integration textarea combobox and form dialog | Native multiline textbox with linked listbox/active descendant; dialog div wraps native form |
| `label-content-name-mismatch`, serious | Tool summaries, thread action, file Save/Show, older-message terminal label | Names include visible text contiguously; tool name uses native content plus structural outcome; state-specific history name |
| `scrollable-region-focusable`, serious | Real-core unavailable Records content and long retained output | Named keyboard-focusable section and output regions |
| `aria-prohibited-attr`, incomplete | Named generic pre elements | Give scrollable output valid region role |
| `aria-valid-attr-value`, incomplete | Textarea aria-haspopup made axe unable to evaluate controls target | Remove inapplicable popup attribute; CDP/DOM verify listbox target and active descendant |

## Measured keyboard/focus defects and implemented fixes

| Area | Defect and disposition |
|---|---|
| Focus/reflow | Textarea suppressed focus outline; restore visible accent outline. Responsive minimum widths, wrapped controls, bounded/scrollable status footer, sidebar overflow, minmax grid row and nonshrinking composer prevent overlap at zoom. Native full-Xvfb captures inspected at 200/400 percent; page screenshot was not used as whole-window evidence. |
| Modal | No trap/restore/background exclusion; trap Tab both directions, inert shell siblings, Escape cancels and restore connected opener. Global view shortcuts are ignored inside a modal; asynchronous view focus cannot pre-empt a modal. Real AX excludes background controls. |
| Menus | Missing arrow/Home/End behavior, lost opener and viewport overflow; implement roving menu focus, Escape/Tab exit, opener restoration, bounded placement and popup relationships. |
| Composer | Suggestion Tab trap and Escape draft loss; complete once, allow next Tab/Shift+Tab, preserve dismissed draft and IME. Native named Steer/Queue radio group uses arrows. Associate attachment/composer errors with Message. |
| History/search | Incoming updates dragged readers to end, loading could replace history or disable focused controls; preserve mounted committed messages, current highlight and focus during delayed loads. Final pagination focuses first new hit; replacement search returns removed-hit focus to search. 130-message CDP capture sees offscreen anchors 0 and 129 with content-visibility retained. |
| Results | Repeated unnamed/context-free copy/file/page controls and pending-focus loss; target-specific names, guarded aria-disabled controls, copy-choice focus/restore, report content retained on loading/error, retry and current-page copy. Unsupported report Save added during development was removed: report refs are not file refs. File Save is real; report export is not claimed. |
| Work | Symbol close, duplicate controls, focus loss on terminal updates and generic Settings focus overriding explicit conversation navigation; named target controls, owned-focus repair, Escape/opener return and coordinated history navigation. |
| Settings | Three quiet-hour controls shared one ambiguous label; distinct Quiet hours/start/end labels. Schema IDs/descriptions/errors, visible management labels, contextual actions and disclosure relationships. Field validation invalidates only the responsible control, not every field on generic backend failure. |
| Provider login | Code lacked keyboard copy; readable/copyable temporary code with concise status, never device ID or credential. Code removed when waiting ends. Password sentinel absent from Chromium AX while editing and after save. |
| Announcements/privacy | Transcript is not a live log. Structural busy/completed/queued/consumed/unknown announcements exclude draft/steer/tool contents and ignore tool-detail churn. Injected unpublished/rejected assistant draft absent from DOM/AX; committed reply appears. |

## Passing task inventory and qualification boundaries

1. Chat send; native Attach files cancel/selection, remove; message Markdown copy, code copy, generated-file Save;
   stored report Previous/Next/current-page copy.
2. Conversation menu keyboard endpoints/wrap/Escape, rename modal trap/restore, child creation and original navigation.
3. Stop, Steer consumed, queued follow-up, interrupted-task Resume and unknown-effect no-resume state.
4. Search result navigation and message focus, delayed history loading, final search pagination and replacement-hit focus.
5. All 11 settings sections by keyboard; quiet hours, timeout validation/success, schema secret edit/save, provider code copy,
   tool parameters, skill editor, MCP tools/form, host enrollment form, schedule editor, memory disclosure, record filters,
   personality preset fields and Other content. This is not exhaustive backend mutation qualification.
6. Work agent/process Stop without new confirmation, Escape focus return and Settings work-to-conversation history focus.
7. Command listbox navigation/completion/dismissal, retained tool output, reduced motion, native zoom accelerators and reflow.
8. Real Phase-2 step-one core: `/status`, refused `/usage`, all settings/unavailable-service panels; no fixture rows.
   Chat/control/management successes are fixture-only until their reviewed real services land.

### Incomplete axe checks are not passes

Remaining color-contrast incomplete nodes are retained per checkpoint in JSON. Axe cannot infer backgrounds for
offscreen/partially obscured content, and reports non-text glyphs. No rule is disabled and these are not counted as
passing contrast determinations. Determinate failures were fixed; full-Xvfb zoom screenshots were inspected and
the palette uses explicit foreground/background colors. This does not certify every obscured or arbitrary
user-provided rich-content combination. Remaining label-content-name-mismatch incomplete checks are close glyphs
inside `aria-hidden` spans; DOM/Chromium AX show named Close search/Close work buttons. Disposition: reviewed
symbol-only false indeterminacy, not a suppressed violation.

| Later qualification row | Status |
|---|---|
| Orca/AT-SPI, Cinnamon/X11 VM | OPEN, part 2; no speech or native AT bridge claim |
| Orca/AT-SPI, GNOME/Wayland VM | OPEN, part 2 |
| Orca/AT-SPI, KDE/Wayland VM | OPEN, part 2 |
| First-run keyboard/Orca | OPEN, P3.2 does not exist in this base |
| Real full-core chat/control/management | OPEN, awaiting reviewed Phase 2/P3.1 handoff |
| Native portal/notifications/input qualification | Not tested here; namespace GTK file chooser is not a platform matrix |

## P3.4 part 2: Orca lab execution

Part 2 starts from pulled `main@1c72a3f14b1257126ddd8f51863e0f707bccd4c5`.
The VM lane is separate from part 1: its host Xvfb/PID-namespace requirements
remain unchanged. `app/test/e2e/orca.spec.ts` uses actual guest sessions and
Orca's `SPEECH OUTPUT` records. Chromium AX, DOM names and debug event dumps
alone cannot satisfy a speech assertion. The guest fixture uses part 1's
adversarial core, including its unpublished/rejected draft sentinel. No real
credential is entered or copied into a guest.

### Rootless lab-test repair (review P3)

The eight KDE `user_config` cases previously invoked nested `sudo -n env -i`.
The installed isolated runner reproduced **15 passed, 8 setup errors** because
its unprivileged `no_new_privs` account cannot acquire host root. They now run
the actual sourceable configuration emitter as the test account. Only
`install` ownership flags and `chown` are modeled at a narrow fixture command
boundary; every explicitly requested intermediate directory/file owner is
asserted. Contents, modes, stale-file repair, preservation of unrelated user
configuration and unprivileged writes are real filesystem operations.

**No cases skipped.** All five user-configuration lab modules passed **104
tests**, including a byte-identical snapshot run as `hyprlab` UID 986/GID 977
with zero effective/bounding capabilities, `NoNewPrivs: 1`, and general
`sudo -n /usr/bin/true` denied. Privileged setup created the isolated
namespace only; pytest and fixture subprocesses did not run as root.
This is explicitly **not** a claim that a rootless fixture exercised kernel
repair of genuinely root-owned files. That behavior belongs to the disposable
guest provisioning path.

### Silent speech and native task boundary

The bootstrap runs only inside one of the three named, marked/capped VMs,
with the `odq` user's active logind session and actual guest bus/display.
App profiles are disposable and separate from the desktop profile. Orca uses
private preferences and a private speech-dispatcher Unix socket with only
`sd_dummy`, backed by the ALSA `null` sink. Its debug output records intended
speech without audible playback. Typing echo is disabled to measure password
widget privacy, not explicit key-echo behavior. This does not certify every
possible user-selected speech preference or a physical braille display.

Native file-dialog keyboard input is grounded in the owned, active AT-SPI
dialog. The guest's synthetic `/dev/uinput` access is temporary and restored;
no host input/display/audio device is attached. Electron retains its renderer
sandbox, context isolation and disabled node integration, with native X11 for
Cinnamon and native Wayland for GNOME/KDE. D9 and D17 are unchanged.

### Development findings, distinct from product defects

| Finding | Evidence and disposition |
|---|---|
| Dummy speech startup tried PulseAudio | Actual `sd_dummy` module loaded but speech-dispatcher exited on audio initialization. Explicit ALSA `null` makes the private sink non-audible without a host or guest hardware-audio dependency. |
| Orca erases launch argv | Guest `/proc/PID/cmdline` contains only `orca` after startup. Log binding uses its actual open file descriptor, UID and live process, not erased `--debug-file` arguments. |
| Part 1 discovered VM-only tests | New E2E support was discovered by the existing Playwright directory scan. Part 1 now explicitly selects `accessibility.spec.ts`; parser unit tests live outside the E2E directory. No isolation guard was removed. |
| Buffered Orca debug delivery | The failed speech windows were empty while teardown's actual `SPEECH OUTPUT` records contained the expected names and roles. Orca's debug file uses block buffering. Private lab customizations change only the debug writer to line-buffered/write-through I/O; no utterance is generated, rewritten or imported from the AX tree. |
| Silent local command report readiness | Actual `/status` created a Status AT-SPI landmark but emitted no success announcement. Local command reports are not chat task completion events. Composer now has one persistent polite/atomic status announcing only `<report title> report ready.`, never report text or a draft. A component regression failed before the change and then passed alongside command/composer tests. Native speech must independently verify it below. |

Task verdicts and source-bound evidence below are filled only after actual
guest runs. Successful process startup or a passing role/DOM audit is not
Orca task qualification.

### Wayland launch probes after Aaron's steering

Aaron stopped the repeated full-suite attempts and required one-launch probes
before any further task matrix. The existing failures were not seven separate
application defects: KDE failed the common native launch, and GNOME stayed in
the initial Shell overview without a visible/focused Odin window.

- **KDE single-launch probe passed.** Full Electron stderr retained with
  `ELECTRON_ENABLE_LOGGING=1`. The original user-owned archive could not supply
  the required Chromium sandbox helper under KDE's user-namespace policy;
  installing under `/run` then failed because that guest mount is
  `nosuid,noexec`. The exact manifest-verified Electron runtime is now installed
  in a root-owned, non-user-writable, executable guest-only directory under
  `/usr/local/lib/odq/`, with its standard root-owned `4755` sandbox helper.
  The probe mapped a native Wayland window, focused Message, produced actual
  `Message entry` speech, and retained sandbox/contextIsolation with
  nodeIntegration disabled. No `--no-sandbox`, host change or global kernel
  policy relaxation was used. Runtime/helper retirement is part of cleanup.
- **GNOME plain GTK probe passed first.** Orca emitted the actual GTK window
  name, `Probe message text.`, and `Probe action push button.`. This isolates
  the speech pipeline from Electron.
- **GNOME single Electron probe then passed.** The guest accessibility bus and
  toolkit accessibility remained enabled. Dismissing the guest's initial
  overview with native keyboard input, then presenting the actual native
  Wayland window made focus observable. Orca emitted `Odin frame.`, named
  buttons and `Message entry Message Odin…`. Full guest screenshots of GTK and
  Odin were inspected: actual windows are visible, not just a CDP document.

Probe evidence is retained at
`/home/odin/reviews/p34-focused-{kde,gnome}-v13/`. These are **focused launch and
speech proofs**, not passes for the full seven-task matrix. Full qualification
must use the repaired setup, source-bound artifacts and all requested tasks.

### Native chooser probes

The Cinnamon registered desktop tree omits Electron's separate GTK accessible
root, despite Orca receiving its real activation events. A collector now starts
before app launch and binds the actual AT-SPI sender/object path to the live
owned process. The Cinnamon Attach focused probe passed at
`/home/odin/reviews/p34-focused-native-attach-cinnamon-v16/`: real chooser speech,
event reference, current name/role/states, and Escape cancellation.

GNOME's chooser is its actual `xdg-desktop-portal-gnome` backend, not an Electron
process. The narrowly scoped native binding accepts only that exact installed,
canonical root-owned executable and its observed GTK accessible path in this
owned GNOME guest session. GTK4 exposes MODAL/SHOWING/VISIBLE but omits ACTIVE
from GetState; its real latest `active(1)` event supplies the activation witness.
A later `active(0)` or another activation revokes that witness. Every native
chord revalidates the process incarnation and current title/role/states.
No portal request-token correlation is claimed, and no title-only target or
security prompt is admitted.

The GNOME focused Attach probe passed at
`/home/odin/reviews/p34-focused-native-attach-gnome-v19/`. Its native portal
screenshot was inspected: actual **Attach files** dialog with Cancel/Open and
guest-only paths. Escape cancellation and cleanup were confirmed. These
cancellation probes do **not** qualify positive file selection or Save. Those
remain part of the final full task run.

### Positive native-file probes and final harness review

Source-bound development evidence is checked in at
`maintenance/evidence/phase3-orca-native-files-20261006/`. Cinnamon v22 and
GNOME v26 passed one-launch cancellation, positive Attach with actual returned
path and attachment UI, and native Save with the exact 25 generated bytes.
Their completed screenshots were inspected. These are not final full-task passes.

The GNOME probe found two harness issues, not application defects: GTK4 Text
readback needs CharacterCount and the focused EDITABLE entry, not the first
FOCUSED container; and bare keypad Enter can activate the default Save button.
Description now only revalidates the modal and relies on opening speech captured
from a mark taken before activation. Matching field text is not acceptance.

KDE v30 still fails the native chooser binding. Its inspected screenshot shows
Attach files, Name, Open and Cancel, but AT-SPI exposes only plasmashell's task
button, never the portal dialog. Both accessibility status properties are true.
The exact installed backend, restarted after Orca and collector readiness with
both Qt accessibility flags, has the matching graphical environment and the same
accessibility bus. Temporary manager values are restored. None of those checks
made the actual chooser accessible. No foreign task button is accepted, no
toolkit fallback is substituted, and no chooser operation is counted as passing.

Final code review also found and fixed three fail-closed harness defects:
the suite now polls only observation before a single input invocation; collector
exhaustion/processing errors invalidate old activation evidence and terminate;
and valid foreign GTK4 activation paths revoke the modal lease without becoming
eligible input targets. Regressions execute the actual suite retry function and
model collector exhaustion, malformed sources, queued callbacks and sticky
invalidation. These are safety tests, not native runtime qualification.

### Final part 2 task results

Evidence: `maintenance/evidence/phase3-orca-final-20261006/`, frozen implementation
`587242b3960f14db69711dc5c16e2433394a00c8`. Both requested one-launch startup
probes passed before the final task run. The final matrix ran **exactly once per
desktop**, seven groups each, retry 0, no skips or flaky results. Later commits
update only ledger/docs/evidence, not the tested runtime implementation.

| Task | Cinnamon/X11 | GNOME/Wayland | KDE/Wayland |
|---|---|---|---|
| Named Message and native button bridge | PASS | PASS | PASS |
| Chat, Attach/cancel, Save/copy/report results | PASS | PASS | FAIL at native Attach |
| Conversation, children, modal and search | PASS | PASS | PASS |
| Busy, Steer, consumed/queued, Stop/Resume, unknown/no-flood | PASS | PASS | PASS |
| All eleven settings, names/roles/states/errors/secret | PASS | PASS | PASS |
| Delayed history/search preserves focused message | PASS | PASS | PASS |
| Provisioned real-core services | PASS | PASS | PASS |
| Total | **7/7** | **7/7** | **6/7** |

**P3.4 part 2 is not fully qualified.** KDE's actual portal chooser still lacks
an eligible active AT-SPI source, despite verified accessibility status, Qt flags,
backend restart and matching bus/session. No chooser cancellation, selection or
Save is claimed after that failure. Other six KDE groups passed. The final native
results screenshots were inspected; Cinnamon/GNOME show saved notes and report
results, while KDE retains the actual Attach dialog. No input guard was relaxed.

Final local gates on the frozen source: app typecheck/build and **620 unit tests**;
**507 lab tests** through the isolated runner; **15/15 part 1 accessibility tasks**
and fixture smoke on isolated Xvfb; Ruff and drift/lint gates clean. Engine
qualification passed all **30 groups, 14,031 passing executions and 2 skips**.
The first engine attempt stopped during group 2 with host ENOSPC, not a test
failure. Twenty-eight owned intermediate artifacts were moved with SHA-256
verification to `/mnt/storage/odin-desktop-orca-artifacts-20261006/`; no evidence
was deleted. Group 1's 3,158 passes were retained and the remaining 29 groups
passed after space recovery. The phase2 subreaper corpus still emitted an
unsuppressed `Event loop is closed` unraisable warning. This working-checkout
validation is not a new fresh-checkout claim.

The exact-byte ledger is refreshed with pending independent review unchanged.
Several active patches use small insertion chunks to avoid oversized delivery;
their previous payloads remain as `previous_patch` audit metadata. The active
`patch` alone reconstructs and verifies current source bytes. This is accounting,
not permission to call the native blocker passed.

## Historical part 1 fresh-checkout gate

Executed from separate clone `/home/odin/desktop-p34-fresh` at source
`4d4ce76f1b54b62e771245f1c7ace3036799a72f`. The following final commit changes this evidence record only.
Fresh clone tracked status was clean; no dependency symlinks or reused build output. Node 22.23.3, npm 10.9.9,
Python 3.12.3, Electron 44.5.1, Playwright 1.63.0 and axe 4.14.0 on Linux Mint. Repository-only dependencies
provisioned with `uv sync --frozen --no-install-project`, `npm ci --ignore-scripts`, and explicit pinned
`node node_modules/electron/install.js`. No host package installation.

| Command | Result |
|---|---|
| `npm run check` | Typecheck, 580 tests in 61 files and production build passed |
| `npm run smoke` | Fixture handshake/render/normal Exit passed on isolated Xvfb |
| `npm run test:a11y` | 15/15 passed, zero skipped/flaky, 49 axe checkpoints with zero violations, 29 full Chromium AX attachments |
| `npm run smoke:real-core` | Real handshake/version/capabilities, 37 screen/refusal checks and orderly cleanup passed |
| Cleanup | All 15 E2E Electron exits were exit 0; all disposable app profiles removed. No Electron from this fresh/working checkout remained in process inspection. Unrelated concurrent qualification jobs were not touched. |

The first extra real-core smoke runs exposed stale title-based selectors after controls gained accessible names.
Those assertions now select named Attach files/New conversation controls; no capability condition was weakened.
The final full gates above were repeated after these changes. No final product code changed afterward.

Final report: `/home/odin/desktop-p34-evidence/final-accessibility.json` (run 2026-10-05 22:08:42 UTC, 65.4 seconds).
There are 454 **repeated checkpoint node observations**, not 454 unique defects, under incomplete color-contrast,
and four incomplete close-glyph name observations. Their reviewed dispositions/limits above remain open to
native/manual qualification. No incomplete rule is filtered out of the captured JSON.

| Evidence | SHA-256 |
|---|---|
| `final-accessibility.json` | `35c9a3f120a8dde95b2d65c94410348db947fb6d0ef97cec1c6a4cdd711e245a` |
| `final-check.log` | `e34520ce1bde49ca55580b51e8cc01c207fc365f1cbee8483f3ed82f2b9bdc7a` |
| `final-smoke.log` | `2aff2e7338a44477ff390eea3eb4e8d3e8999f79baa6b6ff5b15c99dcffdb69f` |
| `final-real-smoke.log` | `46ab3531c1efd97547e4bcc5929d1906117d5b4372a6a96e159303c36c485c93` |
| `app/package-lock.json` | `13dcbeacd74b9ebbd1a0c3f1ba4b79a2746436df52cfdbc405dd01683b79068b` |
