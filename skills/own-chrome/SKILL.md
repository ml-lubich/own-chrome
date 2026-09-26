---
name: own-chrome
description: Drive the Google Chrome the user already has open (own-chrome) and query LinkedIn in that same window (li), via Chrome's DevTools Protocol on 127.0.0.1:9222 — no second browser, no Playwright. Use when the user wants their real signed-in Chrome tabs read, filtered, navigated, or JS-evaluated ("check my tabs", "what's open in Chrome", "read this page", "check LinkedIn unread", "check my LinkedIn inbox", "classify this LinkedIn thread"). Do not use to launch a fresh/automated browser — that's a different tool. Read-only by default; only `li popups --apply` and `own-chrome goto/eval` can act on the page, and only when the user explicitly asks.
---

# own-chrome / li

Two stdlib-only Python CLIs (`own-chrome`, `li`) that talk to the Google Chrome
the user already launched with debugging enabled — no separate automation
browser, no Playwright/Selenium/Chrome-for-Testing (those are explicitly
rejected, see below).

## Install

```bash
uv tool install -e ~/dev/own-chrome
```

From a fresh clone:

```bash
git clone https://github.com/ml-lubich/own-chrome && uv tool install -e ./own-chrome
```

## Required Chrome setup (must happen before either CLI works)

Chrome must be listening on `127.0.0.1:9222`. **Chrome 136+ ignores
`--remote-debugging-port` on the default profile directory**, so you must
point `--user-data-dir` at a non-default path:

```bash
"/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" \
  --remote-debugging-port=9222 --user-data-dir="$HOME/chrome-debug"
```

That is a separate Chrome profile (own cookies/logins). To keep the user's
real LinkedIn/etc. session, they need to be already signed in inside that
profile (or have copied their real profile into it once) — this tool never
manages that for you and never logs anyone in.

Verify: `own-chrome status` should print the browser version, pid, and open
tabs. If it errors, Chrome isn't up on 9222 yet, or the listener isn't the
real Google Chrome (automation-launched Chrome — flagged by
`--enable-automation`, Playwright, or "chrome for testing" — is deliberately
rejected).

## own-chrome commands (from `own-chrome --help`)

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

## li commands (from `li --help`)

```
li query {threads,unread,read,title,url} [--filter F] [--limit N] [--json]
li threads | unread | read | status               # shorthand for query
li inbox [--no-navigate]                           # navigates to /messaging/ first
li queries
li popups [--apply]                                # inspect/dismiss a LinkedIn modal
li workflow run <spec.json> [--text TEXT] [--dry-run]
```

```bash
li query threads --filter acme --limit 5 --json
li query unread --json
li popups --json                # --apply clicks the configured button; omit to just report it
li workflow run examples/job-reply.json --text "coffee tomorrow?"
```

`li workflow run` always returns `sent: false` — it classifies and drafts,
it never sends. A regex miss skips the model entirely; a hit calls an intent
model (default `gpt-5-nano`) for go/no-go, then a write model (default
`gpt-5-mini`) only if intent says go. Override models in the spec file or
`~/.config/li/config.json`. The OpenAI key comes from `OPENAI_API_KEY` or
Keychain (service `openai`, account `li`) — never written by this tool.

**Bug fixed in this repo:** `li` used to pick a tab by `"linkedin.com" in url`,
so a Google search results page for "linkedin.com ..." could be chosen over
the real LinkedIn tab. It now matches the URL's actual hostname
(`urllib.parse` + `hostname == "linkedin.com"` or `.endswith(".linkedin.com")`),
so lookalike URLs (search results, `notlinkedin.com`, etc.) are never picked.

## MCP

There is no MCP server in this repo — `own-chrome` and `li` are CLI-only.
Call them via Bash/subprocess from an agent, not `claude mcp add`.

## macOS permissions

None. This tool never uses AppleScript/Apple Events — it talks to Chrome
purely over `127.0.0.1:9222` (CDP HTTP + a hand-rolled WebSocket client) and
shells out to `ps`/`lsof` to verify the listening process is the real Google
Chrome. No Automation, Full Disk Access, Contacts, or Calendar prompt is
triggered. The only requirement is Chrome itself running with the launch
flags above.

## Safety rules

- Read-only by default: `status`, `tabs`, `query`, `threads`, `unread`,
  `read`, `queries`, `popups` (without `--apply`) never modify the page.
- `li workflow run` never sends a LinkedIn message — `sent` is always `false`.
- `li popups --apply` and `own-chrome goto`/`eval` can act on or navigate the
  real, already-open tab. Only use `--apply` or `eval` with side effects when
  the user explicitly asked for that action — never send, delete, post, or
  submit anything on their behalf without being asked.
