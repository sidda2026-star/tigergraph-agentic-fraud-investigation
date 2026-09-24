# Demo Video Script: TigerGraph Agentic Fraud Investigation (HHGOA_IEEE)

**Target Duration**: 3:30 – 4:30 Minutes  
**Presenter**: Senior AI Engineer / Team Lead  
**Application**: Streamlit Dashboard (`streamlit run dashboard.py`)

---

## 🎬 Shot List & Narrative Flow

### [0:00 – 0:40] Introduction & Architecture
- **Visual**: Streamlit Header and Architecture Mermaid Diagram in README.
- **Narrator**:
  > *"Welcome to our submission for the TigerGraph Agentic Fraud Investigation Hackathon. We built an autonomous, graph-native fraud investigator powered by TigerGraph, GSQL, the TigerGraph Model Context Protocol (MCP), and a policy engine enforcing strict R1-R10 rules.
  > Instead of dumping raw CSV rows into an LLM, our agent uses TigerGraph to analyze entity neighborhoods, historical baselines, and connected components for ring detection. Today we'll demonstrate three distinct real-world cases."*

---

### [0:41 – 1:35] Case 1: Coordinated Device Ring (HHG-014)
- **Visual**: Select `HHG-014` from the dropdown in the UI. Switch to the **Interactive Graph Neighborhood** tab and the **SAR Regulatory Filing** tab.
- **Key Focus**:
  - Show the trigger: Analyst request regarding an unusual shared device.
  - Show the graph neighborhood: Card `C13487-K1` connected to the `Samsung SM-G935F | Android 7.0 | Chrome` hardware profile behind an anonymous proxy.
  - Show the Connected Components algorithm result unmasking the multi-card ring.
  - Show the policy outcome: Pattern identified as `undocumented`, triggering Rule R6 & R9.
  - Highlight the Approval Routes: `BLOCK_CARD` (L1), `CREATE_CASE` (auto), `FILE_REPORT` (L2), `MONITOR_CONNECTED_CARDS` (auto).
  - Show the generated 10-sentence SAR narrative.
- **Narrator**:
  > *"In Case HHG-014, an analyst flagged potential shared device activity. Our agent queried TigerGraph's device neighbors and executed a connected components algorithm. It discovered a coordinated fraud ring using Samsung hardware behind an anonymous proxy across multiple cardholders.
  > Rather than forcing this into a standard category, the agent recognized the undocumented ring under Policy R9, opened an internal case, queued a Suspicious Activity Report for Level 2 fraud manager approval, and placed all connected cards under monitoring."*

---

### [1:36 – 2:30] Case 2: Legitimate False Alarm Cleared (HHG-001)
- **Visual**: Select `HHG-001` from the dropdown. Toggle between **Agent Timeline** and **Evidence Brief**.
- **Key Focus**:
  - Show the trigger: Risk score 0.61 on transaction 3514030 ($77.07, billing region 444.0).
  - Show the evidence table: Historical baseline indicates region 444.0 was already a home region.
  - Show the Dual-Assessment progression:
    - Initial recommendation: `VERIFY_WITH_CUSTOMER` under Policy R1 (weak signal with probability < 0.70).
    - Simulated customer reply: Cardholder confirms the in-person grocery purchase.
    - Final recommendation: `CLOSE_NO_FRAUD` under Policy R3, $0.00 exposure, no cards blocked.
- **Narrator**:
  > *"In Case HHG-001, the bank's machine learning model flagged an in-person charge at 0.61 risk score due to an apparent region anomaly.
  > Our agent inspected the card baseline and found region 444.0 was already an established home billing region. Under Policy Rule R1, because this was a single weak signal with probability below 0.70, the agent refused to block the customer. It initiated customer verification, received confirmation, and cleared the alert with CLOSE_NO_FRAUD. An over-aggressive agent would have blocked an innocent customer."*

---

### [2:31 – 3:30] Case 3: Evolving Recommendation & Human Approval (HHG-002)
- **Visual**: Select `HHG-002`. Show the **Next Best Actions & Routing** tab with interactive Approve/Reject buttons.
- **Key Focus**:
  - Show initial action: `VERIFY_WITH_CUSTOMER` (auto).
  - Show simulated cardholder response: Denial of unrecognized $292.36 online charge.
  - Show recommendation evolution: `BLOCK_CARD` (L1) and `CREATE_CASE` (auto).
  - Click the **Approve BLOCK_CARD** button in the UI, demonstrating the interactive human-in-the-loop governance gate.
  - Show the **Graph Memory** tab confirming the case was written back to the graph so subsequent investigations can retrieve it.
- **Narrator**:
  > *"Finally, Case HHG-002 shows dynamic recommendation evolution. The initial risk score alert proposed verification before blocking. When the cardholder confirmed denial, the agent updated the probability to 88%, escalated to BLOCK_CARD, and queued the action for Level 1 team lead approval.
  > With our interactive console, human investigators can review the evidence brief, audit the route, and click Approve to execute. The case is then written back into TigerGraph's case memory, completing the virtuous feedback loop."*

---

### [3:31 – 4:00] Conclusion & Technical Wrap-up
- **Visual**: Show the terminal running `python scripts/validate_answers.py` with 20/20 PASS status.
- **Narrator**:
  > *"Every single one of the 20 answer files has been verified with 100% compliance against the hackathon rubric. TigerGraph Fraud Sentinel proves that combining graph algorithms, GraphRAG memory, and policy-guarded agentic execution delivers the highest standard of fraud investigation accuracy. Thank you."*
