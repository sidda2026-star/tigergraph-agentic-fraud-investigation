from __future__ import annotations

import json
from pathlib import Path

import streamlit as st


ROOT = Path(__file__).resolve().parent
st.set_page_config(page_title="Fraud Investigation", layout="wide")
st.title("Fraud Investigation Console")
files = sorted((ROOT / "cases").glob("HHG-*.json"))
if not files:
    st.warning("Run scripts/run_cases.py first.")
    st.stop()
records = [json.loads(path.read_text(encoding="utf-8")) for path in files]
labels = [f"{x['case_id']} · {x['case']['verdict']} · p={x['case']['fraud_probability']:.2f}" for x in records]
selected = st.selectbox("Case", range(len(records)), format_func=lambda index: labels[index])
record = records[selected]
case = record["case"]
col1, col2, col3, col4 = st.columns(4)
col1.metric("Verdict", case["verdict"])
col2.metric("Fraud probability", f"{case['fraud_probability']:.2f}")
col3.metric("Pattern", case["pattern"])
col4.metric("Exposure", f"${case['exposure_usd']:,.2f}")
st.subheader("Summary")
st.write(case["summary"])
left, right = st.columns(2)
with left:
    st.subheader("Evidence")
    for item in case["evidence"]:
        st.write(f"**{item['source']} · {item['ref']}**: {item['claim']}")
    st.subheader("Similar prior cases")
    st.write(", ".join(case["similar_prior_cases"]) or "None")
with right:
    st.subheader("Actions")
    st.write("Initial")
    st.json(record["next_best_actions"]["initial"])
    st.write("Final")
    st.json(record["next_best_actions"]["final"])
    st.caption(record["next_best_actions"]["what_changed"])
st.subheader("SAR")
st.json(record["sar"])
st.caption(f"tool_calls={record['tool_calls']} · tokens={record['tokens']} · latency_s={record['latency_s']}")