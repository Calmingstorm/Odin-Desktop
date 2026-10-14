"""macOS: the command tools' descriptions name the bash found and say the Mac's tools differ.

Odin's ``apply_shell_contracts`` adds one live sentence per command tool naming the local shell.
On a Mac that sentence also says which bash it is, by its path alone (Odin's shell selection runs
no probes): ``/bin/bash`` is Apple's bash 3.2 on every macOS, and any other is the user's own
(Homebrew's, usually). It adds that the system's own tools are the BSD versions, not GNU. Remote
clauses and the refusal wording are Linux's. Each clause starts with Linux's marker, so a
decorated catalog is redecorated cleanly.
"""
from __future__ import annotations

APPLE_BASH = "/bin/bash"
TOOLS = ("where the system's own tools are the BSD versions, not GNU (for example sed -i needs a "
         "suffix argument, and stock macOS has no timeout command)")
_MARKERS = (" Local commands run under ", " New local commands are refused because ",
            " New local jobs run under ", " New local jobs are refused because ",
            " Local command checks run under ", " New local command checks are refused because ")


def shell_label(choice) -> str:
    """The shell as the descriptions name it: Apple's bash 3.2, or which one it is."""
    if choice.name == "bash" and choice.executable == APPLE_BASH:
        return f"Apple's bash 3.2 ({APPLE_BASH})"
    return f"{choice.name} ({choice.executable})"


def apply_shell_contracts(definitions: list[dict], mode: str = "auto") -> list[dict]:
    """``apply_shell_contracts`` on macOS: Linux's sentences, with the shell and the Mac named."""
    from src.tools.command_shell import apply_shell_contracts as routed
    from src.tools.command_shell import resolve_local_shell

    try:
        label = shell_label(resolve_local_shell(mode))
    except FileNotFoundError:
        return routed.linux_original(definitions, mode)  # a refusal reads as on Linux
    command = f"Local commands run under {label} on this Mac, {TOOLS}"
    clauses = {
        "run_command": f"{command}; remote commands use the remote account's login shell.",
        "run_command_multi": f"{command}; remote commands use the remote account's login shell.",
        "manage_process": f"New local jobs run under {label} on this Mac; remote jobs run under "
                          "/bin/sh.",
        "validate_action": f"Local command checks run under {label} on this Mac; remote command "
                           "checks use the remote account's login shell.",
    }
    result = []
    for tool in definitions:
        name = tool["name"]
        description = tool["description"]
        if name in clauses:
            body, separator, footer = description.partition("\n\n[affordances:")
            for marker in _MARKERS:
                body = body.partition(marker)[0]
            description = body + " " + clauses[name] + separator + footer
        result.append({**tool, "description": description})
    return result
