"""The single redactor every string from a profile's config passes through.

The report is built from named, typed values (model ids, provider ids, numbers,
key paths); base URLs and keys are never copied into it. Free-form strings are
still scrubbed for secret-shaped text, stripped of control characters and
length-limited, because a user may have pasted a token anywhere.
"""

from __future__ import annotations

import re
from urllib.parse import urlsplit

MAX_LEN = 120

_CONTROL = re.compile(r"[\x00-\x1f\x7f-\x9f]")
_SECRET_PATTERNS = (
    re.compile(r"\bsk-[A-Za-z0-9_\-]{6,}"),
    re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._\-]{8,}"),
    re.compile(r"[A-Za-z0-9_\-]{32,}"),
    re.compile(r"://[^/@\s]*@"),
)


def clean(value: object, limit: int = MAX_LEN) -> str:
    """A config-derived string that is safe to show to a person or a model."""
    text = _CONTROL.sub("", str(value if value is not None else ""))
    for pattern in _SECRET_PATTERNS:
        text = pattern.sub("[redacted]", text)
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 3] + "..."


def url(value: object) -> str:
    """Scheme and host (with port) only: no user info, path or query."""
    raw = str(value or "").strip()
    if not raw:
        return ""
    try:
        parts = urlsplit(raw)
    except ValueError:
        return "[redacted]"
    host = parts.hostname or ""
    port = f":{parts.port}" if parts.port else ""
    return f"{parts.scheme}://{host}{port}" if parts.scheme and host else "[redacted]"
