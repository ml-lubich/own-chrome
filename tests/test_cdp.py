"""Tests for own_chrome.cdp.

Boundary mocks only: subprocess.check_output (process inspection) and
urllib.request.urlopen / socket.create_connection (talking to Chrome).
Everything else -- flag parsing, page filtering, websocket framing, error
paths -- runs for real.
"""

from __future__ import annotations

import json
import subprocess

import pytest

from own_chrome import cdp


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


def test_flag_extracts_equals_value():
    command = "google-chrome --user-data-dir=/Users/me/chrome-debug --remote-debugging-port=9222"
    assert cdp._flag(command, "--user-data-dir") == "/Users/me/chrome-debug"


def test_flag_missing_returns_empty():
    assert cdp._flag("google-chrome --remote-debugging-port=9222", "--user-data-dir") == ""


def test_flag_stops_at_next_dashed_arg():
    command = "google-chrome --profile-directory=Default --remote-debugging-port=9222"
    assert cdp._flag(command, "--profile-directory") == "Default"


@pytest.mark.parametrize(
    "command,expected",
    [
        ("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome --port=9222", True),
        ("chrome --headless", True),
        ("/usr/bin/chrome-for-testing --port=9222", False),
        ("node ms-playwright/chromium --port=9222", False),
        ("chrome --enable-automation", False),
        ("/usr/bin/vim", False),
    ],
)
def test_real_chrome_detection(command, expected):
    assert cdp._real_chrome(command) is expected


def test_filter_pages_matches_title_or_url_case_insensitively():
    tabs = [
        {"title": "LinkedIn Feed", "url": "https://linkedin.com/feed"},
        {"title": "Example", "url": "https://example.com"},
    ]
    rows = cdp.filter_pages(tabs, "linkedin", limit=10)
    assert rows == [{"title": "LinkedIn Feed", "url": "https://linkedin.com/feed"}]


def test_filter_pages_no_query_returns_all_up_to_limit():
    tabs = [{"title": f"tab{i}", "url": f"https://x/{i}"} for i in range(5)]
    rows = cdp.filter_pages(tabs, "", limit=2)
    assert len(rows) == 2


def test_filter_pages_zero_limit_is_unbounded():
    tabs = [{"title": f"tab{i}", "url": f"https://x/{i}"} for i in range(5)]
    rows = cdp.filter_pages(tabs, "", limit=0)
    assert len(rows) == 5


# ---------------------------------------------------------------------------
# subprocess boundary
# ---------------------------------------------------------------------------


def test_listener_pid_parses_lsof_output(monkeypatch):
    output = "COMMAND PID USER FD TYPE\nGoogle 4321 me 10u IPv4\n"
    monkeypatch.setattr(cdp.subprocess, "check_output", lambda *a, **k: output)
    assert cdp._listener_pid(9222) == 4321


def test_listener_pid_no_match_raises(monkeypatch):
    monkeypatch.setattr(cdp.subprocess, "check_output", lambda *a, **k: "COMMAND PID\n")
    with pytest.raises(cdp.ChromeError, match="Nothing is listening"):
        cdp._listener_pid(9222)


def test_listener_pid_lsof_failure_raises(monkeypatch):
    def raise_error(*a, **k):
        raise subprocess.CalledProcessError(1, "lsof")

    monkeypatch.setattr(cdp.subprocess, "check_output", raise_error)
    with pytest.raises(cdp.ChromeError, match="Could not see who is listening"):
        cdp._listener_pid(9222)


def test_command_line_strips_output(monkeypatch):
    monkeypatch.setattr(cdp.subprocess, "check_output", lambda *a, **k: "google chrome --port=9222\n")
    assert cdp._command_line(4321) == "google chrome --port=9222"


# ---------------------------------------------------------------------------
# HTTP boundary
# ---------------------------------------------------------------------------


class _FakeResponse:
    def __init__(self, payload: bytes):
        self._payload = payload

    def read(self) -> bytes:
        return self._payload

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def test_http_json_parses_body(monkeypatch):
    monkeypatch.setattr(
        cdp.urllib.request,
        "urlopen",
        lambda url, timeout=3: _FakeResponse(json.dumps({"ok": True}).encode()),
    )
    assert cdp._http_json("http://127.0.0.1:9222/json/version") == {"ok": True}


def test_http_json_connection_refused_raises(monkeypatch):
    def raise_error(url, timeout=3):
        raise cdp.urllib.error.URLError("connection refused")

    monkeypatch.setattr(cdp.urllib.request, "urlopen", raise_error)
    with pytest.raises(cdp.ChromeError, match="Chrome CDP is not up"):
        cdp._http_json("http://127.0.0.1:9222/json/version")


def _mock_process_boundary(monkeypatch, command: str):
    def fake_check_output(args, **kwargs):
        if args[0] == "lsof":
            return "COMMAND PID\nGoogle 4321 me\n"
        return command

    monkeypatch.setattr(cdp.subprocess, "check_output", fake_check_output)


def test_describe_returns_browser_info(monkeypatch):
    _mock_process_boundary(
        monkeypatch,
        "/Applications/Google Chrome.app/MacOS/Google Chrome "
        "--user-data-dir=/tmp/chrome-debug --remote-debugging-port=9222",
    )
    monkeypatch.setattr(
        cdp.urllib.request,
        "urlopen",
        lambda url, timeout=3: _FakeResponse(json.dumps({"Browser": "Chrome/120.0"}).encode()),
    )
    info = cdp.describe(9222)
    assert info["pid"] == 4321
    assert info["browser"] == "Chrome/120.0"
    assert info["user_data_dir"] == "/tmp/chrome-debug"
    assert info["profile_directory"] == "(chrome default)"


def test_describe_rejects_non_chrome_listener(monkeypatch):
    _mock_process_boundary(monkeypatch, "node ms-playwright/launch.js --port=9222")
    with pytest.raises(cdp.ChromeError, match="not the installed Google Chrome"):
        cdp.describe(9222)


def test_pages_filters_to_page_type(monkeypatch):
    monkeypatch.setattr(
        cdp.urllib.request,
        "urlopen",
        lambda url, timeout=3: _FakeResponse(
            json.dumps(
                [
                    {"type": "page", "url": "https://a", "title": "A"},
                    {"type": "background_page", "url": "https://b", "title": "B"},
                ]
            ).encode()
        ),
    )
    rows = cdp.pages(9222)
    assert [r["title"] for r in rows] == ["A"]


def test_open_tab_quotes_url(monkeypatch):
    captured = {}

    def fake_urlopen(url, timeout=3):
        captured["url"] = url
        return _FakeResponse(json.dumps({"url": "https://example.com/a b", "title": "t"}).encode())

    monkeypatch.setattr(cdp.urllib.request, "urlopen", fake_urlopen)
    tab = cdp.open_tab(9222, "https://example.com/a b")
    assert "a%20b" in captured["url"]
    assert tab["title"] == "t"


def test_pick_page_returns_matching_tab(monkeypatch):
    monkeypatch.setattr(cdp, "pages", lambda port: [
        {"url": "https://a.com", "id": "1"},
        {"url": "https://linkedin.com/x", "id": "2"},
    ])
    page = cdp.pick_page(9222, "linkedin")
    assert page["id"] == "2"


def test_pick_page_no_match_raises(monkeypatch):
    monkeypatch.setattr(cdp, "pages", lambda port: [{"url": "https://a.com", "id": "1"}])
    with pytest.raises(cdp.ChromeError, match="No open tab URL contains"):
        cdp.pick_page(9222, "linkedin")


def test_pick_page_no_pages_raises(monkeypatch):
    monkeypatch.setattr(cdp, "pages", lambda port: [])
    with pytest.raises(cdp.ChromeError, match="no open pages"):
        cdp.pick_page(9222, "")


def test_pick_page_defaults_to_first(monkeypatch):
    monkeypatch.setattr(cdp, "pages", lambda port: [{"url": "https://a.com", "id": "1"}])
    assert cdp.pick_page(9222, "")["id"] == "1"


# ---------------------------------------------------------------------------
# Websocket boundary (fake socket standing in for Chrome's end)
# ---------------------------------------------------------------------------


class _FakeSocket:
    """Feeds pre-scripted byte chunks to whatever calls .recv(n)."""

    def __init__(self, chunks: list[bytes]):
        self._chunks = list(chunks)
        self.sent: list[bytes] = []
        self.closed = False

    def sendall(self, data: bytes) -> None:
        self.sent.append(data)

    def recv(self, n: int) -> bytes:
        if not self._chunks:
            return b""
        chunk = self._chunks.pop(0)
        assert len(chunk) <= n, f"chunk of {len(chunk)} bytes exceeds requested {n}"
        return chunk

    def close(self) -> None:
        self.closed = True


def _server_frame_chunks(text: str, opcode: int = 0x1) -> list[bytes]:
    """Byte chunks sized exactly as cdp._ws_recv's read_exact calls expect them."""
    payload = text.encode()
    length = len(payload)
    chunks = []
    if length < 126:
        chunks.append(bytes([0x80 | opcode, length]))
    elif length < 65536:
        chunks.append(bytes([0x80 | opcode, 126]))
        chunks.append(length.to_bytes(2, "big"))
    else:
        chunks.append(bytes([0x80 | opcode, 127]))
        chunks.append(length.to_bytes(8, "big"))
    chunks.append(payload)
    return chunks


HANDSHAKE_OK = b"HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\n\r\n"


def test_ws_round_trip_via_cdp_call(monkeypatch):
    message = json.dumps({"id": 1, "result": {"value": 42}})
    fake = _FakeSocket([HANDSHAKE_OK, *_server_frame_chunks(message)])
    monkeypatch.setattr(cdp.socket, "create_connection", lambda addr, timeout=5: fake)

    result = cdp.cdp_call("ws://127.0.0.1:9222/devtools/page/1", "Runtime.evaluate", {"expression": "1"})
    assert result == {"value": 42}
    assert fake.closed is True
    # the outgoing CDP frame (sent after the handshake request) is masked, per RFC 6455
    outgoing = fake.sent[-1]
    assert outgoing[0] == 0x81
    assert outgoing[1] & 0x80


def test_ws_medium_length_frame_round_trips(monkeypatch):
    big_value = "x" * 200
    message = json.dumps({"id": 1, "result": {"value": big_value}})
    fake = _FakeSocket([HANDSHAKE_OK, *_server_frame_chunks(message)])
    monkeypatch.setattr(cdp.socket, "create_connection", lambda addr, timeout=5: fake)

    result = cdp.cdp_call("ws://127.0.0.1:9222/devtools/page/1", "Runtime.evaluate", None)
    assert result == {"value": big_value}


def test_ws_connect_bad_upgrade_raises(monkeypatch):
    fake = _FakeSocket([b"HTTP/1.1 404 Not Found\r\n\r\n"])
    monkeypatch.setattr(cdp.socket, "create_connection", lambda addr, timeout=5: fake)
    with pytest.raises(cdp.ChromeError, match="WebSocket upgrade failed"):
        cdp.cdp_call("ws://127.0.0.1:9222/devtools/page/1", "Runtime.evaluate")


def test_cdp_call_error_message_raises(monkeypatch):
    message = json.dumps({"id": 1, "error": {"message": "boom"}})
    fake = _FakeSocket([HANDSHAKE_OK, *_server_frame_chunks(message)])
    monkeypatch.setattr(cdp.socket, "create_connection", lambda addr, timeout=5: fake)
    with pytest.raises(cdp.ChromeError, match="boom"):
        cdp.cdp_call("ws://127.0.0.1:9222/devtools/page/1", "Runtime.evaluate")


def test_cdp_call_close_opcode_raises(monkeypatch):
    close_header = bytes([0x88, 0])
    fake = _FakeSocket([HANDSHAKE_OK, close_header])
    monkeypatch.setattr(cdp.socket, "create_connection", lambda addr, timeout=5: fake)
    with pytest.raises(cdp.ChromeError, match="closed the CDP session"):
        cdp.cdp_call("ws://127.0.0.1:9222/devtools/page/1", "Runtime.evaluate")


def test_ws_recv_skips_non_text_frames(monkeypatch):
    message = json.dumps({"id": 1, "result": {"value": "ok"}})
    fake = _FakeSocket(
        [
            HANDSHAKE_OK,
            *_server_frame_chunks("ignored", opcode=0x2),
            *_server_frame_chunks(message),
        ]
    )
    monkeypatch.setattr(cdp.socket, "create_connection", lambda addr, timeout=5: fake)
    result = cdp.cdp_call("ws://127.0.0.1:9222/devtools/page/1", "Runtime.evaluate")
    assert result == {"value": "ok"}


def test_cdp_call_socket_closed_mid_read_raises(monkeypatch):
    # Handshake succeeds, then Chrome hangs up before sending a full frame header.
    fake = _FakeSocket([HANDSHAKE_OK, b"\x81"])
    monkeypatch.setattr(cdp.socket, "create_connection", lambda addr, timeout=5: fake)
    with pytest.raises(cdp.ChromeError, match="closed the CDP socket"):
        cdp.cdp_call("ws://127.0.0.1:9222/devtools/page/1", "Runtime.evaluate")


# ---------------------------------------------------------------------------
# evaluate / navigate (compose pick_page + cdp_call)
# ---------------------------------------------------------------------------


def test_evaluate_returns_value(monkeypatch):
    monkeypatch.setattr(cdp, "pages", lambda port: [
        {"url": "https://linkedin.com", "webSocketDebuggerUrl": "ws://x"}
    ])
    monkeypatch.setattr(cdp, "cdp_call", lambda ws_url, method, params=None: {"result": {"value": "hi"}})
    assert cdp.evaluate(9222, "1+1", "linkedin") == "hi"


def test_evaluate_raises_on_exception_details(monkeypatch):
    monkeypatch.setattr(cdp, "pages", lambda port: [
        {"url": "https://linkedin.com", "webSocketDebuggerUrl": "ws://x"}
    ])
    monkeypatch.setattr(
        cdp,
        "cdp_call",
        lambda ws_url, method, params=None: {"exceptionDetails": {"text": "ReferenceError"}},
    )
    with pytest.raises(cdp.ChromeError, match="ReferenceError"):
        cdp.evaluate(9222, "bad js", "linkedin")


def test_evaluate_requires_websocket_url(monkeypatch):
    monkeypatch.setattr(cdp, "pages", lambda port: [{"url": "https://linkedin.com"}])
    with pytest.raises(cdp.ChromeError, match="no CDP websocket"):
        cdp.evaluate(9222, "1+1", "linkedin")


def test_navigate_calls_page_navigate(monkeypatch):
    calls = []
    monkeypatch.setattr(cdp, "pages", lambda port: [
        {"url": "https://linkedin.com", "id": "42", "webSocketDebuggerUrl": "ws://x"}
    ])

    def fake_cdp_call(ws_url, method, params=None):
        calls.append((method, params))
        return {}

    monkeypatch.setattr(cdp, "cdp_call", fake_cdp_call)
    tab_id = cdp.navigate(9222, "https://linkedin.com/feed", "linkedin")
    assert tab_id == "42"
    assert calls == [("Page.navigate", {"url": "https://linkedin.com/feed"})]


def test_navigate_requires_websocket_url(monkeypatch):
    monkeypatch.setattr(cdp, "pages", lambda port: [{"url": "https://linkedin.com", "id": "42"}])
    with pytest.raises(cdp.ChromeError, match="no CDP websocket"):
        cdp.navigate(9222, "https://linkedin.com/feed", "linkedin")
