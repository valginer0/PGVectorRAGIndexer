#!/bin/bash

# Database Inspection Helper Script
# Quick commands to manually inspect the database

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

echo -e "${BLUE}=== PGVectorRAGIndexer Database Inspector ===${NC}"
echo ""

# Check if container is running
if ! docker ps --format '{{.Names}}' | grep -q "^vector_rag_db$"; then
    echo -e "${YELLOW}⚠ Database container is not running!${NC}"
    echo "Start it with: docker compose up -d"
    exit 1
fi

echo -e "${GREEN}Database is running. Choose an option:${NC}"
echo ""
echo "1. List all documents"
echo "2. Count chunks per document"
echo "3. Show recent chunks (last 10)"
echo "4. Search for text in chunks"
echo "5. Show database statistics"
echo "6. List extensions"
echo "7. Show table schema"
echo "8. Interactive psql session"
echo "9. Custom SQL query"
echo ""
read -p "Enter choice (1-9): " choice

case $choice in
    1)
        echo -e "${BLUE}Listing all documents:${NC}"
        docker exec vector_rag_db psql -U rag_user -d rag_vector_db -c \
            "SELECT DISTINCT document_id, source_uri, COUNT(*) as chunks 
             FROM document_chunks 
             GROUP BY document_id, source_uri 
             ORDER BY MAX(indexed_at) DESC;"
        ;;
    2)
        echo -e "${BLUE}Chunk count per document:${NC}"
        docker exec vector_rag_db psql -U rag_user -d rag_vector_db -c \
            "SELECT document_id, COUNT(*) as chunk_count, 
                    MIN(indexed_at) as first_indexed, 
                    MAX(updated_at) as last_updated 
             FROM document_chunks 
             GROUP BY document_id 
             ORDER BY chunk_count DESC;"
        ;;
    3)
        echo -e "${BLUE}Recent chunks (last 10):${NC}"
        docker exec vector_rag_db psql -U rag_user -d rag_vector_db -c \
            "SELECT chunk_id, document_id, chunk_index, 
                    LEFT(text_content, 80) as preview, 
                    indexed_at 
             FROM document_chunks 
             ORDER BY indexed_at DESC 
             LIMIT 10;"
        ;;
    4)
        read -p "Enter search text: " search_text
        echo -e "${BLUE}Searching for '$search_text':${NC}"
        docker exec vector_rag_db psql -U rag_user -d rag_vector_db -c \
            "SELECT document_id, chunk_index, 
                    LEFT(text_content, 100) as preview 
             FROM document_chunks 
             WHERE text_content ILIKE '%$search_text%' 
             LIMIT 20;"
        ;;
    5)
        echo -e "${BLUE}Database statistics:${NC}"
        docker exec vector_rag_db psql -U rag_user -d rag_vector_db -c \
            "SELECT 
                COUNT(DISTINCT document_id) as total_documents,
                COUNT(*) as total_chunks,
                pg_size_pretty(pg_total_relation_size('document_chunks')) as table_size,
                MIN(indexed_at) as oldest_chunk,
                MAX(indexed_at) as newest_chunk
             FROM document_chunks;"
        ;;
    6)
        echo -e "${BLUE}Installed extensions:${NC}"
        docker exec vector_rag_db psql -U rag_user -d rag_vector_db -c "\dx"
        ;;
    7)
        echo -e "${BLUE}Table schema:${NC}"
        docker exec vector_rag_db psql -U rag_user -d rag_vector_db -c "\d document_chunks"
        ;;
    8)
        echo -e "${BLUE}Starting interactive psql session...${NC}"
        echo -e "${YELLOW}(Type \q to exit)${NC}"
        docker exec -it vector_rag_db psql -U rag_user -d rag_vector_db
        ;;
    9)
        echo -e "${YELLOW}Enter SQL query (end with semicolon):${NC}"
        read -p "> " query
        docker exec vector_rag_db psql -U rag_user -d rag_vector_db -c "$query"
        ;;
    *)
        echo "Invalid choice"
        exit 1
        ;;
esac

echo ""
echo -e "${GREEN}Done!${NC}"
