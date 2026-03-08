"""
Edge = model_probability - market_probability. Flag when edge > threshold.
"""
import pandas as pd


def compute_edges(
    model_probabilities: pd.DataFrame,
    market_df: pd.DataFrame,
    edge_threshold: float = 0.10,
) -> pd.DataFrame:
    """
    Join model (word, model_probability) with market (word, market_probability).
    edge = model_probability - market_probability; flagged = edge > edge_threshold.
    """
    if model_probabilities.empty or "word" not in model_probabilities.columns or "model_probability" not in model_probabilities.columns:
        return pd.DataFrame(columns=["word", "market_probability", "model_probability", "edge", "flagged"])
    if market_df.empty or "word" not in market_df.columns:
        return pd.DataFrame(columns=["word", "market_probability", "model_probability", "edge", "flagged"])
    # Aggregate market by word (take max or mean if multiple contracts per word)
    market_agg = market_df.groupby("word", as_index=False)["market_probability"].mean()
    merged = model_probabilities[["word", "model_probability"]].merge(
        market_agg, on="word", how="inner"
    )
    merged["edge"] = (merged["model_probability"] - merged["market_probability"]).round(4)
    merged["flagged"] = merged["edge"] > edge_threshold
    return merged
