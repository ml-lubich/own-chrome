"""Stdlib CDP client for the Google Chrome that is already running."""

from __future__ import annotations

import base64
import json
import os
import platform
import re
import socket
import subprocess
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any
from typing import Sequence

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


def _http_json(url: str, method: str = "GET") -> Any:
    request = urllib.request.Request(url, method=method) if method != "GET" else url
    try:
        with urllib.request.urlopen(request, timeout=3) as response:
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
        local = any(
            part.startswith((f"127.0.0.1:{port}", f"[::1]:{port}", f"localhost:{port}"))
            for part in parts
        )
        if len(parts) > 1 and parts[1].isdigit() and local:
            return int(parts[1])
    raise ChromeError(f"Nothing is listening on loopback 127.0.0.1:{port}")


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


def _default_user_data_dirs() -> list[Path]:
    configured = os.environ.get("OWN_CHROME_USER_DATA_DIR")
    if configured:
        return [Path(configured).expanduser()]
    system = platform.system()
    if system == "Darwin":
        return [Path.home() / "Library/Application Support/Google/Chrome"]
    if system == "Windows":
        local_app_data = os.environ.get("LOCALAPPDATA")
        return [Path(local_app_data) / "Google/Chrome/User Data"] if local_app_data else []
    return [Path.home() / ".config/google-chrome"]


def discover(
    port: int | None = None,
    user_data_dirs: Sequence[str | Path] | None = None,
) -> dict[str, Any]:
    """Find and verify a running local Chrome CDP endpoint.

    With an explicit port, inspect only that port. Otherwise, inspect Chrome's
    DevToolsActivePort file in the known user-data directory (or the supplied
    directories). Never probes remote endpoints or launches another browser.
    """
    configured_port = os.environ.get("OWN_CHROME_CDP_PORT")
    if port is None and configured_port:
        try:
            port = int(configured_port)
        except ValueError as exc:
            raise ChromeError("OWN_CHROME_CDP_PORT must be an integer from 1 to 65535") from exc
    if port is not None:
        return _describe_process(port)

    roots = [Path(item).expanduser() for item in user_data_dirs] if user_data_dirs is not None else _default_user_data_dirs()
    errors: list[str] = []
    for root in roots:
        active_port = root / "DevToolsActivePort"
        if not active_port.is_file():
            continue
        try:
            lines = active_port.read_text(encoding="utf-8").splitlines()
        except OSError as exc:
            errors.append(f"{active_port}: {exc}")
            continue
        if len(lines) < 2:
            errors.append(f"{active_port} is incomplete")
            continue
        try:
            active = int(lines[0].strip())
        except ValueError:
            errors.append(f"{active_port} has an invalid port")
            continue
        if not 1 <= active <= 65535 or not lines[1].startswith("/devtools/browser/"):
            errors.append(f"{active_port} has an invalid CDP endpoint")
            continue
        try:
            return _describe_process(active, expected_user_data_dir=root)
        except ChromeError as exc:
            errors.append(str(exc))
    if errors:
        raise ChromeError("Could not verify Chrome from DevToolsActivePort: " + "; ".join(errors))
    raise ChromeError(
        "No Chrome CDP endpoint found. In Chrome, open chrome://inspect/#remote-debugging "
        "and enable remote debugging for this browser, or set OWN_CHROME_CDP_PORT and "
        "OWN_CHROME_USER_DATA_DIR for an existing local CDP session."
    )


def _describe_process(port: int, expected_user_data_dir: str | Path | None = None) -> dict[str, Any]:
    if not 1 <= port <= 65535:
        raise ChromeError("Chrome CDP port must be from 1 to 65535")
    pid = _listener_pid(port)
    command = _command_line(pid)
    if not _real_chrome(command):
        raise ChromeError(f"Port {port} is pid {pid}, not the installed Google Chrome")
    user_data_dir = _flag(command, "--user-data-dir")
    if expected_user_data_dir is not None:
        defaults = _default_user_data_dirs()
        if not user_data_dir and not defaults:
            raise ChromeError("Cannot verify Chrome user-data directory on this platform")
        actual = Path(user_data_dir).expanduser() if user_data_dir else defaults[0]
        expected = Path(expected_user_data_dir).expanduser()
        if actual.resolve() != expected.resolve():
            raise ChromeError("CDP Chrome profile does not match discovered profile")
    defaults = _default_user_data_dirs()
    return {
        "pid": pid,
        "browser": "",
        "user_data_dir": user_data_dir or (str(defaults[0]) if defaults else ""),
        "profile_directory": _flag(command, "--profile-directory") or "(chrome default)",
        "port": port,
    }


def describe(port: int = DEFAULT_PORT, expected_user_data_dir: str | Path | None = None) -> dict[str, Any]:
    """Return running Chrome metadata, using the version endpoint when Chrome exposes it."""
    info = _describe_process(port, expected_user_data_dir)
    try:
        version = _http_json(f"http://127.0.0.1:{port}/json/version")
    except ChromeError:
        # Chrome 147+ can intentionally withhold the HTTP discovery endpoint
        # while exposing the browser WebSocket through DevToolsActivePort.
        return info
    info["browser"] = version.get("Browser", "")
    return info


def browser_ws_url(info: dict[str, Any]) -> str:
    """Build the local browser WebSocket URL from a verified Chrome profile.

    The capability URL is deliberately not included in status metadata because
    it grants broad control over every page in that Chrome instance.
    """
    try:
        port = int(info["port"])
        root = Path(info["user_data_dir"]).expanduser()
        lines = (root / "DevToolsActivePort").read_text(encoding="utf-8").splitlines()
    except (KeyError, TypeError, ValueError, OSError) as exc:
        raise ChromeError("Could not read Chrome DevToolsActivePort for the selected profile") from exc
    if len(lines) < 2 or lines[0].strip() != str(port):
        raise ChromeError("Chrome DevToolsActivePort does not match the selected port")
    path = lines[1].strip()
    if not re.fullmatch(r"/devtools/browser/[A-Za-z0-9_-]+", path):
        raise ChromeError("Chrome DevToolsActivePort has an invalid browser WebSocket path")
    return f"ws://127.0.0.1:{port}{path}"


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


def _hostname(url: str) -> str:
    try:
        return (urllib.parse.urlparse(url).hostname or "").lower()
    except ValueError:
        return ""


def host_matches(url: str, host: str) -> bool:
    """True if url's hostname is exactly host or a subdomain of it.

    Unlike a plain substring check, this will not match a URL that merely
    mentions the host in its path or query string -- e.g. a search results
    page for "example.com" does not match host="example.com".
    """
    hostname = _hostname(url)
    host = host.lower()
    return hostname == host or hostname.endswith(f".{host}")


def pick_page(port: int, url_contains: str = "", host: str = "") -> dict[str, Any]:
    found = pages(port)
    if host:
        match = [tab for tab in found if host_matches(tab.get("url", ""), host)]
        if not match:
            raise ChromeError(f"No open tab with hostname {host!r} (or a subdomain of it)")
        return match[0]
    if url_contains:
        match = [tab for tab in found if url_contains in tab.get("url", "")]
        if not match:
            raise ChromeError(f"No open tab URL contains {url_contains!r}")
        return match[0]
    if not found:
        raise ChromeError("Chrome has no open pages")
    return found[0]


def evaluate(
    port: int,
    expression: str,
    url_contains: str = "",
    host: str = "",
    page: dict[str, Any] | None = None,
) -> Any:
    if page is None:
        page = pick_page(port, url_contains, host)
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


def navigate(port: int, url: str, url_contains: str = "", host: str = "") -> str:
    page = pick_page(port, url_contains, host)
    ws_url = page.get("webSocketDebuggerUrl")
    if not ws_url:
        raise ChromeError("Tab has no CDP websocket")
    cdp_call(ws_url, "Page.navigate", {"url": url})
    return page.get("id", "")


def open_tab(port: int, url: str) -> dict[str, Any]:
    quoted = urllib.parse.quote(url, safe=":/?&=%")
    # Chrome 154 returns 405 for GET /json/new. PUT has been the supported method.
    return _http_json(f"http://127.0.0.1:{port}/json/new?{quoted}", method="PUT")
