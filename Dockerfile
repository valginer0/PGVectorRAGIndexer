# PGVectorRAGIndexer Application Container
# Uses pre-built base image with all heavy dependencies (PyTorch, CUDA, etc.)
# This makes rebuilds much faster (~50MB instead of 8.3GB)

# Use base image with all dependencies pre-installed
# To rebuild base: docker build -f Dockerfile.base -t ghcr.io/valginer0/pgvectorragindexer:base .
FROM ghcr.io/valginer0/pgvectorragindexer:base

# Working directory is already set in base image
WORKDIR /app

# Copy application code
COPY *.py ./
COPY init-db.sql ./

# Copy static files for Web UI
COPY static/ ./static/

# Create directories
RUN mkdir -p /app/documents

# Ensure LibreOffice is available (needed for .doc conversion)
RUN if ! command -v soffice >/dev/null 2>&1 && ! command -v libreoffice >/dev/null 2>&1; then \
        apt-get update && \
        apt-get install -y libreoffice && \
        rm -rf /var/lib/apt/lists/*; \
    fi

# Expose API port
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD python -c "import requests; requests.get('http://localhost:8000/health')"

# Default command (can be overridden)
CMD ["uvicorn", "api:app", "--host", "0.0.0.0", "--port", "8000"]
