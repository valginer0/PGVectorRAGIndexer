PGVectorRAGIndexer: Local Semantic Document Search
This project demonstrates a fully local Retrieval-Augmented Generation (RAG) pipeline using PostgreSQL with the pgvector extension as the vector database. It is designed to index various document formats (PDF, DOCX, XLSX, TXT, and Web URLs) and allow for efficient semantic search based on content context.

The entire environment, including the PostgreSQL database with pgvector enabled, runs locally inside a Docker container.

🚀 Key Features
Local Vector Database: Uses PostgreSQL 16 (via Docker) with the powerful pgvector extension.

Multi-Format Support: Ingests documents from diverse sources, including:

Plain Text (.txt)

PDF Documents (.pdf)

Microsoft Word Documents (.docx)

Microsoft Excel Spreadsheets (.xlsx)

Web URLs (http(s)://...)

Semantic Search: Indexes document chunks using the highly efficient all-MiniLM-L6-v2 Sentence Transformer model (384 dimensions) for fast and accurate semantic retrieval.

Cross-OS Compatibility: Designed to be run primarily in the Ubuntu WSL 2 environment on Windows 11, with utilities to handle Windows filesystem paths (C:\...).

🛠️ Setup Instructions
1. Prerequisites
Docker Desktop: Must be installed and running (using the WSL 2 backend is highly recommended for performance).

WSL 2: A working Ubuntu environment on Windows 11.

Python: Python 3.9+ installed inside your Ubuntu WSL instance.

2. Configure Environment
Navigate to Project: Open your Ubuntu WSL terminal and navigate to the project directory:

cd /home/valginer0/projects/PGVectorRAGIndexer

Create Virtual Environment & Install Dependencies:

python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

3. Database Setup (Docker)
Ensure the .env file is present in the root directory (containing the credentials: rag_user, rag_password, etc.).

Launch the PostgreSQL Container:

docker compose up -d

(The container will automatically run the init-db.sql script to create the vector extension and the document_chunks table on the first run.)

Verify Setup (Optional): You can check the container status:

docker ps

⚙️ How to Use the Application
1. Indexing Documents (Populating the Vector DB)
Run the indexer.py script, passing the full path or URL of the document you wish to index.

A. Indexing Local Windows Files (Using WSL Path Conversion):

If your file is on your Windows C: drive, use the full Windows path, and the script will convert it for you (e.g., C:\Users\YourName\Desktop\report.pdf becomes /mnt/c/Users/YourName/Desktop/report.pdf internally).

python indexer.py "C:\Users\YourUser\Desktop\Project_Summary.docx"

B. Indexing Web URLs:

python indexer.py "[https://en.wikipedia.org/wiki/Vector_database](https://en.wikipedia.org/wiki/Vector_database)"

2. Retrieving Information (Searching)
Run the retriever.py script, passing your natural language search query in quotes.

python retriever.py "What were the main topics discussed in the document about Docker setup?"

The script will embed your query, search the PostgreSQL database for the 5 most semantically similar chunks, and display the relevant text snippets and their source URIs.