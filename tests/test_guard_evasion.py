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


@pytest.mark.parametrize("command", ["hermes tuneup check", 'echo "tuneup" "report"', "hermes tuneup report --json"])
def test_read_only_commands_still_pass(command):
    assert not guard.invokes_fix(command)
