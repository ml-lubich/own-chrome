"""LinkedIn queries against the Chrome tab that is already open."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

from own_chrome.cdp import DEFAULT_PORT, ChromeError, evaluate, navigate
from own_chrome.popups import choose_popup_action
from own_chrome.workflow import run_workflow

CONFIG_PATH = Path.home() / ".config" / "li" / "config.json"

MESSAGING = "https://www.linkedin.com/messaging/"
TAB = "linkedin.com"

QUERIES = ("threads", "unread", "read", "title", "url")

_PAGE_JS = r"""
(opts) => {
  const q = (opts.filter || "").toLowerCase();
  const limit = opts.limit || 20;
  const nameOf = (el) => {
    const node = el.querySelector(
      ".msg-conversation-listitem__participant-names, .msg-conversation-card__participant-names"
    );
    return (node && node.innerText || "").trim();
  };
  const seen = new Set();
  const threads = [];
  for (const el of document.querySelectorAll(".msg-conversation-listitem, .msg-conversation-card")) {
    const name = nameOf(el);
    if (!name || seen.has(name)) continue;
    seen.add(name);
    const previewNode = el.querySelector(".msg-conversation-card__message-snippet, .msg-conversation-listitem__message-snippet");
    const unread = /unread/i.test(el.className) || !!el.querySelector(".notification-badge, .msg-conversation-card__unread-count");
    if (q && !name.toLowerCase().includes(q) && !(previewNode && previewNode.innerText.toLowerCase().includes(q))) continue;
    threads.push({
      name,
      preview: previewNode ? previewNode.innerText.trim() : "",
      unread
    });
    if (threads.length >= limit) break;
  }
  const lines = [...document.querySelectorAll(".msg-s-event-listitem")]
    .map((n) => n.innerText.trim())
    .filter(Boolean)
    .slice(-limit);
  return {
    query: opts.query,
    url: location.href,
    title: document.title,
    threads: opts.query === "unread" ? threads.filter((t) => t.unread) : threads,
    lines: opts.query === "read" ? lines : []
  };
}
"""


def _expression(query: str, needle: str, limit: int) -> str:
    opts = json.dumps({"query": query, "filter": needle, "limit": limit})
    return f"({_PAGE_JS})({opts})"


def load_config() -> dict:
    if not CONFIG_PATH.exists():
        return {"popups": {"share_contact": "decline"}, "intent_model": "gpt-5-nano", "write_model": "gpt-5-mini"}
    return json.loads(CONFIG_PATH.read_text())


def api_key() -> str:
    env = os.environ.get("OPENAI_API_KEY", "").strip()
    if env:
        return env
    try:
        out = subprocess.check_output(
            ["security", "find-generic-password", "-s", "openai", "-a", "li", "-w"],
            text=True,
            stderr=subprocess.DEVNULL,
        )
    except (subprocess.CalledProcessError, FileNotFoundError) as exc:
        raise ChromeError("OpenAI key is not in the environment or keychain (service openai, account li)") from exc
    return out.strip()


def complete(model: str, messages: list[dict]) -> str:
    body = json.dumps({"model": model, "messages": messages}).encode()
    request = urllib.request.Request(
        "https://api.openai.com/v1/chat/completions",
        data=body,
        headers={"Authorization": f"Bearer {api_key()}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            payload = json.loads(response.read().decode())
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode(errors="replace")[:300]
        raise ChromeError(f"OpenAI {exc.code}: {detail}") from exc
    return payload["choices"][0]["message"]["content"]


def _popups(args: argparse.Namespace) -> int:
    raw = evaluate(
        args.port,
        """(() => {
          const dialog = document.querySelector('[role="dialog"]');
          if (!dialog) return JSON.stringify({title:'', buttons:[]});
          const title = ((dialog.querySelector('h1, h2') || dialog).innerText || '').split('\\n')[0];
          const buttons = [...dialog.querySelectorAll('button')].map((b) => b.innerText.trim()).filter(Boolean);
          return JSON.stringify({title, buttons});
        })()""",
        TAB,
    )
    dialog = json.loads(raw) if isinstance(raw, str) else raw
    policy = load_config().get("popups") or {"share_contact": "decline"}
    action = choose_popup_action(dialog.get("title") or "", dialog.get("buttons") or [], policy)
    dialog["action"] = action
    dialog["applied"] = False
    if args.apply and action:
        clicked = evaluate(
            args.port,
            "((label) => { const dialog = document.querySelector('[role=\"dialog\"]');"
            " if (!dialog) return false;"
            " const btn = [...dialog.querySelectorAll('button')].find((b) => b.innerText.trim() === label);"
            " if (!btn) return false; btn.click(); return true; })(" + json.dumps(action) + ")",
            TAB,
        )
        dialog["applied"] = bool(clicked)
    emit(dialog, args.json)
    return 0


def _workflow(args: argparse.Namespace) -> int:
    spec = json.loads(Path(args.spec).read_text())
    config = load_config()
    spec.setdefault("intent_model", config.get("intent_model") or "gpt-5-nano")
    spec.setdefault("write_model", config.get("write_model") or "gpt-5-mini")
    text = args.text
    if not text:
        raw = evaluate(
            args.port,
            "JSON.stringify([...document.querySelectorAll('.msg-s-event-listitem')].slice(-4).map((n) => n.innerText.trim()).join('\\n\\n'))",
            TAB,
        )
        text = json.loads(raw) if isinstance(raw, str) else raw
    result = run_workflow(spec, text, complete, dry_run=True)
    emit(result, True)
    return 0 if result.get("go") or result.get("reason") == "regex miss" else 2


def emit(payload: dict, as_json: bool) -> None:
    if as_json:
        json.dump(payload, sys.stdout, ensure_ascii=False)
        sys.stdout.write("\n")
        return
    print(payload.get("title", ""))
    print(payload.get("url", ""))
    for thread in payload.get("threads") or []:
        mark = " *" if thread.get("unread") else ""
        preview = thread.get("preview") or ""
        print(f"- {thread.get('name', '')}{mark}  {preview[:80]}")
    for line in payload.get("lines") or []:
        print(line.replace("\n", " | ")[:240])


def main(argv: list[str] | None = None) -> int:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--port", type=int, default=DEFAULT_PORT)
    common.add_argument("--json", action="store_true")
    common.add_argument("--filter", default="", help="Case-insensitive match on name or preview")
    common.add_argument("--limit", type=int, default=20)
    parser = argparse.ArgumentParser(prog="li", description="Query LinkedIn in the already-open Chrome.")
    sub = parser.add_subparsers(dest="cmd", required=True)
    query = sub.add_parser("query", parents=[common])
    query.add_argument("name", choices=QUERIES)
    for name in ("threads", "unread", "read", "status"):
        sub.add_parser(name, parents=[common])
    inbox = sub.add_parser("inbox", parents=[common])
    inbox.add_argument("--no-navigate", action="store_true")
    sub.add_parser("queries", parents=[common])
    pop = sub.add_parser("popups", parents=[common])
    pop.add_argument("--apply", action="store_true", help="Click the button from ~/.config/li/config.json")
    flow = sub.add_parser("workflow", parents=[common])
    flow.add_argument("action", choices=("run",))
    flow.add_argument("spec")
    flow.add_argument("--text", default="", help="Thread text. Default is the open thread.")
    flow.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    if args.cmd == "popups":
        return _popups(args)
    if args.cmd == "workflow":
        return _workflow(args)
    if args.cmd == "queries":
        if args.json:
            emit({"query": "queries", "url": "", "title": "", "threads": [], "lines": [], "queries": list(QUERIES)}, True)
        else:
            for name in QUERIES:
                print(name)
        return 0
    kind = {
        "status": "threads",
        "threads": "threads",
        "unread": "unread",
        "read": "read",
        "inbox": "threads",
        "query": args.name if args.cmd == "query" else "threads",
    }[args.cmd]
    if args.cmd == "query" and args.name in ("title", "url"):
        kind = args.name
    try:
        if args.cmd == "inbox" and not args.no_navigate:
            navigate(args.port, MESSAGING, TAB)
        if kind in ("title", "url"):
            raw = evaluate(args.port, "JSON.stringify({title: document.title, url: location.href})", TAB)
            payload = json.loads(raw)
            payload["query"] = kind
            payload["threads"] = []
            payload["lines"] = []
        else:
            raw = evaluate(args.port, _expression(kind, args.filter, args.limit), TAB)
            payload = json.loads(raw) if isinstance(raw, str) else raw
    except ChromeError as exc:
        print(f"li: {exc}", file=sys.stderr)
        return 1
    except json.JSONDecodeError as exc:
        print(f"li: page did not return JSON ({exc})", file=sys.stderr)
        return 1
    if kind == "title":
        payload["url"] = ""
    if kind == "url":
        payload["title"] = ""
    emit(payload, args.json)
    if args.filter and kind in ("threads", "unread") and not payload.get("threads"):
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
