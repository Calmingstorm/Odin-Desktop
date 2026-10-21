# Install Odin Desktop on macOS

Odin Desktop for macOS is an app for **Macs with Apple silicon** (M1 or later) on **macOS 26 or later**. It runs
the same local engine as the Linux and Windows apps, with the same chats, tools, memory, knowledge, background work,
hosts, MCP servers and skills. Computer use isn't available on macOS yet. Intel Macs aren't supported.

## Download and check the file

Download `odin-desktop-<version>-arm64.dmg` and `SHA256SUMS` from
[Releases](https://github.com/Calmingstorm/Odin-Desktop/releases), and read the release notes. Before you open the
disk image, compare its SHA-256 with the value in `SHA256SUMS`, in Terminal:

```sh
shasum -a 256 ~/Downloads/odin-desktop-1.4.0-arm64.dmg
```

The two must match exactly. The app and the disk image are **signed by Aaron Charpentier** with his Apple
Developer ID and **notarized by Apple**, so macOS opens them without a warning. To see that for yourself after
installing:

```sh
spctl --assess --type execute -vv /Applications/Odin.app
```

It answers `accepted`, `source=Notarized Developer ID` and `origin=Developer ID Application: Aaron Charpentier
(3HSA4RMW29)`.

## Install

Open the disk image and drag **Odin** onto **Applications**, then eject the disk image. Nothing starts until you
open Odin from Applications, Launchpad or Spotlight.

Each start first checks the files Odin ships inside the app (its engine, Python runtime, browser and search model)
against the list they were built with. It takes a second or two before the window appears. A damaged or changed
copy is refused with **Odin didn't start** and what to do; nothing is changed.

## Quit, close and start at login

Closing the window (**⌘W**) keeps Odin running: background work and schedules carry on, and Odin's icon stays in
the menu bar. Click the Dock icon, or **Open Odin** in the menu bar icon's menu, to bring the window back.

To stop Odin, choose **Odin → Quit Odin** (**⌘Q**) or **Exit Odin** from the menu bar icon. Quitting stops Odin's
engine and its background work, and records whether the cleanup finished.

**Start Odin when you log in** is in Settings → General. Odin then starts hidden, with its menu bar icon, and is
listed in System Settings → General → Login Items & Extensions.

## Notifications and privacy

Odin notifies you when a reply or a reminder arrives while its window isn't in front. The first time, macOS asks
whether to allow Odin's notifications; change that later in System Settings → Notifications → Odin, and Odin's own
choices (previews, quiet hours) in Settings → General → **Desktop notifications**.

When a command or a file tool reaches into Desktop, Documents, Downloads, an external drive or a network drive,
macOS asks whether Odin may. If you decline, the command fails with "Operation not permitted", and Odin's result
says where to allow it: System Settings → Privacy & Security → Files and Folders (or Full Disk Access).

## Your tools

Odin runs commands in bash: Homebrew's, when you have it, otherwise macOS's own. Its PATH starts with Homebrew's
folders (`/opt/homebrew/bin`, `/opt/homebrew/sbin`), then the folders in `/etc/paths` and `/etc/paths.d`, then the
PATH macOS gives apps. No shell startup file is run, so a folder you add only in `~/.zshrc` or `~/.zprofile` isn't
on it: add a file naming the folder to `/etc/paths.d`, or run the tool by its full path. Built-in features need
nothing installed: Odin brings its own Python, browser and search model, and downloads the PDF reader on first use.

macOS's command-line tools are BSD's, not GNU's, so some options differ from Linux; Odin knows it's on a Mac. Your
hosts are unaffected: Odin still sends Linux commands to Linux machines.

## Your profile and privacy

| What | Where |
|---|---|
| Settings, chats and records | `~/Library/odin-desktop/default`, readable only by your account |
| Odin's working folder for tools | `~/Library/odin-desktop/.odin-desktop-workspaces/default` |
| Caches and attachments | `~/Library/Caches/odin-desktop/default` |
| Provider and API credentials (your ChatGPT sign-in, API keys, MCP server secrets) | Your login Keychain |
| Odin's SSH key for your hosts | `~/Library/odin-desktop/default/data/secrets/id_ed25519`, a file readable only by your account, as on Linux |
| The window's own state | `~/Library/Application Support/odin-desktop` |

In Keychain Access, Odin's credentials are the items whose name reads `Password for '<setting>' on
'odin-desktop:default:…'`; searching for `odin-desktop` finds them. Credentials have no plain-text fallback: if the
login Keychain is locked or refuses, Odin says so and offers to try again.

## Update

1. Download the newer disk image and check it the same way.
2. Quit Odin (**⌘Q**, or **Exit Odin** from the menu bar icon) and wait for it to close. Closing the window isn't
   quitting.
3. Drag the new **Odin** onto **Applications** and choose **Replace**. Your profile is kept.
4. Open Odin. Its first start checks the new copy and the end of the previous session:
   - **"An earlier Odin is still stopping"**: wait a minute, then open Odin again.
   - **"Odin was replaced after a session that ended without confirmed cleanup since this Mac started"**: Odin
     ended without confirming its cleanup (a crash, a force quit or a power cut). Restart the Mac, then open Odin.
   - **"Odin's app files don't match the ones that were installed"**: the copy is damaged or incomplete. Drag Odin
     from the disk image again.

Settings → General → **Check for updates** offers a Mac update only when the newer release carries a Mac disk image.

## Uninstall

Turn off **Start Odin when you log in** first, then quit Odin and drag it from Applications to the Trash. This keeps
your profile. To remove it as well, delete `~/Library/odin-desktop`, `~/Library/Caches/odin-desktop` and
`~/Library/Application Support/odin-desktop`, and in Keychain Access delete the items a search for `odin-desktop`
finds.

## Known limits

- **Computer use** isn't available on macOS yet.
- **Stopping background work is a best effort.** Each background command runs in its own session, and Stop, Quit
  and cleanup stop that session and check it until it stays quiet. A program that detaches into a session of its
  own can outlive them, so the result always says the cleanup is best effort ("detached or raced descendants are
  unverified"), never verified.
- **Shortcuts:** the app menu uses ⌘ (⌘W closes the window, ⌘Q quits). The shortcuts inside the window use Control,
  as on Linux: **⌃,** for Settings, **⌃⇧F** for search and **⌃.** to stop a request.
- **Schedules** can run late while the Mac sleeps; they don't wake it.
- **Finder replaces a running app** without asking Odin: quit Odin before replacing it. The start check then finds
  a changed or incomplete copy, but it can't undo the replacement.
