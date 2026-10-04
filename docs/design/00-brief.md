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
- Existing personality and system-prompt text never changes. New tool guidance belongs in tool descriptions, not in new
  always-on prompt lines.
- Other people will install this, so we design for every install, not only Aaron's.
- Removed features leave no references behind.
