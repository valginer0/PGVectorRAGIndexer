"""
License utility functions for expiry and validation logic.
"""

import time
from typing import Optional


def compute_days_until_expiry(expiry_timestamp: float, now: float = None) -> Optional[int]:
    """Compute the number of days remaining until the license expires.

    Args:
        expiry_timestamp: The Unix timestamp when the license expires.
        now: Optional override for the current time (used for testing).

    Returns:
        The number of full days remaining, or None if the license never expires.
    """
    if expiry_timestamp <= 0:
        return None  # Community/Never expires

    if now is None:
        now = time.time()

    remaining = expiry_timestamp - now
    return int(remaining / 86400)


def is_expired(expiry_timestamp: float, now: float = None) -> bool:
    """Check if a license has expired.

    Args:
        expiry_timestamp: The Unix timestamp when the license expires.
        now: Optional override for the current time (used for testing).

    Returns:
        True if the current time is past the expiry timestamp.
    """
    if expiry_timestamp <= 0:
        return False  # Community/Never expires

    if now is None:
        now = time.time()

    return now > expiry_timestamp
