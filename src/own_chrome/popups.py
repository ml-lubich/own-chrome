from __future__ import annotations

SHARE_CONTACT = "share your contact info"
DECLINE = "No, don't share"
SHARE = "Yes, please share"


def choose_popup_action(title: str, buttons: list[str], policy: dict) -> str | None:
    if SHARE_CONTACT not in title.lower():
        return None
    wanted = SHARE if policy.get("share_contact") == "share" else DECLINE
    for button in buttons:
        if button.strip().lower() == wanted.lower():
            return button
    return None
