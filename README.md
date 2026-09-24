# TigerGraph Fraud Investigation MVP

This repository implements the Hacker House Goa fraud-investigation task from the supplied `data/README.md`. It uses DuckDB for the 708 MB transaction CSV, TigerGraph for graph evidence and case memory, a pure Python policy engine for R1-R10, and a small Streamlit console.

## Quick start

```powershell
python -m pip install -r requirements.txt
python scripts/build_trimmed_transactions.py
python scripts/build_graph_inputs.py
$env:PYTHONPATH = "."
python scripts/run_cases.py
python scripts/validate_outputs.py
streamlit run dashboard.py
```

The batch runner is usable without credentials. It uses deterministic DuckDB evidence and conservative simulated evidence requests. `tokens=0` is intentional when no LLM provider is configured. No external IEEE-CIS or Kaggle outcomes are used.

## TigerGraph

Copy `.env.example` to `.env` and set `TIGERGRAPH_HOST`, `TIGERGRAPH_GRAPH`, `TIGERGRAPH_USERNAME`, and `TIGERGRAPH_PASSWORD` (or the optional API token). Run `scripts/load_tigergraph.py` after graph inputs are built. The GSQL files are in `tigergraph/`: `schema.gsql`, `loading.gsql`, and `queries.gsql`. The write-back command is:

```powershell
python scripts/write_cases_to_graph.py
```

It upserts `InvestigationCase` vertices and links them to transactions, connected cards, and prior closed cases. It updates `written_to_graph` only after a successful upsert. The MCP wiring example is `mcp_config.example.json`; install the TigerGraph MCP server from the linked repository and expose the four graph queries listed there.

Without TigerGraph credentials, use `python scripts/write_cases_to_graph.py --local` to materialize the same case-memory vertices and edges in `data/local_graph_memory.json`. This is an offline fallback, not a substitute for the remote TigerGraph graph.

## Architecture

1. `scripts/build_trimmed_transactions.py` filters the source CSV in DuckDB by customers present in the case pack or closed history and writes Parquet.
2. `scripts/build_graph_inputs.py` creates stable graph CSVs and reconciles customer card IDs from supplied case/history joins.
3. `fraud_app/investigator.py` gathers card-window, device, region, and closed-case evidence without loading the large CSV into memory.
4. `fraud_app/policy.py` owns action identifiers, approval routes, R1-R10, case/SAR conditions, and block thresholds. The LLM cannot invent actions.
5. `scripts/run_cases.py` writes the exact answer format to `cases/HHG-001.json` through `HHG-020.json`; `scripts/validate_outputs.py` checks fields, types, IDs, exposure, actions, routes, and SAR consistency.

The current fallback keeps reasoning deterministic until an LLM adapter and TigerGraph credentials are configured. This is deliberate for a reliable hackathon MVP.
