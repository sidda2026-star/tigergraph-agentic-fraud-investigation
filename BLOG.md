# Building an Autonomous Fraud Investigation Agent with TigerGraph and GraphRAG

*How we engineered an autonomous, graph-native fraud investigation system for the TigerGraph × Hacker House Goa (IEEE-CIS) Hackathon.*

---

## 1. The Challenge

Real-world fraud detection systems are plagued by alert fatigue. Typical bank machine learning models assign risk scores to hundreds of thousands of transactions daily. However, a high risk score is merely a reason to inspect—**never a final verdict**. Over 50% of alerts triggered by elevated risk scores turn out to be legitimate cardholders making routine purchases, traveling across regions, or upgrading mobile phones. Conversely, organized crime rings engineer subtle transaction sequences with low risk scores to evade legacy rule engines.

The challenge was to build an autonomous AI agent capable of investigating 20 complex exam cases, distinguishing true fraud from false alarms, enforcing strict regulatory policies (R1-R10), recommending approval-routed actions, drafting legally binding Suspicious Activity Reports (SAR), and dynamically persisting case memory.

---

## 2. Architecture & Design Principles

Our solution—**TigerGraph Fraud Sentinel**—is built around five core architectural pillars:

```
[Exam Transactions] ──► [TigerGraph Graph Layer] ──► [Deterministic Graph Tools]
                                 │                            │
                                 ▼                            ▼
                       [GraphRAG Hybrid Search]     [12-Step Agentic Loop]
                                 │                            │
                                 ▼                            ▼
                       [Policy Engine R1-R10] ───► [SAR Filing & Graph Write-Back]
```

1. **The Graph Does the Analysis, the Agent Reasons**: Raw transaction rows are never dumped directly into an LLM context. Instead, TigerGraph executes parameterized GSQL queries and graph algorithms to compute card historical baselines, device fan-out, regional mobility clusters, and ring connectivity.
2. **Dual-Assessment Loop with Evolving Recommendations**: An agent cannot jump to conclusions on weak signals. Under Policy Rule R1, if fraud probability is below 0.70 on a single signal, the agent must recommend `VERIFY_WITH_CUSTOMER` or `STEP_UP_AUTH` before any blocking action. Only after ground-truth verification is simulated does the recommendation solidify.
3. **Strict Policy Engine Guardrail**: Large language models can hallucinate actions and fabricate approval routes. We implemented the bank's Fraud Policy (Rules R1-R10) as a deterministic, pure-Python state machine that strictly validates and overrides proposed actions, ensuring 100% regulatory compliance.
4. **GraphRAG Hybrid Memory**: Because fraud notes often share templated phrases, text vector search alone is noisy. We designed a hybrid retrieval engine combining structured graph filters (same card, customer, device, region) with semantic vector similarity across 5,565 closed cases and FinCEN SAR guidance.
5. **Graph Memory Write-Back**: Investigations are processed in chronological order. Once a case is settled, it is written back into the graph as a `Case` vertex, allowing subsequent investigations to retrieve it as prior memory.

---

## 3. How TigerGraph Powers the Solution

### GSQL Schema Design
Our graph schema models the financial ecosystem with high fidelity:
- **Vertices**: `Customer`, `Card`, `Transaction`, `DeviceProfile` (DeviceInfo + OS + browser + screen), `EmailDomain`, `BillingRegion`, `ClosedCase`, `Case` (agent-written memory), and `PolicyDoc`.
- **Edges**: `OWNS`, `MADE`, `FROM_DEVICE`, `PURCHASER_EMAIL`, `RECIPIENT_EMAIL`, `BILLED_IN`, `NEXT` (card chronological link), `INVOLVES`, `ON_CARD`, `CONNECTED_TO`, and `SIMILAR_TO`.

### Parameterized GSQL Queries
We implemented seven high-performance GSQL queries:
- `card_baseline(card_id, before_ts)`: Computes historical median amount, 90th percentile, maximum transaction, known channels, known regions, and known devices prior to the alert.
- `card_window(card_id, start_ts, end_ts)`: Extracts all transactions in a ±72-hour window around the incident to capture testing authorizations and subsequent bursts.
- `device_neighbors(device_id, window_days)`: Calculates device fan-out (how many distinct cards and customer accounts share the hardware profile) and linked closed cases.
- `region_neighbors(region, window_days)`: Evaluates regional clustering and multi-party exposure.
- `email_neighbors(domain)`: Identifies recipient email sharing.
- `similar_closed_cases(card, device, region)`: Connects current entities to historical outcomes.
- `case_write(...)`: Bulk-upserts completed investigations and links them to affected entities.

### Graph Algorithm: Ring Detection via Connected Components
To uncover organized crime syndicates, we run a trailing 30-day Connected Components algorithm across the bipartite Card-DeviceProfile projection. This instantly exposed the 9 historical "undocumented" cases and unmasked exam case **HHG-014** as an active syndicate: multiple cardholders tied to a single Samsung SM-G935F Android device operating behind an anonymous proxy.

### TigerGraph MCP Integration
The agent interacts with TigerGraph using the official **TigerGraph Model Context Protocol (MCP)** standard (`tigergraph-mcp`). By exposing standard tools like `tigergraph__run_installed_query`, `tigergraph__get_neighbors`, and `tigergraph__search_top_k_similarity`, the agent autonomously selects and executes graph queries with complete context isolation.

---

## 4. Agentic Capabilities in Action

Let's examine how the agent handles different investigation archetypes:

### Case 1: Coordinated Device Ring (HHG-014)
- **Trigger**: Analyst request noting several cards showing purchases from an unusual device profile.
- **Graph Findings**: The device profile (`Samsung SM-G935F | Android 7.0 | Chrome for Android | 1920x1080`) has an anonymous proxy flag (`id_23`) and touches multiple accounts.
- **Decision**: Identified pattern as `undocumented`, applied Rules R6 and R9, recommended `BLOCK_CARD` (L1), `CREATE_CASE` (auto), `FILE_REPORT` (L2), and `MONITOR_CONNECTED_CARDS` (auto). Drafted a full 10-sentence SAR narrative citing coordinated abuse.

### Case 2: Legitimate False Alarm (HHG-001)
- **Trigger**: Risk score model flagged transaction 3514030 ($77.07, billing region 444.0) at 0.61.
- **Graph Findings**: Baseline analysis revealed billing region 444.0 was already part of the cardholder's historical home regions. The transaction was an in-person grocery purchase (Product code W).
- **Decision**: Initial action: `VERIFY_WITH_CUSTOMER` (Rule R1). Following simulated customer confirmation, the final action transitioned to `CLOSE_NO_FRAUD` (Rule R3) with $0.00 exposure and no blocks.

### Case 3: Disputed Recurring Charge (HHG-003)
- **Trigger**: Customer message claiming: *"I never made this $49.00 purchase."*
- **Graph Findings**: Historical transaction window revealed identical $49.00 charges occurring at 30-day intervals over the prior three months.
- **Decision**: Applied Policy Rule R7 (Disputed but legitimate recurring subscription). Recommended `CREATE_CASE`, `VERIFY_WITH_CUSTOMER`, and `WARN_CUSTOMER`, without blocking the card or damaging customer relations.

---

## 5. What We Learned

1. **Graph Structure Beats Raw Volume**: Trying to pass 397 columns of raw tabular data into an LLM wastes tokens and yields hallucinations. Synthesizing graph topology into a 5-point evidence brief produces faster, more accurate reasoning.
2. **Deterministic Guardrails are Mandatory in Finance**: An autonomous agent must never be allowed to invent actions or bypass approval hierarchies. Separating the reasoning agent from the policy validator guarantees regulatory compliance.
3. **Real-world Alerts are Often False**: Without contextual baseline intelligence, an over-aggressive agent would block innocent customers traveling or buying new phones. Calibration and verification loops are the hallmark of mature agentic engineering.

---

## 6. What We'd Improve

- **Real-Time Streaming GSQL Triggers**: Deploy TigerGraph Kafka connectors to ingest transaction streams in real time and trigger agent investigations asynchronously.
- **GNN-Powered Embeddings**: Train a Graph Neural Network (such as Graph Convolutional Networks or GraphSAGE) directly inside TigerGraph to generate topological node embeddings for fraud ring classification.
- **Multi-Agent Deliberation**: Introduce an adversarial "defense agent" that advocates for customer legitimacy to stress-test the lead investigator before any blocking action.
