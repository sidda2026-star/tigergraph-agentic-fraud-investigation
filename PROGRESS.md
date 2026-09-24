# Progress

## Current status

- Phase 1 complete: DuckDB trimmed extract built from the supplied data.
- Phase 2 complete locally: TigerGraph schema, loading job, queries, and graph-input builder exist.
- Phase 3 in progress: deterministic evidence gathering and pure Fraud Policy engine.
- Live TigerGraph and LLM calls are blocked until `.env` contains credentials. The MVP has an offline deterministic fallback so output generation can proceed without guessing secrets or outcomes.

## Assumptions and fallbacks

- Card IDs are reconciled from case/history first-transaction joins, then remaining card1 values receive deterministic customer `-K<n>` IDs.
- Evidence uses only the supplied files. No external IEEE-CIS/Kaggle outcomes are used.
- When no LLM key is available, the fallback produces conservative calibrated assessments and labels its evidence as deterministic graph/data evidence.

## Next

The validator, case runner, graph write-back adapter, MCP configuration, dashboard, and documentation are complete. The five least-confident cases are HHG-013 and HHG-015 (new-device signals remain uncertain at 0.74), HHG-017 (low-information risk alert at 0.26), HHG-001 (shared-origin evidence was weak and resolved legitimate), and HHG-002 (high model score resolved legitimate after verification).

Live TigerGraph write-back is blocked until `.env` contains `TIGERGRAPH_HOST`, `TIGERGRAPH_GRAPH`, `TIGERGRAPH_USERNAME`, and `TIGERGRAPH_PASSWORD` or an API token. No credentials were guessed or printed.

Offline graph memory fallback completed: 20 `InvestigationCase` vertices, 36 transaction links, 598 connected-card links, and 52 similar-case links were materialized in `data/local_graph_memory.json`. The JSON cases now carry local graph IDs; remote TigerGraph remains gated by credentials.
