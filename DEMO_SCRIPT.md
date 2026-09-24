# Demo Script: 3-5 Minutes

1. Show `data/README.md` briefly and state the separation of responsibilities: DuckDB gathers evidence, the policy engine controls actions, and the graph stores reusable case memory.
2. Run `python scripts/run_cases.py` and show the mixed output: legitimate, uncertain, and fraud cases rather than treating risk score as the verdict.
3. Open `HHG-014.json`. Explain the analyst-request trigger, shared-origin investigation, undocumented pattern description, prior-case retrieval, and R9 actions.
4. Open a customer-report case such as `HHG-003.json`. Show the simulated customer denial, initial versus final actions, approval routes, and SAR narrative.
5. Run `python scripts/validate_outputs.py`, then launch `streamlit run dashboard.py`. Select a legitimate case and a fraud case to show evidence, uncertainty, actions, SAR state, and similar prior cases.
6. If TigerGraph credentials are available, run the loader and write-back commands and show the `InvestigationCase` vertex plus its transaction/card/prior-case edges.
