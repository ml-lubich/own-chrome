---
name: own-chrome
description: Drive the Google Chrome the user already has open, via Chrome's DevTools Protocol on 127.0.0.1:9222 — no second browser, no Playwright. Use when the user wants their real signed-in Chrome tabs read or navigated ("check my tabs", "open that page", "read this tab's title"). Do not launch a fresh browser. For LinkedIn automation, use linkedin-mcp instead.
---

# own-chrome

A stdlib-only Python CLI (`own-chrome`) that talks to the Google Chrome the
user already launched with debugging enabled — no separate automation
browser, no Playwright/Selenium/Chrome-for-Testing (those are explicitly
rejected, see below).

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
tabs. If it errors, Chrome isn't up on 9222 yet, or the listener isn't the
real Google Chrome (automation-launched Chrome — flagged by
`--enable-automation`, Playwright, or "chrome for testing" — is deliberately
rejected).

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
