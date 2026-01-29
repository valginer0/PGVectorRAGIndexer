#!/usr/bin/env python3
"""
Update version references in documentation files.
Reads version from VERSION file and updates doc headers.

Usage:
    python scripts/update_version_docs.py
    python scripts/update_version_docs.py --dry-run
"""

import os
import re
import sys

# Files to update and their patterns
# Format: (file_path, [(pattern, replacement_template), ...])
DOC_PATTERNS = [
    ("README.md", [
        # Main title: # PGVectorRAGIndexer v2.4
        (r'^# PGVectorRAGIndexer v[\d.]+', '# PGVectorRAGIndexer v{major_minor}'),
        # What's New section: ## 🋹 What's New in v2.4
        (r"^## 🋹 What's New in v[\d.]+", "## 🋹 What's New in v{major_minor}"),
        # Latest Features: ### 🆕 Latest Features (v2.4)
        (r'^### 🆕 Latest Features \(v[\d.]+\)', '### 🆕 Latest Features (v{major_minor})'),
    ]),
    ("QUICK_START.md", [
        # Main title: # Quick Start Guide - PGVectorRAGIndexer v2.4
        (r'^# Quick Start Guide - PGVectorRAGIndexer v[\d.]+', 
         '# Quick Start Guide - PGVectorRAGIndexer v{major_minor}'),
        # What's New: ## 🆕 What's New in v2.4
        (r"^## 🆕 What's New in v[\d.]+", "## 🆕 What's New in v{major_minor}"),
    ]),
    ("DEPLOYMENT.md", [
        # Main title: # Deployment Guide - PGVectorRAGIndexer v2.2
        (r'^# Deployment Guide - PGVectorRAGIndexer v[\d.]+',
         '# Deployment Guide - PGVectorRAGIndexer v{major_minor}'),
    ]),
]


def get_version():
    """Read version from VERSION file."""
    version_path = os.path.join(os.path.dirname(__file__), '..', 'VERSION')
    try:
        with open(version_path, 'r') as f:
            return f.read().strip()
    except FileNotFoundError:
        print(f"ERROR: VERSION file not found at {version_path}")
        sys.exit(1)


def parse_version(version):
    """Parse version into components."""
    parts = version.split('.')
    return {
        'full': version,
        'major': parts[0] if len(parts) > 0 else '0',
        'minor': parts[1] if len(parts) > 1 else '0',
        'patch': parts[2] if len(parts) > 2 else '0',
        'major_minor': f"{parts[0]}.{parts[1]}" if len(parts) >= 2 else version,
    }


def update_file(file_path, patterns, version_info, dry_run=False):
    """Update version references in a file."""
    full_path = os.path.join(os.path.dirname(__file__), '..', file_path)
    
    if not os.path.exists(full_path):
        print(f"  ⚠ File not found: {file_path}")
        return False
    
    with open(full_path, 'r') as f:
        content = f.read()
    
    original_content = content
    changes = []
    
    for pattern, replacement_template in patterns:
        replacement = replacement_template.format(**version_info)
        # Use MULTILINE flag to match ^ at start of lines
        new_content, count = re.subn(pattern, replacement, content, flags=re.MULTILINE)
        if count > 0:
            changes.append((pattern, replacement, count))
            content = new_content
    
    if content != original_content:
        if not dry_run:
            with open(full_path, 'w') as f:
                f.write(content)
        print(f"  ✓ {file_path}: {len(changes)} pattern(s) updated")
        for pattern, replacement, count in changes:
            print(f"      → {replacement}")
        return True
    else:
        print(f"  - {file_path}: no changes needed")
        return False


def main():
    dry_run = '--dry-run' in sys.argv
    
    if dry_run:
        print("DRY RUN - No files will be modified\n")
    
    # Get version
    version = get_version()
    version_info = parse_version(version)
    
    print(f"Updating documentation to version {version}...")
    print(f"  (using v{version_info['major_minor']} in doc headers)\n")
    
    # Update each file
    updated_count = 0
    for file_path, patterns in DOC_PATTERNS:
        if update_file(file_path, patterns, version_info, dry_run):
            updated_count += 1
    
    print(f"\n{'Would update' if dry_run else 'Updated'} {updated_count} file(s)")
    
    if dry_run:
        print("\nRun without --dry-run to apply changes")
    
    return 0


if __name__ == '__main__':
    sys.exit(main())
