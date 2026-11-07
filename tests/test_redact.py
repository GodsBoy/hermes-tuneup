"""U3: nothing secret reaches the report, whatever the config holds."""

from __future__ import annotations

import json

from tuneup import redact, report


def test_secrets_in_config_never_reach_the_report(make_profile):
    make_profile(
        "default",
        """
        model:
          default: claude-opus-5-5
          provider: anthropic
          base_url: "https://user:sk-test-123@proxy.example/v1?key=abc"
          api_key: sk-test-456
        custom_providers:
          - {name: mine, base_url: "https://tok:sk-test-789@gw.example", api_key: sk-test-000}
        """,
    )
    text = json.dumps(report.build_report(active="default", checks=[]))
    for secret in ("sk-test-123", "sk-test-456", "sk-test-789", "sk-test-000", "key=abc", "proxy.example/v1"):
        assert secret not in text


def test_secret_shaped_text_inside_a_model_name_is_scrubbed():
    cleaned = redact.clean("gpt-6 sk-live-ABCDEFGHIJKLMNOPQRSTUVWX Bearer abcdefghijklmnopqrstuvwxyz0123")
    assert "sk-live" not in cleaned
    assert "abcdefghijklmnopqrstuvwxyz0123" not in cleaned
    assert cleaned.startswith("gpt-6")


def test_control_characters_are_stripped_and_length_is_limited():
    cleaned = redact.clean("claude\x1b[31m-opus\x00\n" + "x" * 500)
    assert "\x1b" not in cleaned and "\x00" not in cleaned and "\n" not in cleaned
    assert len(cleaned) <= redact.MAX_LEN


def test_url_is_reduced_to_scheme_and_host():
    assert redact.url("https://user:pw@proxy.example:8443/v1?key=abc") == "https://proxy.example:8443"
    assert redact.url("") == ""
