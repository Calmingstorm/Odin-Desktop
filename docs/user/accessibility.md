# Keyboard and accessibility

## Navigate without a pointer

Use **Tab** and **Shift+Tab** between controls. The visible outline marks keyboard
focus. **Enter** or **Space** activates buttons; arrows change native select or
radio controls. In menus, **Up/Down** moves and **Home/End** selects an endpoint.
**Escape** dismisses a menu and returns to its opener.

Confirmation dialogs keep Tab inside. Escape cancels, rather than activating a
destructive action. View shortcuts do not act behind an open confirmation.

| Shortcut | Action |
|---|---|
| Enter in Message | Send or run the selected slash command; not during IME composition. |
| Shift+Enter | Insert a newline. |
| Ctrl+. in Message | Ask the current request to stop; completed effects remain. |
| Ctrl+Shift+F | Show/hide conversation search. |
| Ctrl+, | Open Settings, or return to chat. |
| Ctrl+W | Close/hide the window, not stop Odin. |
| Ctrl+Q | Exit Odin, including without a tray. |

With slash suggestions open, Up/Down selects, Home/End moves to an endpoint, Tab
completes once, and Escape dismisses suggestions without discarding the draft.
The next Tab can leave Message.

## Common tasks

1. Tab to **Settings** and press Enter. Navigate to **Models and providers** or
   another section; **Back to chat** returns to chat.
2. Tab to **New conversation**, activate it and move to **Message**. Type a request and send
   with Enter, or use Shift+Enter for more lines.
3. Tab to **Attach files**. Choose a file in the desktop dialog, or Escape to
   cancel. Check its named upload state and Remove control.
4. On a reply, activate **Copy**, choose Markdown or plain text, and return to its
   opener. On a file card, **Save as…** opens the native destination dialog.
5. Use Ctrl+Shift+F, enter search terms and open a hit. **Back to latest** returns
   to current messages. Tab to **Conversation history** to scroll by keyboard.
6. Open the conversation's named **Actions** menu. Use arrows and Escape. In
   Rename or another dialog, Tab in either direction stays inside until dismissed.
7. Use the **View** menu's zoom controls to enlarge content. Message, Settings,
   errors and result controls remain in scrollable regions when enlarged.
8. Reopen Odin from the launcher after Close, then use Ctrl+Q to Exit.

Use the Work column and report controls described in
[Background work](background-work.md). A service refusal is not an empty list
or proof a task completed.

## Screen readers and privacy

Controls, errors and file actions have contextual names. Task announcements
describe busy, queued, consumed, completed or unknown states. The transcript
does not read every tool output or unfinished draft aloud; navigate history to
read committed replies. Password fields are write-only. Temporary provider
sign-in codes are readable because you need them to finish login.

Notification previews are on by default. Turn them off in **General** if others
could see or hear them. Copied text goes to the system clipboard, which other
apps may inspect. Do not record credentials or private history in screenshots,
screen-reader recordings or support attachments.

## Limits and reporting a problem

Keyboard navigation, enlarged layout and named controls do not guarantee Orca
speech or that every desktop's native dialogs, keyring prompts, portals, tray and
notifications work. The **1.0.0 app supports Cinnamon/X11, GNOME/Wayland,
KDE/Wayland and Hyprland**, but that scope does not claim complete native
screen-reader coverage. **Computer use is supported on X11 only, at parity with
Odin**; Wayland computer use is planned for **1.1** and is refused with guidance
until then. Actual accessibility behavior can depend on desktop, screen reader
and display setup.

The current Raven interface has been exercised with Orca in isolated
Cinnamon/X11 and GNOME/Wayland sessions: all seven task groups passed in each.
KDE/Wayland passed six of seven; the native Attach dialog was visible but its
controls were unavailable to the screen reader. Do not assume accessible
Attach/Save on KDE. This limitation remains recorded; the
[Linux release checklist](../release/linux-v1-checklist.md) defines the current
candidate gate rather than the earlier P3.6/D11 matrix. These observations do
not claim every desktop or version was tested, including Hyprland screen-reader
coverage.

Report app version, package format, desktop/session (**X11** or **Wayland**),
screen reader/version, zoom/scaling, control name, expected result and actual
result. Reproduce with non-private content. Preserve unknown or quarantined
state rather than repeating input to demonstrate it. See [Recovery](recovery.md).
