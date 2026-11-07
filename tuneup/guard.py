"""A pre_tool_call hook that stops the agent's own tools from running a tuneup fix.

The CLI fix also refuses inside agent-launched commands (confirm.cli_refusal);
this hook is the second layer. It is a pure string check: no I/O, never raises,
because Hermes blocks the tool if a pre_tool_call callback fails or hangs.

Being a text match, it is a guard rail, not a sandbox: a command assembled at
run time (a variable or command substitution) can get past it.
"""

from __future__ import annotations

import re

BLOCK_MESSAGE = (
    "tuneup fixes are applied only by the user. Do not run them: tell the user to type the exact "
    "fix command from the finding (for example /tuneup fix <code>) themselves."
)
FILE_TOOLS = {"write_file", "edit_file", "patch", "apply_patch", "str_replace", "create_file"}
SCRIPT_SUFFIXES = (".sh", ".bash", ".zsh", ".fish", ".py", ".command", ".ps1")

_INVOCATIONS = (
    re.compile(r"\btuneup\s+fix\b"),
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


def _normalise(text: str) -> str:
    # A quote or backslash inside a word is a shell no-op (tune""up, tun\eup), so join the word first.
    joined = re.sub(r"(?<=\w)['\"`\\]+(?=\w)", "", text.lower())
    return re.sub(r"[\s'\"`\\]+", " ", joined)


def invokes_fix(text: str) -> bool:
    flat = _normalise(text)
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
