"""
Pipeline automation. run_pipeline() runs ingest → weekly stats → narrative → Kalshi → edges → export.
For daily execution, use cron: 0 9 * * * cd /path/to/speech_word_market_model && python main.py
"""
import json
import os

from scripts.ingest_transcripts import ingest_transcripts
from scripts.ingest_news import ingest_news
from scripts.weekly_stats import compute_weekly_probabilities
from scripts.probability_model import compute_baseline_probabilities
from scripts.narrative_model import apply_narrative_adjustment
from scripts.kalshi_parser import parse_kalshi_markets
from scripts.edge_detector import compute_edges


def run_pipeline(config_path: str, base_dir: str) -> None:
    """Run full pipeline: ingest transcripts, update weekly model, ingest news, narrative multipliers, Kalshi, edges, export."""
    with open(config_path, encoding="utf-8") as f:
        config = json.load(f)
    data_dir = os.path.join(base_dir, "data")
    output_dir = os.path.join(base_dir, "output")
    os.makedirs(output_dir, exist_ok=True)
    transcripts_dir = os.path.join(data_dir, "transcripts")
    processed_transcripts = os.path.join(transcripts_dir, "processed_transcripts.json")
    news_dir = os.path.join(data_dir, "news")
    processed_news = os.path.join(news_dir, "processed_news.json")
    markets_dir = os.path.join(data_dir, "markets")
    tracked_words = config.get("tracked_words", [])
    recency_weights = config.get("recency_weights", [0.1, 0.2, 0.3, 0.4])
    news_multipliers = config.get("news_multipliers", {"0": 0.9, "1": 1.1, "3": 1.4, "5": 1.8})
    edge_threshold = config.get("edge_threshold", 0.10)
    stopwords = config.get("stopwords", [])

    # 1. Ingest transcripts
    ingest_transcripts(transcripts_dir, processed_transcripts, config=config)

    # 2. Weekly stats
    reference_date = config.get("reference_date")
    weekly_df = compute_weekly_probabilities(processed_transcripts, tracked_words, reference_date=reference_date)

    # 3. Baseline probability model
    baseline_df = compute_baseline_probabilities(weekly_df, recency_weights)

    # 4. Ingest news
    ingest_news(news_dir, processed_news)

    # 5. Narrative adjustment
    final_prob_df = apply_narrative_adjustment(
        baseline_df,
        processed_news,
        tracked_words,
        news_multipliers,
        stopwords=stopwords,
    )

    # 6. Word probabilities CSV: word, week1..week4, model_probability (optional baseline)
    prob_out = weekly_df.merge(
        final_prob_df[["word", "model_probability"]],
        on="word",
        how="left",
    )
    if "model_probability" in baseline_df.columns:
        prob_out = prob_out.merge(
            baseline_df[["word", "model_probability"]].rename(columns={"model_probability": "model_probability_baseline"}),
            on="word",
            how="left",
        )
    prob_path = os.path.join(output_dir, "word_probabilities.csv")
    prob_out.to_csv(prob_path, index=False)

    # 7. Ingest Kalshi markets
    market_paths = [
        os.path.join(markets_dir, f)
        for f in os.listdir(markets_dir)
        if f.endswith((".json", ".csv")) and not f.startswith(".")
    ]
    if not market_paths:
        market_paths = [os.path.join(markets_dir, "kalshi_sample.json")]
    market_df = parse_kalshi_markets(market_paths, tracked_words)

    # 8. Edge detection
    edges_df = compute_edges(final_prob_df, market_df, edge_threshold=edge_threshold)
    edges_path = os.path.join(output_dir, "kalshi_edges.csv")
    edges_df.to_csv(edges_path, index=False)
