# Changelog

## [1.5.0]

**A remote command stops when its call does, and a silent loop's quiet check is no longer an error.** Linux,
Windows and macOS (Odin 4.21.0).

- **A remote command stops with the call that ran it.** On a remote host, `run_command`, `run_script`,
  `run_command_multi` and `validate_action` checks now run under a small Python helper on the host that owns the
  command's processes. When the call is cancelled (stopping an agent from its Work card or with `kill_agent`,
  stopping the chat), times out, or Odin Desktop quits, the command gets TERM, then KILL 3 seconds later. Before,
  only the ssh client on this computer stopped, and the command kept running on the host.
  - Work a command starts in the background with its output sent elsewhere (`nohup job >/dev/null 2>&1 &`) keeps
    running, as before.
  - The host needs `python3` (on a Mac, the developer tools). Without it, the command runs as before, after a
    one-line notice in its output.
  - Output and exit codes are unchanged, except that a command killed by a signal now reports 128 plus the signal
    number, as a shell does (ssh reported 255).
  - The host's login shell reads its startup files once more per command.
- **A remote command that may have started is never sent twice.** A timeout or a lost connection (exit status
  255) used to send the same command again. It is now reported once and marked as an uncertain outcome, because
  the command may have run. On Linux and macOS, a shared connection that never reached the host is still retried,
  since nothing was sent. On Windows, which has no shared connections, such a command gets one attempt.
- **Windows: a command too long for Windows is refused before anything is sent.** Windows limits a program's
  command line to 32,767 characters, and the helper adds about 6,000. Quotes, backslashes, characters outside the
  Basic Multilingual Plane and scripts (sent base64-encoded) take more room than their length. The error gives the
  length and Windows' limit, and says that nothing was sent. Keep a remote command or script well under about
  19,000 characters, or put it in a file on the host.
- **Windows: if Windows doesn't confirm that the ssh client exited, the result says so.** The outcome is then
  marked uncertain, because the remote command may still be running.
- **A silent loop's quiet check is its answer.** A silent loop replies with nothing when there's nothing to report.
  Every provider treated that as a failed request: the Codex client sent it twice more and counted a failure. A
  reply that finished normally with no text is now the check's answer on its first request. Chat, agents and other
  loops keep the old handling.

Limits, as in Odin 4.21.0: processes that leave the command's process group or session, a helper killed with
SIGKILL, or a host failure are outside this cleanup. During a network outage it waits until the host notices the
closed connection. Odin's `read_channel` change doesn't apply: Desktop reads a conversation with
`read_conversation`.

## [1.4.1]

**Reading a folder on Windows, and stopping work that has already ended, now give Odin's own answers.** Linux,
Windows and macOS.

- **Windows: `read_file` on a folder says it is a directory.** Reads on the Windows computer itself don't go
  through a shell, and Windows can't open a folder, so reading one said "Permission denied" and Odin was offered
  `sudo`. It now says `Error: <path> is a directory, not a file.`, as on Linux and macOS, for a folder or a link to
  one. A file that really can't be opened still says "Permission denied".
- **Stopping or messaging work that has ended gets Odin's own answer.** `kill_agent`, `send_to_agent`,
  `cancel_task`, `stop_loop` and `manage_process` kill said only "bound work control is not available" when the
  agent, task, loop or process had ended or didn't exist. They now answer as Odin does:
  - `kill_agent` on a finished agent: "Agent '…' already in terminal state: completed. Kill signal sent to 0
    descendant(s)." This isn't an error.
  - An unknown ID: "Agent '…' not found.", "No task found with ID …", "No loop found with ID …" or "No process with
    PID …".
  - Something that has ended: "… is not running (status: …)" or "Process … already completed.".
  - `manage_process` kill reports these as failures, as Odin does. Before, they counted as successes.
- **Killing a finished agent still stops the agents it started that are running**, as Odin's `kill_agent` does.
  Once a finished agent had been cleared (five minutes after it ended), a kill no longer reached its sub-agents
  that were still running, or their background jobs. Each one is now stopped through its own Work card, which
  records the stop.
- Outbound webhooks no longer get a `loop.stopped` event when `stop_loop` stopped nothing.

## [1.4.0]

**Stopping an agent stops the background jobs it started, and a start on an unreachable host fails fast.** Linux,
Windows and macOS (Odin 4.20.0).

- **Cancelling an agent stops its background jobs.** Cancelling an agent from its Work card, or with Odin's
  `kill_agent`, now also stops the background processes that agent (and the agents it started) launched with
  `manage_process`, including one still starting. The cancel's receipt lists each job and how it ended.
  - When a stop can't be confirmed, the receipt says so (`outcome_unknown=true`), Odin keeps ownership of the job,
    and a shutdown or host revoke doesn't claim its cleanup is complete.
  - On macOS a stopped job is reported as a best-effort stop of its session, as macOS jobs already were.
  - The card stays "requested" until the jobs' cleanup has finished, never "done" before it.
  - Unchanged on purpose: an agent that finishes, fails or times out leaves its jobs running.
- **A remote background job makes one direct connection attempt.** When the host can't be reached, Odin says that
  nothing was started and retrying is safe, in seconds instead of after several retries. A failure that leaves the
  outcome uncertain is still reported as unknown and cleaned up as before. Other remote commands keep their retries.
- **`search_audit` returns one result per tool call**, showing approval and outcome separately (succeeded, failed,
  denied, cancelled, outcome_unknown, started), and its status filter matches those outcomes. Settings → Records
  still lists the raw audit records.
- **Search:** knowledge results say how they matched (similarity, keyword match), and exact ties put keyword hits
  first; history search keeps to its limit and refuses a blank query.
- **`read_file`** refuses a directory in both modes, raw reads work on hosts whose login shell is zsh (macOS), and
  numbered reads of non-UTF-8 files no longer start with gawk's locale warning. Windows reads of remote hosts get
  the same fixes.
- **`apply_patch`** ends lines added to an empty file with a newline, and gives an unterminated last line a line
  break when lines are added after it. Every other line ending is kept byte for byte.
- **Schedules:** a fixed-time schedule fires once, not twice, on the night clocks fall back.
- **Process output:** a poll offers more output only when some was actually held back.

## [1.3.3]

**A command that finished while Odin was busy keeps its real result.** Linux and macOS (Odin 4.19.2).

- **A finished local command no longer comes back as "Local command supervisor ownership lost".** Every local
  command runs under a small helper that confirms the command and everything it started have exited, reports that,
  then waits up to two seconds for Odin's acknowledgement. When Odin was busy for longer than that, the
  acknowledgement came too late, and the finished command was reported as a failure with an uncertain outcome,
  although its output and exit code had arrived. `run_command`, `read_file`, `run_script` and the other foreground
  local commands now return the real output and exit code in that case.
  - Unchanged on purpose: the command's cleanup is still recorded as unconfirmed, and every other failure (a
    timeout, a helper error, cancellation) is reported as before. Background processes (`manage_process`) behave as
    before.
  - The engine log's warning now names the failing stage, for example
    `Local supervisor settlement failed at ack (ConnectionResetError)`.
- Windows didn't have this problem: commands there run in a Windows job object, without this helper.

## [1.3.2]

**New large results keep their full output when storage is full, and an ambiguous patch says where it matched.**
Linux, Windows and macOS (Odin 4.19.1).

- **A full tool-output store makes room instead of refusing.** Odin keeps a full copy of each large tool result for
  up to 24 hours, so he can read past the start and end he sees first. The store holds 64 MiB. Before, once it was
  full, every new large result lost its middle for good while older results waited out their 24 hours. Now the
  oldest results expire early, oldest first, and only as far as the new one needs.
  - A tool output's **Kept until** time is now the latest it stays: it can go sooner when newer output needs the
    room, and reading it then says it is no longer available.
  - A result's files leave together with their manifest, and are held while their result is delivered, so the
    result's file reference is readable when the reply arrives.
- **`apply_patch` says where an ambiguous change matched.** When the unchanged lines around an edit appear in more
  than one place, the patch is still refused and nothing is written, but the error now names up to five matching
  lines, each with the line above it, and advice that fits the case, so Odin can fix the patch in one more try.

## [1.3.1]

**Exit ends cleanly on a slow, busy machine, so the next install doesn't ask for a restart.** Linux, Windows and macOS.

- **A slow shutdown is no longer recorded as unknown cleanup.** Right after Odin starts, or while an installer runs,
  a busy machine can keep Odin's core from answering for a few seconds. Exit gave the core 5 seconds in all to accept
  the shutdown, counting the answers to requests it was still working through, then recorded the cleanup as unknown
  even though the core went on to shut down in order. On Windows the next install or uninstall then refused until
  the computer restarted.
  - Exit now first lets the core answer what it was already asked, for as long as answers keep coming, then gives the
    shutdown request 10 seconds of its own. An acceptance that arrives while the core is being stopped still counts.
  - A core that answers nothing is stopped as before. A request that reaches its own deadline without an answer
    counts as no answer, so Exit doesn't wait on behind it. A frozen core takes at most about 5 seconds longer to
    stop.
- **The tool reference links `report_to_parent` to its source.** Its link pointed at an Odin revision older than the
  file and returned a 404; it now points at the revision Desktop carried it from.

## [1.3.0]

**Spawned agents can report back while they work.** Linux, Windows and macOS.

- **Interim reports from agents.** A new agent-only tool, `report_to_parent`, lets a spawned agent queue a report for
  whoever spawned it: its parent agent, or the conversation that started it. The agent gets a receipt at once and
  keeps working; the receipt confirms queuing, not reading. A report never wakes a wait or interrupts work. It is
  delivered at the recipient's next eligible step, in one message marked as agent-produced evidence, not
  instructions, and the recipient can answer with `send_to_agent`. Final results stay the complete record (Odin
  4.19).
  - Only spawned agents get the tool; conversations, loops, schedules and skills never do. It is listed in Settings →
    Tools → Built-in tools, so you can switch it off there.
  - Empty reports and reports over 12,000 characters are refused, and so are reports that would put the reports
    waiting for the recipient over 60,000 characters, reports from an agent that a schedule or loop started (there is
    no conversation to report to) and reports to a recipient that is stopping or closed. Refusals say why; reports
    are never truncated.
  - Waiting reports are held in memory and discarded unread when the recipient finishes, stops or is replaced, or the
    app quits. The sending agent's audit log and history keep the report text either way.
- **Agents are told which tool reports back.** `spawn_agent` now tells the model, when it wants interim reports, to
  brief agents with their agent-only `report_to_parent` tool rather than `send_to_agent`, and `send_to_agent` says
  the same. A live test showed a spawner briefing agents to report with `send_to_agent` (Odin 4.19).
- **Calls an agent holds back say why.** When a message from its parent, a stop or the lifetime limit comes before an
  agent's queued calls start, those calls are held back. They all read "Error (not_executed): Not executed: agent
  stopped or parent correction queued before dispatch.", so agents that should carry on read that they might be
  stopped. Each now names its cause. The one an agent actually reads says a message from its parent arrived first,
  that the call neither failed nor was stopped, and to reissue it only if it still fits that message (Odin 4.19).

## [1.2.2]

**The quota display, finished.** Linux, Windows and macOS.

- **"Limit reached" whenever the app stops using an account for its quota.** When OpenAI names the window that
  reached its limit, the app treats that window as limited until its reset, also when its percentage reads lower. The
  ChatGPT account list now says "Limit reached" for such an account instead of showing it as healthy. A 429 that the
  account's quota doesn't explain shows "Quota check failed" again (Odin 4.18.2, Odin #666).
- **No "Quota check failed" from a stale sign-in.** After the app sits closed for a while, the first quota check can
  meet an expired access token. It now refreshes the token once, the way replies do, and checks again; before, it
  showed "Quota check failed" until the next check (Odin 4.18.2).

## [1.2.1]

**Odin 4.18's prompt-cache fix on the desktop.** Linux, Windows and macOS.

- **ChatGPT requests reuse the prompt cache.** Each conversation sends its own random ID (a UUID the app generates)
  as the `session_id` header and as `prompt_cache_key`, so OpenAI's backend keeps that conversation's cached prompt
  on one machine. Before this, the app sent no such ID, and most follow-up requests inside a reply re-read the whole
  prompt: in a controlled test, no follow-up request reused any of the previous prompt, and with the ID every one
  reused all of it (90% of follow-up input cached; 91% was the maximum possible). Cached input is read faster, and
  OpenAI's Codex credit rate card bills it at a twentieth of the uncached rate (GPT-6.1 Sol); OpenAI doesn't publish
  how included plan limits count it.
  - Each conversation keeps its ID across replies, from history compaction before a reply to the reply after a
    skill hands off. Resetting a conversation's context starts a new ID, and IDs are kept in memory, so restarting
    the app starts new ones too.
  - A reply keeps the ID it started with, so a preserved request resumed after a context reset never joins the new
    conversation's cache (Odin 4.18.1).
  - Each spawned agent, loop and background task has its own ID for its whole run, as does each background
    reflection.
  - Image generation and the quota check send no ID.
- **An account at its usage limit no longer shows "Quota check failed".** The ChatGPT account list showed it under
  an account's "Limit reached · Resets …" line, because the quota check counted the 429 that an exhausted account
  answers with as a failed check. A 429 whose own quota shows the exhausted window, or names the reached limit, now
  counts as a successful check; one it doesn't explain still shows as a failure (Odin 4.18.1).
- **The app names itself on ChatGPT requests.** Every request to OpenAI's ChatGPT backend now sends
  `originator: odin` and `User-Agent: odin (<os>; <arch>)` instead of no originator and the HTTP library's default
  user agent. The browser sign-in link says `originator=odin` instead of `pi`.

## [1.2.0]

**Odin 4.17's agent vision on the desktop.** Linux, Windows and macOS.

- **Agents see images.** An agent that calls `analyze_image` now gets the picture as a real image, the way the main
  chat does. Until now it got an error saying image results were unsupported in spawned agents. The picture never
  enters tool result text, saved trajectories, the audit log or the agent's stored result. An agent on a model
  without vision still sends the image; if the provider can't take it, the request fails with the provider's own
  error, and there is no text fallback.
- **Agents drop images to fit a request only when it would otherwise fail.** While a request is being fitted, images
  the model has already seen are replaced, oldest first, by a one-line note:
  - when the context budget says the request won't fit and dropping seen images alone makes it fit;
  - when the provider reports a context overflow that no text compaction step can shrink;
  - when a Codex request would be over OpenAI's documented 512 MB limit. Such a request is never sent: it is fitted
    (seen images first, then text compaction, then unseen images) or the step fails with "Request exceeds the
    provider's size limit even without images".

  Images the model hasn't seen yet are left out, with a note saying so, only when nothing else makes the request fit.
  Ordinary history compaction, as before, can also summarize older steps that held images.
- **The repetition check counts pixels.** Looking at a file again after its picture changed is progress, not a
  repeated call.
- **A broken image result is a short error.** In agents, loops and scheduled steps, an image result that can't be
  delivered becomes a failed tool result, and its data never reaches the conversation, trajectories or audit log.
- **Scheduled steps that return images** post their text and `[N image(s) omitted from text output.]` instead of the
  image's base64 text.

## [1.1.1]

**Odin 4.16's reliability fixes on the desktop.** Linux, Windows and macOS.

- **Background-process commands no longer pick up stray text.** Odin filled in `manage_process` with six empty
  fields after a start's command. A model done with the command could not stop there, so a stray word, a period or
  even a second command ended up inside it: 3 of this app's first 6 process starts in testing. Each action now ends
  on its own fields. In Odin's live test this went from 14 of 60 to 0 of 60 starts (gpt-6-astra) and from 4 of 20
  to 0 of 20 (gpt-6.1-sol).
- **Knowledge and search reads are safe beside a write.** The knowledge store and the session archive store share
  one database connection across worker threads, and only writes were serialized. A list read beside a save could
  come back empty, and a saved archive could read back as missing. Every use of the connection now holds the store's
  lock.
- **The core stays responsive while knowledge is written.** Health, the `list_knowledge` tool, background tasks and
  imports read the knowledge store through a worker thread, and shutdown closes it there too, so a long write never
  stalls the core.

## [1.1.0]

**Odin 4.14 and 4.15 on the desktop, and a round of fixes.** Linux, Windows and macOS.

- **Hosts and checks (Odin 4.15 and 4.15.1):**
  - a check that `validate_action` runs on a Mac now uses macOS's own tools: launchd for services, the unified log
    for log checks (message text only), and a port check that needs no GNU tools. This covers the Mac Odin runs on
    and any host whose platform is macOS. Linux hosts keep their exact checks;
  - a log check reads the journal once. A read that fails is reported as an error, never as "not found";
  - a move in `apply_patch` that only changes a name's case now works where names ignore case (APFS on a Mac,
    NTFS on Windows). Another file, or a hard link under that name, still refuses before anything changes;
  - known-hosts files whose paths contain spaces, quotes or backslashes reach SSH as one file (Linux and Mac;
    Windows already did this);
  - a failed host test no longer reports a platform it never saw, and leaving a host's setup unfinished removes the
    trust file it made.
- **Tools (Odin 4.14):**
  - the command governor reads `rm`'s recursive and force options within their own command, so a path or a later
    command's flags no longer label a delete as recursive;
  - `fetch_url` retries once with a plain user agent after a 403 or 406;
  - `manage_list` can delete a whole list;
  - an aborted background task records every step it never ran as skipped;
  - history search results name the conversation they came from, and never return the asking request itself;
  - Codex account reloads follow each account, and its quota marks reset when its credentials change.
- **Settings (Odin 4.14):** about a hundred numeric settings now refuse out-of-range values when saved. A value
  already in your profile still loads, with a warning, and is never rewritten.
- **Work:** a card whose outcome can never be known (it ended without a record of how) can now be dismissed. Its
  history, audit entries and chat stay.
- **Fixed:**
  - after a crash or power cut during an install's bookkeeping, a leftover file blocked every later Linux package
    or AppImage update, and the Mac's start check, until removed by hand. Now it doesn't;
  - opening Odin again, or asking it to exit, while a packaged start was still checking its files was lost. Odin
    now does what was asked once the check finishes;
  - an Exit asked for while Odin was still starting ended it before its core had started, so the next install or
    update asked for a restart first. Odin now finishes starting its core (at most a minute), then exits cleanly;
  - on Linux, starting at login showed the window if it was last maximized. It now stays in the tray;
  - a loop that stopped itself ended without a notification. It now notifies, as a loop that runs out of
    iterations does;
  - notifications showed Markdown marks (`**`, backticks, links) literally. They now show plain text, as the chat
    does;
  - the engine reported its version as 0.0.0-dev. It now reports its release. The first start of a new version
    backs your profile up before any change, as the update guide always said, and keeps only the latest backup.
- **Smaller changes:** on a Mac, the window's shortcuts use ⌘ (⇧⌘F search, ⌘, settings, ⌘. stop). The governor
  setting now reads "Let your commands past the governor". Start at login on a Mac names the menu bar. Mac builds
  attach disk images with `diskutil`.
- See [Background work](docs/user/background-work.md) and [Updates](docs/user/updates.md).

## [1.0.10]

**Odin Desktop for macOS.** The first macOS release: a signed, notarized disk image for Macs with Apple silicon
on macOS 26 or later. The Linux packages and the Windows installer are rebuilt at 1.0.10 and behave as 1.0.9 did.

- **Install:** open `odin-desktop-1.0.10-arm64.dmg` and drag Odin to Applications. The app and the disk image
  are signed by Aaron Charpentier with his Apple Developer ID and notarized by Apple, so macOS opens them without a
  warning. Each start checks the files Odin ships inside the app, and refuses a damaged or changed copy.
- **The same Odin:** the same engine, tools and settings as on Linux and Windows, run locally: chats, tools,
  memory, knowledge search by meaning, schedules, agents and background work, hosts over SSH, MCP servers and
  skills, including skills with compiled Python packages. Computer use isn't available on macOS yet.
- **Background work:** each background command runs in its own session. Stop, Quit and cleanup stop that session
  as a best effort and say so: a program that detaches into a session of its own can outlive them.
- **Your tools:** commands run in bash, with Homebrew's folders and those in `/etc/paths` and `/etc/paths.d` on
  the PATH. Shell startup files such as `~/.zshrc` aren't run.
- **Your profile** lives in `~/Library/odin-desktop/default`, private to your account, and your provider and API
  credentials in your login Keychain. Dragging Odin to the Trash keeps both.
- **Quit and start at login:** closing the window keeps Odin running in the menu bar, and **⌘Q** quits. **Start
  Odin when you log in** is in Settings → General.
- **Updates:** quit Odin, then drag the new version over the old one. If Odin ended without confirmed cleanup since
  the Mac started, the new version asks you to restart the Mac first.
- See [Install on macOS](docs/user/install-macos.md).

## [1.0.9]

**Agent models save, and the list is compact.** Linux and Windows.

- **Fixed: agent candidates with their own reasoning effort didn't save.** Saving showed
  "agents.auto_model_allowlist.0.model: changed through settings.set", kept "Unsaved changes", and the choice was gone
  on return. Editing a model's description failed the same way. Both now save.
- **A compact model list:** each model is one line, with its description, its reasoning effort and its order. The full
  description, editing it, a thinking mode where the model has one, and any notes open with the row's details toggle.
- See [Settings](docs/user/settings.md).

## [1.0.8]

**Sign in from chat, and an agent model list that saves.** On first open, signing in happens right in
the chat. Choosing which models agents may use is now a checklist, and saving it works. Linux and
Windows.

- **Sign in from chat:** on first open, chat shows **Sign in to start chatting** with **Sign in with
  ChatGPT**. The sign-in link and code appear in the banner, and the message box takes focus once Odin
  is ready. **Use another provider** and **Import from Odin** go straight to their place in Settings.
  After **Set up later**, a note by the message box offers **Show setup**, and a message sent before
  signing in stays in the box instead of failing.
- **Agent models are a checklist:** with **Choose automatically**, **Models Odin can choose from**
  lists each model with a checkbox and the description Odin itself uses for it. With nothing chosen,
  Odin's default models show ticked, as the engine actually uses them. Tick, untick and reorder models,
  set a per-model reasoning effort, or replace a description with your own.
- **Fixed: saving automatic candidates failed** on every install with "The save outcome could not be
  confirmed", and nothing was saved: the page handed Electron a live list it can't copy. Every call
  from the page to the engine now sends plain data, and a test fails if any code skips that.
- **Fixed:** a reasoning-effort error stayed on screen after a later save succeeded.
- See [First run](docs/user/first-run.md) and [Settings](docs/user/settings.md).

## [1.0.7]

**A signed Windows installer.** The Windows installer, the Odin app and its uninstaller are now
code-signed by **Aaron Charpentier** through Microsoft's Artifact Signing. The Linux packages are
rebuilt at 1.0.7 and behave as 1.0.6 did.

- **Windows names the publisher:** the installer's Properties → Digital Signatures, and SmartScreen's
  **More info**, show Aaron Charpentier instead of an unknown publisher. SmartScreen can still ask
  first while a new release builds its reputation: choose **More info**, check the publisher, then
  **Run anyway**.
- **Smart App Control** still blocks Odin when it's on: some parts the app bundles, its Python
  runtime among them, aren't signed yet.
- **Checked on every release:** the release build checks each signature (valid, by the expected
  publisher, timestamped), and its install test checks the installer, the installed app and its
  uninstaller.
- **Updating from 1.0.6:** run the new installer while Odin is closed (**Exit Odin** from its tray
  icon), as before. Your profile and settings stay.
- See [Install on Windows](docs/user/install-windows.md).

## [1.0.6]

**Odin Desktop for Windows.** The first Windows release: a per-user installer for 64-bit Windows 11,
built and checked by its own release workflow. The Linux packages are rebuilt at 1.0.6 and behave as
1.0.5 did.

- **Install:** `odin-desktop-1.0.6-x64-setup.exe` installs for your account only, into
  `%LOCALAPPDATA%\Programs\Odin`, with a Start menu entry and without administrator rights. Nothing
  starts when it finishes. It refuses to run elevated (Run as administrator), and so does the app.
- **Unsigned:** the installer and the app aren't code-signed yet. Check the file's SHA-256 against
  `SHA256SUMS` first. Windows SmartScreen then shows "Windows protected your PC": choose **More info**,
  then **Run anyway**. Smart App Control, when it's on, blocks unsigned apps with no override, so Odin
  can't be installed there until it's signed.
- **The same Odin:** the same engine, tools and settings as on Linux, run locally: chats, tools,
  memory, knowledge, schedules, agents and background work, hosts over SSH, MCP servers and skills.
  Computer use isn't available on Windows yet.
- **Your profile** lives in `%LOCALAPPDATA%\odin-desktop\default`, private to your account.
  Uninstalling (Settings → Apps → Odin → Uninstall) removes the app and keeps the profile, as on
  Linux.
- **Start at login** is in Settings → General. Odin then starts hidden, in the notification area.
- **Updates:** run the newer installer. It refuses while Odin runs ("Choose Exit Odin from its tray
  icon"). After Odin ends without confirmed cleanup (a crash, or a power cut), installing and
  uninstalling wait for a restart of Windows, and say so.
- **Known limits** of this first Windows release are listed in
  [Windows install safety](docs/design/windows-install-safety.md#accepted-limits).
- See [Install on Windows](docs/user/install-windows.md).

## [1.0.5]

- **Fixed:** once an agent, task, loop or process had finished, the engine kept one CPU core at 100% until the app
  restarted. It now goes idle when the work ends.
- **Fixed:** an MCP server's tools never reached Odin in chats, even while Settings showed the server connected. Odin
  now sees and uses them.
- **Fixed:** knowledge search matched literal words only. It now uses the bundled search model and a full-text index,
  as Odin does. Documents saved before 1.0.5 are added to the full-text index at the first start, in one quick step.
  If the search model can't load, search still matches words.
- **Fixed:** the auxiliary (background) model didn't start with the app, so summaries and background follow-ups ran
  on the main model until its setting was saved again. It now starts with the app.
- **Fixed:** reminders, finished background tasks and loop alerts never raised a desktop notification. They now do,
  under the same settings as replies: off, quiet hours, muted chats and the focused window.
- **Fixed:** a text attachment over 4 MiB failed the whole message. The message now goes through with the part of the
  file that fits, as in Odin.
- **Settings → Models:** the auxiliary model is chosen from the model list, like the main model. New profiles start
  it on gpt-6.1-sol; existing profiles keep their choice.
- **Fixed:** a cron schedule with no time zone runs on UTC, but Settings → Work called it "Odin's time zone", and its
  Next preview ignored the zone you picked. It now says UTC, the preview uses your zone, and a new schedule starts in
  Odin's time zone (Settings → General).
- A refused schedule or outbound webhook says why (a bad time zone, cron or run time; an unknown event or a blocked
  address) instead of "Invalid method parameters" or "invalid webhook configuration". A password in a pasted URL is
  masked in that reason.
- **Fixed:** `analyze_pdf` was never offered, so its PDF reader never downloaded. It is offered now and downloads the
  reader the first time it runs.
- **Fixed:** Odin couldn't open his own browser screenshots. Each one is also saved privately in the workspace
  folder (`screenshots/`), as generated images are.
- **Fixed:** failed image, file, screenshot, knowledge, scheduling and agent tool calls showed a green check. They
  now show as failures.
- **Fixed:** after Stop, an interrupted wait stayed "running" in the chat. It now shows as stopped.
- **Fixed:** a background task left a frozen progress post and posted its results twice. Its result now comes once;
  its Work card shows the progress.
- **Fixed:** after a restart, a finished process in Work showed "(retained output)" instead of its command.
- Work keeps the newest 50 finished items of each kind and drops the finished items of a deleted chat. Older finished
  items are removed; an item whose outcome isn't confirmed stays until it is.
- A webhook-triggered schedule's Work card says which webhook it waits for, and why it can't run while incoming
  webhooks are off.
- Each day of a chat starts with its date (Today, Yesterday or the date), and a message's time shows its full date
  on hover.
- Chat titles are one line: line breaks and control characters become spaces, and a blank rename is refused.
- Turning a skill off says what happened ("Turned off. Odin can't use it until it's turned on again.") instead of
  Odin's tool advice.
- On Linux, Odin is listed under Development (Programming in most menus) instead of Utility (Accessories), so docks
  and window lists that pick an icon by category show a coding icon.
- **Settings:** every page now follows the layout of General and Models. Data and privacy, Work, Tools, Hosts, MCP
  and Skills use labelled rows with a visible label for every control, put their actions in the section header,
  and show Save or Cancel only when something changed.
  - Knowledge details: pick documents from menus instead of typing their names, with readable results and the full
    record a click away. Adding a document is its own section.
  - Learned context lists its entries, with Edit and Delete in place.
  - Memory lists keys and values in aligned columns, and its editor is a bordered form.
  - Records lists trajectory files by name; choosing one fills in the file name. Closing SSH connection pools says
    what it closed.
  - Settings that can be left unset offer Default, so you can go back to the default.
  - Counts read "1 chunk", not "1 chunks". Tables no longer squeeze short cells to a letter per line.

## [1.0.4]

- **Fixed:** a schedule Odin set up in chat didn't appear in Work until its first run (or until Settings → Work was
  opened), so it had no Pause or Cancel there. Work now shows it as soon as Odin creates it, and a schedule Odin
  pauses or deletes in chat changes in Work right away. Schedules saved before 1.0.4 appear when the app starts.
- **Fixed:** the `/status`, `/usage` and `/reload` reports showed Markdown marks such as `**`. Their headings are bold
  and file names show as code, as in Odin's replies on Discord, and each line keeps its layout.

## [1.0.3]

- **Your name and picture in chat:** Settings → General → Your profile. Your messages show them instead of "You",
  and Odin calls you by that name.
- **A picture for each personality:** Settings → Personality. Replies show the active personality's picture, so a
  custom personality such as Clippy can have its own face. Without a picture, the Odin mark stays.
- Pictures stay on this computer. The app crops a PNG, JPEG or WebP image (up to 2 MB) to its centred square and keeps
  a 256 × 256 copy in your profile. Odin and the model never see your pictures.

## [1.0.2]

- **Fixed:** the "unknown outcome" line under a task, and the status bar count, never went away. They now have a
  Dismiss button. Dismissing hides the notice only: the actions stay unknown and are never repeated.
- **Fixed:** Odin couldn't look at an image he had just generated. Each generated image is also saved privately in
  the workspace folder (`generated-images/`), and Odin is told where, so he can describe it or post it again.
- **Fixed:** a one-time schedule that had run stayed under Scheduled in Work, shown as still running. It now moves to
  Finished with its run's result. A deleted schedule moves to Finished too: `cancelled` if it never ran, otherwise
  its last run's result, or `unknown` when that result was never recorded. Schedules deleted, and one-time
  schedules that finished, before 1.0.2 show as `unknown`, because their last run can't be confirmed.
- **Fixed:** Settings, Records reported "unhealthy" with chat history, knowledge, the scheduler, loops and agents "not
  initialised" while all of them worked.
- **Fixed:** some tool calls, such as `schedule_task`, showed no details when expanded.
- **Fixed:** `/status` and Settings showed the engine as 0.1.0.dev1. They now show the release number.
- Notices, Steer and Stop lines and task outcome lines line up with the messages, and Steer and Stop lines go away
  when their task ends. A stopped task no longer says so twice.
- While Stop waits for a running step to finish, the button and the working line name the step and how long it has
  been running.
- Work cards show what each item is, a plain state, local times, the result or last error, and their buttons, without
  internal identifiers.
- The window no longer scrolls past the bottom of the app.
- Tool rows no longer repeat the tool name.
- Every line in the engine log starts with its date, time, level and source.

## [1.0.1]

- **Fixed:** a saved personality, such as one brought over with Import from Odin, applied only until the app
  restarted. After a restart Odin Desktop answered as Odin again. Saved personalities now apply from the first
  message after every start.
- The chat names the assistant after the active personality: replies, the message box, the empty chat, the working,
  Steer and resume text, and their screen-reader announcements use its name, for example Clippy. The window title
  and the tray still say Odin.
- Settings, Personality lists saved presets by their own names, so presets that share a display name can be told
  apart.
- Settings, Models: each automatic agent candidate has a description field, as in Odin's own settings. It tells
  automatic selection which tasks suit that model, and it saves with the other agent settings.

## [1.0.0]

The first release of Odin Desktop, a desktop app for [Odin](https://github.com/Calmingstorm/Odin),
the self-hosted AI execution agent. It runs Odin's engine on your own computer with a
profile of its own, with or without an existing Odin install.

- Chat with Odin's local engine, search conversations, attach files, keep knowledge,
  and save results. Follow tool activity and use Stop, Steer or Resume with explicit
  outcomes rather than treating a submitted request as completed work.
- Manage providers and models, tools, managed SSH hosts, skills and MCP servers,
  memory and records. Run background work, schedules and stored reports from the app.
- Settings are plain-language pages rather than raw configuration keys. Switch the
  main model and its reasoning level from the header. The window remembers its size
  and position, and first-run setup appears only until it is done or skipped.
- **Import from Odin** (Settings, General, Support and advanced) brings memory, skills,
  MCP servers, personality, managed hosts and model settings over from an Odin install,
  using its admin API token for that import only. It never replaces anything that
  already exists. Skills that are off in Odin arrive off and MCP servers arrive switched
  off. Secrets Odin never returns, such as API keys and MCP environment and header
  values, have to be entered again. A host is added once Odin Desktop's own SSH key
  can sign in to it.
- The app is supported on **Cinnamon/X11, GNOME/Wayland, KDE/Wayland and Hyprland**.
  Closing the window leaves Odin running; use Exit Odin to stop it. Login startup
  is optional, and shutdown, reboot and logout request bounded orderly Exit.
- **Computer use is supported on X11 only, at parity with Odin.** Wayland computer
  use is planned for **1.1**; until then the app refuses it with guidance. App
  support on a Wayland desktop does not imply mouse/keyboard automation support.
- Linux x86-64 **unsigned `.deb` and AppImage** packages bundle the normal runtime;
  on Arch and other distributions without `.deb` support, use the AppImage.
  Verify the supplied SHA-256; it is not a publisher signature. AppImage still
  requires compatible FUSE and user-namespace/sandbox policy; use the `.deb` where
  supported if AppImage startup is refused. Do not disable the sandbox.
- PDF support is downloaded automatically on first use, pinned by hash. If that
  download fails, a later use can retry.
- Install and upgrade manually through your package manager or by replacing the
  AppImage after clean Exit. The app can check for release notices, but does not
  download or install updates, restart itself, or replay work after an upgrade.
  Its profile stays separate from an existing Odin installation.
- Planned for **1.1**: Wayland computer-use integration and the remaining native
  harness follow-ups. The [user guides](https://github.com/Calmingstorm/Odin-Desktop#user-guide)
  cover installation and recovery limits.

## [0.1.0]

Unreleased desktop candidate. These are curated rehearsal notes, not acceptance
or publication authorization.

- Electron desktop application with local core integration and explicit settings.
- Linux x86-64 `.deb` and AppImage candidates with a bundled runtime.
- Ownership and alongside-installation boundaries separate this product from an
  existing Odin installation.
- Installation and upgrades remain manual user actions. No in-app downloader,
  installer, update feed or automatic restart is introduced.

The current publication gate is the
[Linux release checklist](docs/release/linux-v1-checklist.md), which supersedes
the earlier Phase 3/4 release procedure.
