"""LinkedIn commands against the Chrome tab that is already open."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

from own_chrome.actions import COMMANDS, act_expression, choose_linkedin_tab, on_messaging, ready_expression
from own_chrome.cdp import DEFAULT_PORT, ChromeError, evaluate, navigate, open_tab, pages
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
    raw = _eval(
        args.port,
        """(() => {
          const dialog = document.querySelector('[role="dialog"]');
          if (!dialog) return JSON.stringify({title:'', buttons:[]});
          const title = ((dialog.querySelector('h1, h2') || dialog).innerText || '').split('\\n')[0];
          const buttons = [...dialog.querySelectorAll('button')].map((b) => b.innerText.trim()).filter(Boolean);
          return JSON.stringify({title, buttons});
        })()""",
    )
    dialog = json.loads(raw) if isinstance(raw, str) else raw
    policy = load_config().get("popups") or {"share_contact": "decline"}
    action = choose_popup_action(dialog.get("title") or "", dialog.get("buttons") or [], policy)
    dialog["action"] = action
    dialog["applied"] = False
    if args.apply and action:
        clicked = _eval(
            args.port,
            "((label) => { const dialog = document.querySelector('[role=\"dialog\"]');"
            " if (!dialog) return false;"
            " const btn = [...dialog.querySelectorAll('button')].find((b) => b.innerText.trim() === label);"
            " if (!btn) return false; btn.click(); return true; })(" + json.dumps(action) + ")",
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
        raw = _eval(
            args.port,
            "JSON.stringify([...document.querySelectorAll('.msg-s-event-listitem')].slice(-4).map((n) => n.innerText.trim()).join('\\n\\n'))",
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
    if payload.get("action"):
        bits = [str(payload["action"])]
        if payload.get("matched"):
            bits.append(str(payload["matched"]))
        elif payload.get("opened"):
            bits.append(str(payload["opened"]))
        if payload.get("action") == "tell":
            bits.append(f"{payload.get('chars', 0)} chars")
        if "sent" in payload and payload.get("action") in ("tell", "send"):
            bits.append("sent" if payload.get("sent") else "not sent")
        print(" ".join(bits))
        if payload.get("ambiguous"):
            for name in payload.get("matches") or []:
                print(f"- {name}")
        return
    print(payload.get("title", ""))
    print(payload.get("url", ""))
    for thread in payload.get("threads") or []:
        mark = " *" if thread.get("unread") else ""
        preview = thread.get("preview") or ""
        print(f"- {thread.get('name', '')}{mark}  {preview[:80]}")
    for line in payload.get("lines") or []:
        print(line.replace("\n", " | ")[:240])


def _as_dict(raw: object) -> dict:
    if isinstance(raw, dict):
        return raw
    if not isinstance(raw, str):
        raise ChromeError("page did not return JSON")
    return json.loads(raw)


def linkedin_tab(port: int) -> dict:
    chosen = choose_linkedin_tab(pages(port))
    if chosen is None:
        raise ChromeError(f"No open tab with hostname {TAB!r} (or a subdomain of it)")
    return chosen


def _eval(port: int, expression: str) -> object:
    return evaluate(port, expression, page=linkedin_tab(port))


def ensure_messaging(port: int) -> dict:
    """Open messaging in the attached Chrome. Does not start a browser.

    An existing messaging tab wins over a feed tab. The feed tab is only
    navigated when it is the only LinkedIn tab.
    """
    try:
        page = linkedin_tab(port)
    except ChromeError:
        tab = open_tab(port, MESSAGING)
        return {
            "action": "open",
            "opened": "tab",
            "ok": True,
            "url": tab.get("url") or MESSAGING,
            "title": tab.get("title") or "",
        }
    url = page.get("url") or ""
    if on_messaging(url):
        return {
            "action": "open",
            "opened": "already",
            "ok": True,
            "url": url,
            "title": page.get("title") or "",
        }
    navigate(port, MESSAGING, host=TAB)
    return {"action": "open", "opened": "navigated", "ok": True, "url": MESSAGING, "title": ""}


def _wait_ready(port: int) -> dict:
    # ponytail: 1s in-page poll plus a short retry. The feed document can still
    # be the execution context for the first call after Page.navigate.
    last = "messaging list did not load"
    for _attempt in range(12):
        try:
            payload = _as_dict(_eval(port, ready_expression()))
        except (ChromeError, json.JSONDecodeError) as exc:
            last = str(exc)
            time.sleep(0.25)
            continue
        if payload.get("ready"):
            return payload
        last = str(payload.get("url") or last)
        time.sleep(0.25)
    raise ChromeError(f"messaging list did not load ({last})")


def _prepare(port: int) -> dict:
    info = ensure_messaging(port)
    if info["opened"] == "already":
        return info
    ready = _wait_ready(port)
    info["url"] = ready.get("url") or info["url"]
    info["title"] = ready.get("title") or info.get("title") or ""
    info["ready"] = True
    return info


def _wants_messaging(args: argparse.Namespace, kind: str) -> bool:
    if getattr(args, "no_navigate", False):
        return False
    return kind in ("threads", "unread")


def _act(args: argparse.Namespace, op: str) -> int:
    name = (getattr(args, "name", "") or "").strip()
    text = getattr(args, "text", "") or ""
    send = bool(getattr(args, "send", False))
    if op != "send" and not name:
        print("li: name is required", file=sys.stderr)
        return 2
    if op != "send":
        _prepare(args.port)
    payload = _as_dict(_eval(args.port, act_expression(op, name, text, send)))
    emit(payload, args.json)
    if payload.get("ambiguous"):
        return 3
    if not payload.get("ok"):
        return 2
    return 0


def _commands(as_json: bool) -> int:
    payload = {"commands": [dict(row) for row in COMMANDS]}
    if as_json:
        emit(payload, True)
        return 0
    for row in COMMANDS:
        print(f"{row['name']}\t{row['summary']}")
    return 0


def run_open(args: argparse.Namespace) -> int:
    info = _prepare(args.port)
    info["action"] = "open"
    info["ok"] = True
    emit(info, args.json)
    return 0


def run_queries(as_json: bool) -> int:
    if as_json:
        emit({"query": "queries", "url": "", "title": "", "threads": [], "lines": [], "queries": list(QUERIES)}, True)
    else:
        for name in QUERIES:
            print(name)
    return 0


def run_query(args: argparse.Namespace) -> int:
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
        if _wants_messaging(args, kind):
            _prepare(args.port)
        if kind in ("title", "url"):
            raw = _eval(args.port, "JSON.stringify({title: document.title, url: location.href})")
            payload = json.loads(raw)
            payload["query"] = kind
            payload["threads"] = []
            payload["lines"] = []
        else:
            raw = _eval(args.port, _expression(kind, args.filter, args.limit))
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


def main(argv: list[str] | None = None) -> int:
    from own_chrome.li_app import main as app_main

    return app_main(argv)


if __name__ == "__main__":
    raise SystemExit(main())
