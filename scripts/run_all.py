"""Run autonomous fraud investigation agent on all 20 exam cases in chronological order."""

from __future__ import annotations

import sys
import json
import csv
from pathlib import Path
from datetime import datetime

# Ensure project root is in python path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from graph.store import get_graph_store
from agent.core import FraudInvestigationAgent


def main():
    data_dir = Path("data")
    cases_dir = Path("cases")
    cases_dir.mkdir(exist_ok=True)

    print("Initializing GraphStore and TigerGraph / Local memory...")
    store = get_graph_store(data_dir=data_dir)
    agent = FraudInvestigationAgent(store)

    # Read case_pack.csv
    cases_path = data_dir / "case_pack.csv"
    with open(cases_path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        cases = list(reader)

    # Sort in chronological order of opened_at so later cases can retrieve earlier agent-written cases from graph memory
    cases.sort(key=lambda c: datetime.strptime(c["opened_at"], "%Y-%m-%d %H:%M:%S"))
    print(f"Loaded {len(cases)} exam cases. Processing in chronological order...\n")

    summary_rows = []

    for idx, c in enumerate(cases, 1):
        cid = c["case_id"]
        print(f"[{idx}/20] Investigating {cid} (Opened: {c['opened_at']}, Trigger: {c['trigger_type']})...")
        
        result = agent.investigate_case(c)

        out_path = cases_dir / f"{cid}.json"
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(result, f, indent=2)

        case_obj = result["case"]
        nba = result["next_best_actions"]
        init_act_str = ",".join(a["action"] for a in nba["initial"])
        fin_act_str = ",".join(a["action"] for a in nba["final"])

        summary_rows.append({
            "case_id": cid,
            "verdict": case_obj["verdict"],
            "prob": case_obj["fraud_probability"],
            "pattern": case_obj["pattern"],
            "exposure": case_obj["exposure_usd"],
            "initial": init_act_str,
            "final": fin_act_str,
            "sar": result["sar"]["file"],
        })

    print("\n" + "=" * 90)
    print(f"{'Case ID':<10} | {'Verdict':<12} | {'Prob':<5} | {'Pattern':<25} | {'Exposure':<9} | {'SAR':<5} | {'Final Actions'}")
    print("-" * 90)
    for r in summary_rows:
        print(f"{r['case_id']:<10} | {r['verdict']:<12} | {r['prob']:<5.2f} | {r['pattern']:<25} | ${r['exposure']:<8.2f} | {str(r['sar']):<5} | {r['final']}")
    print("=" * 90)
    print("\nAll 20 cases completed and saved to cases/")


if __name__ == "__main__":
    main()
