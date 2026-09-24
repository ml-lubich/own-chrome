from __future__ import annotations

import json
import re
from typing import Callable

Complete = Callable[[str, list[dict]], str]


def route(
    text: str,
    pattern: str,
    intent_model: str,
    write_model: str,
    intent_prompt: str,
    write_prompt: str,
    complete: Complete,
) -> dict:
    if pattern and not re.search(pattern, text, re.IGNORECASE):
        return {"go": False, "route": "skip", "reason": "regex miss"}
    raw = complete(
        intent_model,
        [
            {
                "role": "system",
                "content": intent_prompt + ' Reply with JSON {"go": bool, "reason": string} and nothing else.',
            },
            {"role": "user", "content": text},
        ],
    )
    try:
        parsed = json.loads(raw)
        go = bool(parsed["go"])
        reason = str(parsed.get("reason") or "")
    except (json.JSONDecodeError, KeyError, TypeError):
        return {"go": False, "route": "skip", "reason": "intent model did not return json"}
    if not go:
        return {"go": False, "route": "skip", "reason": reason}
    draft = complete(
        write_model,
        [
            {"role": "system", "content": write_prompt},
            {"role": "user", "content": text},
        ],
    ).strip()
    return {"go": True, "route": "write", "reason": reason, "draft": draft}
