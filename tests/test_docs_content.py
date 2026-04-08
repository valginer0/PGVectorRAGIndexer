"""
Automated content verification for client-facing documentation.

Replaces the manual visual-inspection checklist from the release plan.
No database, no network — pure filesystem reads.  Runs in < 1s.

Checks:
  - COMMERCIAL.md : pricing tiers, contact email, license stacking
  - QUICK_START.md : correct installer filename, What's New section
"""

from pathlib import Path

ROOT = Path(__file__).parent.parent


def _read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


# ── COMMERCIAL.md ─────────────────────────────────────────────────────────────

class TestCommercialMd:
    """Verify COMMERCIAL.md reflects current pricing and contact details."""

    def test_team_annual_price(self):
        assert "$299/yr" in _read("COMMERCIAL.md"), "Team annual price should be $299/yr"

    def test_team_perpetual_price(self):
        assert "$499" in _read("COMMERCIAL.md"), "Team one-time price should be $499"

    def test_org_annual_price(self):
        assert "$799/yr" in _read("COMMERCIAL.md"), "Organization annual price should be $799/yr"

    def test_org_perpetual_price(self):
        assert "$1,299" in _read("COMMERCIAL.md"), "Organization one-time price should be $1,299"

    def test_contact_email_correct(self):
        content = _read("COMMERCIAL.md")
        assert "hello@ragvault.net" in content, "Contact email must be hello@ragvault.net"

    def test_old_email_gone(self):
        assert "valginer0@gmail.com" not in _read("COMMERCIAL.md"), \
            "Old personal email must not appear in COMMERCIAL.md"

    def test_license_stacking_documented(self):
        content = _read("COMMERCIAL.md").lower()
        assert "multiple organization licenses" in content or "license stacking" in content, \
            "License stacking must be described in COMMERCIAL.md"

    def test_no_old_team_price(self):
        content = _read("COMMERCIAL.md")
        assert "$199/yr" not in content, "Old Team price $199/yr must not appear"

    def test_no_old_org_price(self):
        content = _read("COMMERCIAL.md")
        assert "$599/yr" not in content, "Old Org price $599/yr must not appear"


# ── QUICK_START.md ────────────────────────────────────────────────────────────

class TestQuickStartMd:
    """Verify QUICK_START.md has the correct installer and current feature list."""

    def test_windows_installer_is_msi(self):
        content = _read("QUICK_START.md")
        assert "PGVectorRAGIndexer.msi" in content, \
            "Windows installer must be referenced as .msi"

    def test_old_exe_installer_gone(self):
        assert "PGVectorRAGIndexer-Setup.exe" not in _read("QUICK_START.md"), \
            "Old .exe installer reference must be removed"

    def test_current_version_in_whats_new(self):
        assert "v2.13.0" in _read("QUICK_START.md"), \
            "What's New section must reference v2.13.0"

    def test_license_stacking_in_whats_new(self):
        assert "License Stacking" in _read("QUICK_START.md"), \
            "License Stacking must appear in What's New"

    def test_setup_wizard_mentioned(self):
        content = _read("QUICK_START.md")
        assert "Wizard" in content or "wizard" in content, \
            "First-run Setup Wizard must be mentioned"

    def test_admin_console_in_whats_new(self):
        assert "Admin Console" in _read("QUICK_START.md"), \
            "Admin Console Licenses Panel must appear in What's New"
