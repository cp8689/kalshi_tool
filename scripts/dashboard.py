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
st.caption("Predicted P(word in next speech) vs Kalshi market prices. Model uses week-by-week probability for the past 4 weeks and the last 3 days of news to predict the current week.")

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
    # Use only columns we need; normalize names and fill NaN so data always displays
    required = ["word", "market_probability", "model_probability", "edge"]
    edges_df = edges_df.rename(columns=lambda c: c.strip() if isinstance(c, str) else c)
    missing = [c for c in required if c not in edges_df.columns]
    if missing:
        st.warning(f"Edges file missing columns: {missing}. Re-run pipeline.")
    else:
        edges_clean = edges_df[required].copy()
        edges_clean["market_probability"] = pd.to_numeric(edges_clean["market_probability"], errors="coerce").fillna(0)
        edges_clean["model_probability"] = pd.to_numeric(edges_clean["model_probability"], errors="coerce").fillna(0)
        edges_clean["edge"] = pd.to_numeric(edges_clean["edge"], errors="coerce").fillna(0)
        if "flagged" in edges_df.columns:
            edges_clean["flagged"] = edges_df["flagged"].reindex(edges_clean.index).fillna(False)
        edges_sorted = edges_clean.sort_values("edge", ascending=False).head(20)
        # edge_pct = edge as percentage points (model − market)
        edge_pct_pct = (edges_sorted["edge"] * 100).round(1)
        display_df = pd.DataFrame({
            "word": edges_sorted["word"].values,
            "market_probability": edges_sorted["market_probability"].round(4).values,
            "model_probability": edges_sorted["model_probability"].round(4).values,
            "edge": edges_sorted["edge"].round(4).values,
            "edge_pct": [f"{x:+.1f}%" for x in edge_pct_pct.values],
        })
        st.dataframe(display_df, use_container_width=True, hide_index=True)
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
    chart_probs = prob_df[["word", "model_probability"]].copy()
    chart_probs["model_probability"] = pd.to_numeric(chart_probs["model_probability"], errors="coerce").fillna(0)
    chart_df = chart_probs.sort_values("model_probability", ascending=False)
    st.caption("Model P(word in next speech) from pipeline — same scale as the model_probability column in the table above.")
    st.bar_chart(chart_df.set_index("word"))
else:
    st.warning("No word probabilities yet. Add transcripts and run the pipeline.")

# Week-by-week frequency (past 4 weeks)
st.header("Week-by-week frequency (past 4 weeks)")
week_labels = ["Week 1 (most recent)", "Week 2", "Week 3", "Week 4"]
use_counts = not prob_df.empty and all(c in prob_df.columns for c in ["word", "week1_count", "week2_count", "week3_count", "week4_count"])
use_probs = not prob_df.empty and all(c in prob_df.columns for c in ["word", "week1", "week2", "week3", "week4"])
if use_counts:
    week_cols = ["week1_count", "week2_count", "week3_count", "week4_count"]
    week_table = prob_df[["word"] + week_cols].copy()
    week_table.columns = ["word"] + week_labels
    for c in week_labels:
        week_table[c] = pd.to_numeric(week_table[c], errors="coerce").fillna(0).astype(int)
    st.caption("Number of speeches containing the word in each week. Current week prediction (Top edges) is adjusted by the last 3 days of news.")
    st.dataframe(week_table, use_container_width=True, hide_index=True)
    trend = prob_df[["word"] + week_cols].set_index("word")
    trend.columns = week_labels
    st.line_chart(trend)
    # Top 10 most used words (past 4 weeks)
    count_df = prob_df[["word"] + week_cols].copy()
    for c in week_cols:
        count_df[c] = pd.to_numeric(count_df[c], errors="coerce").fillna(0).astype(int)
    count_df["total"] = count_df[week_cols].sum(axis=1)
    top10 = count_df.nlargest(10, "total")[["word"] + week_cols].copy()
    top10.columns = ["word"] + week_labels
    st.subheader("Top 10 most used words (past 4 weeks)")
    st.caption("Words that appeared in the most speeches across the past 4 weeks, with count per week.")
    st.dataframe(top10, use_container_width=True, hide_index=True)
elif use_probs:
    week_cols = ["week1", "week2", "week3", "week4"]
    week_table = prob_df[["word"] + week_cols].copy()
    week_table.columns = ["word"] + week_labels
    for c in week_labels:
        week_table[c] = pd.to_numeric(week_table[c], errors="coerce").fillna(0).round(4)
    st.caption("P(word | week) from transcripts (run pipeline to get frequency counts).")
    st.dataframe(week_table, use_container_width=True, hide_index=True)
    trend = prob_df[["word"] + week_cols].set_index("word")
    trend.columns = week_labels
    st.line_chart(trend)
else:
    st.warning("Weekly columns missing. Run the pipeline to generate word_probabilities.csv.")
