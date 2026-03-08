"""
Stub: trading alerts when edge exceeds threshold.
Reads output/kalshi_edges.csv; can send email or webhook for flagged rows.
Extension point for production alerts.
"""


def send_alerts(edges_csv_path: str, edge_threshold: float = 0.10) -> None:
    """Stub: notify when any row has edge > edge_threshold. Not implemented in v1."""
    pass
