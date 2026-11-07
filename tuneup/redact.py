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
    re.compile(r"\b[A-Za-z0-9_]{32,}\b"),
    re.compile(r"://[^/@\s]*@"),
)


def _sanitise(value: object) -> str:
    """Control characters removed and secret-shaped text replaced; the one place the patterns apply."""
    text = _CONTROL.sub("", str(value if value is not None else ""))
    for pattern in _SECRET_PATTERNS:
        text = pattern.sub("[redacted]", text)
    return text


def _truncate(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: limit - 3] + "..."


def clean(value: object, limit: int = MAX_LEN) -> str:
    """A config-derived string that is safe to show to a person or a model."""
    return _truncate(" ".join(_sanitise(value).split()), limit)


def clean_line(value: object, limit: int = 200) -> str:
    """Like clean(), but keeps spacing, for diff lines whose indentation carries meaning."""
    return _truncate(_sanitise(value), limit)


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


# Words that mark a config key as holding a secret. The report scrubber and the fix
# preview diff both build their patterns from this one list.
SECRET_KEY_WORDS = r"key|token|secret|password|passwd|auth|header|cookie|credential|url|env"
_SECRET_KEY = re.compile(rf"(?i)({SECRET_KEY_WORDS})")


def scrub(value: object) -> object:
    """A deep copy safe to show: string values under secret-named keys are redacted, every string cleaned."""
    if isinstance(value, dict):
        return {
            clean(k): ("[redacted]" if _SECRET_KEY.search(str(k)) and isinstance(v, str) and v else scrub(v))
            for k, v in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [scrub(v) for v in value]
    if isinstance(value, str):
        return clean(value)
    return value
