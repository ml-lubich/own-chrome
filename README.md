# own-chrome

`own-chrome` is a small local CLI for finding and checking a running Google
Chrome debugging endpoint. It does not launch a browser or copy profile data.
For agent-driven browsing, use Browser Use's local `browser-harness` CLI as the
single interaction layer; its skill gives coding agents semantic page snapshots
and browser actions over Chrome DevTools Protocol (CDP).

## Use your signed-in Chrome

Install `own-chrome` and Browser Harness separately. Browser Harness setup and
its agent skill are documented in the
[Browser Harness install guide](https://github.com/browser-use/browser-harness/blob/main/install.md).
Use `own-chrome agent` as the guarded front door to the harness. It checks
that the selected local Chrome endpoint is real, then pins Browser Harness to
that exact CDP WebSocket. `own-chrome agent --check` verifies readiness without
starting the harness.

Each selected Chrome data directory gets an isolated Browser Harness daemon
runtime, so an existing harness daemon cannot silently keep controlling another
profile. An explicitly set `BH_RUNTIME_DIR` is preserved.

```bash
own-chrome agent --check
own-chrome agent <<'PY'
print(page_info())
PY
```

Browser Harness reads its agent instructions from the installed `browser-harness`
skill. The handoff does not start Chrome or pass cloud/browser-launch options.
Use `own-chrome status --port PORT` to inspect an explicitly exposed fixed-port
Chrome; the agent handoff discovers Chrome's dynamic endpoint from
`DevToolsActivePort`.

On Chrome 136 and newer, Chrome ignores remote-debugging command-line flags
when they target Chrome's default data directory. On supported Chrome versions,
enable the browser's explicit remote debugging setting once at
`chrome://inspect/#remote-debugging` (“Allow remote debugging for this browser
instance”). Chrome may also show an Allow prompt when a local tool first
connects. The harness does not bypass those Chrome controls.

CDP attaches to a Chrome process. One endpoint may expose tabs and windows
from multiple profiles opened in that process; each profile's login state stays
separate, but the agent may be able to reach all exposed tabs. Close unrelated
windows before attaching, or use a dedicated Chrome data directory signed into
only the accounts needed for agent work. Never copy Chrome's live profile data.

If no eligible local endpoint is exposed, `own-chrome agent` should stop and
explain the Chrome setup needed. It must not silently start Chrome for Testing,
another profile, or a cloud browser. When connected, the harness detaches at
the end of a run; it does not close or terminate the user's Chrome.

## Browser UI fallback

CDP operates web pages. For browser chrome or native UI that CDP cannot reach,
AppleScript/JXA may be used as a narrow macOS fallback. That path may require
macOS Automation permission for the calling app. It is not needed for normal
page automation over CDP, and permission must never be granted or changed by the
CLI. Never use the fallback to switch to another Chrome profile or bypass a
blocked CDP connection.

## own-chrome commands

```
own-chrome status [--port PORT] [--json] [--filter F] [--limit N]
own-chrome tabs   [--port PORT] [--json] [--filter F] [--limit N]
own-chrome agent  [--check] [--json]
```

For page interaction, follow the installed Browser Harness skill and pipe its
Python instructions to `own-chrome agent`. `own-chrome` remains the endpoint
discovery and health-check tool; it is not a second page-action framework.

## Develop

```bash
uv run --with pytest --python 3.12 pytest -q
```

Tests mock only the browser and process-inspection boundaries; CLI parsing,
endpoint validation, and tab filtering run for real.
