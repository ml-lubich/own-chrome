---
name: own-chrome
description: Drive the Google Chrome the user already has open (own-chrome) and LinkedIn in that same window (li), via Chrome's DevTools Protocol on 127.0.0.1:9222 — no second browser, no Playwright. Use when the user wants their real signed-in Chrome tabs read or navigated, or LinkedIn messaging listed, a thread selected, or a reply typed ("check my tabs", "open LinkedIn messaging", "select that thread", "tell them"). Do not launch a fresh browser. `li tell` types only; add `--send` only when the user named the recipient and the text.
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

## li commands (from `li -h` / `li --help`)

`li` is Typer. `-h` and `--help` work on the root and on every command. The help
opens with an `LI` wordmark and the agent commands. `--json` does not print
the wordmark. Do not drive LinkedIn with `python -c` or raw CDP.

```
li commands [--json]                                 # catalog, no browser
li open [--json]                                     # messaging tab in the attached Chrome
li threads | unread | inbox [--no-navigate] [--json] # open messaging, then list
li select NAME [--json]                              # one thread; exit 3 if several match
li read [--limit N] [--json]
li tell NAME --text TEXT [--send] [--json]           # types; Send only with --send
li send [--json]                                     # click Send on the open composer
li query {threads,unread,read,title,url} [--filter F] [--limit N] [--json]
li popups [--apply]
li workflow run <spec.json> [--text TEXT] [--dry-run]
```

```bash
li commands --json
li open --json
li threads --filter acme --limit 5 --json
li select "Ada Lovelace" --json
li tell "Ada Lovelace" --text "Thanks, I'll look." --json
li popups --json
li workflow run examples/job-reply.json --text "coffee tomorrow?"
```

`threads` and `unread` open messaging when the LinkedIn tab is somewhere else (the feed, for example). `--no-navigate` keeps the old read-the-open-tab behavior. `li` does not launch a second browser.

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

- Read-only by default: `status`, `tabs`, `query` of `title`/`url`/`read`,
  `queries`, `commands`, and `popups` (without `--apply`) never modify the page.
- `threads`, `unread`, `inbox`, and `open` may navigate the LinkedIn tab to
  messaging. `select` clicks one thread. `tell` types. None of those send.
- `li tell` sends only with `--send`. `li send` clicks Send on the open composer.
  Use either only when this turn names the recipient and the text.
- `li workflow run` never sends a LinkedIn message — `sent` is always `false`.
- `li popups --apply` and `own-chrome goto`/`eval` can act on or navigate the
  real, already-open tab. Only use `--apply` or `eval` with side effects when
  the user explicitly asked for that action.
