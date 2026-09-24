"""Pure Fraud Policy implementation enforcing R1-R10 and approval routing."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

AUTO_ACTIONS = {
    "ALLOW_TRANSACTION",
    "MONITOR_CARD",
    "MONITOR_CONNECTED_CARDS",
    "WARN_CUSTOMER",
    "VERIFY_WITH_CUSTOMER",
    "STEP_UP_AUTH",
    "GENERATE_REPORT",
    "CREATE_CASE",
    "ESCALATE_TO_ANALYST",
    "CLOSE_NO_FRAUD",
}

L1_ACTIONS = {"DECLINE_TRANSACTION"}
L2_ACTIONS = {"BLOCK_ALL_CARDS", "FILE_REPORT"}
ALL_ACTIONS = AUTO_ACTIONS | L1_ACTIONS | L2_ACTIONS | {"BLOCK_CARD"}

# Operational execution order: what happens first
ACTION_PRIORITY = {
    "DECLINE_TRANSACTION": 10,
    "BLOCK_CARD": 20,
    "BLOCK_ALL_CARDS": 25,
    "CREATE_CASE": 30,
    "FILE_REPORT": 40,
    "MONITOR_CONNECTED_CARDS": 50,
    "MONITOR_CARD": 60,
    "STEP_UP_AUTH": 70,
    "VERIFY_WITH_CUSTOMER": 80,
    "WARN_CUSTOMER": 90,
    "ALLOW_TRANSACTION": 100,
    "ESCALATE_TO_ANALYST": 110,
    "CLOSE_NO_FRAUD": 120,
    "GENERATE_REPORT": 130,
}


@dataclass(frozen=True)
class Assessment:
    verdict: str
    probability: float
    exposure_usd: float
    pattern: str
    weak_signal_only: bool = False
    evidence_conflict: bool = False
    customer_response: str | None = None
    shared_origin: bool = False
    connected_fraud: bool = False
    coordinated: bool = False
    disputed_recurring: bool = False
    pending_authorization: bool = False
    cleared_purchase_over_100: bool = False
    confirmed_credentials_compromised: bool = False
    confirmed_two_cards: bool = False


def route(action_name: str, exposure_usd: float) -> str:
    if action_name == "BLOCK_CARD":
        return "L1" if exposure_usd <= 2500.0 else "L2"
    if action_name in L2_ACTIONS:
        return "L2"
    if action_name in L1_ACTIONS:
        return "L1"
    if action_name in AUTO_ACTIONS:
        return "auto"
    raise ValueError(f"Unknown policy action: {action_name}")


def make_action(action_name: str, reason: str, exposure_usd: float) -> dict[str, Any]:
    if action_name not in ALL_ACTIONS:
        raise ValueError(f"Unknown policy action: {action_name}")
    return {
        "action": action_name,
        "route": route(action_name, exposure_usd),
        "reason": reason,
    }


def _dedupe_and_sort(actions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    deduped = []
    for item in actions:
        if item["action"] not in seen:
            seen.add(item["action"])
            deduped.append(item)
    # Order by execution priority (what happens first)
    return sorted(deduped, key=lambda x: ACTION_PRIORITY.get(x["action"], 999))


def recommend(assessment: Assessment) -> list[dict[str, Any]]:
    """Return policy-controlled actions in strict execution order."""
    actions: list[dict[str, Any]] = []
    denied = assessment.customer_response == "denied"
    confirmed = assessment.customer_response == "confirmed"

    # R3: Customer confirms transaction
    if confirmed:
        return [make_action("CLOSE_NO_FRAUD", "R3: customer confirmed the transaction as legitimate", assessment.exposure_usd)]

    # R7: Disputed but matches recurring monthly subscription
    if assessment.disputed_recurring:
        return _dedupe_and_sort([
            make_action("CREATE_CASE", "R7: disputed charge matches recurring monthly customer pattern", assessment.exposure_usd),
            make_action("VERIFY_WITH_CUSTOMER", "R7: verify recurring charge details with customer", assessment.exposure_usd),
            make_action("WARN_CUSTOMER", "R7: advise customer regarding recurring subscription", assessment.exposure_usd),
        ])

    # R5: Card testing sequence
    if assessment.pattern == "card_testing":
        actions.extend([
            make_action("DECLINE_TRANSACTION", "R5: small online testing authorizations preceded transaction", assessment.exposure_usd),
            make_action("STEP_UP_AUTH", "R5: require step-up authentication before further authorizations", assessment.exposure_usd),
        ])
        if assessment.cleared_purchase_over_100 or denied:
            actions.append(make_action("BLOCK_CARD", "R5: card testing confirmed with cleared purchase over $100 or customer denial", assessment.exposure_usd))

    # R2: Customer denies transaction
    elif denied:
        actions.extend([
            make_action("BLOCK_CARD", "R2: customer denied transaction", assessment.exposure_usd),
            make_action("CREATE_CASE", "R2: open case for confirmed unauthorized use", assessment.exposure_usd),
        ])

    # R4: No customer reply within 24 hours
    elif assessment.customer_response == "no_reply":
        actions.extend([
            make_action("DECLINE_TRANSACTION", "R4: decline pending authorization after 24h silence", assessment.exposure_usd),
            make_action("MONITOR_CARD", "R4: monitor card sensitivity after 24h silence", assessment.exposure_usd),
        ])
        if assessment.exposure_usd > 500:
            actions.append(make_action("ESCALATE_TO_ANALYST", "R4: escalation required for exposure > $500 with no reply", assessment.exposure_usd))

    # R9: Undocumented coordinated pattern
    elif assessment.pattern == "undocumented" and assessment.coordinated:
        actions.extend([
            make_action("CREATE_CASE", "R9: coordinated multi-customer abuse does not fit standard categories", assessment.exposure_usd),
            make_action("FILE_REPORT", "R9: regulatory filing required for coordinated ring abuse", assessment.exposure_usd),
            make_action("ESCALATE_TO_ANALYST", "R9: refer novel coordinated pattern to fraud analyst", assessment.exposure_usd),
        ])

    # R6: Shared origin (device, region cluster, or recipient email)
    elif assessment.shared_origin:
        actions.extend([
            make_action("CREATE_CASE", "R6: shared infrastructure links multiple cards", assessment.exposure_usd),
            make_action("FILE_REPORT", "R6: shared origin indicates organized multi-party compromise", assessment.exposure_usd),
            make_action("MONITOR_CONNECTED_CARDS", "R6: place all connected cards sharing origin under monitoring", assessment.exposure_usd),
        ])

    # R1: Single weak signal with P < 0.70 -> VERIFY before block
    elif assessment.weak_signal_only and assessment.probability < 0.70:
        actions.append(make_action("VERIFY_WITH_CUSTOMER", "R1: weak signal with probability < 0.70 requires customer validation before blocking", assessment.exposure_usd))

    # R8: Uncertain verdict with exposure > $500 or conflicting evidence
    elif (assessment.verdict == "uncertain" and assessment.exposure_usd > 500) or assessment.evidence_conflict:
        actions.append(make_action("ESCALATE_TO_ANALYST", "R8: escalate uncertain verdict with exposure > $500 or conflicting evidence", assessment.exposure_usd))

    # Legitimate verdict
    elif assessment.verdict == "legitimate":
        actions.append(make_action("CLOSE_NO_FRAUD", "R3: investigation determined activity is legitimate", assessment.exposure_usd))

    # Default uncertain monitoring
    else:
        actions.append(make_action("MONITOR_CARD", "R8: continue monitoring pending definitive evidence", assessment.exposure_usd))

    # Shared origin connected monitoring
    if assessment.shared_origin and not any(x["action"] == "MONITOR_CONNECTED_CARDS" for x in actions):
        actions.append(make_action("MONITOR_CONNECTED_CARDS", "R6: monitor connected cards sharing entity", assessment.exposure_usd))

    # Policy 3a Case opening condition: P >= 0.30 or evidence requested or customer dispute
    if (assessment.probability >= 0.30 or assessment.customer_response is not None or assessment.weak_signal_only) and not any(x["action"] == "CREATE_CASE" for x in actions):
        actions.append(make_action("CREATE_CASE", "3a: open case when fraud probability >= 0.30 or evidence requested", assessment.exposure_usd))

    # Policy 3a SAR filing condition: confirmed/strongly suspected AND (exposure > 1000 OR shared origin OR connected fraud OR coordinated R9)
    is_strongly_suspected = assessment.probability >= 0.85 or denied
    meets_sar_criteria = (
        assessment.exposure_usd > 1000.0
        or assessment.shared_origin
        or assessment.connected_fraud
        or assessment.coordinated
    )
    if is_strongly_suspected and meets_sar_criteria and not any(x["action"] == "FILE_REPORT" for x in actions):
        actions.append(make_action("FILE_REPORT", "3a: confirmed/strongly suspected fraud meeting threshold or shared origin criteria", assessment.exposure_usd))

    # R10: BLOCK_ALL_CARDS only when 2+ cards confirmed or credentials compromised
    if assessment.confirmed_two_cards or assessment.confirmed_credentials_compromised:
        actions.append(make_action("BLOCK_ALL_CARDS", "R10: customer has multiple confirmed compromised cards or credentials", assessment.exposure_usd))

    return _dedupe_and_sort(actions)


def sar_required(actions: list[dict[str, Any]]) -> bool:
    return any(item["action"] == "FILE_REPORT" for item in actions)
