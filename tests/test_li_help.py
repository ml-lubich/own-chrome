"""Help is the agent interface. Banner plus a command, on every -h."""

from __future__ import annotations

from own_chrome import linkedin as li

WORDMARK = "|_____|___|"
AGENT_LINE = "li threads --filter NAME --limit 5 --json"


def _help(argv: list[str], capsys) -> str:
    rc = li.main(argv)
    assert rc == 0
    return capsys.readouterr().out


def test_root_help_shows_wordmark_and_the_agent_path(capsys):
    out = _help(["-h"], capsys)
    assert WORDMARK in out
    assert AGENT_LINE in out
    assert "python -c" in out
    assert "--json" in out


def test_root_long_help_matches_short_help(capsys):
    out = _help(["--help"], capsys)
    assert WORDMARK in out
    assert AGENT_LINE in out


def test_every_command_help_names_itself_and_json(capsys):
    commands = (
        "open",
        "threads",
        "unread",
        "select",
        "read",
        "tell",
        "send",
        "inbox",
        "commands",
        "popups",
        "queries",
        "query",
        "workflow",
        "status",
    )
    for name in commands:
        out = _help([name, "-h"], capsys)
        assert name in out
        assert "--json" in out or name == "workflow"
        assert WORDMARK in out
