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

# Default document patterns in the main repository
MAIN_DOC_PATTERNS = [
    ("README.md", [
        (r'^# PGVectorRAGIndexer v[\d.]+', '# PGVectorRAGIndexer v{full}'),
        (r"^## 🋹 What's New in v[\d.]+", "## 🋹 What's New in v{full}"),
        (r'^### 🆕 Latest Features \(v[\d.]+\)', '### 🆕 Latest Features (v{full})'),
    ]),
    ("QUICK_START.md", [
        (r'^# Quick Start Guide - PGVectorRAGIndexer v[\d.]+', 
         '# Quick Start Guide - PGVectorRAGIndexer v{full}'),
        (r"^## 🆕 What's New in v[\d.]+", "## 🆕 What's New in v{full}"),
    ]),
    ("DEPLOYMENT.md", [
        (r'^# Deployment Guide - PGVectorRAGIndexer v[\d.]+',
         '# Deployment Guide - PGVectorRAGIndexer v{full}'),
    ]),
    ("USAGE_GUIDE.md", [
        (r'^# PGVectorRAGIndexer Usage Guide - v[\d.]+',
         '# PGVectorRAGIndexer Usage Guide - v{full}'),
    ]),
]

# Patterns for the website repository
WEBSITE_PATTERNS = [
    ("package.json", [
        (r'"version": "[\d.]+"', '"version": "{full}"'),
    ]),
    ("index.html", [
        (r'<span>Production Ready · v[\d.]+</span>', '<span>Production Ready · v{full}</span>'),
        (r'releases/download/v[\d.]+/PGVectorRAGIndexer\.msi', 'releases/download/v{full}/PGVectorRAGIndexer.msi'),
        (r'releases/download/v[\d.]+/install\.command', 'releases/download/v{full}/install.command'),
        (r'releases/download/v[\d.]+/install-linux\.sh', 'releases/download/v{full}/install-linux.sh'),
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


def update_file(file_path, patterns, version_info, base_dir, dry_run=False):
    """Update version references in a file."""
    full_path = os.path.join(base_dir, file_path)
    
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
    
    # Directories
    main_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
    website_dir = os.path.abspath(os.path.join(main_dir, '..', 'PGVectorRAGIndexerWebsite'))
    
    updated_count = 0
    
    # 1. Update main repo docs
    print(f"\n[Main Repository: {main_dir}]")
    for file_path, patterns in MAIN_DOC_PATTERNS:
        if update_file(file_path, patterns, version_info, main_dir, dry_run):
            updated_count += 1
            
    # 2. Update website repo if it exists
    print(f"\n[Website Repository: {website_dir}]")
    if os.path.exists(website_dir):
        for file_path, patterns in WEBSITE_PATTERNS:
            if update_file(file_path, patterns, version_info, website_dir, dry_run):
                updated_count += 1
    else:
        print("  ⚠ Website directory not found at sibling path. Skipping.")
    
    print(f"\n{'Would update' if dry_run else 'Updated'} {updated_count} file(s)")
    
    if dry_run:
        print("\nRun without --dry-run to apply changes")
    
    return 0


if __name__ == '__main__':
    sys.exit(main())
