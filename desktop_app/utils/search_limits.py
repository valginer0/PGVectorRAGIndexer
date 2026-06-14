from typing import Optional

UNIQUE_FILE_CANDIDATE_MULTIPLIER = 20
UNIQUE_FILE_CANDIDATE_EXTRA = 50
UNIQUE_FILE_CANDIDATE_MAX = 500


def candidate_limit_for_unique_files(visible_limit: Optional[int]) -> Optional[int]:
    """Fetch extra chunk-level matches so file-level dedupe does not hide files."""
    if visible_limit is None:
        return None
    return min(
        max(
            visible_limit * UNIQUE_FILE_CANDIDATE_MULTIPLIER,
            visible_limit + UNIQUE_FILE_CANDIDATE_EXTRA,
        ),
        UNIQUE_FILE_CANDIDATE_MAX,
    )
