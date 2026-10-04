"""Neutral credential comparison, not an admission or identity issuer."""
import hmac


def credential_equals(left: str, right: str) -> bool:
    """Constant-time comparison supporting every configured UTF-8 credential."""
    return hmac.compare_digest(left.encode("utf-8"), right.encode("utf-8"))
