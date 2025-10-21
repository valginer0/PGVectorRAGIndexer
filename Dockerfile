# PGVectorRAGIndexer Application Container
FROM python:3.12-slim

# Set working directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    g++ \
    postgresql-client \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first for better caching
COPY requirements.txt .

# Install Python dependencies with cache mount for faster rebuilds
# BuildKit will cache downloaded packages and reuse them if versions match
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --upgrade pip && \
    pip install -r requirements.txt

# Copy application code
COPY *.py ./
COPY init-db.sql ./

# Copy static files for Web UI
COPY static/ ./static/

# Create directories
RUN mkdir -p /app/documents

# Expose API port
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD python -c "import requests; requests.get('http://localhost:8000/health')"

# Default command (can be overridden)
CMD ["uvicorn", "api:app", "--host", "0.0.0.0", "--port", "8000"]
