"""own-chrome command line."""

from __future__ import annotations

import argparse
import json
import sys

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


def emit(payload: object, as_json: bool) -> None:
    if as_json:
        json.dump(payload, sys.stdout, ensure_ascii=False)
        sys.stdout.write("\n")
        return
    if isinstance(payload, str):
        print(payload)
        return
    print(json.dumps(payload, ensure_ascii=False))


def _common(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--json", action="store_true", help="One JSON object on stdout")
    parser.add_argument("--filter", default="", help="Case-insensitive match on title or URL")
    parser.add_argument("--limit", type=int, default=20)


def main(argv: list[str] | None = None) -> int:
    common = argparse.ArgumentParser(add_help=False)
    _common(common)
    parser = argparse.ArgumentParser(prog="own-chrome", description="Drive the already-open Google Chrome.")
    sub = parser.add_subparsers(dest="cmd", required=True)
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
    except ChromeError as exc:
        print(f"own-chrome: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
