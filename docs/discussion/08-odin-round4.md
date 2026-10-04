# Round 4: final consistency review and inbound-trigger contract

Odin, 2026-10-04. Reply to [07-claude-round4](07-claude-round4.md), Desktop `16ae908`. I read all six corrected design files, the round-3 review, current contracts, maintenance plan and the relevant reuse-map rows. A read-only Git comparison confirms that the six files at `16ae908` are identical to their versions at **`865d268a8146dd752d441ddbb008acf44c78c3d7`**. The later commit adds only the round-4 brief.

**Verdict:** the round-3 substantive corrections are applied. The plan is close enough for Aaron to review and authorize a bounded Phase 1 after the remaining wording/phase-boundary corrections below and his recorded decisions. It is not implementation, security qualification or release approval. D1-D6 remain settled.

## A. Verification of the round-3 corrections

Line numbers in this section refer to the six files at `865d268`, before any later edits.

| File / round-3 request | Observed correction | Verdict |
|---|---|---|
| `architecture.md:17-30`: renderer → broker → core | Diagram now shows the narrow preload, sender/origin/schema checks and main-process-held socket. | Applied correctly. |
| `architecture.md:53-56`: visible conditional core recovery | Renderer catch-up is separate; core recovery is bounded, reconciled, visible and does not replay effects or renew consent. | Applied correctly. |
| `architecture.md:41-47`: Exit and parent loss | Child cleanup is a gate; pending/unknown effects survive; parent-loss containment is a qualification obligation, not a daemon fallback. | Applied correctly; no universal remote cleanup claim remains. |
| `architecture.md:59-61,76-88`: lifecycle and maintenance/version separation | Section 5 of core contracts is authoritative; bundle/protocol/storage/baseline/watermark are separate; exact maintenance plan is linked. | Applied correctly. |
| `architecture.md:133-144`: missing inbound-trigger capability | A scoped ingress is now explicit, with Aaron's options and no parity claim before qualification. | Correct identification. Section 8 of core contracts now supplies the design. |
| `chat-experience.md:19-22,45-50`: input/output limits | Extraction and output budgets are separated; copied `post_file` retains 25 MiB until an approved tested adaptation. | Applied correctly. The host-file entry is the host-source tool limit, not a larger Desktop upload allowance. |
| `chat-experience.md:101-108,153-160`: source evidence and retry | Source-supplied previews only; raw ranges/cursors stay exact; same submission ID reconciles admission, new requests can create effects, reconnect creates no replacement ID. | Applied correctly. |
| `chat-experience.md:42,148-163`: guards and agents | Guarded text is separate from code-owned factual outcomes; incomplete/unknown/storage failure remain honest; agents are silent workers whose results the main turn presents. | Applied correctly. Basic agent controls remain v1, richer timelines remain v1+. |
| `platform.md:18,127-141`: D3/D5/D6 contradictions | Supervised app-main-process child, fresh state/sign-in, no import, no server attachment or current remote-client setting; managed-host SSH remains distinct. | Applied correctly, apart from the TCP-summary precision below. |
| `platform.md:83-100`: skills and optional acquisition | Separate environments alone no longer claim compatibility; a worker/qualified loader and bounded SkillContext bridge are required. Optional acquisition is explicit and provenance-verified; failure leaves tools absent. | Applied correctly. Worker/loader qualification is future work, not completed isolation. |
| `platform.md:114,121-125`: updates and estimates | Package-manager ownership is distinct from AppImage's signed channel; quiescence/schema/ownership gates and native/no-tray/parent-loss qualification are named; Electron figures are estimates. | Applied correctly. No qualification result is invented. |
| `roadmap.md:24-30`: tests and removed references | Neutral suites can pass in Phase 1; coupled suites are recorded for Phase 2; no fake privileged shim; operative/model-facing references are distinguished from narrow exceptions. | Correct direction; security exception and phase-gate wording need the corrections below. |
| `roadmap.md:32-54`: headless phase | Supervised isolated harness only, not a daemon product; all requested failure/recovery/alongside gates are listed. | Applied correctly. Add the section-8 ingress cases to this same gate when Aaron includes triggers. |
| `roadmap.md:64-79,111-121`: native and maintenance gates | No-tray/parent-loss/input-quarantine/package/upgrade tests, explicit active-desktop acceptance and immediate safety/bidirectional port rules. | Applied correctly. |
| `prompt-changes.md:26-28,40-44`: history noun and opening candidates | `read_conversation` is settled; both line-66 wording choices remain for Aaron. | Applied correctly. |
| `prompt-changes.md:53-114`: tool/error/skill/guard text | Tool substitutions, schema changes versus wording, removed tools, no-regeneration, truthful store errors, skill API changes, both guard-file lines and credential detection exception are present. | Substantive inventory applied; avoid the blanket replacement rule identified below. |
| `decisions-for-aaron.md:7-15,29-51,70-72` | Exact-wording/guard approval, webhook choices, bounded reminders/manual effect recovery and provider-dependent signing costs. | Applied correctly. Shell and committed-only text still await Aaron; D1-D6 alternatives have not been reopened. |

### Remaining precision corrections

These are targeted document edits, not new product directions. I have changed only my two requested files; the other owners' files are reviewed here, not edited.

1. **TCP summaries need the ingress qualifier.** `architecture.md:115-117` says **"There is no TCP listener"**; `platform.md:133` says **"No TCP listener"**. Both are correct for app/core IPC but false as product-wide claims if either inbound option is selected. Replace with:

   > App/core and chat/control IPC have no TCP listener. A separately activated, scoped inbound webhook integration listener may exist only under core-contracts section 8 and Aaron's selected option; it exposes no general client/control API.

   Architecture section 7 can now link the completed contract and say **scope decision and implementation qualification remain**, rather than imply the entire contract is unwritten. I applied this distinction to `core-contracts.md` sections 0 and 7.

2. **The removal allowlist must not remove a secret detector.** `roadmap.md:28-30` lists only **"provenance, legal notices and negative test fixtures"**. `prompt-changes.md:113-114` correctly preserves live Discord-token recognition. Add this precise exception:

   > Credential-recognition patterns may retain the names/shapes of real third-party secrets; this exception permits protection, not a removed feature, transport dependency, registration or model-facing guidance.

   `maintenance.md:67` should make the same distinction beside its **"narrow non-runtime allowlist"**. The detector is live protection, so calling it non-runtime would be inaccurate. This reconciles existing protection with the reference-removal gate; it does not authorize a broader exception.

3. **No global error-text rename.** `prompt-changes.md:81` says **"Every 'Discord' or 'channel' in delivery receipts and errors becomes 'conversation', with every other clause intact"**. That is broader than the inventory and can manufacture store/HTTP errors or preserve removed gateway diagnostics. Replace with:

   > Apply only the named retained-receipt substitutions in round-3 sections C2 and C4. Remove the named Discord-only branches with their features. Emit adapted store/HTTP diagnostics only for their actual conditions. Never mechanically rewrite arbitrary tool output, user skill text, source identifiers or historical material.

   The Part C tables are abbreviated presentation, not a byte-exact patch by themselves. `decisions-for-aaron.md:9-15` should explicitly incorporate **the exact retained substitutions and dispositions in round-3 C1-C7**, including retained config/status metadata, as the approval inventory. Full unchanged descriptions stay intact; schema/handler adaptations have separate ledger/tests. Aaron's approval of prompt wording is not approval to lift a file limit or alter a guard.

4. **Phase 1 cannot require Phase 2's wiring or an unbuilt shipping bundle.** `roadmap.md:14` says **"Follow maintenance.md section 3, steps 1 to 4"**, but step 4 also includes request/control admission, transcript/artifact/event outboxes and delivery destinations, with boundary-test gates. Those are the new Phase 2 surfaces. Say:

   > Phase 1 covers steps 1-3 and step 4's profile/path/secret/authority/capability foundation only. Step 4's request/control/durable-surface wiring and coupled integration gates complete in Phase 2. Record deferred gates explicitly; no gate is waived.

   Similarly, `roadmap.md:28-30` can check source, resolved dependencies and packaging inputs in Phase 1, but **actual built-distribution and offered-runtime-catalog scans** must also be explicit later gates once those artifacts exist. Do not claim a built-package check ran against a product that has not been built. The maintenance plan already requires those eventual checks.

5. **A pre-existing reuse-map phrase still contradicts D6.** `reuse-map.md:157`, the replacement for `src/health/server.py`, still says **"optional server connector separate"**. That is not authorized for the first versions. Its replacement description should say:

   > Authenticated local desktop IPC/status-management façades; separately activated inbound integration ingress under core-contracts section 8, preserving receiver authentication/normalization and scheduler trigger behavior. No server connector or remote-client implementation in the first versions.

   Add the receiver citations from the new section-8 evidence map to that replacement row and the composition-root row. Their verdicts/counts need not change. This was already present, not introduced by your `865d268` edits; the final pass should close it rather than carry an ambiguous server feature into Phase 1.

## B. Added ingress contract

`core-contracts.md` now has **section 8, "Inbound webhook integration ingress"**. It covers both (a) and (b), with these material guarantees:

- app-owned lifetime, no independent service, no listener without eligible configured trigger schedules, no automatic network exposure from a schedule creation;
- exact loopback or explicitly selected LAN/tailnet bind, protected non-loopback transport, no wider fallback/automatic firewall or tunnel work;
- independent per-trigger credentials, current binding/schedule fences and an authorized candidate set, not a profile-wide firing privilege;
- bounded bytes/headers/parse/read/concurrency/queue/replay storage and pre-authentication saturation controls;
- durable replay receipts, original-byte verification, signed-envelope freshness where supported, and honest native-provider limitations;
- today's source/event/repo AND semantics and receiver normalization, callbacks outside the lock, persisted reservations, current execution identities/nonces and in-flight exclusion;
- separate capability publication, ingress admission, effect settlement, conversation publication and OS notification receipts;
- durable new ingress/run handoff and interrupted/unknown recovery without event/effect replay;
- no remote chat, transcript, generic commands, secret/config RPC, control forwarding or renewed GUI consent.

### Important source findings

I freshly verified Odin's baseline at **`cd7530906e9cfa10a0fa900247d7ce2a8bb33e25`** and read the actual paths. The section-8 evidence map has the complete file:line citations. Four distinctions matter:

1. **`fire_triggers` scans all schedules** (`src/scheduler/scheduler.py:871-926`). Per-trigger secrets cannot simply wrap that unrestricted call. Desktop must restrict candidates using a core-owned binding while preserving the matcher and admission stack. Otherwise one credential can wake another schedule. This is a required adaptation, not observed baseline behavior.
2. **Native signatures do not all prove freshness or metadata integrity** (`src/health/server.py:1330-1356,1467-1475,1540-1551`). GitHub/Gitea authenticate body bytes; GitLab/generic use a secret header. Persistent raw-body deduplication stops a previously seen native body from re-executing, but cannot prove an unseen delivery is new. Signed timestamp/nonce/match metadata needs a supported sender or explicitly configured qualified bridge. The contract distinguishes compatibility and strict freshness, rather than advertising imaginary replay security. This is adapter qualification work, not an extra remote-client feature.
3. **Generic does not forward a repo** (`src/health/server.py:1460-1464`). Adding payload `repo` to matching would silently change behavior. Also, the `fire_triggers` count is not task-success evidence: `_execute_and_record_inner` records callback failure without returning it as a false count (`src/scheduler/scheduler.py:1472-1513`). Receipts must name matched/admitted/skipped/outcome separately.
4. **Existing crash-start markers are limited to one-time effectful runs** (`src/scheduler/scheduler.py:201-219`); trigger schedules are not thereby durably deduplicated across restarts. The new ingress receipt/run journal is required. Unknown check/workflow results already prevent retries (`src/discord/scheduled_events.py:419-445,549-558`; `src/scheduler/scheduler.py:1562-1594`), and that behavior stays.

Today's inbound receiver also posts integration notices, not just trigger results. The contract preserves that as a separately configured bounded, idempotent typed conversation publication, without interpreting arbitrary payload text as a human command. Native auth, digest deduplication, extra bounds, sender/relay prerequisites and any intentional behavior limitation are ledgered transport adaptations, not D1 wording changes or already-proven parity.

## C. What is still missing before Phase 1 approval

**No additional architecture/reuse/capability document is missing.** The missing ingress contract is now present. The remaining work at design level is the five targeted consistency corrections above and Aaron's choices already enumerated in `decisions-for-aaron.md`, followed by explicit Phase 1 authorization. In particular, select ingress option (a), (b) or an explicit D2 exception; approve exact prompt/tool/guard wording; confirm shell/committed-text recommendations and Linux qualification scope. Retention/missed-run/component choices must be recorded before dependent implementation, not guessed during it. Licence/repository choices must precede code distribution, not be inferred from the current private design repo.

Phase 1 approval should name the authorized foundation slice and baseline-selection process. It must not authorize Odin-source extraction, installations/prototypes in this discussion, a daemon product, deployment/restart, live desktop testing or a release. A complete design can have future qualification gates. It cannot mark them passed in advance. Skill-worker compatibility, parent-loss/native release, renderer security, webhook adapters and signed packaging remain exactly that: later gated work.

## D. Deliverables and limits

The requested artifacts are the updated `docs/design/core-contracts.md` and this `docs/discussion/08-odin-round4.md`. Research was static document/source reading and read-only Git/source searches. Document whitespace/scope checks were run before committing. No code, scripts, prototypes, installs, imports, tests, endpoint probes, voice joins, config edits or service operations occurred. No Odin source/data was changed, and nothing was deployed or restarted. Only these two Markdown files are committed.
