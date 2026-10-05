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

## Final fresh-checkout gate

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
