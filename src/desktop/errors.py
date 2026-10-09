"""Unavailable results never authorize effect replay."""

import re


class CapabilityUnavailableError(RuntimeError):
    """A required capability/consumer has no admitted route."""


CapabilityUnavailable = CapabilityUnavailableError


class NoLLMProviderError(RuntimeError):
    """The admitted request has no selected provider, not a runner failure."""


# Credentials a refused value can carry, which the shared scrubber does not mask: a
# URL's userinfo (plain or percent-encoded) and a bare user:password@host.
_URL_USERINFO = re.compile(r"(?i)\b([a-z][a-z0-9+.\-]*://)[^\s/?#@'\"]+@")
_ENCODED_USERINFO = re.compile(r"(?i)\b([a-z][a-z0-9+.\-]*%3a%2f%2f)[^\s/?#@'\"]+?%40")
_BARE_USERINFO = re.compile(r"(?<![\w/:%.@-])([^\s:/@'\"]+):[^\s/@'\"]+@(?=[a-z0-9.\-]+)", re.I)


def _scrub_userinfo(text: str) -> str:
    text = _URL_USERINFO.sub(r"\1***@", text)
    text = _ENCODED_USERINFO.sub(r"\1***%40", text)
    return _BARE_USERINFO.sub(r"\1:***@", text)


def refusal_reason(error: Exception, fallback: str = "Invalid method parameters") -> str:
    """A validation refusal's own reason for a form: its first line, scrubbed and bounded.

    Refusals can echo what was typed, so a pasted credentialed URL is masked too.
    """
    from ..llm.secret_scrubber import scrub_output_secrets

    lines = [line.strip() for line in str(error).splitlines() if line.strip()]
    reason = _scrub_userinfo(scrub_output_secrets(lines[0]))[:300] if lines else ""
    return reason or fallback
