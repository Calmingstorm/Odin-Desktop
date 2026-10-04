# Odin Desktop: brief

Owner: Claude. This file records what Aaron asked for. It changes only when Aaron changes the ask.

## Aaron's ask (verbatim, 2026-10-04)

> Scope out Odin Desktop with Odin, you two plan extensively, no code. It would be an app that ran, had the ability to
> run at startup, and could be installed instead of or alongside existing Odin, its chat interface would need to be
> every bit as capable, or more capable than interfacing with Odin via Discord, webui chat doesnt really meet that bar.
> We would start with linux only, but would eventually want to build out windows and mac clients also. You two will
> work together in a design gist, or make an Odin-Desktop repository/project to work out of. It will live in a separate
> repo, most of odins code can/will likely get re-used, functionality should be at parity or better, but with things
> that are not relevant to Odin-Desktop removed (user access control, etc).

## Requirements as stated

| ID | Requirement |
|---|---|
| R1 | A desktop app that runs on the user's machine. |
| R2 | It can run at startup. |
| R3 | It can be installed instead of, or alongside, an existing Odin install. |
| R4 | Its chat is at least as capable as using Odin through Discord, and ideally more capable. Today's WebUI chat does not meet that bar. |
| R5 | Linux first. Windows and macOS clients come later, so the design must not lock us into Linux. |
| R6 | It lives in its own repository (this one). Most of Odin's code is expected to be reused. |
| R7 | Functionality is at parity with Odin or better, with things that don't apply to a personal desktop removed (user access control and the like). |

## Phase rules

- **Design only.** No code, prototypes, dependency installs, build tooling, or changes to the Odin repository or to any
  live Odin install.
- **Deliverable:** a complete plan that Aaron can approve or change. It covers product scope, the chat experience,
  architecture, a reuse map, packaging and startup, cross-platform, a phased roadmap, risks, and the decisions that are
  Aaron's.

## Carried over from Odin

These are Odin's standing decisions. Each one applies unchanged to Odin Desktop unless Aaron says otherwise.

- The anti-hedging guards, the completion classifier and the response guards are never weakened.
- A feature that is not configured exposes no tools.
- Existing personality and system-prompt text never changes, except that the Desktop prompt drops its Discord references
  (D1 below). New tool guidance belongs in tool descriptions, not in new always-on prompt lines.
- Other people will install this, so we design for every install, not only Aaron's.
- Removed features leave no references behind.

## Aaron's decisions (2026-10-04, after round 1)

> obviously his prompt would change to not mention discord, as far as what to import from my current odin, if you
> mean like my memory etc? this is a project for all users, we would address that separately, features/functionality
> should all make their way over from the normal Odin app to Odin Desktop, agents, anti hedging, continuation, etc, he
> should "work" the exact same way, but just with a new interface and be reliant on the application being running/in
> system tray by default when closed unless right clicked and exited, etc, not sure what you mean about where the shared
> core lives, you would take what you need from Odin and bring it over to Odin Desktop, and we would maintain both when
> doing updates etc. As far as reach odin from phone, for Odin Desktop, that wont immediately be available.

| ID | Decision |
|---|---|
| D1 | **Prompt.** Odin Desktop's prompt text does not mention Discord. Only the Discord references change. The rest of the personality and system prompt stays the same, and Aaron approves the exact wording ([`prompt-changes.md`](prompt-changes.md)). This replaces the round-1 assumption that the bytes stay unchanged. |
| D2 | **Behaviour.** Odin works exactly the same: every feature and function comes over, including agents, anti-hedging, continuation and the rest. Only the interface is new. |
| D3 | **Lifecycle.** Odin runs while the application is running. Closing the window leaves it in the system tray, still working. Odin stops only when the user right-clicks the tray icon and chooses Exit. |
| D4 | **Code.** Take what's needed from Odin and bring it into Odin Desktop. Both repositories are maintained when updates are made. There is no shared core package and no extraction campaign in the Odin repository. |
| D5 | **Importing an existing user's data** (memory and so on) is out of scope. It will be handled separately later. |
| D6 | **Phone and remote access** is not in the first versions. |
