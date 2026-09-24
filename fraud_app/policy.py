"""Pure Fraud Policy implementation. No LLM or database calls belong here."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

AUTO_ACTIONS = {
    "ALLOW_TRANSACTION", "MONITOR_CARD", "MONITOR_CONNECTED_CARDS", "WARN_CUSTOMER",
    "VERIFY_WITH_CUSTOMER", "STEP_UP_AUTH", "GENERATE_REPORT", "CREATE_CASE",
    "ESCALATE_TO_ANALYST", "CLOSE_NO_FRAUD",
}
L1_ACTIONS = {"DECLINE_TRANSACTION"}
ALL_ACTIONS = AUTO_ACTIONS | L1_ACTIONS | {"BLOCK_CARD", "BLOCK_ALL_CARDS", "FILE_REPORT"}


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


def route(action: str, exposure_usd: float) -> str:
    if action == "BLOCK_CARD":
        return "L1" if exposure_usd <= 2500 else "L2"
    if action in {"BLOCK_ALL_CARDS", "FILE_REPORT"}:
        return "L2"
    if action in L1_ACTIONS:
        return "L1"
    if action in AUTO_ACTIONS:
        return "auto"
    raise ValueError(f"Unknown policy action: {action}")


def action(action_name: str, reason: str, exposure_usd: float) -> dict[str, Any]:
    if action_name not in ALL_ACTIONS:
        raise ValueError(f"Unknown policy action: {action_name}")
    return {"action": action_name, "route": route(action_name, exposure_usd), "reason": reason}


def _dedupe(actions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    result = []
    for item in actions:
        if item["action"] not in seen:
            seen.add(item["action"])
            result.append(item)
    return result


def recommend(assessment: Assessment) -> list[dict[str, Any]]:
    """Return policy-controlled actions in execution order."""
    actions: list[dict[str, Any]] = []
    denied = assessment.customer_response == "denied"
    confirmed = assessment.customer_response == "confirmed"

    if confirmed:
        return [action("CLOSE_NO_FRAUD", "R3: customer confirmed the transaction", assessment.exposure_usd)]
    if assessment.disputed_recurring:
        return _dedupe([
            action("CREATE_CASE", "R7: disputed charge matches a recurring customer pattern", assessment.exposure_usd),
            action("VERIFY_WITH_CUSTOMER", "R7", assessment.exposure_usd),
            action("WARN_CUSTOMER", "R7", assessment.exposure_usd),
        ])
    if assessment.pattern == "card_testing":
        actions.extend([
            action("DECLINE_TRANSACTION", "R5: at least three small online authorizations preceded the purchase", assessment.exposure_usd),
            action("STEP_UP_AUTH", "R5", assessment.exposure_usd),
        ])
        if assessment.cleared_purchase_over_100 or denied:
            actions.append(action("BLOCK_CARD", "R5: a purchase over $100 has cleared", assessment.exposure_usd))
    elif denied:
        actions.extend([
            action("BLOCK_CARD", "R2: customer denied the transaction", assessment.exposure_usd),
            action("CREATE_CASE", "R2", assessment.exposure_usd),
        ])
    elif assessment.customer_response == "no_reply":
        actions.extend([
            action("MONITOR_CARD", "R4: no reply within 24 hours", assessment.exposure_usd),
            action("DECLINE_TRANSACTION", "R4: pending authorizations require decline", assessment.exposure_usd),
        ])
        if assessment.exposure_usd > 500:
            actions.append(action("ESCALATE_TO_ANALYST", "R4: exposure exceeds $500", assessment.exposure_usd))
    elif assessment.pattern == "undocumented" and assessment.coordinated:
        actions.extend([
            action("CREATE_CASE", "R9: coordinated abuse does not fit a known pattern", assessment.exposure_usd),
            action("FILE_REPORT", "R9", assessment.exposure_usd),
            action("ESCALATE_TO_ANALYST", "R9", assessment.exposure_usd),
        ])
    elif assessment.shared_origin:
        actions.extend([
            action("CREATE_CASE", "R6: shared device, region, or recipient email links cards", assessment.exposure_usd),
            action("FILE_REPORT", "R6: shared origin connects activity across cards", assessment.exposure_usd),
            action("MONITOR_CONNECTED_CARDS", "R6", assessment.exposure_usd),
        ])
    elif assessment.weak_signal_only and assessment.probability < 0.70:
        actions.append(action("VERIFY_WITH_CUSTOMER", "R1: single weak signal with probability below 0.70", assessment.exposure_usd))
    elif assessment.verdict == "uncertain" and assessment.exposure_usd > 500:
        actions.append(action("ESCALATE_TO_ANALYST", "R8: uncertain verdict with exposure above $500", assessment.exposure_usd))
    elif assessment.verdict == "legitimate":
        actions.append(action("CLOSE_NO_FRAUD", "R3: evidence supports legitimate activity", assessment.exposure_usd))
    else:
        actions.append(action("MONITOR_CARD", "R8: continue monitoring while evidence remains uncertain", assessment.exposure_usd))

    if assessment.shared_origin and not any(x["action"] == "MONITOR_CONNECTED_CARDS" for x in actions):
        actions.append(action("MONITOR_CONNECTED_CARDS", "R6", assessment.exposure_usd))
    if assessment.probability >= 0.30 and not any(x["action"] == "CREATE_CASE" for x in actions):
        actions.append(action("CREATE_CASE", "3a: open a case at probability 0.30 or after an evidence request", assessment.exposure_usd))
    if (assessment.probability >= 0.85 or denied) and (assessment.exposure_usd > 1000 or assessment.shared_origin or assessment.connected_fraud or assessment.coordinated) and not any(x["action"] == "FILE_REPORT" for x in actions):
        actions.append(action("FILE_REPORT", "3a: confirmed or strongly suspected fraud meets the reporting conditions", assessment.exposure_usd))
    if assessment.confirmed_two_cards or assessment.confirmed_credentials_compromised:
        actions.append(action("BLOCK_ALL_CARDS", "R10: at least two cards are confirmed compromised", assessment.exposure_usd))
    return _dedupe(actions)


def sar_required(actions: list[dict[str, Any]]) -> bool:
    return any(item["action"] == "FILE_REPORT" for item in actions)
