# Keyboard and accessibility

**First draft.** See the [documentation watermark](../../README.md#documentation-watermark).
The current app has keyboard, focus, DOM and Chromium accessibility-tree regression coverage. That is not a claim
that Orca speech, every native dialog or every Wayland desktop has passed release acceptance.

## Navigate without a pointer

Use Tab and Shift+Tab between controls. A visible outline identifies keyboard focus. Enter or Space activates
buttons; use the arrow keys for a native select or radio group. In menus, Up/Down moves among actions and Home/End
selects the first/last. Escape dismisses the menu and returns to its opener. Confirmation dialogs keep Tab inside
the dialog; Escape cancels rather than activating a destructive action.

| Shortcut | Action |
|---|---|
| Enter in Message | Send, or run the selected slash command. It does not send during IME composition. |
| Shift+Enter | Insert a newline. |
| Ctrl+. in Message | Ask the current request to stop; completed effects remain. |
| Ctrl+Shift+F | Show/hide conversation search. |
| Ctrl+, | Open Settings, or return to chat from Settings. |
| Ctrl+W | Close/hide the window, not stop Odin. |
| Ctrl+Q | Exit Odin, including the no-tray case. |

Global view shortcuts do not operate behind an open confirmation dialog. With slash suggestions open, Up/Down
selects, Home/End moves to an endpoint, Tab completes the selected command once, and Escape dismisses suggestions
without discarding the draft. The next Tab can leave Message.

## A first keyboard walkthrough

Use a disposable candidate with synthetic data, not private history or credentials, for acceptance testing.

1. Launch Odin. Tab to **Settings**, press Enter, and visit **Models and providers**. Check that controls and
   errors are named, and that Back returns to a meaningful control. Do not enter a real key for an accessibility
   demonstration. [First run](first-run.md) covers actual setup separately.
2. Return to chat. Tab to **+ New**, activate it and move to **Message**. In a candidate with a controlled working
   provider, send a harmless request. Verify focus remains usable while work completes.
3. Tab to **Attach files**. Use the native file dialog to choose a harmless test file, or Escape to cancel.
   Check the named upload status and Remove control. This dialog belongs to the desktop toolkit and needs its own
   native acceptance; renderer tests cannot prove it on every desktop.
4. On a committed reply, activate **Copy**, choose Markdown or plain text, then return to the opener. On a file
   result choose **Save as…**, select a disposable destination, and confirm the actual saved file. A success
   announcement alone is not a byte check.
5. Open search with Ctrl+Shift+F, enter known synthetic words, and activate a hit. Check focus/highlight in
   history, then choose **Back to latest**. Tab to the **Conversation history** region to scroll with the keyboard.
6. Open a conversation's named **Actions** menu. Navigate with arrows and Escape. Open Rename and check Tab in
   both directions and Escape cancellation, without deleting test evidence.
7. Use the **View** menu's zoom controls for larger content. Check that Message, Settings, errors and result
   controls remain reachable at 200% and 400%, including scrollable regions. Zoom does not eliminate the need
   to test actual display scaling and compositor behavior.
8. Close the window, reopen Odin from its launcher, then use Ctrl+Q to Exit. A visible tray is not required.

Report reading and Work controls depend on the services included in the candidate. See
[Chat and results](chat-and-results.md) and [Background work](background-work.md) for pending service labels; an
unavailable panel is not a reason to replace real-core testing with a fixture.

## Screen-reader and privacy expectations

Controls, settings errors, reports and file actions have contextual names. Task announcements convey structural
states such as busy, queued, consumed, completed or unknown; the transcript is not a live region that reads every
tool output or hidden model draft aloud. Use history navigation to read committed replies. Password fields are
write-only; provider verification codes are intentionally readable for completing login.

Notifications can show previews by default. Turn them off in General if reading them aloud or on a shared screen
would expose content. Copying text uses the desktop clipboard, which other applications may inspect. Do not record
credential entry or private history in screenshots, screen-reader recordings, bug reports or support attachments.

## Limits and reporting a problem

The automated gate covers keyboard tasks, 200/400% reflow, axe findings and the Chromium accessibility tree in
isolated Xvfb. It does **not** prove Orca/AT-SPI speech, native Secret Service unlock, GNOME/KDE portals, real tray
visibility, notification delivery, physical displays or every GPU/driver. Native Orca and desktop-specific tests
remain release gates, not silently successful rows.

When reporting a problem, include app version, package format, desktop/session (X11 or Wayland), screen reader
and its version, zoom/scaling, the named control, expected behavior and what actually happened. Reproduce with
synthetic data. Preserve an unknown/quarantined state rather than repeating computer input to demonstrate it.
See [Recovery](recovery.md).

Sources: [accessibility evidence and open rows](../../maintenance/phase3-accessibility.md),
[app shortcuts](../../app/src/renderer/src/App.vue),
[composer keys](../../app/src/renderer/src/components/Composer.vue),
[native menu/Exit](../../app/src/main/index.ts) and the [release checklist](../release/linux-v1-checklist.md).
