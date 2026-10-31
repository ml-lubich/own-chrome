"""own-chrome command line."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

from own_chrome import cdp
from own_chrome.cdp import (
    DEFAULT_PORT,
    ChromeError,
    describe,
    evaluate,
    filter_pages,
    navigate,
    open_tab,
    pages,
)

try:
    __version__ = version("own-chrome")
except PackageNotFoundError:
    __version__ = "unknown"


def emit(payload: object, as_json: bool) -> None:
    if as_json:
        json.dump(payload, sys.stdout, ensure_ascii=False)
        sys.stdout.write("\n")
        return
    if isinstance(payload, str):
        print(payload)
        return
    print(json.dumps(payload, ensure_ascii=False))


class HelpFormatter(argparse.RawDescriptionHelpFormatter):
    """Branded help with shaded terminal art and a monochrome fallback."""

    def __init__(self, *args, **kwargs):
        try:
            is_tty = sys.stdout.isatty()
        except (AttributeError, OSError, ValueError):
            is_tty = False
        self._color = (
            is_tty
            and os.environ.get("NO_COLOR") is None
            and os.environ.get("TERM", "") not in ("", "dumb")
        )
        super().__init__(*args, **kwargs)

    def format_help(self):
        body = super().format_help()
        art = (
            "                      __                                __\n"
            "  ____ _ _      ___  / /_      ________  ________  ____/ /__\n"
            " / __ `// | /| / / |/ / /     / ___/ _ \\/ ___/ _ \\/ __  / _ \\\n"
            "/ /_/ //| |/ |/ /|   / /__   (__  )  __/ /  /  __/ /_/ /  __/\n"
            "\\__,_/ |__/|__/ |_/|_/____/  /____/\\___/_/   \\___/\\__,_/\\___/"
        )
        if self._color:
            shades = (
                "\033[38;2;225;204;255m",
                "\033[38;2;205;222;255m",
                "\033[38;2;190;237;255m",
                "\033[38;2;210;250;243m",
                "\033[38;2;255;226;241m",
                "\033[38;2;232;210;255m",
            )
            art = "\n".join(
                f"{shades[index]}{line}\033[0m"
                for index, line in enumerate(art.splitlines())
            )
        return art + "\n\n" + body


class VersionAction(argparse.Action):
    def __init__(self, option_strings, dest, version, **kwargs):
        self.version = version
        super().__init__(option_strings, dest, nargs=0, **kwargs)

    def __call__(self, parser, namespace, values, option_string=None):
        print(self.version)
        parser.exit()


def _parser(*args, **kwargs) -> argparse.ArgumentParser:
    kwargs.setdefault("formatter_class", HelpFormatter)
    return argparse.ArgumentParser(*args, **kwargs)


def _common(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--json", action="store_true", help="One JSON object on stdout")
    parser.add_argument("--filter", default="", help="Case-insensitive match on title or URL")
    parser.add_argument("--limit", type=int, default=20)


def _browser_harness_env(browser: dict[str, object], endpoint: str) -> dict[str, str]:
    """Pin Browser Harness to this profile without reusing another profile's daemon."""
    env = os.environ.copy()
    env["BU_CDP_WS"] = endpoint
    if "BH_RUNTIME_DIR" not in env:
        user_data_dir = browser.get("user_data_dir")
        if not isinstance(user_data_dir, str) or not user_data_dir:
            raise ChromeError("Chrome discovery did not return the selected user data directory")
        normalized = str(Path(user_data_dir).expanduser().resolve())
        profile_hash = hashlib.sha256(normalized.encode()).hexdigest()[:12]
        env["BH_RUNTIME_DIR"] = str(Path.home() / ".config/own-chrome/bh" / profile_hash)
    return env


def main(argv: list[str] | None = None) -> int:
    common = _parser(add_help=False)
    _common(common)
    parser = argparse.ArgumentParser(
        prog="own-chrome",
        description="Drive the already-open Google Chrome.",
        formatter_class=HelpFormatter,
    )
    parser.add_argument("-V", "--version", action=VersionAction, version=f"own-chrome {__version__}")
    sub = parser.add_subparsers(dest="cmd", required=True, parser_class=_parser)
    sub.add_parser("status", parents=[common])
    sub.add_parser("tabs", parents=[common])
    open_cmd = sub.add_parser("open", parents=[common])
    open_cmd.add_argument("url")
    goto = sub.add_parser("goto", parents=[common])
    goto.add_argument("url")
    goto.add_argument("--tab", default="", help="Navigate the tab whose URL contains this")
    ev = sub.add_parser("eval", parents=[common])
    ev.add_argument("expression")
    ev.add_argument("--tab", default="")
    agent = sub.add_parser(
        "agent",
        help="Run Browser Harness against an already-running local Chrome",
        description=(
            "Hand off to Browser Use's browser-harness CLI for agent-directed browsing in the existing local "
            "Chrome session. This never launches a browser or uses a cloud browser."
        ),
    )
    agent.add_argument(
        "--check",
        action="store_true",
        help="Check for a reachable, real Chrome CDP endpoint without starting the harness",
    )
    agent.add_argument("--json", action="store_true", help="Print the check result as JSON")
    args = parser.parse_args(argv)
    try:
        if args.cmd == "status":
            info = describe(args.port)
            info["tabs"] = filter_pages(pages(args.port), args.filter, args.limit)
            if args.json:
                emit(info, True)
            else:
                print(f"browser: {info['browser']}")
                print(f"pid: {info['pid']}")
                print(f"profile: {info['profile_directory']}")
                print(f"data_dir: {info['user_data_dir']}")
                print(f"cdp: http://127.0.0.1:{args.port}")
                for tab in info["tabs"]:
                    print(f"  {tab['title'][:60]}  {tab['url']}")
        elif args.cmd == "tabs":
            rows = filter_pages(pages(args.port), args.filter, args.limit)
            if args.json:
                emit({"tabs": rows}, True)
            else:
                for tab in rows:
                    print(f"{tab['title'][:60]}\t{tab['url']}")
            if args.filter and not rows:
                return 2
        elif args.cmd == "open":
            tab = open_tab(args.port, args.url)
            emit({"url": tab.get("url", args.url), "title": tab.get("title", "")}, args.json)
        elif args.cmd == "goto":
            navigate(args.port, args.url, args.tab)
            emit({"url": args.url}, args.json)
        elif args.cmd == "eval":
            value = evaluate(args.port, args.expression, args.tab or args.filter)
            emit({"value": value}, args.json)
        elif args.cmd == "agent":
            try:
                browser = cdp.discover()
            except ChromeError as exc:
                message = str(exc)
                if "chrome://inspect/#remote-debugging" not in message:
                    message += (
                        ". In Chrome, open chrome://inspect/#remote-debugging and enable "
                        "'Allow remote debugging for this browser instance', then retry."
                    )
                raise ChromeError(message) from exc
            if args.check:
                browser_name = browser.get("browser") or "Google Chrome (version unavailable)"
                if args.json:
                    emit({**browser, "browser": browser_name}, True)
                else:
                    print(
                        f"Chrome CDP ready: {browser_name} on 127.0.0.1:{browser['port']} "
                        f"({browser.get('profile_directory', 'profile')})"
                    )
                return 0
            endpoint = cdp.browser_ws_url(browser)
            harness = shutil.which("browser-harness")
            if harness is None:
                raise ChromeError(
                    "browser-harness is not installed. Install Browser Use's local Browser "
                    "Harness, then retry; no browser was launched."
                )
            # Browser Harness reads agent-provided Python from stdin. execvpe preserves stdin,
            # stdout, stderr, signals, and exit status, and lets the harness detach cleanly.
            env = _browser_harness_env(browser, endpoint)
            os.execvpe(harness, ["browser-harness"], env)
    except ChromeError as exc:
        print(f"own-chrome: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
