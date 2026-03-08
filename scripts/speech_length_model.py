"""
Stub: speech length prediction.
Consumes transcript metadata (word_count, duration_seconds) when available.
Extension point for future length-based features.
"""


def predict_speech_length(transcript_metadata: dict) -> float:
    """Stub: return predicted length (e.g. word count or seconds). Not implemented in v1."""
    return 0.0
