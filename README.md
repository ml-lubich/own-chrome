# own-chrome

Two commands for the Google Chrome window that is already open. Neither one starts a browser.

`own-chrome` talks to Chrome's debugging port. `li` drives LinkedIn in that same window: it opens messaging, lists threads, selects one thread, and types a reply. Sending is a separate flag. A classify-then-draft workflow can draft a reply and does not send it.

`li` is a Typer command. `own-chrome` stays stdlib. No Playwright, no Chrome for Testing.

```bash
uv tool install git+https://github.com/ml-lubich/own-chrome
```

Chrome must already be listening on `127.0.0.1:9222`. Start it yourself with a non-default user-data directory:

```bash
google-chrome --remote-debugging-port=9222 --user-data-dir="$HOME/chrome-debug"
```

On Chrome 136 and newer, the debugging port is ignored if you point it at the default profile directory.

## Agents

Agents start with `li -h` or `li --help`. Every command has the same flags. Do not drop into `python -c` or raw CDP. `--json` is one object and does not print the wordmark. `--filter` is a case-insensitive substring. `--limit` caps rows. A filter that matches nothing exits 2.

```bash
own-chrome status --json --filter linkedin --limit 5
own-chrome tabs --json --filter linkedin
li commands --json
li open --json
li threads --limit 5 --json
li select "Ada Lovelace" --json
li read --limit 8 --json
li tell "Ada Lovelace" --text "Thanks, I'll look." --json
li tell "Ada Lovelace" --text "Thanks, I'll look." --send --json
li send --json
li popups --json
li workflow run examples/job-reply.json --text "coffee tomorrow?"
```

`li open` opens `https://www.linkedin.com/messaging/` in the attached Chrome. If a messaging tab is already open, `li` uses that tab and leaves a feed tab alone. The feed tab is navigated only when it is the only LinkedIn tab. `--no-navigate` reads the open tab as it is. If no LinkedIn tab exists, `open` creates one. Exit codes: `0` ok, `1` Chrome or page error, `2` no match, `3` several threads match (nothing is clicked).

`li tell` types into the composer and leaves `sent: false` unless `--send` is present. `li send` clicks Send on text already in the composer. `li select` and `li tell` refuse when more than one name matches.

`li commands --json` is the catalog agents should read. One JSON object, no browser required.

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
