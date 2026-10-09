"""Unavailable results never authorize effect replay."""


class CapabilityUnavailableError(RuntimeError):
    """A required capability/consumer has no admitted route."""


CapabilityUnavailable = CapabilityUnavailableError


class NoLLMProviderError(RuntimeError):
    """The admitted request has no selected provider, not a runner failure."""


def refusal_reason(error: Exception, fallback: str = "Invalid method parameters") -> str:
    """A validation refusal's own reason for a form: its first line, scrubbed and bounded."""
    from ..llm.secret_scrubber import scrub_output_secrets

    lines = [line.strip() for line in str(error).splitlines() if line.strip()]
    reason = scrub_output_secrets(lines[0])[:300] if lines else ""
    return reason or fallback
