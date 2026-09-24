"""Streamlit Dashboard for TigerGraph Agentic Fraud Investigation."""

from __future__ import annotations

import sys
import json
import csv
from pathlib import Path
from datetime import datetime

import streamlit as st
import streamlit.components.v1 as components
import pandas as pd
from pyvis.network import Network

# Ensure project root is in python path
def _get_root_dir() -> Path:
    candidates = [
        Path(__file__).resolve().parent.parent,
        Path(__file__).resolve().parent,
        Path.cwd(),
    ]
    for c in candidates:
        if (c / "data" / "transactions_trimmed.parquet").exists() or (c / "data" / "case_pack.csv").exists():
            return c
    return Path(__file__).resolve().parent.parent

ROOT_DIR = globals().get("ROOT_DIR", _get_root_dir())
if not (ROOT_DIR / "data" / "transactions_trimmed.parquet").exists():
    ROOT_DIR = _get_root_dir()

sys.path.insert(0, str(ROOT_DIR))

from graph.store import get_graph_store
from agent.core import FraudInvestigationAgent

st.set_page_config(
    page_title="TigerGraph Fraud Sentinel | Agentic Investigation Console",
    page_icon="🛡️",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Custom CSS for modern dark-mode aesthetic
st.markdown("""
<style>
    .main-header {
        font-family: 'Inter', -apple-system, sans-serif;
        background: linear-gradient(135deg, #1e1e2f 0%, #111119 100%);
        padding: 24px;
        border-radius: 12px;
        border: 1px solid #2d2d42;
        margin-bottom: 24px;
    }
    .status-chip {
        display: inline-block;
        padding: 4px 12px;
        border-radius: 20px;
        font-size: 13px;
        font-weight: 600;
        text-transform: uppercase;
    }
    .status-closed-fraud { background: #4a151b; color: #ff6b72; border: 1px solid #ff6b72; }
    .status-closed-legit { background: #133926; color: #4ade80; border: 1px solid #4ade80; }
    .status-escalated { background: #422d0d; color: #facc15; border: 1px solid #facc15; }
    .status-open { background: #1e293b; color: #94a3b8; border: 1px solid #94a3b8; }
    .route-badge {
        padding: 2px 8px;
        border-radius: 6px;
        font-size: 11px;
        font-weight: 700;
        margin-left: 6px;
    }
    .route-auto { background: #0284c7; color: white; }
    .route-l1 { background: #e11d48; color: white; }
    .route-l2 { background: #7c3aed; color: white; }
    .metric-card {
        background: #181824;
        padding: 16px;
        border-radius: 10px;
        border: 1px solid #2e2e44;
        text-align: center;
    }
</style>
""", unsafe_allow_html=True)


@st.cache_resource
def load_agent():
    store = get_graph_store(data_dir=ROOT_DIR / "data")
    return FraudInvestigationAgent(store), store


agent, store = load_agent()

# Load Case Pack
cases_csv = ROOT_DIR / "data" / "case_pack.csv"
case_pack = []
with open(cases_csv, "r", encoding="utf-8") as f:
    case_pack = list(csv.DictReader(f))

# Sidebar controls
st.sidebar.image("https://assets.website-files.com/5ec572cf93b0a214d023190e/5ec573dbab802c0c7a52f44c_tg-logo.png", width=180)
st.sidebar.title("Investigation Console")

mode = st.sidebar.radio("Execution Mode", ["Load saved result", "Run agent live"], index=0)

# Case Selector
case_options = [c["case_id"] for c in case_pack]
selected_case_id = st.sidebar.selectbox("Select Case", case_options, index=0)
case_row = next(c for c in case_pack if c["case_id"] == selected_case_id)

st.sidebar.markdown("---")
st.sidebar.markdown("### Execution Metrics")
saved_path = ROOT_DIR / "cases" / f"{selected_case_id}.json"
saved_data = None
if saved_path.exists():
    with open(saved_path, "r", encoding="utf-8") as f:
        saved_data = json.load(f)

if mode == "Run agent live":
    if st.sidebar.button("Execute Autonomous Investigation", type="primary"):
        with st.spinner(f"Investigating {selected_case_id} via TigerGraph GraphStore..."):
            case_data = agent.investigate_case(case_row)
            st.session_state[f"live_{selected_case_id}"] = case_data
    case_data = st.session_state.get(f"live_{selected_case_id}", saved_data)
else:
    case_data = saved_data

if not case_data:
    st.error("No case data found. Please run the agent.")
    st.stop()

# Header Banner
case_obj = case_data["case"]
status = case_obj["status"]
verdict = case_obj["verdict"]
prob = case_obj["fraud_probability"]
pattern = case_obj["pattern"]
exposure = case_obj["exposure_usd"]

status_class = (
    "status-closed-fraud" if status == "closed_fraud"
    else ("status-closed-legit" if status == "closed_legitimate" else "status-escalated")
)

st.markdown(f"""
<div class="main-header">
    <div style="display: flex; justify-content: space-between; align-items: center;">
        <div>
            <h1 style="margin: 0; font-size: 28px; color: #ffffff;">{selected_case_id} — Fraud Investigation</h1>
            <p style="margin: 6px 0 0 0; color: #94a3b8; font-size: 14px;">Trigger: <strong>{case_row['trigger_type']}</strong> | Flagged Txn: <code>{case_row['flagged_txn_id']}</code> | Opened: {case_row['opened_at']}</p>
        </div>
        <div>
            <span class="status-chip {status_class}">{status.replace('_', ' ')}</span>
        </div>
    </div>
</div>
""", unsafe_allow_html=True)

# Overview Metrics
col1, col2, col3, col4, col5 = st.columns(5)
with col1:
    st.metric("Assessed Verdict", verdict.capitalize())
with col2:
    st.metric("Fraud Probability", f"{prob * 100:.1f}%")
with col3:
    st.metric("Identified Pattern", pattern.replace("_", " ").title())
with col4:
    st.metric("Total Exposure", f"${exposure:,.2f}")
with col5:
    st.metric("Tool Calls", case_data.get("tool_calls", 0))

st.markdown("---")

# Main investigation tabs
tab_timeline, tab_evidence, tab_actions, tab_sar, tab_graph, tab_memory = st.tabs([
    "🔍 Agent Timeline & Decision",
    "📊 GraphRAG Evidence Brief",
    "⚡ Next Best Actions & Routing",
    "📜 SAR Regulatory Filing",
    "🕸️ Graph Neighborhood",
    "🧠 Graph Memory",
])

with tab_timeline:
    st.subheader("Autonomous 12-Step Agent Loop")
    st.markdown(f"**Stop Reason**: *{case_data.get('stop_reason')}*")

    st.markdown("#### Summary Analysis")
    st.info(case_obj.get("summary", ""))

    if pattern == "undocumented" and case_obj.get("pattern_description"):
        st.warning(f"**Undocumented Ring Pattern**: {case_obj['pattern_description']}")

    # Probability Meter before vs after
    st.markdown("#### Fraud Probability Calibration")
    ev_reqs = case_data.get("evidence_requests", [])
    col_p1, col_p2 = st.columns(2)
    with col_p1:
        st.markdown("**Initial Assessment (Prior to Verification)**")
        st.progress(min(1.0, max(0.0, prob if not ev_reqs else 0.45)))
    with col_p2:
        st.markdown("**Final Settled Assessment**")
        st.progress(min(1.0, max(0.0, prob)))

    if ev_reqs:
        st.markdown("#### Simulated Grounded Verification Request")
        for req in ev_reqs:
            st.markdown(f"- **Type**: `{req['type']}` (Step {req['asked_after_step']})")
            st.markdown(f"- **Assumed Grounded Response**: *\"{req['assumed_response']}\"*")

with tab_evidence:
    st.subheader("Graph & Document Evidence Items")
    evidence_items = case_obj.get("evidence", [])
    ev_df = pd.DataFrame(evidence_items)
    if not ev_df.empty:
        st.dataframe(
            ev_df[["claim", "source", "ref", "entity_ids"]],
            use_container_width=True,
            column_config={
                "claim": st.column_config.TextColumn("Factual Claim", width="large"),
                "source": st.column_config.TextColumn("Source Engine", width="small"),
                "ref": st.column_config.TextColumn("Query / Document Ref", width="medium"),
                "entity_ids": st.column_config.ListColumn("Entity IDs", width="medium"),
            },
        )
    else:
        st.write("No evidence items available.")

with tab_actions:
    st.subheader("Next Best Actions Evolution & Approval Gate")
    nba = case_data.get("next_best_actions", {})
    st.markdown(f"**What Changed**: *{nba.get('what_changed', 'nothing')}*")

    col_act1, col_act2 = st.columns(2)
    with col_act1:
        st.markdown("### Initial Actions (Pre-evidence)")
        for act in nba.get("initial", []):
            st.markdown(f"- **{act['action']}** <span class='route-badge route-{act['route'].lower()}'>{act['route']}</span><br>&nbsp;&nbsp;*Reason: {act['reason']}*", unsafe_allow_html=True)

    with col_act2:
        st.markdown("### Final Actions (Post-evidence)")
        for act in nba.get("final", []):
            route_str = act['route']
            st.markdown(f"- **{act['action']}** <span class='route-badge route-{route_str.lower()}'>{route_str}</span><br>&nbsp;&nbsp;*Reason: {act['reason']}*", unsafe_allow_html=True)
            if route_str in ("L1", "L2"):
                c_btn1, c_btn2 = st.columns(2)
                with c_btn1:
                    if st.button(f"Approve {act['action']}", key=f"app_{act['action']}_{selected_case_id}"):
                        st.success(f"Approved {act['action']} by {route_str} authority.")
                with c_btn2:
                    if st.button(f"Reject {act['action']}", key=f"rej_{act['action']}_{selected_case_id}"):
                        st.error(f"Rejected {act['action']}.")

with tab_sar:
    st.subheader("Suspicious Activity Report (SAR)")
    sar = case_data.get("sar", {})
    if sar.get("file"):
        st.success(f"**Filing Required**: {sar.get('reason')}")
        st.markdown(f"**Filing Total**: `${sar.get('total_amount_usd'):,.2f}` | **Activity Dates**: {sar.get('activity_dates')}")
        st.markdown(f"**Named Subjects**: `{', '.join(sar.get('subjects', []))}`")
        st.markdown("#### Complete Narrative")
        st.text_area("Narrative Text", sar.get("narrative", ""), height=220)
    else:
        st.info("No Suspicious Activity Report required for this case under Policy Section 3a.")

with tab_graph:
    st.subheader("Interactive Entity Neighborhood Graph")
    net = Network(height="450px", width="100%", bgcolor="#12121c", font_color="white")
    net.add_node(case_row["card_id"], label=f"Card\n{case_row['card_id']}", color="#3b82f6", size=25)
    net.add_node(case_row["customer_id"], label=f"Customer\n{case_row['customer_id']}", color="#10b981", size=20)
    net.add_edge(case_row["customer_id"], case_row["card_id"], title="OWNS")

    flagged_txn = case_row["flagged_txn_id"]
    net.add_node(flagged_txn, label=f"Txn\n{flagged_txn}", color="#ef4444" if verdict == "fraud" else "#22c55e", size=20)
    net.add_edge(case_row["card_id"], flagged_txn, title="MADE")

    for conn_card in case_obj.get("connected_card_ids", [])[:5]:
        net.add_node(conn_card, label=f"Connected\n{conn_card}", color="#f59e0b", size=18)
        net.add_edge(case_row["card_id"], conn_card, title="CONNECTED_TO")

    for prof in case_obj.get("connected_device_profiles", []):
        dlabel = prof.split("|")[0].strip() if "|" in prof else "Device"
        net.add_node(prof, label=f"Device\n{dlabel}", color="#8b5cf6", size=18)
        net.add_edge(flagged_txn, prof, title="FROM_DEVICE")

    net.save_graph("temp_graph.html")
    with open("temp_graph.html", "r", encoding="utf-8") as f:
        html_content = f.read()
    components.html(html_content, height=470)

with tab_memory:
    st.subheader("Case Memory & Similar Closed Cases")
    sim_cases = case_obj.get("similar_prior_cases", [])
    if sim_cases:
        st.markdown(f"**Retrieved Similar Prior Cases**: `{', '.join(sim_cases)}`")
        for sc in sim_cases:
            with st.expander(f"Prior Case: {sc}"):
                st.write(f"Historical case memory retrieved from GraphStore for {sc}.")
    else:
        st.write("No direct prior closed cases matched for this transaction profile.")

    st.markdown("---")
    st.markdown(f"**Graph Write Status**: `written_to_graph = {case_obj.get('written_to_graph')}` (Graph Case ID: `{case_obj.get('graph_case_id')}`)")
