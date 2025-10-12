# retriever.py
#
# This script handles querying the PostgreSQL vector database for the most
# relevant document chunks based on semantic similarity.

import os
import argparse
import logging
from dotenv import load_dotenv
import psycopg2
from pgvector.psycopg2 import register_vector

# Embedding Model (Requires 'sentence-transformers' package)
from sentence_transformers import SentenceTransformer

# --- Configuration and Setup ---

# Load environment variables from .env file
load_dotenv()

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Database credentials from .env
DB_HOST = os.getenv("DB_HOST")
DB_PORT = os.getenv("DB_PORT")
DB_NAME = os.getenv("POSTGRES_DB")
DB_USER = os.getenv("POSTGRES_USER")
DB_PASS = os.getenv("POSTGRES_PASSWORD")

# Embedding Model settings - MUST MATCH indexer.py settings
EMBEDDING_MODEL_NAME = 'all-MiniLM-L6-v2'
RETRIEVAL_LIMIT = 5 # Number of top chunks to retrieve

# Global model instance
model = SentenceTransformer(EMBEDDING_MODEL_NAME)

# --- Database Connection and Utility Functions ---

def get_db_connection():
    """Establishes a connection to the PostgreSQL database."""
    try:
        conn = psycopg2.connect(
            host=DB_HOST,
            port=DB_PORT,
            dbname=DB_NAME,
            user=DB_USER,
            password=DB_PASS
        )
        # Register the vector type converter for psycopg2
        register_vector(conn)
        logging.info("Successfully connected to PostgreSQL database.")
        return conn
    except Exception as e:
        logging.error(f"Failed to connect to database: {e}")
        return None

def find_similar_chunks(conn, query_text: str, k: int = RETRIEVAL_LIMIT):
    """
    Embeds the query and performs a vector similarity search (Nearest Neighbor).
    
    The <=> operator is used for cosine distance, which measures semantic similarity.
    """
    if not conn:
        return []

    logging.info(f"Generating embedding for query: '{query_text}'")
    
    try:
        # 1. Generate the query vector using the same model as the indexer
        query_embedding = model.encode(query_text).tolist()

        # 2. Execute the vector search query
        # ORDER BY embedding <=> %s sorts by smallest cosine distance (closest match)
        search_query = """
        SELECT text_content, source_uri, chunk_index, embedding <=> %s AS distance
        FROM document_chunks
        ORDER BY distance
        LIMIT %s;
        """
        
        with conn.cursor() as cursor:
            # Note: query_embedding is passed as a list, and psycopg2/pgvector handles conversion
            cursor.execute(search_query, (query_embedding, k))
            results = cursor.fetchall()
            
        logging.info(f"Retrieved {len(results)} nearest neighbor chunks.")
        return results

    except Exception as e:
        logging.error(f"Error during vector search: {e}")
        return []


# --- Main Execution ---

def main(query: str):
    """Main function to run the retrieval process."""
    
    # 1. Connect to the database
    conn = get_db_connection()
    if not conn:
        return

    # 2. Find similar chunks
    results = find_similar_chunks(conn, query)
    
    if not results:
        print("\n[Search Results]\nNo relevant documents found.")
    else:
        print("\n[Search Results]\nFound the following relevant chunks (sorted by similarity):")
        
        # 3. Display results
        for content, uri, index, distance in results:
            print("-" * 60)
            print(f"Source URI: {uri} (Chunk #{index})")
            print(f"Distance (Cosine): {distance:.4f}")
            print(f"Snippet: {content[:150].replace('\n', ' ')}...")
            
    # 4. Close connection
    conn.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Retriever for the PGVector RAG system. Searches for semantic matches to a query."
    )
    parser.add_argument(
        "query",
        type=str,
        help="The text query to search for (e.g., 'What are the steps for setting up Docker?')"
    )
    args = parser.parse_args()
    
    main(args.query)
