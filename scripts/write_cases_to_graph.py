"""Write generated investigation cases into TigerGraph case memory."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

import pyTigerGraph as tg
from dotenv import load_dotenv


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cases-dir", type=Path, default=Path("cases"))
    parser.add_argument("--local", action="store_true", help="Write graph-shaped case memory locally when TigerGraph is unavailable.")
    parser.add_argument("--local-output", type=Path, default=Path("data/local_graph_memory.json"))
    args = parser.parse_args()
    load_dotenv()
    if args.local:
        graph = {"vertices": {"InvestigationCase": {}}, "edges": {"MEMORY_INVOLVES": [], "MEMORY_ON_CARD": [], "MEMORY_SIMILAR": []}}
        for path in sorted(args.cases_dir.glob("HHG-*.json")):
            data = json.loads(path.read_text(encoding="utf-8"))
            case = data["case"]
            graph_case_id = f"CASE-{data['case_id']}"
            graph["vertices"]["InvestigationCase"][graph_case_id] = {"case_id": data["case_id"], "verdict": case["verdict"], "fraud_probability": case["fraud_probability"], "pattern": case["pattern"], "status": case["status"], "exposure_usd": case["exposure_usd"], "summary": case["summary"]}
            graph["edges"]["MEMORY_INVOLVES"].extend([[graph_case_id, txn_id] for txn_id in case["affected_txn_ids"]])
            graph["edges"]["MEMORY_ON_CARD"].extend([[graph_case_id, card_id] for card_id in case.get("connected_card_ids", [])])
            graph["edges"]["MEMORY_SIMILAR"].extend([[graph_case_id, prior_id] for prior_id in case["similar_prior_cases"]])
            case["written_to_graph"] = True
            case["graph_case_id"] = graph_case_id
            path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        args.local_output.parent.mkdir(parents=True, exist_ok=True)
        args.local_output.write_text(json.dumps(graph, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"Wrote local graph memory to {args.local_output.resolve()}")
        return
    required = ["TIGERGRAPH_HOST", "TIGERGRAPH_GRAPH", "TIGERGRAPH_USERNAME", "TIGERGRAPH_PASSWORD"]
    missing = [name for name in required if not os.getenv(name)]
    if missing:
        raise SystemExit("TigerGraph write-back blocked; set " + ", ".join(missing) + " in .env")
    connection = tg.TigerGraphConnection(host=os.environ["TIGERGRAPH_HOST"], graphname=os.environ["TIGERGRAPH_GRAPH"], username=os.environ["TIGERGRAPH_USERNAME"], password=os.environ["TIGERGRAPH_PASSWORD"], apiToken=os.getenv("TIGERGRAPH_API_TOKEN"))
    written = 0
    for path in sorted(args.cases_dir.glob("HHG-*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        case = data["case"]
        graph_case_id = f"CASE-{data['case_id']}"
        connection.upsertVertex("InvestigationCase", graph_case_id, {"case_id": data["case_id"], "verdict": case["verdict"], "fraud_probability": case["fraud_probability"], "pattern": case["pattern"], "status": case["status"], "exposure_usd": case["exposure_usd"], "summary": case["summary"]})
        for transaction_id in case["affected_txn_ids"]:
            connection.upsertEdge("InvestigationCase", graph_case_id, "MEMORY_INVOLVES", "Transaction", transaction_id, {})
        for card_id in case.get("connected_card_ids", []):
            connection.upsertEdge("InvestigationCase", graph_case_id, "MEMORY_ON_CARD", "Card", card_id, {})
        for prior_id in case["similar_prior_cases"]:
            connection.upsertEdge("InvestigationCase", graph_case_id, "MEMORY_SIMILAR", "ClosedCase", prior_id, {})
        case["written_to_graph"] = True
        case["graph_case_id"] = graph_case_id
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        written += 1
    print(f"Wrote {written} investigation cases to TigerGraph")


if __name__ == "__main__":
    main()