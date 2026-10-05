"""Unavailable results never authorize effect replay."""


class CapabilityUnavailableError(RuntimeError):
    """A required capability/consumer has no admitted route."""


CapabilityUnavailable = CapabilityUnavailableError


class NoLLMProviderError(RuntimeError):
    """The admitted request has no selected provider, not a runner failure."""
