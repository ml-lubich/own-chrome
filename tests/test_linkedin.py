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

_MESSAGING_TAB = {
    "id": "msg",
    "url": "https://www.linkedin.com/messaging/",
    "title": "Messaging",
    "webSocketDebuggerUrl": "ws://msg",
}


@pytest.fixture(autouse=True)
def _default_linkedin_tab(monkeypatch):
    monkeypatch.setattr(li, "pages", lambda port: [_MESSAGING_TAB])


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
        lambda port, expr, host="", page=None: json.dumps(
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

    def fake_evaluate(port, expr, host="", page=None):
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
        lambda port, expr, host="", page=None: json.dumps(
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
        li, "evaluate", lambda port, expr, host="", page=None: json.dumps({"title": "Messaging settings", "buttons": ["Save"]})
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

    monkeypatch.setattr(li, "evaluate", lambda port, expr, host="", page=None: json.dumps("no roles mentioned here"))

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


def _already_messaging(monkeypatch) -> None:
    monkeypatch.setattr(li, "pages", lambda port: [_MESSAGING_TAB])


def test_main_threads_json(monkeypatch, capsys):
    _already_messaging(monkeypatch)
    monkeypatch.setattr(
        li,
        "evaluate",
        lambda port, expr, host="", page=None: json.dumps({"query": "threads", "url": "u", "title": "t", "threads": [], "lines": []}),
    )
    rc = li.main(["threads", "--json"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["title"] == "t"


def test_main_query_title_kind(monkeypatch, capsys):
    monkeypatch.setattr(li, "evaluate", lambda port, expr, host="", page=None: json.dumps({"title": "My Feed", "url": "https://x"}))
    rc = li.main(["query", "title", "--json"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["title"] == "My Feed"
    assert payload["url"] == ""


def test_main_query_url_kind(monkeypatch, capsys):
    monkeypatch.setattr(li, "evaluate", lambda port, expr, host="", page=None: json.dumps({"title": "My Feed", "url": "https://x"}))
    rc = li.main(["query", "url", "--json"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["url"] == "https://x"
    assert payload["title"] == ""


def test_main_inbox_navigates_by_default(monkeypatch, capsys):
    calls = []
    monkeypatch.setattr(
        li,
        "pages",
        lambda port: [{"id": "feed", "url": "https://www.linkedin.com/feed/", "title": "Feed", "webSocketDebuggerUrl": "ws://feed"}],
    )
    monkeypatch.setattr(li, "navigate", lambda port, url, host: calls.append((url, host)))

    def fake_eval(port, expr, host="", page=None):
        if '"query"' in expr:
            return json.dumps({"query": "threads", "url": "u", "title": "t", "threads": [], "lines": []})
        return json.dumps({"ready": True, "url": li.MESSAGING, "title": "Messaging"})

    monkeypatch.setattr(li, "evaluate", fake_eval)
    rc = li.main(["inbox", "--json"])
    assert rc == 0
    assert calls == [(li.MESSAGING, li.TAB)]


def test_main_inbox_no_navigate_skips_navigation(monkeypatch, capsys):
    calls = []
    monkeypatch.setattr(li, "navigate", lambda port, url, host: calls.append((url, host)))
    monkeypatch.setattr(
        li,
        "evaluate",
        lambda port, expr, host="", page=None: json.dumps({"query": "threads", "url": "u", "title": "t", "threads": [], "lines": []}),
    )
    rc = li.main(["inbox", "--no-navigate", "--json"])
    assert rc == 0
    assert calls == []


def test_main_filter_with_no_threads_exits_2(monkeypatch, capsys):
    _already_messaging(monkeypatch)
    monkeypatch.setattr(
        li,
        "evaluate",
        lambda port, expr, host="", page=None: json.dumps({"query": "unread", "url": "u", "title": "t", "threads": [], "lines": []}),
    )
    rc = li.main(["unread", "--filter", "nobody", "--json"])
    assert rc == 2


def test_main_chrome_error_reported(monkeypatch, capsys):
    def fail(port, expr, host="", page=None):
        raise ChromeError("Chrome CDP is not up")

    monkeypatch.setattr(li, "evaluate", fail)
    rc = li.main(["threads", "--no-navigate"])
    assert rc == 1
    assert "li: Chrome CDP is not up" in capsys.readouterr().err


def test_main_bad_json_from_page_reported(monkeypatch, capsys):
    monkeypatch.setattr(li, "evaluate", lambda port, expr, host="", page=None: "not json at all")
    rc = li.main(["threads", "--no-navigate"])
    assert rc == 1
    assert "did not return JSON" in capsys.readouterr().err


def test_main_popups_dispatches(monkeypatch, capsys):
    monkeypatch.setattr(
        li, "evaluate", lambda port, expr, host="", page=None: json.dumps({"title": "Messaging settings", "buttons": ["Save"]})
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


def test_main_threads_navigates_off_the_feed(monkeypatch, capsys):
    calls = []
    monkeypatch.setattr(
        li,
        "pages",
        lambda port: [{"id": "feed", "url": "https://www.linkedin.com/feed/", "title": "Feed", "webSocketDebuggerUrl": "ws://feed"}],
    )
    monkeypatch.setattr(li, "navigate", lambda port, url, host: calls.append(url))

    def fake_eval(port, expr, host="", page=None):
        if '"query"' in expr:
            return json.dumps(
                {
                    "query": "threads",
                    "url": li.MESSAGING,
                    "title": "Messaging",
                    "threads": [{"name": "Ada", "preview": "hi", "unread": False}],
                    "lines": [],
                }
            )
        return json.dumps({"ready": True, "url": li.MESSAGING, "title": "Messaging"})

    monkeypatch.setattr(li, "evaluate", fake_eval)
    rc = li.main(["threads", "--json"])
    assert rc == 0
    assert calls == [li.MESSAGING]
    payload = json.loads(capsys.readouterr().out)
    assert payload["threads"][0]["name"] == "Ada"


def test_main_open_creates_a_tab_when_linkedin_is_missing(monkeypatch, capsys):
    opened = []
    state: dict[str, list] = {"tabs": []}

    def fake_pages(_port):
        return state["tabs"]

    def fake_open(_port, url):
        opened.append(url)
        tab = {"id": "new", "url": url, "title": "", "webSocketDebuggerUrl": "ws://new"}
        state["tabs"] = [tab]
        return tab

    monkeypatch.setattr(li, "pages", fake_pages)
    monkeypatch.setattr(li, "open_tab", fake_open)
    monkeypatch.setattr(
        li,
        "evaluate",
        lambda port, expr, host="", page=None: json.dumps({"ready": True, "url": li.MESSAGING, "title": "Messaging"}),
    )
    rc = li.main(["open", "--json"])
    assert rc == 0
    assert opened == [li.MESSAGING]
    payload = json.loads(capsys.readouterr().out)
    assert payload["opened"] == "tab"
    assert payload["ready"] is True


def test_main_open_stays_when_already_in_messaging(monkeypatch, capsys):
    _already_messaging(monkeypatch)
    monkeypatch.setattr(li, "navigate", lambda *a, **k: (_ for _ in ()).throw(AssertionError("navigate")))
    rc = li.main(["open", "--json"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["opened"] == "already"


def test_main_select_ambiguous_exits_3(monkeypatch, capsys):
    _already_messaging(monkeypatch)
    monkeypatch.setattr(
        li,
        "evaluate",
        lambda port, expr, host="", page=None: json.dumps(
            {"action": "select", "ok": False, "ambiguous": True, "matches": ["Ada Lovelace", "Ada Wong"], "matched": ""}
        ),
    )
    rc = li.main(["select", "Ada", "--json"])
    assert rc == 3
    payload = json.loads(capsys.readouterr().out)
    assert payload["matches"] == ["Ada Lovelace", "Ada Wong"]


def test_main_select_missing_exits_2(monkeypatch, capsys):
    _already_messaging(monkeypatch)
    monkeypatch.setattr(
        li,
        "evaluate",
        lambda port, expr, host="", page=None: json.dumps(
            {"action": "select", "ok": False, "ambiguous": False, "matches": [], "matched": ""}
        ),
    )
    rc = li.main(["select", "Nobody", "--json"])
    assert rc == 2


def test_main_select_blank_name_exits_2(capsys):
    rc = li.main(["select", "   "])
    assert rc == 2
    assert "name is required" in capsys.readouterr().err


def test_main_tell_types_without_sending(monkeypatch, capsys):
    seen = []
    _already_messaging(monkeypatch)

    def fake_eval(port, expr, host="", page=None):
        seen.append(expr)
        return json.dumps(
            {
                "action": "tell",
                "ok": True,
                "sent": False,
                "matched": "Ada",
                "chars": 2,
                "ambiguous": False,
                "matches": ["Ada"],
            }
        )

    monkeypatch.setattr(li, "evaluate", fake_eval)
    rc = li.main(["tell", "Ada", "--text", "hi", "--json"])
    assert rc == 0
    assert '"send": false' in seen[-1]
    payload = json.loads(capsys.readouterr().out)
    assert payload["sent"] is False


def test_main_tell_send_flag_is_in_the_page_call(monkeypatch, capsys):
    seen = []
    _already_messaging(monkeypatch)

    def fake_eval(port, expr, host="", page=None):
        seen.append(expr)
        return json.dumps({"action": "tell", "ok": True, "sent": True, "matched": "Ada", "chars": 2, "ambiguous": False})

    monkeypatch.setattr(li, "evaluate", fake_eval)
    rc = li.main(["tell", "Ada", "--text", "hi", "--send", "--json"])
    assert rc == 0
    assert '"send": true' in seen[-1]


def test_main_send_does_not_navigate(monkeypatch, capsys):
    def boom(*_a, **_k):
        raise AssertionError("send must not navigate")

    monkeypatch.setattr(li, "navigate", boom)
    monkeypatch.setattr(
        li,
        "evaluate",
        lambda port, expr, host="", page=None: json.dumps({"action": "send", "ok": True, "sent": True, "ambiguous": False}),
    )
    rc = li.main(["send", "--json"])
    assert rc == 0
    assert json.loads(capsys.readouterr().out)["sent"] is True


def test_main_send_unavailable_exits_2(monkeypatch, capsys):
    monkeypatch.setattr(
        li,
        "evaluate",
        lambda port, expr, host="", page=None: json.dumps({"action": "send", "ok": False, "sent": False, "ambiguous": False}),
    )
    rc = li.main(["send", "--json"])
    assert rc == 2


def test_main_commands_lists_agent_verbs(capsys):
    rc = li.main(["commands", "--json"])
    assert rc == 0
    names = [row["name"] for row in json.loads(capsys.readouterr().out)["commands"]]
    assert "open" in names
    assert "select" in names
    assert "tell" in names
    assert "send" in names


def test_threads_uses_the_messaging_tab_when_a_feed_tab_is_listed_first(monkeypatch, capsys):
    feed = {"id": "feed", "url": "https://www.linkedin.com/feed/", "title": "Feed | LinkedIn", "webSocketDebuggerUrl": "ws://feed"}
    msg = {
        "id": "msg",
        "url": "https://www.linkedin.com/messaging/thread/abc/",
        "title": "(5) Messaging | LinkedIn",
        "webSocketDebuggerUrl": "ws://msg",
    }
    monkeypatch.setattr(li, "pages", lambda port: [feed, msg])

    def forbid_navigate(*_a, **_k):
        raise AssertionError("feed tab must stay put when messaging is already open")

    monkeypatch.setattr(li, "navigate", forbid_navigate)
    seen: list[str] = []

    def fake_eval(port, expr, url_contains="", host="", page=None):
        seen.append("" if page is None else page.get("id", ""))
        target = page or feed
        return json.dumps(
            {
                "query": "threads",
                "url": target["url"],
                "title": target["title"],
                "threads": [{"name": "Scott Simon", "preview": "hi", "unread": False}],
                "lines": [],
            }
        )

    monkeypatch.setattr(li, "evaluate", fake_eval)
    rc = li.main(["threads", "--json", "--limit", "5"])
    assert rc == 0
    assert seen[-1] == "msg"
    payload = json.loads(capsys.readouterr().out)
    assert payload["url"].startswith("https://www.linkedin.com/messaging/")
    assert payload["threads"][0]["name"] == "Scott Simon"


def test_emit_action_plain_line(capsys):
    li.emit({"action": "tell", "matched": "Ada", "chars": 5, "sent": False}, False)
    assert capsys.readouterr().out.strip() == "tell Ada 5 chars not sent"
