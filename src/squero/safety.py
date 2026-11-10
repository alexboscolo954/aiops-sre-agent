"""Output hygiene for anything that reaches the model: redact secrets, cap size.

Tool output is untrusted (pod logs, events, alert annotations) and lands in the
model's context, so it is scrubbed and bounded before it gets there.
"""

import re
from typing import Any

_REDACTED = "[REDACTED]"

# ponytail: regex redaction catches common token shapes, not every secret.
# The real control is not exposing secret values at all (env values and
# Secret objects are never read by the tools).
_PATTERNS = [
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----", re.S),
    re.compile(r"\beyJ[\w-]{10,}\.[\w-]{10,}\.[\w-]{10,}"),  # JWT
    re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"),  # AWS access key id
    re.compile(r"\b(?:sk|pk|rk)-[A-Za-z0-9_-]{16,}"),  # sk-... style API keys
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}"),  # GitHub tokens
    re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}"),  # Slack tokens
    re.compile(r"(?i)((?:bearer|basic)\s+)[A-Za-z0-9._~+/-]{12,}=*"),
    # key=value, key: value, and the JSON / Python-dict forms "key": "value",
    # 'key': 'value', which is how tool results are stored.
    re.compile(
        r"(?i)((?:password|passwd|secret|token|api[_-]?key|access[_-]?key)[\"']?\s*[=:]\s*[\"']?)"
        r"[^\s\"',;]{4,}"
    ),
]


def redact(text: str) -> str:
    for pattern in _PATTERNS:
        if pattern.groups:
            text = pattern.sub(lambda m: m.group(1) + _REDACTED, text)
        else:
            text = pattern.sub(_REDACTED, text)
    return text


def truncate(text: str, limit: int, keep: str = "head") -> str:
    """Cap text at `limit` chars. keep="tail" keeps the end (right for logs)."""
    if len(text) <= limit:
        return text
    cut = len(text) - limit
    marker = f"\n...[truncated {cut} chars]...\n"
    if keep == "tail":
        return marker + text[-limit:]
    return text[:limit] + marker


# Redaction reads this far past the cut, so a secret straddling it is matched whole.
REDACT_MARGIN = 16_384


def redact_capped(text: str, limit: int, keep: str = "head") -> str:
    """Redact, then cap at `limit` chars. Redacting first means a secret cut in half
    can't slip past the patterns as a too-short fragment; reading only a bounded
    window means the patterns never run over unbounded text.
    ponytail: a secret longer than REDACT_MARGIN that straddles the window's far
    edge can be missed; widen the margin if real output has such secrets."""
    span = limit + REDACT_MARGIN
    if len(text) <= span:
        return truncate(redact(text), limit, keep)
    window = redact(text[:span] if keep == "head" else text[-span:])
    marker = f"\n...[truncated, {len(text)} chars in all]...\n"
    return window[:limit] + marker if keep == "head" else marker + window[-limit:]


def redact_strings(value: Any) -> Any:
    """Every string in a JSON-like value, redacted (dict keys stay): tool arguments,
    an alert, anything structured that leaves the Hub or reaches its records."""
    if isinstance(value, str):
        return redact(value)
    if isinstance(value, dict):
        return {k: redact_strings(v) for k, v in value.items()}
    if isinstance(value, list):
        return [redact_strings(v) for v in value]
    return value
