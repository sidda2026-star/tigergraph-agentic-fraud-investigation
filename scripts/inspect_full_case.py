"""Detailed CLI runner to inspect the complete investigation output of a case."""

import sys
import json
from pathlib import Path

# Ensure project root is in python path
ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))

from graph.store import get_graph_store
from agent.core import FraudInvestigationAgent
import csv

def main():
    case_to_inspect = sys.argv[1] if len(sys.argv) > 1 else "HHG-004"
    data_dir = ROOT_DIR / "data"
    
    cases_path = data_dir / "case_pack.csv"
    with open(cases_path, "r", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
        
    case_row = next((r for r in rows if r["case_id"] == case_to_inspect), None)
    if not case_row:
        print(f"Case {case_to_inspect} not found! Available cases: {[r['case_id'] for r in rows]}")
        return

    print("=" * 80)
    print(f"RUNNING AUTONOMOUS INVESTIGATION AGENT: {case_to_inspect}")
    print("=" * 80)
    print(f"Trigger Type:    {case_row.get('trigger_type')}")
    print(f"Flagged Txn ID:  {case_row.get('flagged_txn_id')}")
    print(f"Customer ID:     {case_row.get('customer_id')}")
    print(f"Card ID:         {case_row.get('card_id')}")
    print(f"Timestamp:       {case_row.get('opened_at')}")
    print("=" * 80)
    
    store = get_graph_store(data_dir=data_dir)
    agent = FraudInvestigationAgent(store)
    
    result = agent.investigate_case(case_row)
    
    print("\n>>> INVESTIGATION COMPLETE! SUMMARY:")
    print("=" * 80)
    print(f"STATUS:             {result['case']['status']}")
    print(f"VERDICT:            {result['case']['verdict'].upper()}")
    print(f"FRAUD PROBABILITY:  {result['case']['fraud_probability']:.2f}")
    print(f"PATTERN DETECTED:   {result['case']['pattern']}")
    print(f"EXPOSURE AMOUNT:    ${result['case']['exposure_usd']:.2f}")
    print(f"SAR REQUIRED:       {result['sar']['file']}")
    print("=" * 80)
    
    print("\n[NEXT BEST ACTIONS - INITIAL]:")
    for act in result["next_best_actions"]["initial"]:
        print(f"  * {act['action']:<25} | Route: {act['route']:<6} | Reason: {act['reason']}")
        
    print("\n[NEXT BEST ACTIONS - FINAL]:")
    for act in result["next_best_actions"]["final"]:
        print(f"  * {act['action']:<25} | Route: {act['route']:<6} | Reason: {act['reason']}")
        
    print("\n[SIMILAR CASES RETRIEVED FROM GRAPH MEMORY]:")
    for sc in result.get("similar_cases", []):
        print(f"  * {sc.get('case_id')}: {sc.get('pattern')} (Verdict: {sc.get('verdict')}, Similarity: {sc.get('similarity'):.3f})")
        
    if result["sar"]["file"]:
        print("\n" + "=" * 80)
        print("[FINCEN SUSPICIOUS ACTIVITY REPORT (SAR) NARRATIVE]:")
        print("=" * 80)
        print(result["sar"]["narrative"])
        print("=" * 80)
        
    print("\n[FULL GENERATED ANSWER JSON]:")
    print(json.dumps(result, indent=2))

if __name__ == "__main__":
    main()
