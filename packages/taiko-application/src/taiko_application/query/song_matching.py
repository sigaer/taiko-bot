"""Text normalization and bounded fuzzy matching for song-name fragments."""

from difflib import SequenceMatcher
import unicodedata

from .context import SimilarityProvider


def normalize_song_query(value: str) -> str:
    """Fold width/case and whitespace without dropping title punctuation or numbers."""
    return "".join(unicodedata.normalize("NFKC", value).casefold().split())


def song_similarity(
    query: str,
    candidate: str,
    similarity: SimilarityProvider,
    *,
    allow_partial: bool,
) -> int:
    score = similarity(query, candidate)
    # Tiny fragments and bare numbers provide too little evidence for typo recovery.
    # Only search inside longer names; a short alias must not win by matching just
    # a small part of the user's longer input.
    if not allow_partial or len(query) < 5 or query.isdecimal() or len(candidate) <= len(query):
        return score

    windows: set[str] = set()
    for block in SequenceMatcher(None, query, candidate, autojunk=False).get_matching_blocks():
        if not block.size:
            continue
        start = max(0, block.b - block.a)
        for length in (len(query) - 1, len(query), len(query) + 1):
            window = candidate[start : start + length]
            if len(window) >= len(query) - 1:
                windows.add(window)

    partial = max((similarity(query, window) for window in windows), default=0)
    # Require strong local evidence and leave a full-name match above a fragment.
    return max(score, min(partial, 95)) if partial >= 85 else score
