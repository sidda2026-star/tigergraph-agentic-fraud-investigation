# Building a Graph-Backed Fraud Investigation Agent Under Time Pressure

## What we built

This MVP investigates the 20 supplied alerts and produces the exact case, SAR, and next-best-action JSON contract. It gathers transaction evidence with DuckDB, applies a pure Fraud Policy engine, simulates evidence requests, retrieves closed-case memory, and presents results in Streamlit.

## Architecture

The deterministic layer owns data access, graph query contracts, policy rules, validation, exposure arithmetic, and approval routes. A reasoning layer may write probability estimates, pattern explanations, summaries, and SAR prose, but it cannot create an action identifier or route. The offline fallback keeps the system runnable when credentials or an LLM key are unavailable.

## How TigerGraph is used

Customers, cards, transactions, devices, regions, email domains, closed cases, and investigation cases form the graph. Directed edges support card windows, device neighbours, region neighbours, prior cases, and case memory. The MCP configuration exposes those queries to an agent, while closed analyst notes and policy text are intended for vector retrieval.

## Agentic capabilities

The workflow opens a case, gathers multiple evidence types, compares historical investigations, decides whether more evidence is valuable, simulates a response that follows the evidence, recalculates actions, and writes case memory. The validator is a guardrail: every output ID must come from the supplied dataset and every final SAR flag must agree with `FILE_REPORT`.

## What we learned

Risk scores are useful triggers but poor verdicts. Shared devices and regions become meaningful only in a time window and with independent evidence; otherwise legitimate travel and new phones look like fraud. Policy enforcement belongs outside the language model.

## What to improve

The next iteration should connect a real TigerGraph workspace, install the TigerGraph MCP server, add vector embeddings over analyst notes and policy sections, and use a provider-backed LLM only for calibrated reasoning and prose. It should also add richer merchant features, real analyst/customer responses, and replayable graph query traces.
