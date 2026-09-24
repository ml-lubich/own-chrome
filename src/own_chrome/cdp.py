"""Stdlib CDP client for the Google Chrome that is already running."""

from __future__ import annotations

import base64
import json
import os
import socket
import subprocess
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

DEFAULT_PORT = 9222
REJECT_MARKERS = (
    "--enable-automation",
    "chrome-devtools-mcp",
    "ms-playwright",
    "chrome-for-testing",
    "chrome for testing",
)


class ChromeError(RuntimeError):
    pass


def _http_json(url: str) -> Any:
    try:
        with urllib.request.urlopen(url, timeout=3) as response:
            return json.loads(response.read().decode())
    except urllib.error.URLError as exc:
        raise ChromeError(f"Chrome CDP is not up at {url}: {exc}") from exc


def _listener_pid(port: int) -> int:
    try:
        out = subprocess.check_output(
            ["lsof", "-nP", f"-iTCP:{port}", "-sTCP:LISTEN"],
            text=True,
            stderr=subprocess.DEVNULL,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise ChromeError(f"Could not see who is listening on {port}") from exc
    for line in out.splitlines()[1:]:
        parts = line.split()
        if len(parts) > 1 and parts[1].isdigit():
            return int(parts[1])
    raise ChromeError(f"Nothing is listening on 127.0.0.1:{port}")


def _command_line(pid: int) -> str:
    out = subprocess.check_output(["ps", "-p", str(pid), "-o", "command="], text=True)
    return out.strip()


def _flag(command: str, name: str) -> str:
    needle = f"{name}="
    parts = command.split()
    for index, part in enumerate(parts):
        if not part.startswith(needle):
            continue
        value = [part[len(needle):]]
        for extra in parts[index + 1:]:
            if extra.startswith("--"):
                break
            value.append(extra)
        return " ".join(piece for piece in value if piece)
    return ""


def _real_chrome(command: str) -> bool:
    lowered = command.lower()
    if any(marker in lowered for marker in REJECT_MARKERS):
        return False
    return "google chrome" in lowered or lowered.startswith("chrome ")


def describe(port: int = DEFAULT_PORT) -> dict[str, Any]:
    pid = _listener_pid(port)
    command = _command_line(pid)
    if not _real_chrome(command):
        raise ChromeError(f"Port {port} is pid {pid}, not the installed Google Chrome")
    version = _http_json(f"http://127.0.0.1:{port}/json/version")
    return {
        "pid": pid,
        "browser": version.get("Browser", ""),
        "user_data_dir": _flag(command, "--user-data-dir"),
        "profile_directory": _flag(command, "--profile-directory") or "(chrome default)",
        "port": port,
    }


def pages(port: int = DEFAULT_PORT) -> list[dict[str, Any]]:
    tabs = _http_json(f"http://127.0.0.1:{port}/json/list")
    return [tab for tab in tabs if tab.get("type") == "page"]


def filter_pages(tabs: list[dict[str, Any]], needle: str, limit: int) -> list[dict[str, str]]:
    query = needle.lower()
    rows: list[dict[str, str]] = []
    for tab in tabs:
        title = tab.get("title") or ""
        url = tab.get("url") or ""
        if query and query not in title.lower() and query not in url.lower():
            continue
        rows.append({"title": title, "url": url})
        if limit and len(rows) >= limit:
            break
    return rows


def _ws_connect(ws_url: str) -> socket.socket:
    parsed = urllib.parse.urlparse(ws_url)
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port or 80
    path = parsed.path or "/"
    if parsed.query:
        path = f"{path}?{parsed.query}"
    sock = socket.create_connection((host, port), timeout=5)
    key = base64.b64encode(os.urandom(16)).decode()
    request = (
        f"GET {path} HTTP/1.1\r\n"
        f"Host: {host}:{port}\r\n"
        "Upgrade: websocket\r\n"
        "Connection: Upgrade\r\n"
        f"Sec-WebSocket-Key: {key}\r\n"
        "Sec-WebSocket-Version: 13\r\n"
        "\r\n"
    )
    sock.sendall(request.encode())
    data = b""
    while b"\r\n\r\n" not in data:
        chunk = sock.recv(4096)
        if not chunk:
            break
        data += chunk
    if b" 101 " not in data.split(b"\r\n", 1)[0]:
        raise ChromeError(f"WebSocket upgrade failed: {data[:200]!r}")
    return sock


def _ws_send(sock: socket.socket, text: str) -> None:
    payload = text.encode()
    header = bytearray([0x81])
    length = len(payload)
    if length < 126:
        header.append(0x80 | length)
    elif length < 65536:
        header.append(0x80 | 126)
        header.extend(length.to_bytes(2, "big"))
    else:
        header.append(0x80 | 127)
        header.extend(length.to_bytes(8, "big"))
    mask = os.urandom(4)
    header.extend(mask)
    masked = bytes(byte ^ mask[i % 4] for i, byte in enumerate(payload))
    sock.sendall(bytes(header) + masked)


def _ws_recv(sock: socket.socket) -> str:
    def read_exact(n: int) -> bytes:
        buf = b""
        while len(buf) < n:
            chunk = sock.recv(n - len(buf))
            if not chunk:
                raise ChromeError("Chrome closed the CDP socket")
            buf += chunk
        return buf

    first, second = read_exact(2)
    opcode = first & 0x0F
    length = second & 0x7F
    if length == 126:
        length = int.from_bytes(read_exact(2), "big")
    elif length == 127:
        length = int.from_bytes(read_exact(8), "big")
    if second & 0x80:
        mask = read_exact(4)
        payload = bytes(byte ^ mask[i % 4] for i, byte in enumerate(read_exact(length)))
    else:
        payload = read_exact(length)
    if opcode == 0x8:
        raise ChromeError("Chrome closed the CDP session")
    if opcode != 0x1:
        return ""
    return payload.decode()


def cdp_call(ws_url: str, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    sock = _ws_connect(ws_url)
    try:
        _ws_send(sock, json.dumps({"id": 1, "method": method, "params": params or {}}))
        while True:
            raw = _ws_recv(sock)
            if not raw:
                continue
            message = json.loads(raw)
            if message.get("id") == 1:
                if "error" in message:
                    raise ChromeError(json.dumps(message["error"]))
                return message.get("result", {})
    finally:
        sock.close()


def pick_page(port: int, url_contains: str) -> dict[str, Any]:
    found = pages(port)
    if url_contains:
        match = [tab for tab in found if url_contains in tab.get("url", "")]
        if not match:
            raise ChromeError(f"No open tab URL contains {url_contains!r}")
        return match[0]
    if not found:
        raise ChromeError("Chrome has no open pages")
    return found[0]


def evaluate(port: int, expression: str, url_contains: str = "") -> Any:
    page = pick_page(port, url_contains)
    ws_url = page.get("webSocketDebuggerUrl")
    if not ws_url:
        raise ChromeError("Tab has no CDP websocket")
    result = cdp_call(
        ws_url,
        "Runtime.evaluate",
        {"expression": expression, "returnByValue": True, "awaitPromise": True},
    )
    if "exceptionDetails" in result:
        raise ChromeError(json.dumps(result["exceptionDetails"])[:500])
    return result.get("result", {}).get("value")


def navigate(port: int, url: str, url_contains: str = "") -> str:
    page = pick_page(port, url_contains)
    ws_url = page.get("webSocketDebuggerUrl")
    if not ws_url:
        raise ChromeError("Tab has no CDP websocket")
    cdp_call(ws_url, "Page.navigate", {"url": url})
    return page.get("id", "")


def open_tab(port: int, url: str) -> dict[str, Any]:
    quoted = urllib.parse.quote(url, safe=":/?&=%")
    return _http_json(f"http://127.0.0.1:{port}/json/new?{quoted}")
