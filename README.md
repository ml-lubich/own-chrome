# own-chrome

A stdlib-only agent CLI for the Google Chrome window that is already open. It
never starts a browser: no Playwright, no Chrome for Testing.

`own-chrome` talks to Chrome's debugging port to list tabs, read a tab's
title/URL, navigate one, open a new one, or run JavaScript in it.

LinkedIn automation moved to
[linkedin-mcp](https://github.com/ml-lubich/linkedin-mcp): `linkedin messages ...`.

```bash
uv tool install git+https://github.com/ml-lubich/own-chrome
```

Chrome must already be listening on `127.0.0.1:9222`. Start it yourself with a non-default user-data directory:

```bash
google-chrome --remote-debugging-port=9222 --user-data-dir="$HOME/chrome-debug"
```

On Chrome 136 and newer, the debugging port is ignored if you point it at the default profile directory.

## Agents

```
own-chrome status  [--port PORT] [--json] [--filter F] [--limit N]
own-chrome tabs    [--port PORT] [--json] [--filter F] [--limit N]
own-chrome open    url [--json] [--filter F] [--limit N]
own-chrome goto    url --tab TAB [--json]      # navigate the tab whose URL contains TAB
own-chrome eval    expression --tab TAB [--json]
```

`--filter` is a case-insensitive substring on tab title/URL; a filter that matches nothing exits 2. `--json` prints one object and nothing else.

```bash
own-chrome status --json --filter linkedin --limit 5
own-chrome tabs --json --filter linkedin
own-chrome eval "document.title" --tab example.com --json
```

## Develop

```bash
uv run --with pytest --python 3.12 pytest -q
```

### Coverage

```bash
uv run --with pytest --with pytest-cov --python 3.12 pytest -q --cov=own_chrome --cov-report=term-missing
```

Tests mock only at the boundary (Chrome's CDP websocket/HTTP, subprocess, and `lsof`/`ps`) — argument parsing and tab filtering run for real.
