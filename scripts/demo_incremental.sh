#!/bin/bash
# Demo script for Incremental Indexing

# Colors
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
ORANGE='\033[0;33m'
RED='\033[0;31m'
NC='\033[0m'

DOC_FILE="demo_doc.txt"

echo -e "\n${BLUE}=== Incremental Indexing Demo ===${NC}\n"

# 0. Cleanup
echo -e "${YELLOW}0. Cleaning up previous run...${NC}"
rm -f "$DOC_FILE"
python3 indexer_v2.py delete "$(python3 -c "import hashlib; print(hashlib.sha256('${PWD}/${DOC_FILE}'.encode()).hexdigest()[:16])")" >/dev/null 2>&1

# 1. New File
echo -e "\n${BLUE}1. Simulating NEW file...${NC}"
echo "This is version 1 of the document." > "$DOC_FILE"
echo "File created: $DOC_FILE"
python3 indexer_v2.py index "$DOC_FILE"

# 2. Unchanged File
echo -e "\n${BLUE}2. Simulating UNCHANGED file (Indexing again)...${NC}"
python3 indexer_v2.py index "$DOC_FILE"

# 3. Changed File
echo -e "\n${BLUE}3. Simulating CHANGED file...${NC}"
echo "This is version 2 of the document. Content has changed!" > "$DOC_FILE"
echo "File updated: $DOC_FILE"
python3 indexer_v2.py index "$DOC_FILE"

# 4. Force Reindex
echo -e "\n${BLUE}4. Simulating FORCE REINDEX (Unchanged content)...${NC}"
# Content is still v2, so normally it would skip.
python3 indexer_v2.py index "$DOC_FILE" --force

echo -e "\n${GREEN}=== Demo Complete ===${NC}"
echo "Verify the output above showed:"
echo "1. Success (Indexed)"
echo "2. Skipped (Unchanged)"
echo "3. Success (Re-indexed)"
echo "4. Success (Force Re-indexed)"
