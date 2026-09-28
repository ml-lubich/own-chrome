"""Typer front door for li.

Help is the agent interface. The wordmark is printed on -h/--help only.
--json stays one object.
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Literal

import typer
from typer import _click as click

from own_chrome.cdp import DEFAULT_PORT, ChromeError
from own_chrome.linkedin import (
    _act,
    _commands,
    _popups,
    _workflow,
    run_open,
    run_queries,
    run_query,
)

BANNER = """\
 _     ___
| |   |_ _|
| |    | |
| |___ | |
|_____|___|"""

CHEAT = """\
LinkedIn for agents. Run li. Do not use python -c, raw CDP, or page scraping.

li threads --filter NAME --limit 5 --json
li select NAME --json
li read --limit 8 --json
li tell NAME --text TEXT --json
li tell NAME --text TEXT --send --json

Exit 0 ok, 1 Chrome or page error, 2 no match, 3 several matches and nothing was clicked.
--json prints one object and no wordmark."""

_HELP = {"help_option_names": ["-h", "--help"]}


class LiCommand(typer.core.TyperCommand):
    def get_help(self, ctx: click.Context) -> str:
        return f"{BANNER}\n\n{super().get_help(ctx)}"


class LiGroup(typer.core.TyperGroup):
    def get_help(self, ctx: click.Context) -> str:
        return f"{BANNER}\n\n{CHEAT}\n\n{super().get_help(ctx)}"


app = typer.Typer(
    name="li",
    cls=LiGroup,
    help="Drive LinkedIn in the attached Chrome. Agents start here, not in the page.",
    no_args_is_help=True,
    add_completion=False,
    rich_markup_mode=None,
    pretty_exceptions_enable=False,
    context_settings=_HELP,
)


def _port() -> object:
    return typer.Option(DEFAULT_PORT, "--port", help="Chrome DevTools port.")


def _json() -> object:
    return typer.Option(False, "--json", help="One JSON object on stdout. No wordmark.")


def _filter() -> object:
    return typer.Option(
        "",
        "--filter",
        help="Case-insensitive match on name or preview. Exit 2 if nothing matches.",
    )


def _limit() -> object:
    return typer.Option(20, "--limit", help="Maximum threads or message lines.")


def _no_nav() -> object:
    return typer.Option(False, "--no-navigate", help="Read the current tab. Do not open messaging.")


def _ns(**kwargs: object) -> argparse.Namespace:
    data: dict[str, object] = {
        "port": DEFAULT_PORT,
        "json": False,
        "filter": "",
        "limit": 20,
        "no_navigate": False,
        "apply": False,
        "name": "",
        "text": "",
        "send": False,
        "spec": "",
        "dry_run": False,
        "cmd": "",
    }
    data.update(kwargs)
    return argparse.Namespace(**data)


def _call(fn: object, *args: object) -> None:
    try:
        code = fn(*args)  # type: ignore[operator]
    except ChromeError as exc:
        print(f"li: {exc}", file=sys.stderr)
        raise typer.Exit(code=1) from exc
    except json.JSONDecodeError as exc:
        print(f"li: page did not return JSON ({exc})", file=sys.stderr)
        raise typer.Exit(code=1) from exc
    if code:
        raise typer.Exit(code=code)


def command() -> object:
    return app.command(cls=LiCommand, context_settings=_HELP)


@command()
def open(
    port: int = _port(),
    as_json: bool = _json(),
) -> None:
    """Open LinkedIn messaging in the attached Chrome.

    Creates a tab when LinkedIn is not open. Leaves a feed tab alone when
    messaging is already open.

    \b
    Example:
      li open --json
    """
    _call(run_open, _ns(cmd="open", port=port, json=as_json))


@command()
def threads(
    port: int = _port(),
    as_json: bool = _json(),
    filter_: str = _filter(),
    limit: int = _limit(),
    no_navigate: bool = _no_nav(),
) -> None:
    """List messaging threads.

    Uses the messaging tab when one is open, even if a feed tab is listed
    first. Navigates the feed only when it is the only LinkedIn tab.

    \b
    Example:
      li threads --filter NAME --limit 5 --json
    """
    _call(
        run_query,
        _ns(cmd="threads", port=port, json=as_json, filter=filter_, limit=limit, no_navigate=no_navigate),
    )


@command()
def unread(
    port: int = _port(),
    as_json: bool = _json(),
    filter_: str = _filter(),
    limit: int = _limit(),
    no_navigate: bool = _no_nav(),
) -> None:
    """List unread messaging threads.

    Same tab rules as threads. --filter matches the name or the preview.

    \b
    Example:
      li unread --limit 10 --json
    """
    _call(
        run_query,
        _ns(cmd="unread", port=port, json=as_json, filter=filter_, limit=limit, no_navigate=no_navigate),
    )


@command()
def select(
    name: str = typer.Argument(help="Thread name, or a unique piece of it."),
    port: int = _port(),
    as_json: bool = _json(),
) -> None:
    """Open the one thread whose name contains NAME.

    Exit 2 if none match. Exit 3 if several match; nothing is clicked.

    \b
    Example:
      li select "Ada Lovelace" --json
    """
    _call(_act, _ns(cmd="select", name=name, port=port, json=as_json), "select")


@command()
def read(
    port: int = _port(),
    as_json: bool = _json(),
    limit: int = _limit(),
    no_navigate: bool = _no_nav(),
) -> None:
    """Print the last lines of the open thread.

    Does not switch threads. --limit caps the lines.

    \b
    Example:
      li read --limit 8 --json
    """
    _call(run_query, _ns(cmd="read", port=port, json=as_json, limit=limit, no_navigate=no_navigate))


@command()
def tell(
    name: str = typer.Argument(help="Thread name, or a unique piece of it."),
    text: str = typer.Option(..., "--text", help="Message to type into the composer."),
    send: bool = typer.Option(False, "--send", help="Click Send. Without this, the text is only typed."),
    port: int = _port(),
    as_json: bool = _json(),
) -> None:
    """Select a thread and type TEXT.

    Does not send unless --send is present. Use --send only when this turn
    names the recipient and the text.

    \b
    Example:
      li tell "Ada Lovelace" --text "Thanks, I'll look." --json
      li tell "Ada Lovelace" --text "Thanks, I'll look." --send --json
    """
    _call(_act, _ns(cmd="tell", name=name, text=text, send=send, port=port, json=as_json), "tell")


@command()
def send(
    port: int = _port(),
    as_json: bool = _json(),
) -> None:
    """Click Send on the text already in the open composer.

    Does not choose a thread and does not navigate. Exit 2 if Send is missing
    or disabled.

    \b
    Example:
      li send --json
    """
    _call(_act, _ns(cmd="send", port=port, json=as_json), "send")


@command()
def inbox(
    port: int = _port(),
    as_json: bool = _json(),
    filter_: str = _filter(),
    limit: int = _limit(),
    no_navigate: bool = _no_nav(),
) -> None:
    """Open messaging if needed, then list threads.

    \b
    Example:
      li inbox --limit 5 --json
    """
    _call(
        run_query,
        _ns(cmd="inbox", port=port, json=as_json, filter=filter_, limit=limit, no_navigate=no_navigate),
    )


@command()
def status(
    port: int = _port(),
    as_json: bool = _json(),
    filter_: str = _filter(),
    limit: int = _limit(),
    no_navigate: bool = _no_nav(),
) -> None:
    """List threads. Same as `li threads`.

    \b
    Example:
      li status --json
    """
    _call(
        run_query,
        _ns(cmd="status", port=port, json=as_json, filter=filter_, limit=limit, no_navigate=no_navigate),
    )


@command()
def commands(as_json: bool = _json()) -> None:
    """List the agent commands.

    No browser. Use this, or `li -h`, instead of guessing flags.

    \b
    Example:
      li commands --json
    """
    _call(_commands, as_json)


@command()
def queries(as_json: bool = _json()) -> None:
    """List the read-only query names.

    \b
    Example:
      li queries --json
    """
    _call(run_queries, as_json)


@command()
def query(
    name: Literal["threads", "unread", "read", "title", "url"] = typer.Argument(
        help="threads, unread, read, title, or url."
    ),
    port: int = _port(),
    as_json: bool = _json(),
    filter_: str = _filter(),
    limit: int = _limit(),
    no_navigate: bool = _no_nav(),
) -> None:
    """Run one read-only query.

    threads and unread follow the messaging-tab rule. title and url report
    the tab li would use. read prints the open thread.

    \b
    Example:
      li query threads --filter NAME --limit 5 --json
    """
    _call(
        run_query,
        _ns(cmd="query", name=name, port=port, json=as_json, filter=filter_, limit=limit, no_navigate=no_navigate),
    )


@command()
def popups(
    apply: bool = typer.Option(False, "--apply", help="Click the button from ~/.config/li/config.json."),
    port: int = _port(),
    as_json: bool = _json(),
) -> None:
    """Report the open LinkedIn dialog.

    Without --apply, nothing is clicked. The default for "Share your contact
    info?" is decline.

    \b
    Example:
      li popups --json
    """
    _call(_popups, _ns(cmd="popups", apply=apply, port=port, json=as_json))


@command()
def workflow(
    action: str = typer.Argument(help="Only 'run'."),
    spec: str = typer.Argument(help="Path to the workflow JSON."),
    text: str = typer.Option("", "--text", help="Thread text. Default is the open thread."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Accepted. The workflow never sends."),
    port: int = _port(),
    as_json: bool = _json(),
) -> None:
    """Classify the open thread and draft a reply.

    Never sends. sent is always false. A regex miss does not call a model.

    \b
    Example:
      li workflow run spec.json --text "coffee tomorrow?" --json
    """
    if action != "run":
        raise typer.BadParameter("action must be run")
    _call(_workflow, _ns(cmd="workflow", spec=spec, text=text, dry_run=dry_run, port=port, json=as_json))


def main(argv: list[str] | None = None) -> int:
    try:
        code = app(args=argv, standalone_mode=False)
    except typer.Exit as exc:
        return int(exc.exit_code or 0)
    except click.ClickException as exc:
        exc.show()
        return int(exc.exit_code)
    return int(code or 0)
