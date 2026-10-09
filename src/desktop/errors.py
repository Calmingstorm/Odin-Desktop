"""Unavailable results never authorize effect replay."""

import re


class CapabilityUnavailableError(RuntimeError):
    """A required capability/consumer has no admitted route."""


CapabilityUnavailable = CapabilityUnavailableError


class NoLLMProviderError(RuntimeError):
    """The admitted request has no selected provider, not a runner failure."""


# Credentials a refused value can carry, which the shared scrubber does not mask.
# A URL's userinfo is read as urlsplit reads it: from the "//" to the authority's last
# "@", the authority ending at "/", "?", "#" or whitespace. So quotes, a raw "@" and
# every RFC 3986 sub-delimiter in a password are masked with it. A URL encoded once or
# twice (encodeURIComponent leaves ' ( ) ! * as they are) keeps that shape, with "/",
# "?", "#" and "@" encoded. Each scan starts at its "//" and stops where the next could
# start, so masking stays linear in an echoed value's length.
def _encoded_userinfo(pct: str) -> re.Pattern[str]:
    return re.compile(rf"(?i)({pct}2f{pct}2f)(?:(?!{pct}(?:2f|3f|23))[^\s/?#])*({pct}40)")


_URL_USERINFO = (re.compile(r"(//)[^\s/?#]*(@)"), _encoded_userinfo("%"), _encoded_userinfo("%25"))
# A bare user:password@host: in a run free of whitespace and "/", everything from the
# first ":" to the last "@" before a host name.
_BARE_USERINFO = re.compile(r"(?<![^\s/])([^\s/:]*:)[^\s/]*(@[A-Za-z0-9][^\s/]*)")


def _scrub_userinfo(text: str) -> str:
    for pattern in (*_URL_USERINFO, _BARE_USERINFO):
        text = pattern.sub(r"\1***\2", text)
    return text


def refusal_reason(error: Exception, fallback: str = "Invalid method parameters") -> str:
    """A validation refusal's own reason for a form: its first line, scrubbed and bounded.

    Refusals can echo what was typed, so credentials in a pasted URL are masked too.
    """
    from ..llm.secret_scrubber import scrub_output_secrets

    lines = [line.strip() for line in str(error).splitlines() if line.strip()]
    reason = scrub_output_secrets(_scrub_userinfo(lines[0]))[:300] if lines else ""
    return reason or fallback
