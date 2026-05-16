"""Secret redaction for logs and serialized output."""
from __future__ import annotations

from typing import Any

SENSITIVE_KEYS = frozenset({
    "password", "passwd", "token", "api_key", "apikey", "secret",
    "auth", "credential", "credentials", "smtp_pass", "smtp_password",
    "oci_key", "private_key", "privatekey", "access_key", "secret_key",
    "authorization", "x_auth_token", "bearer", "signing_key",
})

_REPLACEMENT = "***REDACTED***"


def _is_sensitive(key: str) -> bool:
    k = key.lower().replace("-", "_").replace(" ", "_")
    return any(s in k for s in SENSITIVE_KEYS)


def _redact_value(value: Any, replacement: str) -> Any:
    """Mask bare OCID values in logs regardless of key name."""
    if isinstance(value, str) and value.startswith("ocid1.") and len(value) > 20:
        return value[:-20] + "***"
    return value


def redact_secrets(obj: Any, replacement: str = _REPLACEMENT) -> Any:
    """
    Recursively walk dicts and lists, replacing values whose key matches
    a sensitive pattern with *replacement*. Also masks bare OCID values.
    """
    if isinstance(obj, dict):
        return {
            k: replacement if _is_sensitive(str(k)) else redact_secrets(_redact_value(v, replacement), replacement)
            for k, v in obj.items()
        }
    if isinstance(obj, list):
        return [redact_secrets(item, replacement) for item in obj]
    if isinstance(obj, str):
        return _redact_value(obj, replacement)
    return obj


def structlog_redact_processor(logger: Any, method: str, event_dict: dict) -> dict:
    """structlog processor that redacts secrets from the event dict."""
    return redact_secrets(event_dict)
