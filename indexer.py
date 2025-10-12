# document_indexer.py
#
# This script handles document loading, chunking, embedding, and storage
# in the PostgreSQL vector database (via pgvector).

import os
import argparse
import logging
from dotenv import load_dotenv
import pandas as pd
import psycopg2
from psycopg2.extras import execute_values
from pgvector.psycopg2 import register_vector
from typing import List

# RAG Libraries
from langchain_community.document_loaders import TextLoader, PyPDFLoader, WebBaseLoader
from langchain_community.document_loaders.unstructured import UnstructuredFileLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain.schema.document import Document

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

# Embedding Model settings
# Using a good all-around, efficient model with 384 dimensions
EMBEDDING_MODEL_NAME = 'all-MiniLM-L6-v2'
EMBEDDING_DIMENSION = 384
CHUNK_SIZE = 500
CHUNK_OVERLAP = 50

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

def store_chunks_in_db(conn, chunks: List[Document], source_uri: str, document_id: str):
    """Generates embeddings and stores the chunks in the database."""
    if not conn:
        return

    # Prepare data for batch insertion
    data_to_insert = []
    
    logging.info(f"Generating embeddings for {len(chunks)} chunks from {source_uri}...")
    
    try:
        for i, chunk in enumerate(chunks):
            # 1. Generate the embedding vector
            # The model takes the content and converts it to a fixed-size vector
            embedding = model.encode(chunk.page_content).tolist()

            # 2. Prepare the tuple for database insertion
            # (document_id, chunk_index, text_content, source_uri, embedding)
            data_to_insert.append((
                document_id,
                i, # Use chunk index for ordering
                chunk.page_content,
                source_uri,
                embedding
            ))

        # 3. Batch insert using execute_values for efficiency
        insert_query = """
        INSERT INTO document_chunks (document_id, chunk_index, text_content, source_uri, embedding)
        VALUES %s
        """
        with conn.cursor() as cursor:
            execute_values(cursor, insert_query, data_to_insert, page_size=100)
            conn.commit()
        logging.info(f"Successfully indexed {len(chunks)} chunks into the database.")

    except Exception as e:
        logging.error(f"Error during embedding or database insertion: {e}")
        conn.rollback()


# --- Document Loading and Processing Functions ---

def load_and_split_xlsx(file_path: str) -> List[Document]:
    """Loads an Excel file and converts rows to descriptive text chunks."""
    try:
        df = pd.read_excel(file_path)
        
        # Strategy: Convert each row into a single descriptive sentence for embedding
        text_chunks = []
        for index, row in df.iterrows():
            # Customize this template to describe your specific spreadsheet data better
            description = f"Row {index + 1}: {', '.join([f'{col}: {val}' for col, val in row.items()])}"
            text_chunks.append(Document(page_content=description, metadata={"row_index": index}))

        return text_chunks
    except Exception as e:
        logging.error(f"Error loading XLSX file {file_path}: {e}")
        return []

def load_and_split_document(source_uri: str) -> List[Document]:
    """Dynamically loads and splits a document based on its file extension or type."""
    file_extension = os.path.splitext(source_uri)[-1].lower()
    
    # 1. Select the appropriate loader based on extension
    if file_extension == '.pdf':
        loader = PyPDFLoader(source_uri)
    elif file_extension == '.txt':
        loader = TextLoader(source_uri)
    elif file_extension in ['.docx', '.pptx', '.html']:
        # Use UnstructuredFileLoader for robust parsing of complex formats
        loader = UnstructuredFileLoader(source_uri)
    elif file_extension in ['.xlsx', '.csv']:
        # XLSX/CSV need special handling to convert tabular data into semantic text
        return load_and_split_xlsx(source_uri)
    elif source_uri.startswith(('http://', 'https://')):
        loader = WebBaseLoader(source_uri)
    else:
        logging.warning(f"Unsupported file type or URI scheme for: {source_uri}")
        return []

    # 2. Load the raw document(s)
    try:
        docs = loader.load()
    except Exception as e:
        logging.error(f"Failed to load document at {source_uri}: {e}")
        return []

    # 3. Split the loaded documents into chunks
    # Use RecursiveCharacterTextSplitter for general-purpose, semantically-aware splitting
    text_splitter = RecursiveCharacterTextSplitter(
        chunk_size=CHUNK_SIZE,
        chunk_overlap=CHUNK_OVERLAP,
        length_function=len
    )
    
    chunks = text_splitter.split_documents(docs)
    logging.info(f"Document split into {len(chunks)} chunks.")
    return chunks

# --- Main Execution ---

def main(source_path: str):
    """Main function to run the indexing process."""
    # 1. Generate a consistent ID for the document (can be a hash or cleaned path)
    document_id = str(hash(source_path))

    # 2. Load and split the document into chunks
    chunks = load_and_split_document(source_path)

    if not chunks:
        logging.error("No chunks generated. Indexing aborted.")
        return

    # 3. Connect to the database
    conn = get_db_connection()
    if not conn:
        return

    # 4. Store the chunks (embed, then insert)
    store_chunks_in_db(conn, chunks, source_path, document_id)

    # 5. Close the connection
    conn.close()

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Indexer for the PGVector RAG system. Processes a document, creates embeddings, and stores them in PostgreSQL."
    )
    parser.add_argument(
        "source_path",
        type=str,
        help="Path or URI of the document to index (e.g., C:/path/to/doc.pdf or https://example.com)"
    )
    args = parser.parse_args()

    # The input path needs to be converted if running from WSL and accessing Windows files
    # WSL mounts Windows drives under /mnt/
    
    # Simple check: if the path starts with a Windows drive letter and colon, adjust it
    source_path = args.source_path
    if len(source_path) > 1 and source_path[1] == ':' and source_path[0].isalpha():
        drive_letter = source_path[0].lower()
        # Convert C:\Users\... to /mnt/c/Users/...
        source_path = f"/mnt/{drive_letter}/{source_path[3:].replace('\\', '/')}"
        logging.info(f"Adjusted Windows path for WSL access: {source_path}")

    main(source_path)
