# Decisions for Aaron

Owner: Claude. Draft 2, 2026-10-04. Decided items move into the design and leave this list. Decisions D1 to D6 are
recorded in the [brief](00-brief.md#aarons-decisions-2026-10-04-after-round-1). These are what's left.

## 1. Approve the prompt wording

[`prompt-changes.md`](prompt-changes.md) lists the exact before and after for the nine Discord mentions in Odin's prompt
text (D1). Two choices inside it:

- **Line 66:** "an autonomous execution agent running on the user's computer", or simply "an autonomous execution
  agent".
- **Line 97:** its wording follows the name of the desktop history-read tool, which is pending in Odin's round 3.

Odin's round 3 adds the tool descriptions that mention Discord.

## 2. Shell: Electron (recommended)

Claude and Odin both recommend Electron for v1. It renders reliably on Linux and reuses web UI work. It is conditional on
qualifying rendering, accessibility and security on your desktop. Tauri is the lighter alternative; its Linux engine is
the risk.

## 3. Reply text: committed only (recommended)

Recommendation: reply text appears only after Odin's guards accept it, as on Discord today, while live tool and task
activity shows what he's doing. Streaming draft text would let you read unguarded hedges or claims before the guards
catch them. Confirm, or choose to accept that exposure.

## 4. Linux scope for v1

- **Desktops:** Cinnamon on X11 (yours) first. Should GNOME and KDE on Wayland also be qualified for v1?
- **Computer use:** X11 for v1. Should the Wayland portal and Hyprland backends be qualified for v1 too?

## 5. Missed schedules (when the app wasn't running or the machine slept)

Odin's proposal:
- **Overdue reminders** become one catch-up notice, with the due time and how late.
- **Missed runs that would take actions** are recorded and wait for you to run them. They never burst-run on startup.

## 6. History and notifications

- **History:** keep the visible conversation history and files forever (until you delete them), or for a retention
  period?
- **Notifications:** minimal previews by default, so no message content shows on the lock screen. Previews can be turned
  up in settings.

## 7. Heavy optional components

Browser automation (Chromium), semantic-search models, PDF support and computer-use helpers:
- **(a)** download each on first use, with progress (recommended);
- **(b)** bundle them all in the installer.

## 8. Windows and macOS

- **When:** after Linux v1.
- **Costs:** an Apple Developer ID for notarization and a Windows code-signing certificate, both yearly.

## 9. Repository and licence

The repo is private during design. When code exists, should it be public and MIT-licensed like Odin?
