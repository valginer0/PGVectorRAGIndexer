"""
Version information for PGVectorRAGIndexer Windows Installer.
Re-exports from the central version module.
"""

import sys
import os

# Add parent directory to path to import from root version module
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    from version import __version__, get_version
except ImportError:
    # Fallback if running standalone
    __version__ = "2.4.1"
    def get_version() -> str:
        return __version__

INSTALLER_VERSION = __version__
