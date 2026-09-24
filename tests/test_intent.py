import json

from own_chrome.intent import route


def test_regex_miss_does_not_call_models():
    calls = []

    def complete(model, messages):
        calls.append(model)
        return "{}"

    decision = route(
        "want to grab coffee tomorrow",
        pattern=r"\b(role|hiring|engineer)\b",
        intent_model="gpt-5-nano",
        write_model="gpt-5-mini",
        intent_prompt="job only",
        write_prompt="draft",
        complete=complete,
    )
    assert decision["go"] is False
    assert decision["reason"] == "regex miss"
    assert calls == []


def test_nano_no_go_does_not_call_mini():
    calls = []

    def complete(model, messages):
        calls.append(model)
        return json.dumps({"go": False, "reason": "sales pitch, not a job"})

    decision = route(
        "InMail about a role",
        pattern=r"role",
        intent_model="gpt-5-nano",
        write_model="gpt-5-mini",
        intent_prompt="job only",
        write_prompt="draft",
        complete=complete,
    )
    assert decision["go"] is False
    assert calls == ["gpt-5-nano"]
    assert "draft" not in decision


def test_nano_go_calls_mini_once():
    calls = []

    def complete(model, messages):
        calls.append(model)
        if model.endswith("nano"):
            return json.dumps({"go": True, "reason": "recruiter asked about a role"})
        return "thanks, I am not looking."

    decision = route(
        "Software engineer role",
        pattern=r"role",
        intent_model="gpt-5-nano",
        write_model="gpt-5-mini",
        intent_prompt="job only",
        write_prompt="draft",
        complete=complete,
    )
    assert decision["draft"] == "thanks, I am not looking."
    assert calls == ["gpt-5-nano", "gpt-5-mini"]


def test_bad_nano_json_is_a_no_go():
    decision = route(
        "a role",
        pattern=r"role",
        intent_model="gpt-5-nano",
        write_model="gpt-5-mini",
        intent_prompt="job only",
        write_prompt="draft",
        complete=lambda model, messages: "sure thing",
    )
    assert decision["go"] is False
    assert "json" in decision["reason"]
