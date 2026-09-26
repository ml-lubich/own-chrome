import json

from own_chrome.workflow import run_workflow


def test_regex_miss_skips_models_and_does_not_send():
    calls = []

    result = run_workflow(
        {"name": "job-reply", "match": r"\b(role|hiring|engineer)\b", "intent": "job only", "write": "short"},
        thread_text="Hey, want to grab coffee?",
        complete=lambda model, messages: calls.append(model) or "{}",
        dry_run=True,
    )
    assert result["go"] is False
    assert result["sent"] is False
    assert calls == []


def test_dry_run_drafts_when_intent_says_go():
    def complete(model, messages):
        if model.endswith("nano"):
            return json.dumps({"go": True, "reason": "asked about a role"})
        return "hi, not looking right now."

    result = run_workflow(
        {
            "name": "job-reply",
            "match": r"role",
            "intent": "only real job outreach",
            "write": "short reply",
        },
        thread_text="Open role on the platform team",
        complete=complete,
        dry_run=True,
    )
    assert result["sent"] is False
    assert result["draft"] == "hi, not looking right now."


def test_sent_is_always_false_even_with_dry_run_disabled():
    result = run_workflow(
        {"name": "job-reply", "match": r"\b(role|hiring|engineer)\b", "intent": "job only", "write": "short"},
        thread_text="Hey, want to grab coffee?",
        complete=lambda model, messages: "{}",
        dry_run=False,
    )
    assert result["go"] is False
    assert result["sent"] is False
