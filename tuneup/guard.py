"""A pre_tool_call hook that stops the agent's own tools from running a tuneup fix.

The CLI fix also refuses inside agent-launched commands (confirm.cli_refusal);
this hook is the second layer. It is a pure string check: no I/O, never raises,
because Hermes blocks the tool if a pre_tool_call callback fails or hangs.

Before matching it undoes the static shell spellings bash would resolve to the
same command: line continuations, $'..' and $".." quoting, brace expansion and
quotes or backslashes inside a word. Being a text match, it is still a guard
rail, not a sandbox: a command assembled at run time (a variable or command
substitution) can get past it.
"""

from __future__ import annotations

import re

BLOCK_MESSAGE = (
    "tuneup fixes are applied only by the user. Do not run them: tell the user to type the exact "
    "fix command from the finding (for example /tuneup fix <code>) themselves."
)
FILE_TOOLS = {"write_file", "edit_file", "patch", "apply_patch", "str_replace", "create_file"}
SCRIPT_SUFFIXES = (".sh", ".bash", ".zsh", ".fish", ".py", ".command", ".ps1")

# Brace expansion past these bounds is too large to check word by word, so it is blocked when it names tuneup.
_MAX_WORDS = 1024
_MAX_GROUPS = 64

_ANSI_C = re.compile(r"\$'((?:[^'\\]|\\.)*)'", re.DOTALL)
_ANSI_ESCAPE = re.compile(r"\\(x[0-9a-fA-F]{1,2}|u[0-9a-fA-F]{1,4}|U[0-9a-fA-F]{1,8}|[0-7]{1,3}|.)", re.DOTALL)
_ANSI_NAMED = {"a": "\a", "b": "\b", "e": "\x1b", "E": "\x1b", "f": "\f", "n": "\n", "r": "\r", "t": "\t", "v": "\v"}
# An innermost brace group; ${...} is parameter expansion, not a brace group.
_BRACE = re.compile(r"(?<!\$)\{([^{}]*)\}")
_RANGE = re.compile(r"^(?:([a-zA-Z])\.\.([a-zA-Z])|(-?\d{1,9})\.\.(-?\d{1,9}))(?:\.\.(-?\d{1,9}))?$")

_INVOCATIONS = (
    re.compile(r"\btuneup\s+(?:--\s+)?fix\b"),
    re.compile(r"-m\s+tuneup\b"),
    re.compile(r"\btuneup\.(fixes|cli)\b"),
    re.compile(r"\bfrom\s+tuneup(\.\w+)?\s+import\s+[\w ,]*\b(fixes|cli)\b"),
)


def _strings(value, depth: int = 0):
    if depth > 6:
        return
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from _strings(item, depth + 1)
    elif isinstance(value, (list, tuple)):
        for item in value:
            yield from _strings(item, depth + 1)


class _TooLarge(Exception):
    """A brace expansion too large to check word by word."""


def _ansi_escape(match: re.Match) -> str:
    body = match.group(1)
    if len(body) > 1 and body[0] in "xuU":
        return chr(min(int(body[1:], 16), 0x10FFFF))
    if body[0] in "01234567":
        return chr(int(body, 8))
    if body in "\\'\"?":
        return body
    return _ANSI_NAMED.get(body, "\\" + body)


def _alternatives(inner: str) -> list[str] | None:
    """The words a brace group stands for, or None when bash leaves it as literal text."""
    if "," in inner:
        return inner.split(",")
    match = _RANGE.match(inner)
    if match is None:
        return None
    letters = match.group(1) is not None
    low = ord(match.group(1)) if letters else int(match.group(3))
    high = ord(match.group(2)) if letters else int(match.group(4))
    step = abs(int(match.group(5) or 1)) or 1
    if abs(high - low) // step >= _MAX_WORDS:
        raise _TooLarge
    values = range(low, high + 1, step) if high >= low else range(low, high - 1, -step)
    return [chr(v) if letters else str(v) for v in values]


def _first_group(word: str) -> tuple[re.Match, list[str]] | None:
    for match in _BRACE.finditer(word):
        alternatives = _alternatives(match.group(1))
        if alternatives is not None:
            return match, alternatives
    return None


def _expand_word(word: str) -> list[str]:
    """Bash brace expansion of one word, innermost group first, keeping the order bash gives."""
    words = [word]
    for _ in range(_MAX_GROUPS):
        expanded, changed = [], False
        for current in words:
            found = _first_group(current)
            if found is None:
                expanded.append(current)
                continue
            changed = True
            group, alternatives = found
            expanded.extend(current[: group.start()] + alt + current[group.end() :] for alt in alternatives)
            if len(expanded) > _MAX_WORDS:
                raise _TooLarge
        if not changed:
            return [w for w in words if w]
        words = expanded
    raise _TooLarge


def _expand_braces(text: str) -> str:
    words, grown = [], 0
    for word in text.split():
        expanded = _expand_word(word) if "{" in word else [word]
        grown += len(expanded) - 1
        if grown > _MAX_WORDS:
            raise _TooLarge
        words.extend(expanded)
    return " ".join(words)


def _normalise(text: str) -> str:
    """The text as bash would read its words, as far as static spelling goes."""
    text = text.replace("\\\n", "")
    text = _ANSI_C.sub(lambda m: _ANSI_ESCAPE.sub(_ansi_escape, m.group(1)), text).replace('$"', '"')
    text = _expand_braces(text)
    # A quote or backslash inside a word is a shell no-op (tune""up, tun\eup), so join the word first.
    joined = re.sub(r"(?<=\w)['\"`\\]+(?=\w)", "", text.lower())
    return re.sub(r"[\s'\"`\\]+", " ", joined)


def invokes_fix(text: str) -> bool:
    try:
        flat = _normalise(text)
    except _TooLarge:
        return "tuneup" in re.sub(r"\W", "", text.lower())
    return any(pattern.search(flat) for pattern in _INVOCATIONS)


def _is_script_write(args: dict) -> bool:
    path = str(args.get("path") or args.get("file_path") or args.get("filename") or "").lower()
    content = str(args.get("content") or args.get("new_string") or "")
    return path.endswith(SCRIPT_SUFFIXES) or content.lstrip().startswith("#!")


def pre_tool_call(tool_name: str = "", args=None, **_kwargs):
    """Return Hermes' block directive when a tool call would run a fix, else None."""
    try:
        if not isinstance(args, dict):
            return None
        if str(tool_name) in FILE_TOOLS and not _is_script_write(args):
            return None
        if any(invokes_fix(text) for text in _strings(args)):
            return {"action": "block", "message": BLOCK_MESSAGE}
        return None
    except Exception:
        return None
