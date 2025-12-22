# Deployment Guide - PGVectorRAGIndexer v2.2

> **📌 Note:** For quick Docker-only deployment (recommended for most users), see:
> - **Windows**: [WINDOWS_SETUP.md](WINDOWS_SETUP.md)
> - **Linux/macOS/WSL**: [QUICK_START.md](QUICK_START.md)
> - **Comparison**: [DEPLOYMENT_OPTIONS.md](DEPLOYMENT_OPTIONS.md)
>
> This guide covers **advanced production deployment** scenarios.

This guide covers deployment strategies for production environments.

## 📦 Deployment Options

### 1. Local Development (WSL/Ubuntu)

**Prerequisites**:
- WSL 2 with Ubuntu
- Docker Desktop
- Python 3.9+

**Steps**:

```bash
# 1. Clone repository
cd ~/projects/PGVectorRAGIndexer

# 2. Create virtual environment
python3 -m venv venv
source venv/bin/activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Configure environment
cp .env.example .env
# Edit .env with your settings

# 5. Start database
docker compose up -d

# 6. Verify installation
python indexer_v2.py stats
```

### 2. Docker Compose (Recommended)

**Full stack deployment** with database and API:

Create `docker-compose.full.yml`:

```yaml
version: '3.8'

services:
  # PostgreSQL with pgvector
  db:
    image: pgvector/pgvector:pg16
    container_name: rag_db
    restart: always
    environment:
      POSTGRES_USER: ${POSTGRES_USER:-rag_user}
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD:-rag_password}
      POSTGRES_DB: ${POSTGRES_DB:-rag_vector_db}
    ports:
      - "${DB_PORT:-5432}:5432"
    volumes:
      - postgres_data:/var/lib/postgresql/data
      - ./init-db.sql:/docker-entrypoint-initdb.d/init-db.sql
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U rag_user"]
      interval: 10s
      timeout: 5s
      retries: 5

  # API Service
  api:
    build:
      context: .
      dockerfile: Dockerfile
    container_name: rag_api
    restart: always
    environment:
      DB_HOST: db
      DB_PORT: 5432
      POSTGRES_USER: ${POSTGRES_USER:-rag_user}
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD:-rag_password}
      POSTGRES_DB: ${POSTGRES_DB:-rag_vector_db}
      API_HOST: 0.0.0.0
      API_PORT: 8000
    ports:
      - "${API_PORT:-8000}:8000"
    depends_on:
      db:
        condition: service_healthy
    volumes:
      - ./documents:/app/documents:ro

volumes:
  postgres_data:
```

Create `Dockerfile`:

```dockerfile
FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    g++ \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Expose API port
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
  CMD python -c "import requests; requests.get('http://localhost:8000/health')"

# Run API server
CMD ["python", "api.py"]
```

**Deploy**:

```bash
# Build and start all services
docker compose -f docker-compose.full.yml up -d

# Check status
docker compose -f docker-compose.full.yml ps

# View logs
docker compose -f docker-compose.full.yml logs -f api

# Stop services
docker compose -f docker-compose.full.yml down
```

### 3. Production Server (Linux)

**System Requirements**:
- Ubuntu 20.04+ or similar
- 4GB+ RAM
- 20GB+ disk space
- PostgreSQL 16 with pgvector

**Installation**:

```bash
# 1. Update system
sudo apt update && sudo apt upgrade -y

# 2. Install PostgreSQL 16
sudo sh -c 'echo "deb http://apt.postgresql.org/pub/repos/apt $(lsb_release -cs)-pgdg main" > /etc/apt/sources.list.d/pgdg.list'
wget --quiet -O - https://www.postgresql.org/media/keys/ACCC4CF8.asc | sudo apt-key add -
sudo apt update
sudo apt install -y postgresql-16 postgresql-contrib-16

# 3. Install pgvector
sudo apt install -y postgresql-16-pgvector

# 4. Install Python and dependencies
sudo apt install -y python3.11 python3.11-venv python3-pip

# 5. Create application user
sudo useradd -m -s /bin/bash ragapp
sudo su - ragapp

# 6. Clone and setup application
git clone <repository-url> /home/ragapp/app
cd /home/ragapp/app
python3.11 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# 7. Configure PostgreSQL
sudo -u postgres psql << EOF
CREATE USER rag_user WITH PASSWORD 'secure_password';
CREATE DATABASE rag_vector_db OWNER rag_user;
\c rag_vector_db
CREATE EXTENSION vector;
EOF

# 8. Initialize database
psql -U rag_user -d rag_vector_db -f init-db.sql

# 9. Configure environment
cat > .env << EOF
DB_HOST=localhost
DB_PORT=5432
POSTGRES_DB=rag_vector_db
POSTGRES_USER=rag_user
POSTGRES_PASSWORD=secure_password
ENVIRONMENT=production
DEBUG=false
EOF

# 10. Test installation
python indexer_v2.py stats
```

### 4. Systemd Service (Production)

Create `/etc/systemd/system/rag-api.service`:

```ini
[Unit]
Description=PGVectorRAGIndexer API Service
After=network.target postgresql.service
Requires=postgresql.service

[Service]
Type=simple
User=ragapp
Group=ragapp
WorkingDirectory=/home/ragapp/app
Environment="PATH=/home/ragapp/app/venv/bin"
ExecStart=/home/ragapp/app/venv/bin/python api.py
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal

# Security hardening
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=true
ReadWritePaths=/home/ragapp/app

[Install]
WantedBy=multi-user.target
```

**Manage service**:

```bash
# Enable and start service
sudo systemctl enable rag-api
sudo systemctl start rag-api

# Check status
sudo systemctl status rag-api

# View logs
sudo journalctl -u rag-api -f

# Restart service
sudo systemctl restart rag-api
```

### 5. Nginx Reverse Proxy

Create `/etc/nginx/sites-available/rag-api`:

```nginx
upstream rag_api {
    server 127.0.0.1:8000;
}

server {
    listen 80;
    server_name your-domain.com;

    # Redirect to HTTPS
    return 301 https://$server_name$request_uri;
}

server {
    listen 443 ssl http2;
    server_name your-domain.com;

    # SSL certificates (use Let's Encrypt)
    ssl_certificate /etc/letsencrypt/live/your-domain.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/your-domain.com/privkey.pem;

    # SSL configuration
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers HIGH:!aNULL:!MD5;
    ssl_prefer_server_ciphers on;

    # Logging
    access_log /var/log/nginx/rag-api-access.log;
    error_log /var/log/nginx/rag-api-error.log;

    # Client body size (for file uploads)
    client_max_body_size 50M;

    location / {
        proxy_pass http://rag_api;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;

        # Timeouts
        proxy_connect_timeout 60s;
        proxy_send_timeout 60s;
        proxy_read_timeout 60s;
    }

    # Health check endpoint
    location /health {
        proxy_pass http://rag_api/health;
        access_log off;
    }
}
```

**Enable site**:

```bash
sudo ln -s /etc/nginx/sites-available/rag-api /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl reload nginx
```

### 6. Cloud Deployment (AWS Example)

**Architecture**:
- EC2 instance for API
- RDS PostgreSQL with pgvector
- S3 for document storage
- CloudWatch for monitoring

**Setup**:

```bash
# 1. Launch EC2 instance (Ubuntu 22.04, t3.medium)

# 2. Create RDS PostgreSQL 16 instance
# Enable pgvector extension in parameter group

# 3. Configure security groups
# - Allow port 5432 from EC2 to RDS
# - Allow port 443 from internet to EC2

# 4. SSH to EC2 and install application
ssh -i key.pem ubuntu@ec2-instance

# Follow production server installation steps above
# Update .env with RDS endpoint

# 5. Configure CloudWatch agent
sudo wget https://s3.amazonaws.com/amazoncloudwatch-agent/ubuntu/amd64/latest/amazon-cloudwatch-agent.deb
sudo dpkg -i amazon-cloudwatch-agent.deb

# 6. Setup monitoring
cat > /opt/aws/amazon-cloudwatch-agent/etc/config.json << EOF
{
  "logs": {
    "logs_collected": {
      "files": {
        "collect_list": [
          {
            "file_path": "/var/log/rag-api.log",
            "log_group_name": "/aws/ec2/rag-api",
            "log_stream_name": "{instance_id}"
          }
        ]
      }
    }
  }
}
EOF

sudo /opt/aws/amazon-cloudwatch-agent/bin/amazon-cloudwatch-agent-ctl \
  -a fetch-config -m ec2 -s -c file:/opt/aws/amazon-cloudwatch-agent/etc/config.json
```

## 🔒 Security Best Practices

### 1. Database Security

```bash
# Use strong passwords
POSTGRES_PASSWORD=$(openssl rand -base64 32)

# Restrict network access
# In postgresql.conf:
listen_addresses = 'localhost'

# In pg_hba.conf:
host    all    all    127.0.0.1/32    scram-sha-256
```

### 2. API Security

Add authentication middleware in `api.py`:

```python
from fastapi import Security, HTTPException
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

security = HTTPBearer()

async def verify_token(credentials: HTTPAuthorizationCredentials = Security(security)):
    if credentials.credentials != "your-secret-token":
        raise HTTPException(status_code=401, detail="Invalid token")
    return credentials.credentials

# Apply to endpoints
@app.post("/index", dependencies=[Security(verify_token)])
async def index_document(request: IndexRequest):
    ...
```

### 3. Environment Variables

```bash
# Never commit .env file
echo ".env" >> .gitignore

# Use secrets management in production
# AWS Secrets Manager, HashiCorp Vault, etc.
```

### 4. Rate Limiting

Install and configure:

```bash
pip install slowapi

# In api.py:
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address

limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter
app.add_exception_handler(429, _rate_limit_exceeded_handler)

@app.post("/search")
@limiter.limit("10/minute")
async def search_documents(request: Request, search_req: SearchRequest):
    ...
```

## 📊 Monitoring & Logging

### 1. Application Logging

Configure structured logging:

```python
import logging
import json

class JSONFormatter(logging.Formatter):
    def format(self, record):
        log_data = {
            'timestamp': self.formatTime(record),
            'level': record.levelname,
            'message': record.getMessage(),
            'module': record.module,
            'function': record.funcName
        }
        return json.dumps(log_data)

handler = logging.FileHandler('/var/log/rag-api.log')
handler.setFormatter(JSONFormatter())
logging.getLogger().addHandler(handler)
```

### 2. Database Monitoring

```sql
-- Create monitoring view
CREATE VIEW system_health AS
SELECT
    (SELECT COUNT(*) FROM document_chunks) as total_chunks,
    (SELECT COUNT(DISTINCT document_id) FROM document_chunks) as total_docs,
    (SELECT pg_size_pretty(pg_database_size(current_database()))) as db_size,
    (SELECT COUNT(*) FROM pg_stat_activity WHERE state = 'active') as active_connections;

-- Query slow queries
SELECT query, mean_exec_time, calls
FROM pg_stat_statements
ORDER BY mean_exec_time DESC
LIMIT 10;
```

### 3. Prometheus Metrics

Add metrics endpoint:

```python
from prometheus_client import Counter, Histogram, generate_latest

search_counter = Counter('search_requests_total', 'Total search requests')
search_duration = Histogram('search_duration_seconds', 'Search duration')

@app.get("/metrics")
async def metrics():
    return Response(generate_latest(), media_type="text/plain")
```

## 🔄 Backup & Recovery

### Database Backup

```bash
# Daily backup script
#!/bin/bash
BACKUP_DIR="/backups/postgres"
DATE=$(date +%Y%m%d_%H%M%S)
BACKUP_FILE="$BACKUP_DIR/rag_db_$DATE.sql.gz"

# Create backup
docker exec vector_rag_db pg_dump -U rag_user rag_vector_db | gzip > $BACKUP_FILE

# Keep only last 7 days
find $BACKUP_DIR -name "rag_db_*.sql.gz" -mtime +7 -delete

# Upload to S3 (optional)
aws s3 cp $BACKUP_FILE s3://your-bucket/backups/
```

### Restore

```bash
# Restore from backup
gunzip -c backup.sql.gz | docker exec -i vector_rag_db psql -U rag_user rag_vector_db
```

## 🚀 Performance Tuning

### PostgreSQL Configuration

```ini
# postgresql.conf optimizations
shared_buffers = 2GB
effective_cache_size = 6GB
maintenance_work_mem = 512MB
work_mem = 256MB
max_connections = 100

# Vector-specific
max_parallel_workers_per_gather = 4
```

### Application Tuning

```bash
# Increase connection pool
DB_POOL_SIZE=20
DB_MAX_OVERFLOW=40

# Adjust batch sizes
EMBEDDING_BATCH_SIZE=64
CHUNK_SIZE=1000
```

## 📈 Scaling Strategies

### Horizontal Scaling

1. **Read Replicas**: PostgreSQL streaming replication
2. **Load Balancer**: Nginx or HAProxy for API instances
3. **Caching Layer**: Redis for embedding cache
4. **Message Queue**: Celery for async indexing

### Vertical Scaling

1. **Increase RAM**: More memory for PostgreSQL cache
2. **Better CPU**: Faster embedding generation
3. **SSD Storage**: Faster disk I/O

## 🐛 Troubleshooting

### Common Issues

**Issue**: Connection pool exhausted
```bash
# Solution: Increase pool size
DB_POOL_SIZE=50
DB_MAX_OVERFLOW=100
```

**Issue**: Slow vector search
```sql
-- Solution: Rebuild HNSW index with better parameters
DROP INDEX idx_chunks_embedding_hnsw;
CREATE INDEX idx_chunks_embedding_hnsw ON document_chunks 
USING hnsw (embedding vector_cosine_ops)
WITH (m = 32, ef_construction = 128);
```

**Issue**: Out of memory during indexing
```bash
# Solution: Reduce batch size
EMBEDDING_BATCH_SIZE=16
```

## ✅ Deployment Checklist

- [ ] Database configured and secured
- [ ] Application installed and tested
- [ ] Environment variables configured
- [ ] SSL certificates installed
- [ ] Firewall rules configured
- [ ] Backup system in place
- [ ] Monitoring configured
- [ ] Logging configured
- [ ] Health checks working
- [ ] Documentation updated
- [ ] Team trained on operations

---

**Troubleshooting:** If something goes wrong, check logs and documentation first. Review `docker compose logs -f` for detailed error messages.
