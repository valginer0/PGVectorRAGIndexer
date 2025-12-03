#!/bin/bash
# Script to add @pytest.mark.slow to UI test files

UI_TEST_FILES=(
    "tests/test_desktop_app.py"
    "tests/test_documents_tab.py"
    "tests/test_documents_tab_open.py"
    "tests/test_documents_tab_ui.py"
    "tests/test_manage_tab.py"
    "tests/test_manage_tab_open.py"
    "tests/test_recent_activity_tab_ui.py"
    "tests/test_search_tab.py"
    "tests/test_search_tab_open.py"
    "tests/test_upload_tab.py"
    "tests/test_workers.py"
)

for file in "${UI_TEST_FILES[@]}"; do
    if [ -f "$file" ]; then
        # Check if file already has pytest.mark.slow
        if ! grep -q "@pytest.mark.slow" "$file"; then
            echo "Adding @pytest.mark.slow to $file"
            # Add pytestmark at the top after imports
            sed -i '/^import pytest/a\
\
# Mark all tests in this file as slow (UI tests with QApplication)\
pytestmark = pytest.mark.slow' "$file"
        else
            echo "Skipping $file (already marked)"
        fi
    fi
done

echo "Done! All UI test files marked as slow."
