"""Tests for own_chrome.linkedin.

Boundary mocks: talking to Chrome (own_chrome.linkedin.evaluate / navigate),
the OpenAI HTTP API (urllib.request.urlopen), and the macOS keychain
(subprocess.check_output). Query building, config loading, popup/workflow
dispatch, and CLI argument parsing all run for real.
"""

from __future__ import annotations

import json
import subprocess

import pytest

from own_chrome import linkedin as li
from own_chrome.cdp import ChromeError


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


def test_expression_embeds_query_filter_and_limit():
    expr = li._expression("unread", "acme", 5)
    assert '"query": "unread"' in expr
    assert '"filter": "acme"' in expr
    assert '"limit": 5' in expr
    assert expr.startswith("(")


def test_load_config_defaults_when_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(li, "CONFIG_PATH", tmp_path / "missing.json")
    config = li.load_config()
    assert config == {
        "popups": {"share_contact": "decline"},
        "intent_model": "gpt-5-nano",
        "write_model": "gpt-5-mini",
    }


def test_load_config_reads_file(tmp_path, monkeypatch):
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"intent_model": "custom-model"}))
    monkeypatch.setattr(li, "CONFIG_PATH", path)
    assert li.load_config() == {"intent_model": "custom-model"}


# ---------------------------------------------------------------------------
# api_key (env / keychain boundary)
# ---------------------------------------------------------------------------


def test_api_key_prefers_env(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-env-value")
    assert li.api_key() == "sk-env-value"


def test_api_key_falls_back_to_keychain(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr(li.subprocess, "check_output", lambda *a, **k: "sk-keychain-value\n")
    assert li.api_key() == "sk-keychain-value"


def test_api_key_missing_everywhere_raises(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    def raise_error(*a, **k):
        raise subprocess.CalledProcessError(1, "security")

    monkeypatch.setattr(li.subprocess, "check_output", raise_error)
    with pytest.raises(ChromeError, match="OpenAI key is not in the environment or keychain"):
        li.api_key()


# ---------------------------------------------------------------------------
# complete (OpenAI HTTP boundary)
# ---------------------------------------------------------------------------


class _FakeResponse:
    def __init__(self, payload: bytes):
        self._payload = payload

    def read(self):
        return self._payload

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def test_complete_returns_message_content(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setattr(
        li.urllib.request,
        "urlopen",
        lambda request, timeout=30: _FakeResponse(
            json.dumps({"choices": [{"message": {"content": "hello"}}]}).encode()
        ),
    )
    assert li.complete("gpt-5-nano", [{"role": "user", "content": "hi"}]) == "hello"


def test_complete_http_error_raises_chrome_error(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")

    def raise_error(request, timeout=30):
        raise li.urllib.error.HTTPError(request.full_url, 429, "rate limited", {}, None)

    monkeypatch.setattr(li.urllib.request, "urlopen", raise_error)
    with pytest.raises(ChromeError, match="OpenAI 429"):
        li.complete("gpt-5-nano", [])


# ---------------------------------------------------------------------------
# _popups
# ---------------------------------------------------------------------------


class _Args:
    def __init__(self, **kw):
        self.port = 9222
        self.json = True
        self.apply = False
        for key, value in kw.items():
            setattr(self, key, value)


def test_popups_reports_decline_action_without_apply(monkeypatch, capsys):
    monkeypatch.setattr(
        li,
        "evaluate",
        lambda port, expr, tab: json.dumps(
            {"title": "Share your contact info?", "buttons": ["No, don't share", "Yes, please share"]}
        ),
    )
    monkeypatch.setattr(li, "load_config", lambda: {"popups": {"share_contact": "decline"}})
    rc = li._popups(_Args())
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["action"] == "No, don't share"
    assert payload["applied"] is False


def test_popups_apply_clicks_button(monkeypatch, capsys):
    calls = []

    def fake_evaluate(port, expr, tab):
        calls.append(expr)
        if len(calls) == 1:
            return json.dumps({"title": "Share your contact info?", "buttons": ["No, don't share"]})
        return True

    monkeypatch.setattr(li, "evaluate", fake_evaluate)
    monkeypatch.setattr(li, "load_config", lambda: {"popups": {"share_contact": "decline"}})
    rc = li._popups(_Args(apply=True))
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["applied"] is True
    assert len(calls) == 2


def test_popups_plain_text_respects_json_flag(monkeypatch, capsys):
    # Regression test: _popups used to always emit JSON (`args.json or True`)
    # even when --json was not passed. It must honor args.json like every
    # other command.
    monkeypatch.setattr(
        li,
        "evaluate",
        lambda port, expr, tab: json.dumps(
            {"title": "Share your contact info?", "buttons": ["No, don't share"]}
        ),
    )
    monkeypatch.setattr(li, "load_config", lambda: {"popups": {"share_contact": "decline"}})
    rc = li._popups(_Args(json=False))
    assert rc == 0
    out = capsys.readouterr().out
    assert not out.strip().startswith("{")


def test_popups_unknown_dialog_no_action(monkeypatch, capsys):
    monkeypatch.setattr(
        li, "evaluate", lambda port, expr, tab: json.dumps({"title": "Messaging settings", "buttons": ["Save"]})
    )
    monkeypatch.setattr(li, "load_config", lambda: {"popups": {"share_contact": "decline"}})
    rc = li._popups(_Args())
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["action"] is None
    assert payload["applied"] is False


# ---------------------------------------------------------------------------
# _workflow
# ---------------------------------------------------------------------------


def test_workflow_uses_explicit_text_and_reports_regex_miss(tmp_path, capsys):
    spec_path = tmp_path / "spec.json"
    spec_path.write_text(json.dumps({"name": "job-reply", "match": r"\brole\b", "intent": "job only", "write": "short"}))
    rc = li._workflow(_Args(spec=str(spec_path), text="just saying hi", dry_run=True))
    assert rc == 0
    result = json.loads(capsys.readouterr().out)
    assert result["go"] is False
    assert result["sent"] is False


def test_workflow_fetches_thread_text_when_absent(monkeypatch, tmp_path, capsys):
    spec_path = tmp_path / "spec.json"
    spec_path.write_text(json.dumps({"name": "job-reply", "match": r"role", "intent": "job only", "write": "short"}))

    monkeypatch.setattr(li, "evaluate", lambda port, expr, tab: json.dumps("no roles mentioned here"))

    def complete(model, messages):
        return json.dumps({"go": False, "reason": "not relevant"})

    monkeypatch.setattr(li, "complete", complete)
    rc = li._workflow(_Args(spec=str(spec_path), text="", dry_run=True))
    assert rc == 2
    result = json.loads(capsys.readouterr().out)
    assert result["go"] is False


def test_workflow_go_returns_zero(monkeypatch, tmp_path, capsys):
    spec_path = tmp_path / "spec.json"
    spec_path.write_text(json.dumps({"name": "job-reply", "match": r"role", "intent": "job only", "write": "short"}))

    def complete(model, messages):
        if model.endswith("nano"):
            return json.dumps({"go": True, "reason": "recruiter asked about a role"})
        return "not looking, thanks"

    monkeypatch.setattr(li, "complete", complete)
    rc = li._workflow(_Args(spec=str(spec_path), text="Open role on the platform team", dry_run=True))
    assert rc == 0
    result = json.loads(capsys.readouterr().out)
    assert result["draft"] == "not looking, thanks"
    assert result["sent"] is False


# ---------------------------------------------------------------------------
# emit
# ---------------------------------------------------------------------------


def test_emit_json(capsys):
    li.emit({"title": "t", "url": "u"}, True)
    assert json.loads(capsys.readouterr().out) == {"title": "t", "url": "u"}


def test_emit_plain_lists_threads_and_lines(capsys):
    payload = {
        "title": "Inbox",
        "url": "https://linkedin.com/messaging",
        "threads": [{"name": "Ada", "unread": True, "preview": "hi there"}],
        "lines": ["hello\nworld"],
    }
    li.emit(payload, False)
    out = capsys.readouterr().out
    assert "Inbox" in out
    assert "Ada *" in out
    assert "hello | world" in out


# ---------------------------------------------------------------------------
# main() dispatch
# ---------------------------------------------------------------------------


def test_main_queries_lists_known_queries(capsys):
    rc = li.main(["queries"])
    assert rc == 0
    out = capsys.readouterr().out.splitlines()
    assert out == list(li.QUERIES)


def test_main_queries_json(capsys):
    rc = li.main(["queries", "--json"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["queries"] == list(li.QUERIES)


def test_main_threads_json(monkeypatch, capsys):
    monkeypatch.setattr(
        li,
        "evaluate",
        lambda port, expr, tab: json.dumps({"query": "threads", "url": "u", "title": "t", "threads": [], "lines": []}),
    )
    rc = li.main(["threads", "--json"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["title"] == "t"


def test_main_query_title_kind(monkeypatch, capsys):
    monkeypatch.setattr(li, "evaluate", lambda port, expr, tab: json.dumps({"title": "My Feed", "url": "https://x"}))
    rc = li.main(["query", "title", "--json"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["title"] == "My Feed"
    assert payload["url"] == ""


def test_main_query_url_kind(monkeypatch, capsys):
    monkeypatch.setattr(li, "evaluate", lambda port, expr, tab: json.dumps({"title": "My Feed", "url": "https://x"}))
    rc = li.main(["query", "url", "--json"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["url"] == "https://x"
    assert payload["title"] == ""


def test_main_inbox_navigates_by_default(monkeypatch, capsys):
    calls = []
    monkeypatch.setattr(li, "navigate", lambda port, url, tab: calls.append((url, tab)))
    monkeypatch.setattr(
        li,
        "evaluate",
        lambda port, expr, tab: json.dumps({"query": "threads", "url": "u", "title": "t", "threads": [], "lines": []}),
    )
    rc = li.main(["inbox", "--json"])
    assert rc == 0
    assert calls == [(li.MESSAGING, li.TAB)]


def test_main_inbox_no_navigate_skips_navigation(monkeypatch, capsys):
    calls = []
    monkeypatch.setattr(li, "navigate", lambda port, url, tab: calls.append((url, tab)))
    monkeypatch.setattr(
        li,
        "evaluate",
        lambda port, expr, tab: json.dumps({"query": "threads", "url": "u", "title": "t", "threads": [], "lines": []}),
    )
    rc = li.main(["inbox", "--no-navigate", "--json"])
    assert rc == 0
    assert calls == []


def test_main_filter_with_no_threads_exits_2(monkeypatch, capsys):
    monkeypatch.setattr(
        li,
        "evaluate",
        lambda port, expr, tab: json.dumps({"query": "unread", "url": "u", "title": "t", "threads": [], "lines": []}),
    )
    rc = li.main(["unread", "--filter", "nobody", "--json"])
    assert rc == 2


def test_main_chrome_error_reported(monkeypatch, capsys):
    def fail(port, expr, tab):
        raise ChromeError("Chrome CDP is not up")

    monkeypatch.setattr(li, "evaluate", fail)
    rc = li.main(["threads"])
    assert rc == 1
    assert "li: Chrome CDP is not up" in capsys.readouterr().err


def test_main_bad_json_from_page_reported(monkeypatch, capsys):
    monkeypatch.setattr(li, "evaluate", lambda port, expr, tab: "not json at all")
    rc = li.main(["threads"])
    assert rc == 1
    assert "did not return JSON" in capsys.readouterr().err


def test_main_popups_dispatches(monkeypatch, capsys):
    monkeypatch.setattr(
        li, "evaluate", lambda port, expr, tab: json.dumps({"title": "Messaging settings", "buttons": ["Save"]})
    )
    rc = li.main(["popups", "--json"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["action"] is None


def test_main_workflow_dispatches(monkeypatch, tmp_path, capsys):
    spec_path = tmp_path / "spec.json"
    spec_path.write_text(json.dumps({"name": "job-reply", "match": r"\brole\b", "intent": "job only", "write": "short"}))
    rc = li.main(["workflow", "run", str(spec_path), "--text", "just saying hi", "--json"])
    assert rc == 0
    result = json.loads(capsys.readouterr().out)
    assert result["sent"] is False
