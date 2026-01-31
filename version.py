"""
Version information for PGVectorRAGIndexer.
Single source of truth - reads from the VERSION file.
"""

import os

def get_version() -> str:
    """
    Get the application version from the VERSION file.
    Falls back to a default if the file is not found.
    """
    possible_paths = [
        os.path.join(os.path.dirname(__file__), 'VERSION'),
        'VERSION',
    ]
    
    for path in possible_paths:
        try:
            with open(path, 'r') as f:
                version = f.read().strip()
                if version:
                    return version
        except (FileNotFoundError, IOError):
            continue
    
    return "0.0.0-dev"  # Fallback for dev/missing



__version__ = get_version()
