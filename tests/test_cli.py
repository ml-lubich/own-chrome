"""Tests for own_chrome.cli.

Boundary: talking to Chrome, which lives in own_chrome.cdp. cli.py itself is
pure argument parsing / dispatch / output formatting, so we monkeypatch the
cdp functions cli imports and exercise the real parsing and branching logic.
"""

from __future__ import annotations

import json

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
