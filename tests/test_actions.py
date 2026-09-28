"""Deterministic LinkedIn action builders. No Chrome."""

from __future__ import annotations

import json

from own_chrome.actions import ACT_JS, COMMANDS, act_expression, choose_linkedin_tab, on_messaging, ready_expression


def test_on_messaging_accepts_inbox_and_thread_urls():
    assert on_messaging("https://www.linkedin.com/messaging/")
    assert on_messaging("https://www.linkedin.com/messaging/thread/abc")
    assert not on_messaging("https://www.linkedin.com/feed/")
    assert not on_messaging("https://www.google.com/search?q=linkedin.com/messaging")


def test_ready_expression_is_an_async_iife():
    expr = ready_expression()
    assert expr.startswith("(async")
    assert "/messaging" in expr


def test_act_expression_embeds_escaped_payload():
    expr = act_expression("tell", 'Ann "A"', "hi\nthere", False)
    payload = json.dumps({"op": "tell", "name": 'Ann "A"', "text": "hi\nthere", "send": False}, ensure_ascii=False)
    assert payload in expr


def test_ambiguous_match_returns_before_the_card_click():
    assert ACT_JS.index("matches.length > 1") < ACT_JS.index("(link || card).click()")


def test_choose_linkedin_tab_prefers_messaging_over_an_earlier_feed_tab():
    chosen = choose_linkedin_tab([
        {"id": "feed", "url": "https://www.linkedin.com/feed/", "title": "Feed | LinkedIn"},
        {"id": "msg", "url": "https://www.linkedin.com/messaging/thread/abc/", "title": "(5) Messaging | LinkedIn"},
    ])
    assert chosen is not None
    assert chosen["id"] == "msg"


def test_choose_linkedin_tab_uses_the_feed_when_it_is_the_only_linkedin_tab():
    chosen = choose_linkedin_tab([
        {"id": "google", "url": "https://www.google.com/search?q=linkedin.com/messaging"},
        {"id": "feed", "url": "https://www.linkedin.com/feed/"},
    ])
    assert chosen is not None
    assert chosen["id"] == "feed"


def test_choose_linkedin_tab_returns_none_when_linkedin_is_closed():
    assert choose_linkedin_tab([{"id": "google", "url": "https://www.google.com/"}]) is None


def test_command_catalog_covers_agent_verbs():
    names = [row["name"] for row in COMMANDS]
    assert names[:7] == ["open", "threads", "unread", "select", "read", "tell", "send"]
    tell = next(row for row in COMMANDS if row["name"] == "tell")
    send = next(row for row in COMMANDS if row["name"] == "send")
    assert tell["sends"] is False
    assert send["sends"] is True
