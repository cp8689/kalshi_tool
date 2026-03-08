"""
Streamlit dashboard: top edges, word probability distributions, weekly trends.
Reads from output/word_probabilities.csv and output/kalshi_edges.csv.
Run: streamlit run scripts/dashboard.py (from project root)
"""
from __future__ import annotations

import os
import sys

import pandas as pd
import streamlit as st

# Project root = parent of scripts/
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SCRIPT_DIR)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

PROB_PATH = os.path.join(PROJECT_ROOT, "output", "word_probabilities.csv")
EDGES_PATH = os.path.join(PROJECT_ROOT, "output", "kalshi_edges.csv")

st.set_page_config(page_title="Speech Word Market Model", layout="wide")
st.title("Speech Word Market Model")
st.caption("Predicted P(word in next speech) vs Kalshi market prices")

# Load data
@st.cache_data
def load_data():
    prob = pd.DataFrame()
    edges = pd.DataFrame()
    if os.path.isfile(PROB_PATH):
        prob = pd.read_csv(PROB_PATH)
    if os.path.isfile(EDGES_PATH):
        edges = pd.read_csv(EDGES_PATH)
    return prob, edges

prob_df, edges_df = load_data()

if edges_df.empty and prob_df.empty:
    st.info("Run the pipeline first: `python main.py` from the project root. Then refresh this page.")
    st.stop()

# Top edges
st.header("Top edges (model prob − market prob)")
if not edges_df.empty:
    edges_sorted = edges_df.sort_values("edge", ascending=False)
    edges_sorted["edge_pct"] = (edges_sorted["edge"] * 100).round(1).astype(str) + "%"
    st.dataframe(
        edges_sorted[["word", "market_probability", "model_probability", "edge", "edge_pct"]].head(20),
        use_container_width=True,
        hide_index=True,
    )
    if "flagged" in edges_sorted.columns:
        flagged = edges_sorted[edges_sorted["flagged"]]
        if not flagged.empty:
            st.subheader("Flagged opportunities (edge > 10%)")
            st.dataframe(flagged[["word", "market_probability", "model_probability", "edge"]], use_container_width=True, hide_index=True)
else:
    st.warning("No Kalshi edges data. Add market data under data/markets/ and run the pipeline.")

# Word probability distribution
st.header("Word probability distribution")
if not prob_df.empty and "model_probability" in prob_df.columns:
    chart_df = prob_df[["word", "model_probability"]].dropna().sort_values("model_probability", ascending=False)
    st.bar_chart(chart_df.set_index("word"))
else:
    st.warning("No word probabilities yet. Add transcripts and run the pipeline.")

# Weekly trends
st.header("Weekly trends (P(word | week))")
if not prob_df.empty and all(c in prob_df.columns for c in ["word", "week1", "week2", "week3", "week4"]):
    week_cols = ["week1", "week2", "week3", "week4"]
    trend = prob_df[["word"] + week_cols].set_index("word")
    trend.columns = ["Week 1 (recent)", "Week 2", "Week 3", "Week 4"]
    st.line_chart(trend)
else:
    st.warning("Weekly columns missing. Run the pipeline to generate word_probabilities.csv.")
