"""
Unit tests for license_utils.py.
"""

import time
from license_utils import compute_days_until_expiry, is_expired


def test_compute_days_until_expiry():
    now = time.time()
    
    # 30.5 days in future -> 30 full days
    expiry = now + (30.5 * 86400)
    assert compute_days_until_expiry(expiry, now=now) == 30
    
    # 0.5 days in future -> 0 full days
    expiry = now + (0.5 * 86400)
    assert compute_days_until_expiry(expiry, now=now) == 0

    # 1 second ago -> -1 (Expired is negative)
    expiry = now - 1
    assert compute_days_until_expiry(expiry, now=now) == -1

    # Yesterday (exactly 24h ago) -> -1
    expiry = now - 86400
    assert compute_days_until_expiry(expiry, now=now) == -1

    # Yesterday (24h + 1s ago) -> -2
    expiry = now - 86401
    assert compute_days_until_expiry(expiry, now=now) == -2
    
    # Community (never expires)
    assert compute_days_until_expiry(0.0) is None
    assert compute_days_until_expiry(-1.0) is None


def test_is_expired():
    now = time.time()
    
    # Future
    assert not is_expired(now + 100, now=now)
    
    # Past
    assert is_expired(now - 100, now=now)
    
    # Exactly now (Boundary: now > expiry)
    # Policy: Not expired until the clock strictly exceeds the expiry timestamp
    assert not is_expired(now, now=now)
    
    # Community
    assert not is_expired(0.0)
    assert not is_expired(-1.0)
