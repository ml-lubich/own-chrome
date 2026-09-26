from own_chrome.popups import choose_popup_action


def test_share_contact_declines_by_default():
    action = choose_popup_action(
        "Share your contact info?",
        ["No, don't share", "Yes, please share"],
        {"share_contact": "decline"},
    )
    assert action == "No, don't share"


def test_share_contact_can_be_set_to_share():
    action = choose_popup_action(
        "Share your contact info?",
        ["No, don't share", "Yes, please share"],
        {"share_contact": "share"},
    )
    assert action == "Yes, please share"


def test_unknown_dialog_is_left_alone():
    assert choose_popup_action("Messaging settings", ["Save"], {"share_contact": "decline"}) is None


def test_share_contact_dialog_with_no_matching_button_returns_none():
    action = choose_popup_action(
        "Share your contact info?",
        ["Maybe later"],
        {"share_contact": "decline"},
    )
    assert action is None
