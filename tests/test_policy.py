from fraud_app.policy import Assessment, recommend, route, sar_required


def test_block_card_route_threshold():
    assert route("BLOCK_CARD", 2500) == "L1"
    assert route("BLOCK_CARD", 2500.01) == "L2"


def test_r1_weak_signal_verifies_before_case():
    actions = recommend(Assessment("uncertain", 0.45, 77, "card_not_present_fraud", weak_signal_only=True))
    assert actions[0]["action"] == "VERIFY_WITH_CUSTOMER"
    assert actions[0]["route"] == "auto"


def test_r2_denial_creates_case_and_reports_when_shared():
    actions = recommend(Assessment("fraud", 0.90, 200, "card_not_present_fraud", customer_response="denied", shared_origin=True))
    names = [item["action"] for item in actions]
    assert names[:2] == ["BLOCK_CARD", "CREATE_CASE"]
    assert "FILE_REPORT" in names
    assert sar_required(actions)


def test_r5_card_testing_requires_step_up():
    actions = recommend(Assessment("fraud", 0.80, 80, "card_testing", cleared_purchase_over_100=False))
    assert [item["action"] for item in actions[:2]] == ["DECLINE_TRANSACTION", "STEP_UP_AUTH"]


def test_r7_recurring_dispute_does_not_block():
    actions = recommend(Assessment("legitimate", 0.10, 49, "none", disputed_recurring=True))
    names = [item["action"] for item in actions]
    assert "BLOCK_CARD" not in names
    assert names == ["CREATE_CASE", "VERIFY_WITH_CUSTOMER", "WARN_CUSTOMER"]


def test_r10_blocks_all_only_after_two_cards():
    without = [x["action"] for x in recommend(Assessment("fraud", 0.9, 100, "card_not_present_fraud", customer_response="denied"))]
    with_two = [x["action"] for x in recommend(Assessment("fraud", 0.9, 100, "card_not_present_fraud", customer_response="denied", confirmed_two_cards=True))]
    assert "BLOCK_ALL_CARDS" not in without
    assert "BLOCK_ALL_CARDS" in with_two
