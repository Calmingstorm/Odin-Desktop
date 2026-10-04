# Decisions for Aaron

Owner: Claude. Draft 3, 2026-10-04. Decided items move into the design and leave this list. Decisions D1 to D6 are
recorded in the [brief](00-brief.md#aarons-decisions-2026-10-04-after-round-1). These are what's left. Where Claude and
Odin recommend something, it says so.

## 1. Approve the wording changes (D1)

[`prompt-changes.md`](prompt-changes.md) lists every text change, each changing only the Discord reference:
- **A and B: prompt templates (9 lines).** One choice inside: line 66 reads either "…an autonomous execution agent
  running on the user's computer" (Claude) or just "…an autonomous execution agent" (Odin, the strictly minimal option).
  Line 97 now uses the desktop history tool, `read_conversation`.
- **C: tool descriptions, tool errors and skill docs.** Discord becomes "conversation". The Discord-only tools (permissions,
  reactions, polls, purge) are removed.
- **Guard file:** one comment and one docstring, listed separately because they sit in guard code. No logic changes.

## 2. Shell: Electron (recommended)

Claude and Odin both recommend Electron for v1. It renders reliably on Linux and reuses web UI work. It is conditional on
qualifying rendering, accessibility and security on your desktop. Tauri is the lighter alternative; its Linux engine is
the risk.

## 3. Reply text: committed only (recommended)

Recommendation: reply text appears only after Odin's guards accept it, as on Discord today, while live tool and task
activity shows what he's doing. Streaming draft text would let you read unguarded hedges or claims before the guards
catch them. Confirm, or choose to accept that exposure.

## 4. Inbound webhook triggers

Odin's schedules can be fired by webhooks, received today by his web server. The desktop app has no network listener
and no remote access (D6). Keeping this capability (D2) needs a small, separate listener. Options:

- **(a)** A loopback-only listener: scripts and tools on the same machine can trigger schedules.
- **(b)** An opt-in listener that the user binds to the LAN or tailnet, with a per-trigger secret, so other machines and
  services can trigger. It is off until a webhook-triggered schedule exists. **Recommended:** it keeps D2 parity without
  becoming remote control.
- **(c)** Leave webhook triggers out of v1. This is an explicit exception to D2.

## 5. Linux scope for v1

- **Desktops:** Cinnamon on X11 (yours) first. Should GNOME and KDE on Wayland also be qualified for v1?
- **Computer use:** X11 for v1. Should the Wayland portal and Hyprland backends be qualified for v1 too?

## 6. Missed schedules

These apply when the app wasn't running or the machine slept. Recommended (Odin's proposal):
- **Overdue reminders** become one bounded catch-up notice, with the due time, how late it is and how many were
  skipped.
- **Missed runs that would take actions** are recorded and wait for you to run them. They never run on their own at
  startup.
- **An exited app** runs nothing in the background.

## 7. History and notifications

- **History:** keep the visible conversation history and files until you delete them, or for a retention period?
- **Notifications:** minimal previews by default, so no message content shows on the lock screen. Previews can be turned
  up in settings.

## 8. Heavy optional components

Browser automation (Chromium), semantic-search models and PDF support:
- **(a)** acquire each when you turn it on, with progress and verified downloads (recommended);
- **(b)** bundle them all in the installer.

Either way, an unconfigured feature publishes no tools.

## 9. Windows and macOS

- **When:** after Linux v1.
- **Accounts:** Apple Developer membership for notarization (annual). A Windows code signer, whose cost and key-storage
  rules depend on the provider chosen. Verified when that phase starts.

## 10. Repository and licence

The repo is private during design. When code exists, should it be public and MIT-licensed like Odin?
