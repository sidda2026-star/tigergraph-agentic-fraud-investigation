"""Autonomous background monitor scanning the exam period for high-risk alerts."""

from __future__ import annotations

import sys
import json
from pathlib import Path
from datetime import datetime

# Ensure project root in path
ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))

from graph.store import get_graph_store
from agent.core import FraudInvestigationAgent


def main():
    print("Starting Autonomous Stream Monitor...")
    alerts_dir = ROOT_DIR / "optional" / "alerts"
    alerts_dir.mkdir(parents=True, exist_ok=True)

    store = get_graph_store(data_dir=ROOT_DIR / "data")
    agent = FraudInvestigationAgent(store)

    con = store.con
    # Find high-risk transactions in exam window (Nov-Dec 2016)
    rows = con.execute("""
        SELECT 
            transaction_id as flagged_txn_id,
            card_id,
            customer_id,
            ts as opened_at,
            risk_score,
            amount
        FROM enriched_tx
        WHERE ts >= '2016-11-01' AND risk_score >= 0.88 AND card_id IS NOT NULL
        LIMIT 5
    """).fetchall()

    cols = ["flagged_txn_id", "card_id", "customer_id", "opened_at", "risk_score", "amount"]
    print(f"Discovered {len(rows)} unprompted high-risk candidate alerts during the exam period.\n")

    for i, r in enumerate(rows, 1):
        d = dict(zip(cols, r))
        case_id = f"OPT-MON-{i:03d}"
        case_row = {
            "case_id": case_id,
            "opened_at": str(d["opened_at"]),
            "trigger_type": "risk_score",
            "trigger_text": f"Autonomous monitor detected risk score {d['risk_score']} on transaction {d['flagged_txn_id']} (${d['amount']:.2f})",
            "flagged_txn_id": str(d["flagged_txn_id"]),
            "card_id": str(d["card_id"]),
            "customer_id": str(d["customer_id"]),
            "risk_score": d["risk_score"],
        }
        print(f"Investigating {case_id} (Txn: {d['flagged_txn_id']}, Score: {d['risk_score']})...")
        res = agent.investigate_case(case_row)
        out_file = alerts_dir / f"{case_id}.json"
        with open(out_file, "w", encoding="utf-8") as f:
            json.dump(res, f, indent=2)

    print(f"\nAll candidate monitor alerts generated and stored in optional/alerts/")


if __name__ == "__main__":
    main()
