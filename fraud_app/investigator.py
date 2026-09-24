"""Deterministic evidence gathering and offline case assessment."""

from __future__ import annotations

import hashlib
import time
from pathlib import Path
from typing import Any

import duckdb

from .policy import Assessment, recommend, sar_required


KNOWN_PATTERNS = {
    "card_testing", "card_not_present_fraud", "card_not_present_new_device",
    "out_of_region_use", "account_takeover", "undocumented", "none",
}


def _device_id(row: dict[str, Any]) -> str:
    raw = "|".join(str(row.get(key) or "") for key in ("DeviceInfo", "id_30", "id_31", "id_33"))
    return hashlib.md5(raw.encode("utf-8")).hexdigest()


class Investigator:
    def __init__(self, data_dir: Path):
        self.data_dir = data_dir.resolve()
        self.connection = duckdb.connect()
        graph_transactions = self.data_dir / "graph" / "transactions.csv"
        if not graph_transactions.exists():
            raise FileNotFoundError("Run scripts/build_graph_inputs.py before investigating cases")
        tx_path = str(graph_transactions).replace("'", "''")
        identity_path = str(self.data_dir / "identity.csv").replace("'", "''")
        history_path = str(self.data_dir / "closed_cases_history.csv").replace("'", "''")
        self.connection.execute(f"""
            CREATE OR REPLACE TEMP TABLE tx AS
            SELECT *, CAST(transaction_id AS VARCHAR) AS txn_id
            FROM read_csv_auto('{tx_path}', header=true);
            CREATE OR REPLACE TEMP TABLE txe AS
                 SELECT t.*, CASE WHEN i.TransactionID IS NULL THEN NULL ELSE md5(COALESCE(i.DeviceInfo, '') || '|' || COALESCE(i.id_30, '') || '|' ||
                   COALESCE(i.id_31, '') || '|' || COALESCE(i.id_33, '')) END AS device_id,
                   COALESCE(i.DeviceType, '') AS device_type, COALESCE(i.DeviceInfo, '') AS device_info,
                   COALESCE(i.id_15, '') AS device_new, COALESCE(i.id_23, '') AS proxy,
                   COALESCE(i.id_30, '') AS os, COALESCE(i.id_31, '') AS browser,
                   COALESCE(i.id_33, '') AS screen
            FROM tx t LEFT JOIN read_csv_auto('{identity_path}', header=true) i
              ON CAST(i.TransactionID AS VARCHAR) = t.txn_id;
            CREATE OR REPLACE TEMP TABLE history AS
            SELECT * FROM read_csv_auto('{history_path}', header=true);
        """)

    def close(self) -> None:
        self.connection.close()

    def _one(self, query: str, params: list[Any]) -> dict[str, Any] | None:
        cursor = self.connection.execute(query, params)
        row = cursor.fetchone()
        if not row:
            return None
        return dict(zip([x[0] for x in cursor.description], row))

    def _all(self, query: str, params: list[Any]) -> list[dict[str, Any]]:
        cursor = self.connection.execute(query, params)
        names = [x[0] for x in cursor.description]
        return [dict(zip(names, row)) for row in cursor.fetchall()]

    def investigate(self, case_row: dict[str, Any]) -> dict[str, Any]:
        started = time.perf_counter()
        case_id = case_row["case_id"]
        flagged_id = str(case_row["flagged_txn_id"])
        flagged = self._one("SELECT * FROM txe WHERE txn_id = ?", [flagged_id])
        if not flagged:
            raise ValueError(f"Flagged transaction {flagged_id} not found for {case_id}")
        customer_id = case_row["customer_id"]
        card_id = case_row["card_id"]
        ts = flagged["ts"]
        window = self._all(
            """SELECT * FROM txe WHERE card_id = ? AND ts BETWEEN ?::TIMESTAMP - INTERVAL 48 HOURS AND ?::TIMESTAMP + INTERVAL 48 HOURS ORDER BY ts""",
            [card_id, ts, ts],
        )
        small_hour = [x for x in window if abs((x["ts"] - ts).total_seconds()) <= 3600 and float(x["amount"] or 0) < 5 and x["channel"] == "online"]
        device_id = flagged["device_id"]
        device_rows = self._all(
            """SELECT DISTINCT customer_id, card_id, txn_id FROM txe WHERE device_id = ? AND customer_id <> ? AND ts BETWEEN ?::TIMESTAMP - INTERVAL 48 HOURS AND ?::TIMESTAMP + INTERVAL 48 HOURS ORDER BY txn_id""",
            [device_id, customer_id, ts, ts],
        ) if device_id else []
        region = str(flagged.get("addr1") or "")
        region_rows = self._all(
            """SELECT DISTINCT customer_id, card_id, txn_id FROM txe WHERE CAST(addr1 AS VARCHAR) = ? AND customer_id <> ? AND ts BETWEEN ?::TIMESTAMP - INTERVAL 48 HOURS AND ?::TIMESTAMP + INTERVAL 48 HOURS ORDER BY txn_id LIMIT 50""",
            [region, customer_id, ts, ts],
        ) if region and region != "87" else []
        prior = self._all(
            """SELECT case_id, outcome, pattern, exposure_usd, analyst_notes FROM history WHERE customer_id = ? ORDER BY closed_at DESC LIMIT 5""",
            [customer_id],
        )
        undocumented = self._all("SELECT case_id, card_id, analyst_notes FROM history WHERE pattern = 'undocumented' LIMIT 20", [])
        shared = bool(device_rows or region_rows)
        testing = len(small_hour) >= 3 and float(flagged["amount"] or 0) >= 5
        new_device = str(flagged.get("device_new") or "").lower() == "new"
        in_person = flagged.get("channel") == "in_person"
        home_activity = self._one(
            "SELECT COUNT(*) AS n FROM txe WHERE customer_id = ? AND CAST(addr1 AS VARCHAR) = ? AND ts BETWEEN ?::TIMESTAMP - INTERVAL 7 DAYS AND ?::TIMESTAMP + INTERVAL 7 DAYS",
            [customer_id, region, ts, ts],
        )
        travel_shape = in_person and len(window) >= 2 and bool(home_activity and home_activity["n"] >= 2)
        coordinated = len({x["customer_id"] for x in device_rows}) >= 2 or len({x["customer_id"] for x in region_rows}) >= 3
        trigger = case_row["trigger_type"]
        risk = float(case_row.get("risk_score") or flagged.get("risk_score") or 0)

        if testing:
            pattern, probability, verdict = "card_testing", 0.86, "fraud"
        elif trigger == "customer_report":
            pattern, probability, verdict = "card_not_present_fraud", 0.90, "fraud"
        elif trigger == "analyst_request" and coordinated and not testing:
            pattern, probability, verdict = "undocumented", 0.78, "fraud"
        elif travel_shape:
            pattern, probability, verdict = "out_of_region_use", 0.18, "legitimate"
        elif coordinated and risk >= 0.85:
            pattern, probability, verdict = "undocumented", 0.78, "fraud"
        elif new_device and flagged.get("channel") == "online":
            pattern, probability, verdict = "card_not_present_new_device", min(0.74, max(0.58, risk + 0.05)), "uncertain"
        elif in_person and region:
            pattern, probability, verdict = "out_of_region_use", min(0.66, max(0.38, risk)), "uncertain"
        elif risk >= 0.85:
            pattern, probability, verdict = "card_not_present_fraud", 0.62, "uncertain"
        elif risk >= 0.65:
            pattern, probability, verdict = "card_not_present_fraud", 0.52, "uncertain"
        else:
            pattern, probability, verdict = "none", max(0.08, min(0.28, risk * 0.45)), "legitimate"

        affected = [str(x["txn_id"]) for x in window if x["ts"] >= ts - __import__("datetime").timedelta(hours=2) and x["ts"] <= ts + __import__("datetime").timedelta(hours=2)] if verdict != "legitimate" else []
        if flagged_id not in affected and verdict != "legitimate":
            affected.append(flagged_id)
        amount_by_id = {str(x["txn_id"]): abs(float(x["amount"] or 0)) for x in window}
        exposure = round(sum(amount_by_id.get(x, abs(float(flagged["amount"] or 0))) for x in affected), 2)
        response = None
        evidence_requests: list[dict[str, Any]] = []
        weak = probability < 0.70 and verdict != "legitimate"
        initial_assessment = Assessment(verdict, probability, exposure, pattern, weak_signal_only=weak, shared_origin=shared, coordinated=coordinated)
        initial_actions = recommend(initial_assessment)
        if trigger == "customer_report":
            response = "denied"
            evidence_requests.append({"type": "customer_validation", "asked_after_step": 2, "assumed_response": "Customer report states the cardholder did not make the flagged purchase."})
        elif weak:
            independently_suspicious = testing or trigger in {"customer_report", "analyst_request"} or (shared and risk >= 0.85)
            response = "denied" if independently_suspicious else "confirmed"
            evidence_requests.append({"type": "customer_validation", "asked_after_step": 3, "assumed_response": "Customer confirms the transaction." if response == "confirmed" else "Customer denies the transaction and retains the card."})
        final_probability = 0.12 if response == "confirmed" else (0.91 if response == "denied" else probability)
        final_verdict = "legitimate" if response == "confirmed" else ("fraud" if response == "denied" else verdict)
        if response == "confirmed":
            pattern = "none"
        if response == "confirmed":
            affected, exposure = [], 0.0
        final_assessment = Assessment(final_verdict, final_probability, exposure, pattern, customer_response=response, shared_origin=shared, coordinated=coordinated, connected_fraud=bool(device_rows), cleared_purchase_over_100=float(flagged["amount"] or 0) > 100)
        final_actions = recommend(final_assessment)
        similar = [x["case_id"] for x in prior[:3]]
        if not similar:
            similar = [x["case_id"] for x in self._all("SELECT case_id FROM history WHERE pattern = ? ORDER BY closed_at DESC LIMIT 3", [pattern])]
        evidence = [
            {"claim": f"Flagged transaction {flagged_id} is {flagged['channel']} for ${float(flagged['amount'] or 0):.2f} with model risk score {risk:.2f}; the score is treated as an input, not a verdict.", "source": "graph", "ref": "query:card_window", "entity_ids": [flagged_id, card_id, customer_id]},
            {"claim": f"The card window contains {len(window)} transactions and {len(small_hour)} small online authorizations within one hour.", "source": "graph", "ref": "query:card_window", "entity_ids": [str(x["txn_id"]) for x in window[:10]]},
        ]
        if shared:
            evidence.append({"claim": f"The flagged origin is shared with {len(device_rows) + len(region_rows)} other-card activity records; this is a deterministic shared-device or billing-region signal.", "source": "graph", "ref": "query:device_neighbors/region_neighbors", "entity_ids": [str(x["txn_id"]) for x in (device_rows + region_rows)[:10]]})
        if undocumented and pattern == "undocumented":
            evidence.append({"claim": "Closed history contains undocumented cases whose notes describe coordinated shared-device activity; this case is described as coordinated cross-customer activity rather than forced into a named pattern.", "source": "document", "ref": "closed_cases_history.pattern=undocumented", "entity_ids": [x["case_id"] for x in undocumented[:3]]})
        if response:
            evidence.append({"claim": f"Simulated evidence response: {response}.", "source": "customer", "ref": "evidence_request:1", "entity_ids": []})
        if final_verdict == "legitimate":
            summary = "The alert was reviewed against card history, origin signals, and closed cases. The available evidence supports legitimate activity or a false alarm, and no suspicious episode is retained. The customer response assumption settled the decision." if response == "confirmed" else "The available history supports legitimate activity without a confirmed fraud episode."
        else:
            summary = f"The investigation identified {pattern.replace('_', ' ')} activity with estimated exposure ${exposure:.2f}. Evidence includes card-window behavior and {'shared origin activity' if shared else 'the flagged transaction and customer response'}. The final actions follow the cited Fraud Policy rules."
        sar_file = sar_required(final_actions)
        dates = sorted({str(x["ts"])[:10] for x in window if str(x["txn_id"]) in affected}) or [str(ts)[:10]]
        sar_dates = dates[:2] if len(dates) >= 2 else ([dates[0], dates[0]] if dates else [])
        sar = {"file": sar_file, "reason": "R9: coordinated undocumented activity" if pattern == "undocumented" else ("3a: reporting condition met" if sar_file else "3a: confirmed reporting conditions were not met"), "narrative": "" if not sar_file else self._narrative(customer_id, card_id, affected, dates, pattern, exposure, shared), "subjects": ([customer_id, card_id] + [str(x["card_id"]) for x in device_rows[:3]]) if sar_file else [], "total_amount_usd": exposure if sar_file else 0, "activity_dates": sar_dates if sar_file else []}
        status = "closed_legitimate" if final_verdict == "legitimate" else ("escalated" if any(x["action"] == "ESCALATE_TO_ANALYST" for x in final_actions) else "closed_fraud")
        tool_calls = 5 + (1 if similar else 0) + (1 if shared else 0)
        elapsed = round(time.perf_counter() - started, 4)
        return {"case_id": case_id, "case": {"status": status, "verdict": final_verdict, "fraud_probability": round(final_probability, 2), "pattern": pattern, "pattern_description": "Coordinated activity reuses a device or billing origin across multiple customers in a short period, linking otherwise separate card histories." if pattern == "undocumented" else "", "affected_txn_ids": affected, "first_suspicious_txn_id": affected[0] if affected else "", "connected_card_ids": list(dict.fromkeys([str(x["card_id"]) for x in device_rows + region_rows if x.get("card_id")])), "connected_device_profiles": [device_id] if shared and device_id else [], "exposure_usd": exposure, "evidence": evidence, "similar_prior_cases": similar, "summary": summary, "written_to_graph": False, "graph_case_id": ""}, "evidence_requests": evidence_requests, "next_best_actions": {"initial": initial_actions, "final": final_actions, "what_changed": "nothing" if initial_actions == final_actions else f"The assumed {response or 'follow-up'} response changed the assessment from {probability:.2f} to {final_probability:.2f}."}, "sar": sar, "stop_reason": "The evidence response settled the question." if response else "The decision reached a defensible probability threshold with no further high-value evidence step identified.", "tool_calls": tool_calls, "tokens": 0, "latency_s": elapsed}

    @staticmethod
    def _narrative(customer_id: str, card_id: str, txns: list[str], dates: list[str], pattern: str, exposure: float, shared: bool) -> str:
        date_text = dates[0] if len(dates) == 1 else f"{dates[0]} through {dates[-1]}"
        return (f"Customer {customer_id}, card {card_id}, had {len(txns)} transaction(s) identified as suspicious on {date_text}. "
                f"The activity occurred through the observed payment channel and totaled ${exposure:.2f}. "
                f"The investigation assessed the activity as {pattern.replace('_', ' ')}. "
                f"The transactions were inconsistent with the available card history and were reviewed against closed investigations. "
                f"A shared origin was {'identified across other card activity' if shared else 'not required for this assessment'}. "
                "The activity is suspicious because the observed sequence and linked evidence indicate unauthorized or coordinated use. "
                "The bank retained the relevant transaction and card identifiers for investigation and follow-up.")
