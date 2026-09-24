"""Validate all generated case files against the README answer contract."""

from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

import duckdb

from fraud_app.policy import ALL_ACTIONS, AUTO_ACTIONS, route, sar_required

PATTERNS = {"card_testing", "card_not_present_fraud", "card_not_present_new_device", "out_of_region_use", "account_takeover", "undocumented", "none"}
STATUSES = {"open", "closed_fraud", "closed_legitimate", "escalated"}
VERDICTS = {"fraud", "legitimate", "uncertain"}
REQUEST_TYPES = {"customer_validation", "step_up_auth", "analyst_info"}
TOP_KEYS = {"case_id", "case", "evidence_requests", "next_best_actions", "sar", "stop_reason", "tool_calls", "tokens", "latency_s"}
CASE_KEYS = {"status", "verdict", "fraud_probability", "pattern", "pattern_description", "affected_txn_ids", "first_suspicious_txn_id", "connected_card_ids", "connected_device_profiles", "exposure_usd", "evidence", "similar_prior_cases", "summary", "written_to_graph", "graph_case_id"}
SAR_KEYS = {"file", "reason", "narrative", "subjects", "total_amount_usd", "activity_dates"}
ACTION_KEYS = {"action", "route", "reason"}


def fail(errors: list[str], message: str) -> None:
    errors.append(message)


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    with (root / "data/case_pack.csv").open(newline="", encoding="utf-8-sig") as handle:
        case_rows = list(csv.DictReader(handle))
    expected = {x["case_id"] for x in case_rows}
    tx = duckdb.connect()
    tx_ids = {str(x[0]) for x in tx.execute("SELECT transaction_id FROM read_csv_auto(?, header=true)", [str(root / "data/graph/transactions.csv")]).fetchall()}
    amounts = {str(x[0]): abs(float(x[1] or 0)) for x in tx.execute("SELECT transaction_id, amount FROM read_csv_auto(?, header=true)", [str(root / "data/graph/transactions.csv")]).fetchall()}
    history_ids = {x[0] for x in tx.execute("SELECT case_id FROM read_csv_auto(?, header=true)", [str(root / "data/closed_cases_history.csv")]).fetchall()}
    files = sorted((root / "cases").glob("HHG-*.json"))
    errors: list[str] = []
    if {x.stem for x in files} != expected:
        fail(errors, "cases directory does not contain exactly HHG-001 through HHG-020")
    for path in files:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            fail(errors, f"{path.name}: invalid JSON: {exc}")
            continue
        prefix = path.name
        if set(data) != TOP_KEYS: fail(errors, f"{prefix}: top-level fields mismatch")
        if data.get("case_id") != path.stem: fail(errors, f"{prefix}: case_id mismatch")
        case = data.get("case", {})
        if set(case) != CASE_KEYS: fail(errors, f"{prefix}: case fields mismatch")
        if case.get("status") not in STATUSES or case.get("verdict") not in VERDICTS or case.get("pattern") not in PATTERNS: fail(errors, f"{prefix}: invalid status/verdict/pattern")
        if not isinstance(case.get("fraud_probability"), (int, float)) or not 0 <= case["fraud_probability"] <= 1: fail(errors, f"{prefix}: invalid probability")
        if case.get("pattern") == "undocumented" and not case.get("pattern_description"): fail(errors, f"{prefix}: undocumented pattern needs description")
        if any(x not in tx_ids for x in case.get("affected_txn_ids", [])): fail(errors, f"{prefix}: unknown affected transaction")
        calculated = round(sum(amounts[x] for x in case.get("affected_txn_ids", [])), 2)
        if round(float(case.get("exposure_usd", -1)), 2) != calculated: fail(errors, f"{prefix}: exposure mismatch {case.get('exposure_usd')} != {calculated}")
        if case.get("verdict") == "legitimate" and (case.get("affected_txn_ids") or case.get("exposure_usd") != 0): fail(errors, f"{prefix}: legitimate case has exposure")
        for request in data.get("evidence_requests", []):
            if set(request) != {"type", "asked_after_step", "assumed_response"} or request["type"] not in REQUEST_TYPES: fail(errors, f"{prefix}: invalid evidence request")
        actions = data.get("next_best_actions", {})
        if set(actions) != {"initial", "final", "what_changed"}: fail(errors, f"{prefix}: invalid action object")
        for stage in ("initial", "final"):
            for item in actions.get(stage, []):
                if set(item) != ACTION_KEYS or item["action"] not in ALL_ACTIONS or item["route"] != route(item["action"], float(case["exposure_usd"])): fail(errors, f"{prefix}: invalid {stage} action or route")
        sar = data.get("sar", {})
        if set(sar) != SAR_KEYS: fail(errors, f"{prefix}: SAR fields mismatch")
        final_report = sar_required(actions.get("final", []))
        if sar.get("file") != final_report: fail(errors, f"{prefix}: SAR file disagrees with FILE_REPORT")
        if sar.get("file") and not (6 <= len(str(sar.get("narrative", "")).split(". ")) <= 14): fail(errors, f"{prefix}: SAR narrative length is outside expected range")
        if sar.get("file") and (not isinstance(sar.get("activity_dates"), list) or len(sar["activity_dates"]) != 2): fail(errors, f"{prefix}: filed SAR needs two activity dates")
        if not sar.get("file") and (sar.get("narrative") or sar.get("subjects") or sar.get("total_amount_usd") != 0 or sar.get("activity_dates")): fail(errors, f"{prefix}: non-filed SAR must be empty")
    if errors:
        print("\n".join(errors), file=sys.stderr)
        return 1
    print(f"Validated {len(files)} case files successfully")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())