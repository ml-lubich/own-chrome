# own-chrome

Two commands for the Google Chrome window that is already open. Neither one starts a browser.

`own-chrome` talks to Chrome's debugging port. `li` queries LinkedIn in that same window and can run a small classify-then-draft workflow. The workflow does not send messages.

Stdlib only. No Playwright, no Chrome for Testing.

```bash
uv tool install git+https://github.com/ml-lubich/own-chrome
```

Chrome must already be listening on `127.0.0.1:9222`. Start it yourself with a non-default user-data directory:

```bash
google-chrome --remote-debugging-port=9222 --user-data-dir="$HOME/chrome-debug"
```

On Chrome 136 and newer, the debugging port is ignored if you point it at the default profile directory.

## Agents

Pass `--json`. `--filter` is a case-insensitive substring. `--limit` caps rows. A filter that matches nothing exits 2.

```bash
own-chrome status --json --filter linkedin --limit 5
own-chrome tabs --json --filter linkedin
li query threads --filter acme --limit 5 --json
li query unread --json --limit 10
li query read --limit 8 --json
li popups --json
li workflow run examples/job-reply.json --text "coffee tomorrow?"
```

`li workflow run` always returns `sent: false`. A regex miss does not call a model. A hit calls the intent model for go or no-go plus a reason. The write model runs only when intent says go.

Default models are `gpt-5-nano` (intent) and `gpt-5-mini` (writing). Override them in the workflow file or in `~/.config/li/config.json`. The API key is `OPENAI_API_KEY` or a Keychain item: service `openai`, account `li`. The key is never written by this tool.

`li popups --apply` clicks the button named in config. The default for "Share your contact info?" is decline. Set `popups.share_contact` to `share` to change it.

```json
{
  "popups": { "share_contact": "decline" },
  "intent_model": "gpt-5-nano",
  "write_model": "gpt-5-mini"
}
```

## Develop

```bash
uv run --with pytest --python 3.12 pytest -q
```

### Coverage

```bash
uv run --with pytest --with pytest-cov --python 3.12 pytest -q --cov=own_chrome --cov-report=term-missing
```

Tests mock only at the boundary (Chrome's CDP websocket/HTTP, the OpenAI API, subprocess, and the macOS keychain) — argument parsing, LinkedIn query building, popup policy, and intent/workflow routing run for real.
