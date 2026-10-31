"""Tests for own_chrome.cli.

Boundary: talking to Chrome, which lives in own_chrome.cdp. cli.py itself is
pure argument parsing / dispatch / output formatting, so we monkeypatch the
cdp functions cli imports and exercise the real parsing and branching logic.
"""

from __future__ import annotations

import json
import hashlib
from pathlib import Path

import pytest

from own_chrome import cli
from own_chrome.cdp import ChromeError


def test_emit_json_writes_one_line(capsys):
    cli.emit({"a": 1}, True)
    out = capsys.readouterr().out
    assert json.loads(out) == {"a": 1}
    assert out.endswith("\n")
    assert out.count("\n") == 1


def test_emit_plain_string(capsys):
    cli.emit("hello", False)
    assert capsys.readouterr().out == "hello\n"


def test_emit_plain_dict_falls_back_to_json_line(capsys):
    cli.emit({"a": 1}, False)
    assert json.loads(capsys.readouterr().out) == {"a": 1}


def test_status_json(monkeypatch, capsys):
    monkeypatch.setattr(cli, "describe", lambda port: {"browser": "Chrome/1", "pid": 99,
                                                          "profile_directory": "Default",
                                                          "user_data_dir": "/tmp"})
    monkeypatch.setattr(cli, "pages", lambda port: [{"title": "t", "url": "u"}])
    monkeypatch.setattr(cli, "filter_pages", lambda tabs, needle, limit: [{"title": "t", "url": "u"}])
    rc = cli.main(["status", "--json"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["browser"] == "Chrome/1"
    assert payload["tabs"] == [{"title": "t", "url": "u"}]


def test_status_plain_text(monkeypatch, capsys):
    monkeypatch.setattr(cli, "describe", lambda port: {"browser": "Chrome/1", "pid": 99,
                                                          "profile_directory": "Default",
                                                          "user_data_dir": "/tmp"})
    monkeypatch.setattr(cli, "pages", lambda port: [])
    monkeypatch.setattr(cli, "filter_pages", lambda tabs, needle, limit: [{"title": "LinkedIn", "url": "https://linkedin.com"}])
    rc = cli.main(["status"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "browser: Chrome/1" in out
    assert "pid: 99" in out
    assert "LinkedIn" in out
    assert "https://linkedin.com" in out


def test_tabs_json(monkeypatch, capsys):
    monkeypatch.setattr(cli, "pages", lambda port: [{"title": "t", "url": "u"}])
    monkeypatch.setattr(cli, "filter_pages", lambda tabs, needle, limit: [{"title": "t", "url": "u"}])
    rc = cli.main(["tabs", "--json"])
    assert rc == 0
    assert json.loads(capsys.readouterr().out) == {"tabs": [{"title": "t", "url": "u"}]}


def test_tabs_plain(monkeypatch, capsys):
    monkeypatch.setattr(cli, "pages", lambda port: [])
    monkeypatch.setattr(cli, "filter_pages", lambda tabs, needle, limit: [{"title": "t", "url": "u"}])
    rc = cli.main(["tabs"])
    assert rc == 0
    assert "t\tu" in capsys.readouterr().out


def test_tabs_filter_no_match_exits_2(monkeypatch, capsys):
    monkeypatch.setattr(cli, "pages", lambda port: [])
    monkeypatch.setattr(cli, "filter_pages", lambda tabs, needle, limit: [])
    rc = cli.main(["tabs", "--filter", "nope"])
    assert rc == 2


def test_open_command(monkeypatch, capsys):
    monkeypatch.setattr(cli, "open_tab", lambda port, url: {"url": url, "title": "New Tab"})
    rc = cli.main(["open", "https://example.com", "--json"])
    assert rc == 0
    assert json.loads(capsys.readouterr().out) == {"url": "https://example.com", "title": "New Tab"}


def test_goto_command(monkeypatch, capsys):
    calls = []
    monkeypatch.setattr(cli, "navigate", lambda port, url, tab: calls.append((port, url, tab)))
    rc = cli.main(["goto", "https://example.com", "--tab", "abc", "--json"])
    assert rc == 0
    assert calls == [(9222, "https://example.com", "abc")]
    assert json.loads(capsys.readouterr().out) == {"url": "https://example.com"}


def test_eval_command_uses_tab_over_filter(monkeypatch, capsys):
    captured = {}

    def fake_evaluate(port, expression, url_contains):
        captured["args"] = (port, expression, url_contains)
        return 2

    monkeypatch.setattr(cli, "evaluate", fake_evaluate)
    rc = cli.main(["eval", "1+1", "--tab", "abc", "--filter", "ignored", "--json"])
    assert rc == 0
    assert captured["args"] == (9222, "1+1", "abc")
    assert json.loads(capsys.readouterr().out) == {"value": 2}


def test_eval_command_falls_back_to_filter(monkeypatch, capsys):
    captured = {}

    def fake_evaluate(port, expression, url_contains):
        captured["tab"] = url_contains
        return None

    monkeypatch.setattr(cli, "evaluate", fake_evaluate)
    cli.main(["eval", "1+1", "--filter", "linkedin"])
    assert captured["tab"] == "linkedin"


def test_chrome_error_reported_and_exit_1(monkeypatch, capsys):
    def fail(port):
        raise ChromeError("Chrome CDP is not up")

    monkeypatch.setattr(cli, "describe", fail)
    rc = cli.main(["status"])
    assert rc == 1
    assert "own-chrome: Chrome CDP is not up" in capsys.readouterr().err


def test_custom_port_is_forwarded(monkeypatch):
    captured = {}

    def fake_open_tab(port, url):
        captured["port"] = port
        return {"url": url}

    monkeypatch.setattr(cli, "open_tab", fake_open_tab)
    cli.main(["open", "https://example.com", "--port", "9333"])
    assert captured["port"] == 9333


@pytest.mark.parametrize("flag", ["-h", "--help"])
def test_root_help_accepts_both_help_flags(flag, capsys):
    with pytest.raises(SystemExit) as exc:
        cli.main([flag])
    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert "agent" in out
    assert "own-chrome" in out
    assert ".-=========-." in out
    assert "░▒▓" in out


def test_nested_help_has_brand_and_usage(capsys):
    with pytest.raises(SystemExit) as exc:
        cli.main(["agent", "-h"])
    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert "own-chrome" in out
    assert "usage:" in out


def test_help_is_uncolored_without_tty(monkeypatch, capsys):
    monkeypatch.setenv("TERM", "xterm-256color")
    monkeypatch.delenv("NO_COLOR", raising=False)
    with pytest.raises(SystemExit):
        cli.main(["-h"])
    out = capsys.readouterr().out
    assert "\033[" not in out


@pytest.mark.parametrize("flag", ["-V", "--version"])
def test_root_version_accepts_both_version_flags(flag, capsys):
    with pytest.raises(SystemExit) as exc:
        cli.main([flag])
    assert exc.value.code == 0
    assert capsys.readouterr().out.startswith("own-chrome ")


def test_agent_refuses_without_local_cdp_and_does_not_launch_harness(monkeypatch, capsys):
    import own_chrome.cdp as cdp

    def fail():
        raise ChromeError("no eligible Chrome CDP endpoint")

    monkeypatch.setattr(cdp, "discover", fail)
    monkeypatch.setattr(cli.shutil, "which", lambda name: "/usr/local/bin/browser-harness")
    calls = []
    monkeypatch.setattr(cli.os, "execvp", lambda *args: calls.append(args))

    assert cli.main(["agent"]) == 1
    assert calls == []
    assert "no eligible Chrome CDP endpoint" in capsys.readouterr().err


def test_agent_fails_with_setup_hint_when_cdp_is_missing(monkeypatch, capsys):
    import own_chrome.cdp as cdp

    def fail():
        raise ChromeError("Chrome CDP is not enabled")

    monkeypatch.setattr(cdp, "discover", fail)
    assert cli.main(["agent"]) == 1
    assert "chrome://inspect/#remote-debugging" in capsys.readouterr().err


def test_agent_execs_browser_harness_preserving_stdio_and_pinning_verified_cdp(monkeypatch):
    import own_chrome.cdp as cdp

    monkeypatch.delenv("BH_RUNTIME_DIR", raising=False)
    monkeypatch.setattr(
        cdp,
        "discover",
        lambda: {"browser": "Chrome/156", "port": 19222, "user_data_dir": "/tmp/Profile A"},
    )
    monkeypatch.setattr(
        cdp, "browser_ws_url", lambda info: "ws://127.0.0.1:19222/devtools/browser/test-id"
    )
    monkeypatch.setattr(cli.shutil, "which", lambda name: "/usr/local/bin/browser-harness")

    class ExecCalled(Exception):
        pass

    calls = []

    def fake_exec(file, args, env):
        calls.append((file, args, env["BU_CDP_WS"], env["BH_RUNTIME_DIR"]))
        raise ExecCalled

    monkeypatch.setattr(cli.os, "execvpe", fake_exec)
    with pytest.raises(ExecCalled):
        cli.main(["agent"])

    profile_hash = hashlib.sha256(str(Path("/tmp/Profile A").resolve()).encode()).hexdigest()[:12]
    expected_runtime = str(Path.home() / ".config/own-chrome/bh" / profile_hash)
    assert calls == [
        (
            "/usr/local/bin/browser-harness",
            ["browser-harness"],
            "ws://127.0.0.1:19222/devtools/browser/test-id",
            expected_runtime,
        )
    ]


def test_agent_reports_missing_harness_without_launch(monkeypatch, capsys):
    import own_chrome.cdp as cdp

    monkeypatch.setattr(
        cdp,
        "discover",
        lambda: {"browser": "Chrome/156", "port": 9222, "user_data_dir": "/tmp/Profile A"},
    )
    monkeypatch.setattr(
        cdp, "browser_ws_url", lambda info: "ws://127.0.0.1:9222/devtools/browser/test-id"
    )
    monkeypatch.setattr(cli.shutil, "which", lambda name: None)
    calls = []
    monkeypatch.setattr(cli.os, "execvp", lambda *args: calls.append(args))

    assert cli.main(["agent"]) == 1
    assert calls == []
    err = capsys.readouterr().err
    assert "browser-harness" in err
    assert "install" in err.lower()


def test_browser_harness_runtime_isolated_by_profile_and_respects_override(monkeypatch):
    monkeypatch.delenv("BH_RUNTIME_DIR", raising=False)
    first = cli._browser_harness_env(
        {"user_data_dir": "/tmp/chrome/Profile 1"}, "ws://127.0.0.1:9222/devtools/browser/a"
    )
    second = cli._browser_harness_env(
        {"user_data_dir": "/tmp/chrome/Profile 2"}, "ws://127.0.0.1:9223/devtools/browser/b"
    )
    assert first["BH_RUNTIME_DIR"] != second["BH_RUNTIME_DIR"]
    assert first["BH_RUNTIME_DIR"].endswith(
        str(
            Path(".config/own-chrome/bh")
            / hashlib.sha256(str(Path("/tmp/chrome/Profile 1").resolve()).encode()).hexdigest()[:12]
        )
    )

    monkeypatch.setenv("BH_RUNTIME_DIR", "/custom/browser-harness/runtime")
    explicit = cli._browser_harness_env(
        {"user_data_dir": "/tmp/chrome/Profile 1"}, "ws://127.0.0.1:9222/devtools/browser/a"
    )
    assert explicit["BH_RUNTIME_DIR"] == "/custom/browser-harness/runtime"


@pytest.mark.parametrize("flag", ["-h", "--help"])
def test_agent_help_documents_local_cdp_without_cloud(flag, capsys):
    with pytest.raises(SystemExit) as exc:
        cli.main(["agent", flag])
    assert exc.value.code == 0
    out = capsys.readouterr().out.lower()
    assert "browser-harness" in out
    assert "cdp" in out
