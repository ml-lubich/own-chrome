---
name: own-chrome
description: Inspect or lightly navigate the user's already-open Google Chrome via own-chrome. For general interactive web automation, use Veil Browser MCP attached to the intended Chrome session; own-chrome remains the small status/tab/navigation CLI. For LinkedIn workflows, use linkedin-mcp.
---

# own-chrome

A stdlib-only Python CLI (`own-chrome`) for status, tab listing, opening and
navigating tabs in Google Chrome with remote debugging enabled. For richer
interactive automation, prefer the Veil Browser MCP runtime (`veil-mcp`),
which owns its CDP transport and can attach to the intended Chrome session.
Do not add a second CDP client or duplicate Veil's browser interaction layer
here.

LinkedIn automation lives in a separate package,
[linkedin-mcp](https://github.com/ml-lubich/linkedin-mcp) (`linkedin messages ...`),
not here.

## Install

```bash
uv tool install -e ~/dev/own-chrome
```

From a fresh clone:

```bash
git clone https://github.com/ml-lubich/own-chrome && uv tool install -e ./own-chrome
```

## Required Chrome setup (must happen before the CLI works)

Chrome must be listening on `127.0.0.1:9222`. **Chrome 136+ ignores
`--remote-debugging-port` on the default profile directory**, so you must
point `--user-data-dir` at a non-default path:

```bash
"/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" \
  --remote-debugging-port=9222 --user-data-dir="$HOME/chrome-debug"
```

That is a separate Chrome profile (own cookies/logins). To keep the user's
real signed-in sessions, they need to be already signed in inside that
profile (or have copied their real profile into it once) — this tool never
manages that for you and never logs anyone in.

Verify: `own-chrome status` should print the browser version, pid, and open
tabs. If it errors, Chrome isn't up on 9222 yet, or inspect the listener
before acting. Veil is the preferred runtime for agent-driven interaction;
this CLI does not claim to provide stealth or broad automation features.

## Commands (from `own-chrome --help`)

```
own-chrome status  [--port PORT] [--json] [--filter F] [--limit N]
own-chrome tabs    [--port PORT] [--json] [--filter F] [--limit N]
own-chrome open    url [--json] [--filter F] [--limit N]
own-chrome goto    url --tab TAB [--json]      # navigate the tab whose URL contains TAB
own-chrome eval    expression --tab TAB [--json]
```

`--filter` is a case-insensitive substring on tab title/URL; a filter that
matches nothing exits 2. Always pass `--json` from an agent.

```bash
own-chrome status --json --filter linkedin --limit 5
own-chrome tabs --json
own-chrome eval "document.title" --tab example.com --json
```

## MCP

There is no MCP server in this repo — `own-chrome` is CLI-only. Call it via
Bash/subprocess from an agent, not `claude mcp add`.

## macOS permissions

None. This tool never uses AppleScript/Apple Events — it talks to Chrome
purely over `127.0.0.1:9222` (CDP HTTP + a hand-rolled WebSocket client) and
shells out to `ps`/`lsof` to verify the listening process is the real Google
Chrome. No Automation, Full Disk Access, Contacts, or Calendar prompt is
triggered. The only requirement is Chrome itself running with the launch
flags above.

## Safety rules

- Read-only by default: `status`, `tabs`.
- `own-chrome goto`/`eval` can navigate or act on the real, already-open tab.
  Only use them with side effects when the user explicitly asked for that
  action.
