"""Deterministic LinkedIn page actions.

Pure functions: they build the JavaScript the CLI runs in the attached
Chrome tab. They do not open a socket, launch a browser, or send mail.
"""

from __future__ import annotations

import json
import urllib.parse

COMMANDS: tuple[dict[str, object], ...] = (
    {
        "name": "open",
        "sends": False,
        "summary": "Open LinkedIn messaging in the attached Chrome.",
    },
    {
        "name": "threads",
        "sends": False,
        "summary": "Open messaging if the tab is elsewhere, then list threads.",
    },
    {
        "name": "unread",
        "sends": False,
        "summary": "Open messaging if needed, then list unread threads.",
    },
    {
        "name": "select",
        "sends": False,
        "summary": "Open the one thread whose name contains the argument. Refuses if several match.",
    },
    {
        "name": "read",
        "sends": False,
        "summary": "Print the last lines of the open thread.",
    },
    {
        "name": "tell",
        "sends": False,
        "summary": "Select a thread and type --text. Clicks Send only with --send.",
    },
    {
        "name": "send",
        "sends": True,
        "summary": "Click Send on the text already in the open composer.",
    },
    {
        "name": "inbox",
        "sends": False,
        "summary": "Open messaging if needed, then list threads.",
    },
    {
        "name": "popups",
        "sends": False,
        "summary": "Report the open dialog. --apply clicks the configured button.",
    },
    {
        "name": "workflow",
        "sends": False,
        "summary": "Classify the open thread and draft. Never sends.",
    },
    {
        "name": "commands",
        "sends": False,
        "summary": "List these commands.",
    },
)

READY_JS = r"""async () => {
  const deadline = Date.now() + 1000;
  while (Date.now() < deadline) {
    const onMsg = location.pathname.indexOf("/messaging") === 0;
    const list = document.querySelector(
      ".msg-conversation-listitem, .msg-conversation-card, .msg-conversations-container"
    );
    if (onMsg && list) return {ready: true, url: location.href, title: document.title};
    await new Promise((r) => setTimeout(r, 100));
  }
  return {ready: false, url: location.href, title: document.title};
}"""

# Click happens only after the single-match check. Several matches return first.
ACT_JS = r"""async (opts) => {
  const op = opts.op;
  const q = String(opts.name || "").trim().toLowerCase();
  const text = String(opts.text || "");
  const nameOf = (el) => {
    const node = el.querySelector(
      ".msg-conversation-listitem__participant-names, .msg-conversation-card__participant-names"
    );
    return ((node && node.innerText) || "").trim();
  };
  const clickSend = () => {
    const btn = document.querySelector("button.msg-form__send-button");
    if (!btn || btn.disabled || btn.getAttribute("aria-disabled") === "true") return false;
    btn.click();
    return true;
  };
  if (op === "send") {
    const sent = clickSend();
    return {action: "send", ok: sent, sent: sent, matched: "", chars: 0, ambiguous: false, matches: []};
  }
  const seen = new Set();
  const matches = [];
  for (const el of document.querySelectorAll(".msg-conversation-listitem, .msg-conversation-card")) {
    const n = nameOf(el);
    if (!n || seen.has(n)) continue;
    if (!q || !n.toLowerCase().includes(q)) continue;
    seen.add(n);
    matches.push({name: n, el: el});
  }
  if (matches.length === 0) {
    return {action: op, ok: false, sent: false, matched: "", chars: 0, ambiguous: false, matches: []};
  }
  if (matches.length > 1) {
    return {
      action: op,
      ok: false,
      sent: false,
      matched: "",
      chars: 0,
      ambiguous: true,
      matches: matches.map((m) => m.name)
    };
  }
  const card = matches[0].el;
  const link = card.querySelector("a");
  (link || card).click();
  const deadline = Date.now() + 8000;
  let box = null;
  while (Date.now() < deadline) {
    box = document.querySelector(".msg-form__contenteditable");
    if (box) break;
    await new Promise((r) => setTimeout(r, 200));
  }
  if (op === "select") {
    return {
      action: "select",
      ok: !!box,
      sent: false,
      matched: matches[0].name,
      chars: 0,
      ambiguous: false,
      matches: [matches[0].name]
    };
  }
  if (!box) {
    return {
      action: "tell",
      ok: false,
      sent: false,
      matched: matches[0].name,
      chars: 0,
      ambiguous: false,
      matches: [matches[0].name],
      reason: "composer not ready"
    };
  }
  box.focus();
  document.execCommand("insertText", false, text);
  if (!opts.send) {
    return {
      action: "tell",
      ok: true,
      sent: false,
      matched: matches[0].name,
      chars: text.length,
      ambiguous: false,
      matches: [matches[0].name]
    };
  }
  const sent = clickSend();
  return {
    action: "tell",
    ok: sent,
    sent: sent,
    matched: matches[0].name,
    chars: text.length,
    ambiguous: false,
    matches: [matches[0].name],
    reason: sent ? "" : "send button unavailable"
  };
}"""


def _linkedin_host(url: str) -> bool:
    try:
        host = (urllib.parse.urlparse(url).hostname or "").lower()
    except ValueError:
        return False
    return host == "linkedin.com" or host.endswith(".linkedin.com")


def choose_linkedin_tab(tabs: list[dict]) -> dict | None:
    """Prefer an open messaging tab. A feed tab listed first must not win."""
    linkedin = [tab for tab in tabs if _linkedin_host(str(tab.get("url") or ""))]
    messaging = [tab for tab in linkedin if on_messaging(str(tab.get("url") or ""))]
    if messaging:
        return messaging[0]
    if linkedin:
        return linkedin[0]
    return None


def on_messaging(url: str) -> bool:
    try:
        parsed = urllib.parse.urlparse(url)
    except ValueError:
        return False
    host = (parsed.hostname or "").lower()
    if host != "linkedin.com" and not host.endswith(".linkedin.com"):
        return False
    return parsed.path.startswith("/messaging")


def ready_expression() -> str:
    return f"({READY_JS})()"


def act_expression(op: str, name: str, text: str, send: bool) -> str:
    opts = json.dumps({"op": op, "name": name, "text": text, "send": send}, ensure_ascii=False)
    return f"({ACT_JS})({opts})"
