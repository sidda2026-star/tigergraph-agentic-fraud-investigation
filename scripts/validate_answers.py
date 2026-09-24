"""Comprehensive validator checking all 20 answer files against the Answer Format."""

from __future__ import annotations

import json
import re
from pathlib import Path
import duckdb

REQUIRED_TOP_FIELDS = {
    "case_id": str,
    "case": dict,
    "evidence_requests": list,
    "next_best_actions": dict,
    "sar": dict,
    "stop_reason": str,
    "tool_calls": int,
    "tokens": int,
    "latency_s": (int, float),
}

REQUIRED_CASE_FIELDS = {
    "status": str,
    "verdict": str,
    "fraud_probability": (int, float),
    "pattern": str,
    "pattern_description": str,
    "affected_txn_ids": list,
    "first_suspicious_txn_id": str,
    "connected_card_ids": list,
    "connected_device_profiles": list,
    "exposure_usd": (int, float),
    "evidence": list,
    "similar_prior_cases": list,
    "summary": str,
    "written_to_graph": bool,
    "graph_case_id": str,
}

REQUIRED_SAR_FIELDS = {
    "file": bool,
    "reason": str,
    "narrative": str,
    "subjects": list,
    "total_amount_usd": (int, float),
    "activity_dates": list,
}

VALID_STATUSES = {"open", "closed_fraud", "closed_legitimate", "escalated"}
VALID_VERDICTS = {"fraud", "legitimate", "uncertain"}
VALID_PATTERNS = {
    "card_testing",
    "card_not_present_fraud",
    "card_not_present_new_device",
    "out_of_region_use",
    "account_takeover",
    "undocumented",
    "none",
}
VALID_ROUTES = {"auto", "L1", "L2"}


def count_sentences(text: str) -> int:
    if not text.strip():
        return 0
    # Split on sentence terminals . ! ?
    return len([s for s in re.split(r"[.!?]+", text) if s.strip()])


def validate_answers(cases_dir: Path = Path("cases"), data_dir: Path = Path("data")) -> bool:
    print("=" * 80)
    print("VALIDATING 20 CASE ANSWER FILES")
    print("=" * 80)

    # Load dataset IDs to verify existence
    con = duckdb.connect()
    parquet = str((data_dir / "transactions_trimmed.parquet").resolve()).replace("'", "''")
    con.execute(f"CREATE TEMP TABLE tx AS SELECT CAST(TransactionID AS VARCHAR) as tid, customer_id, CAST(TransactionAmt AS DOUBLE) as amount, ts FROM read_parquet('{parquet}')")
    known_txns = set(r[0] for r in con.execute("SELECT tid FROM tx").fetchall())
    txn_amounts = dict(con.execute("SELECT tid, amount FROM tx").fetchall())
    txn_dates = dict(con.execute("SELECT tid, CAST(ts AS VARCHAR)[:10] FROM tx").fetchall())

    all_passed = True
    summary_table = []

    for i in range(1, 21):
        cid = f"HHG-{i:03d}"
        path = cases_dir / f"{cid}.json"
        if not path.exists():
            print(f"[FAIL] Missing file {path}")
            all_passed = False
            continue

        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:
            print(f"[FAIL] {cid}: Corrupted JSON: {e}")
            all_passed = False
            continue

        errors = []

        # 1. Top level fields and types
        for fld, expected_type in REQUIRED_TOP_FIELDS.items():
            if fld not in data:
                errors.append(f"Missing top-level field '{fld}'")
            elif not isinstance(data[fld], expected_type):
                errors.append(f"Field '{fld}' expected {expected_type}, got {type(data[fld])}")

        case_obj = data.get("case", {})
        # 2. Case fields and types
        for fld, expected_type in REQUIRED_CASE_FIELDS.items():
            if fld not in case_obj:
                errors.append(f"Missing case field '{fld}'")
            elif not isinstance(case_obj[fld], expected_type):
                errors.append(f"Case field '{fld}' expected {expected_type}, got {type(case_obj[fld])}")

        # Enums
        if case_obj.get("status") not in VALID_STATUSES:
            errors.append(f"Invalid status '{case_obj.get('status')}'")
        if case_obj.get("verdict") not in VALID_VERDICTS:
            errors.append(f"Invalid verdict '{case_obj.get('verdict')}'")
        if case_obj.get("pattern") not in VALID_PATTERNS:
            errors.append(f"Invalid pattern '{case_obj.get('pattern')}'")

        prob = case_obj.get("fraud_probability", 0)
        if not (0.0 <= prob <= 1.0):
            errors.append(f"Probability {prob} out of bounds [0, 1]")

        # Pattern description check
        if case_obj.get("pattern") == "undocumented":
            if not case_obj.get("pattern_description"):
                errors.append("Pattern is undocumented but pattern_description is empty")
        else:
            if case_obj.get("pattern_description") != "":
                errors.append("Pattern is not undocumented but pattern_description is not empty")

        # 3. ID existence & exposure
        affected_txns = case_obj.get("affected_txn_ids", [])
        for tid in affected_txns:
            if str(tid) not in known_txns:
                errors.append(f"Affected txn {tid} does not exist in dataset!")

        calc_exposure = sum(abs(txn_amounts.get(str(tid), 0.0)) for tid in affected_txns)
        rep_exposure = case_obj.get("exposure_usd", 0.0)
        if abs(calc_exposure - rep_exposure) > 0.05:
            errors.append(f"Exposure mismatch: reported ${rep_exposure:.2f}, sum of txns is ${calc_exposure:.2f}")

        # 4. Legitimate requirements
        if case_obj.get("verdict") == "legitimate":
            if affected_txns:
                errors.append("Verdict is legitimate but affected_txn_ids is not empty")
            if rep_exposure != 0.0:
                errors.append(f"Verdict is legitimate but exposure_usd is {rep_exposure}")

        # 5. SAR validation
        sar_obj = data.get("sar", {})
        for fld, expected_type in REQUIRED_SAR_FIELDS.items():
            if fld not in sar_obj:
                errors.append(f"Missing SAR field '{fld}'")
            elif not isinstance(sar_obj[fld], expected_type):
                errors.append(f"SAR field '{fld}' expected {expected_type}, got {type(sar_obj[fld])}")

        final_actions = [a.get("action") for a in data.get("next_best_actions", {}).get("final", [])]
        sar_file = sar_obj.get("file", False)
        has_file_report = "FILE_REPORT" in final_actions

        if sar_file != has_file_report:
            errors.append(f"SAR file ({sar_file}) does not match FILE_REPORT in final actions ({has_file_report})")

        if case_obj.get("verdict") == "legitimate":
            if sar_file:
                errors.append("Verdict is legitimate but sar.file is true")
            if sar_obj.get("narrative") != "":
                errors.append("Verdict is legitimate but sar.narrative is not empty")
            if sar_obj.get("subjects") != []:
                errors.append("Verdict is legitimate but sar.subjects is not empty")
            if sar_obj.get("total_amount_usd") != 0.0:
                errors.append("Verdict is legitimate but sar.total_amount_usd is not 0.0")
            if sar_obj.get("activity_dates") != []:
                errors.append("Verdict is legitimate but sar.activity_dates is not empty")

        if sar_file:
            sent_count = count_sentences(sar_obj.get("narrative", ""))
            if not (6 <= sent_count <= 12):
                errors.append(f"SAR narrative has {sent_count} sentences, expected between 6 and 12")
            if len(sar_obj.get("activity_dates", [])) != 2:
                errors.append(f"SAR activity_dates expected [start, end], got {sar_obj.get('activity_dates')}")
            else:
                d1, d2 = sar_obj.get("activity_dates")
                if d1 > d2:
                    errors.append(f"SAR activity dates inverted: {d1} > {d2}")

        # 6. Next Best Actions validation
        nba = data.get("next_best_actions", {})
        initial_acts = nba.get("initial", [])
        final_acts = nba.get("final", [])
        for act in initial_acts + final_acts:
            if act.get("route") not in VALID_ROUTES:
                errors.append(f"Invalid route '{act.get('route')}' in action {act.get('action')}")

        ev_reqs = data.get("evidence_requests", [])
        if not ev_reqs:
            if initial_acts != final_acts:
                errors.append("No evidence requested, but initial and final actions differ")
            if nba.get("what_changed") != "nothing":
                errors.append(f"No evidence requested, but what_changed is not 'nothing': '{nba.get('what_changed')}'")

        if errors:
            all_passed = False
            print(f"[FAIL] {cid} encountered {len(errors)} error(s):")
            for err in errors:
                print(f"   - {err}")
        else:
            print(f"[PASS] {cid}")

        summary_table.append({
            "case_id": cid,
            "verdict": case_obj.get("verdict"),
            "prob": case_obj.get("fraud_probability"),
            "pattern": case_obj.get("pattern"),
            "exposure": case_obj.get("exposure_usd"),
            "initial": ",".join(a.get("action", "") for a in initial_acts),
            "final": ",".join(a.get("action", "") for a in final_acts),
            "sar": sar_file,
            "status": "PASS" if not errors else "FAIL",
        })

    print("\n" + "=" * 100)
    print(f"{'Case ID':<9} | {'Status':<6} | {'Verdict':<10} | {'Prob':<5} | {'Pattern':<24} | {'Exposure':<9} | {'SAR':<5} | {'Final Actions'}")
    print("-" * 100)
    for r in summary_table:
        print(f"{r['case_id']:<9} | {r['status']:<6} | {r['verdict']:<10} | {r['prob']:<5.2f} | {r['pattern']:<24} | ${r['exposure']:<8.2f} | {str(r['sar']):<5} | {r['final']}")
    print("=" * 100)

    con.close()
    return all_passed


if __name__ == "__main__":
    import sys
    ok = validate_answers()
    if not ok:
        sys.exit(1)
    print("\nAll validation checks PASSED with 100% compliance!")
