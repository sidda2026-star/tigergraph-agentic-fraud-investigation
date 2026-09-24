# ASSUMPTIONS.md - Hackathon Submission Assumptions & Design Decisions

This document records all engineering assumptions made during the implementation of the TigerGraph Agentic Fraud Investigation platform (HHGOA_IEEE).

## 1. Graph Storage & Execution
- **TigerGraph vs Local GraphStore Fallback**: When TigerGraph Cloud (Savanna) credentials or local Docker instances are configured in `.env`, the system executes queries directly against TigerGraph via REST/pyTigerGraph/GSQL and TigerGraph MCP. If credentials are empty or remote instance is unreachable, the system automatically falls back to an in-memory/DuckDB/NetworkX `LocalGraphStore` implementing the exact identical `GraphStore` interface and community detection algorithms.
- **`written_to_graph` Semantics**: Per policy requirements, `case.written_to_graph` is set to `true` ONLY if the upsert to TigerGraph actually succeeded. In local fallback mode, `written_to_graph` is set to `false`, and local case memory is preserved in `data/local_graph_memory.json`.

## 2. Customer & Evidence Responses
- Customer validation and step-up auth responses are not provided interactively in batch test runs. Per Section 5 of the Fraud Policy, simulated evidence responses are deterministic and grounded in case evidence:
  - Disputed recurring subscriptions (R7) assume customer acknowledgment after clarification.
  - Transactions matching high-frequency fraudulent devices/proxies with bursts and no legitimate home history assume customer denial.
  - Isolated out-of-region clusters where normal home region stops for days (travel signature) assume customer confirmation.
  - All assumptions are explicitly recorded in `evidence_requests[].assumed_response`.

## 3. Approval Routing & Policy Enforcement (R1-R10)
- `auto` actions (`CREATE_CASE`, `VERIFY_WITH_CUSTOMER`, `STEP_UP_AUTH`, `MONITOR_CARD`, `MONITOR_CONNECTED_CARDS`, `WARN_CUSTOMER`, `CLOSE_NO_FRAUD`, `ESCALATE_TO_ANALYST`) can be executed automatically.
- `L1` actions (`DECLINE_TRANSACTION`, `BLOCK_CARD` when exposure <= $2,500) require team lead approval.
- `L2` actions (`BLOCK_CARD` when exposure > $2,500, `BLOCK_ALL_CARDS`, `FILE_REPORT`) require fraud manager approval.
- Order of operations: Emergency containment (`DECLINE_TRANSACTION`, `BLOCK_CARD`) comes first, followed by case creation (`CREATE_CASE`), regulatory filing (`FILE_REPORT`), and secondary monitoring (`MONITOR_CONNECTED_CARDS`).

## 4. SAR Filing Consistency
- A Suspicious Activity Report (`sar.file = true`) is generated if and only if `FILE_REPORT` is present in `next_best_actions.final`.
- Legitimate cases (`verdict = "legitimate"`) have `affected_txn_ids = []`, `exposure_usd = 0.0`, `sar.file = false`, `sar.narrative = ""`, `sar.subjects = []`, and `sar.activity_dates = []`.
- When `pattern == "undocumented"`, `pattern_description` contains a 2-3 sentence narrative describing the coordinated abuse pattern.

## 5. Token Usage & Latency Instrumentations
- Graph retrieval tool calls are counted in `tool_calls`.
- Reasoning iterations, prompt tokens, and completion tokens are tracked in `tokens`.
- Execution wall-clock time is captured in `latency_s`.
