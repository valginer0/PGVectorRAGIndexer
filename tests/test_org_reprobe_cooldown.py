"""
Regression test for the Organization-tab reprobe flood (smoke test, 2026-06-13).

While the Org tab is stuck on its placeholder, MainWindow calls
OrganizationTab.on_backend_healthy() on every health tick (~3s). That method
re-arms its own reprobe flag, so without a cooldown a failing probe re-fires a
multi-request org probe every 3s and floods the backend past the rate limit
(the bug that immediately blocked the UI). The cooldown caps re-probes to once
per 30s while stuck.
"""

import types

from desktop_app.ui.admin_tab import OrganizationTab


def _fake_org_tab():
    """A stand-in 'self' carrying just what on_backend_healthy touches — avoids
    needing a real Qt widget / QApplication."""
    probes = {"count": 0}
    not_tabs_page = object()

    fake = types.SimpleNamespace(
        _outer_stack=types.SimpleNamespace(currentWidget=lambda: not_tabs_page),
        _tabs_page=object(),                  # current widget is NOT this → on placeholder
        _awaiting_backend_healthy_reprobe=True,
        _auto_retry_scheduled=False,
        _last_reprobe_ts=0.0,
        _caps=types.SimpleNamespace(invalidate=lambda: None),
        _probes=probes,
    )
    # _begin_transient_retry_window re-arms the flag (the real behavior that
    # would otherwise cause the every-tick loop).
    fake._begin_transient_retry_window = lambda: setattr(fake, "_awaiting_backend_healthy_reprobe", True)
    fake.probe_and_refresh = lambda: probes.__setitem__("count", probes["count"] + 1)
    return fake, probes


def test_reprobe_fires_once_then_cools_down():
    fake, probes = _fake_org_tab()
    fn = OrganizationTab.on_backend_healthy

    # Simulate many rapid health ticks (every 3s the worker calls this).
    for _ in range(10):
        fn(fake)

    # Without the cooldown this would be ~10 probe bursts; with it, exactly one.
    assert probes["count"] == 1


def test_reprobe_allowed_again_after_cooldown_window():
    fake, probes = _fake_org_tab()
    fn = OrganizationTab.on_backend_healthy

    fn(fake)
    assert probes["count"] == 1
    # Pretend 31s elapsed → re-probe permitted once more.
    fake._last_reprobe_ts -= 31.0
    fn(fake)
    assert probes["count"] == 2


def test_no_reprobe_once_tab_loaded():
    fake, probes = _fake_org_tab()
    # currentWidget IS the tabs page → tab loaded successfully, no reprobe ever.
    fake._outer_stack = types.SimpleNamespace(currentWidget=lambda: fake._tabs_page)
    OrganizationTab.on_backend_healthy(fake)
    assert probes["count"] == 0
