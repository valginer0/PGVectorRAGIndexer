"""
Unit tests for license_utils.py.
"""

import time
from license_utils import compute_days_until_expiry, is_expired


def test_compute_days_until_expiry():
    now = time.time()
    
    # 30 days in future
    expiry = now + (30 * 86400) + 100
    assert compute_days_until_expiry(expiry, now=now) == 30
    
    # Expired yesterday
    expiry = now - 86400
    assert compute_days_until_expiry(expiry, now=now) == -1
    
    # Community (never expires)
    assert compute_days_until_expiry(0.0) is None
    assert compute_days_until_expiry(-1.0) is None


def test_is_expired():
    now = time.time()
    
    # Future
    assert not is_expired(now + 100, now=now)
    
    # Past
    assert is_expired(now - 100, now=now)
    
    # Exactly now (should be expired or at least not false-negative)
    # Most implementations use > expiry
    assert not is_expired(now, now=now)
    
    # Community
    assert not is_expired(0.0)
    assert not is_expired(-1.0)
