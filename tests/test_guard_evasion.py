"""Shell spellings that split or escape a word inside the fix command are still blocked."""

import pytest

from tuneup import guard


@pytest.mark.parametrize(
    "command",
    [
        'hermes tune""up fix ab12cd',
        "hermes tune''up fix ab12cd",
        "hermes tun\\eup fix ab12cd",
        'hermes tuneup f"i"x ab12cd',
        "python -m tune''up fix ab12cd",
    ],
)
def test_quotes_or_backslashes_inside_a_word_do_not_hide_the_fix(command):
    assert guard.invokes_fix(command)


@pytest.mark.parametrize(
    "command",
    [
        "hermes tun\\\neup fix ab12cd",
        "hermes tuneup $'fix' ab12cd",
        "hermes tuneup $'\\x66ix' ab12cd",
        "hermes tuneup $'\\146ix' ab12cd",
        "hermes tuneup $'\\u0066ix' ab12cd",
        'hermes tuneup $"fix" ab12cd',
        "hermes tuneup {fix,} ab12cd",
        "hermes {tuneup,fix} ab12cd",
        "hermes tuneup {f..f}ix ab12cd",
        "hermes tuneup {,{fix,}} ab12cd",
        "hermes tuneup -- fix ab12cd",
    ],
)
def test_static_shell_spellings_that_bash_resolves_to_the_fix_are_blocked(command):
    # Each spelling reaches the fix subcommand in bash: line continuation, ANSI-C and
    # locale quoting, brace lists and ranges, and the end-of-options marker.
    assert guard.invokes_fix(command)
    assert guard.pre_tool_call(tool_name="terminal", args={"command": command})["action"] == "block"


@pytest.mark.parametrize(
    "command",
    [
        "hermes tuneup check",
        'echo "tuneup" "report"',
        "hermes tuneup report --json",
        "mkdir -p out/{logs,cache} && ls tuneup/{fixes,guard}.py",
        "printf $'tuneup\\tcheck\\n'",
        'echo "${HOME}" {a..e}',
    ],
)
def test_read_only_commands_still_pass(command):
    assert not guard.invokes_fix(command)


def test_a_brace_expansion_too_large_to_check_is_blocked_when_it_names_tuneup():
    bomb = "{a,b}" * 24
    assert guard.invokes_fix(f"hermes tuneup {bomb} ab12cd")
    assert not guard.invokes_fix(f"echo {bomb}")


@pytest.mark.parametrize(
    "command", ["hermes tuneup $'\\UFFFFFFFF' x", "hermes tuneup $'unterminated", "{" * 5000 + "a,b" + "}" * 5000]
)
def test_odd_input_never_raises(command):
    guard.invokes_fix(command)
