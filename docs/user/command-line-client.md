# Command-line client

Odin Desktop includes a small client for sending a prompt to the running app from a terminal or a
script. It connects to an already-running profile; it never starts the app or its engine.

## Connect and send a prompt

The client authenticates through the selected profile's private local socket and token file, and
prints only a committed, guarded reply. Supply `--socket`, `--token-file` and `--profile`, then a
positional prompt or `--prompt`. With no prompt argument, text piped on stdin is the prompt.

- `--conversation` continues an existing conversation; otherwise the client creates one.
- `--timeout` bounds the wait. A timeout isn't a cancellation, and the client never retries work the
  app has already accepted.
- `--json` prints the structured outcome, the conversation and request IDs, and the reply text.

## Diagnostics

Use `--method status.get` for the app's status. A positional `status.get` remains the older
spelling of the same diagnostic; use `--prompt status.get` to send that exact text as a prompt.

## What it is and isn't

The client is `python -m src.cli`, not the engine's own supervised `python -m src` entry. It adds no
network listener: there's no HTTP port, URL token, Discord gateway or daemon mode.
