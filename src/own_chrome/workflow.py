from __future__ import annotations

from own_chrome.intent import route


def run_workflow(spec: dict, thread_text: str, complete, dry_run: bool = True) -> dict:
    decision = route(
        thread_text,
        pattern=spec.get("match") or "",
        intent_model=spec.get("intent_model") or "gpt-5-nano",
        write_model=spec.get("write_model") or "gpt-5-mini",
        intent_prompt=spec.get("intent") or "",
        write_prompt=spec.get("write") or "",
        complete=complete,
    )
    decision["name"] = spec.get("name") or ""
    decision["sent"] = False
    if not dry_run:
        decision["sent"] = False
    return decision
