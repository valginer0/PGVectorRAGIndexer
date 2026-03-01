"""
DTO (Data Transfer Object) for license information in the desktop UI.
"""

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class LicenseDisplayDTO:
    """Lightweight dataclass for license information display in the UI."""
    edition_label: str
    is_team: bool
    org_name: str
    seats: int
    days_left: Optional[int]
    expiry_warning: bool
    warning_text: str
