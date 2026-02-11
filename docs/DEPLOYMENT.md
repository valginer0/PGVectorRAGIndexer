# PGVectorRAGIndexer — Deployment Guide

## Architecture Overview

PGVectorRAGIndexer supports two deployment modes:

1. **Local (default)** — Desktop app runs Docker containers on the same machine
2. **Split Deployment** — Server (Docker) runs on one machine, desktop clients connect remotely

```
┌─────────────────┐         ┌─────────────────────────────────┐
│  Desktop Client  │  HTTP   │         Server (Docker)          │
│  (Windows/macOS/ │ ──────► │  ┌─────────┐  ┌──────────────┐ │
│   Linux)         │  :8000  │  │ API      │  │ PostgreSQL   │ │
│                  │ ◄────── │  │ (uvicorn)│  │ + pgvector   │ │
│  No Docker req'd │         │  └─────────┘  └──────────────┘ │
└─────────────────┘         └─────────────────────────────────┘
```

---

## Platform Support Matrix

### Server Platforms

| Platform | Support Level | Notes |
|----------|:------------:|-------|
| **Linux** (Docker) | ✅ Supported | Primary target. Use `server-setup.sh`. |
| **macOS** (Docker Desktop) | ✅ Supported | Works, but Docker Desktop licensing applies for commercial use. |
| **Windows** (WSL2 + Docker) | ✅ Supported | Use `server-setup-wsl.sh`. Requires WSL2 + Docker Desktop. |
| **Windows** (bare Python) | ❌ Not supported | pgvector native build on Windows is fragile. Do not attempt. |
| **NAS** (Synology/QNAP) | ⚠️ Best-effort | Community-tested via Docker. Not officially supported. |

### Desktop Client Platforms

| Platform | Support Level | Docker Required? |
|----------|:------------:|:----------------:|
| **Windows** | ✅ Supported | No (remote mode) |
| **macOS** | ✅ Supported | No (remote mode) |
| **Linux** | ✅ Supported | No (remote mode) |

---

## Quick Start: Server Setup

### Linux / macOS

```bash
# One-line install
curl -fsSL https://raw.githubusercontent.com/valginer0/PGVectorRAGIndexer/main/server-setup.sh | bash

# Or with options
bash server-setup.sh --port 8000 --generate-key
```

### Windows (WSL2)

```bash
# From inside WSL2
bash server-setup-wsl.sh --port 8000 --generate-key
```

### Manual Setup

```bash
git clone https://github.com/valginer0/PGVectorRAGIndexer.git
cd PGVectorRAGIndexer
docker compose up -d
```

---

## Quick Start: Desktop Client (Remote Mode)

### macOS / Linux

```bash
# One-line install with remote backend
curl -fsSL https://raw.githubusercontent.com/valginer0/PGVectorRAGIndexer/main/bootstrap_desktop_app.sh \
  | bash -s -- --remote-backend http://your-server:8000
```

### Windows (PowerShell)

```powershell
.\bootstrap_desktop_app.ps1 -RemoteBackend "http://your-server:8000"
```

### Manual Configuration

1. Install the desktop app normally
2. Open **Settings** tab
3. Switch to **Remote Server** mode
4. Enter the server URL (e.g., `http://192.168.1.100:8000`)
5. Enter your API key

---

## Server-Side CLI

The server includes CLI tools for headless indexing — no desktop GUI required:

```bash
# Index a document (run inside the app container or with venv activated)
docker exec -it vector_rag_app python indexer_v2.py index /app/documents/report.pdf

# List indexed documents
docker exec -it vector_rag_app python indexer_v2.py list

# Search from command line
docker exec -it vector_rag_app python retriever_v2.py "your query"

# Batch reindex all documents
docker exec -it vector_rag_app python scripts/reindex_all.py

# MCP server for AI agent integration
docker exec -it vector_rag_app python mcp_server.py
```

---

## Version Compatibility

The desktop client checks version compatibility on connect via `GET /api/version`:

```json
{
  "server_version": "2.5.0",
  "api_version": "1",
  "min_client_version": "2.4.0",
  "max_client_version": "99.99.99"
}
```

- Client warns if its version is below `min_client_version`
- Client warns if its version is above `max_client_version`
- API version `"1"` is the current stable API

---

## API Key Management

### Generate a Key (Server-Side)

```bash
# Via API
curl -X POST http://localhost:8000/api/v1/api-keys \
  -H "Content-Type: application/json" \
  -d '{"name": "alice-laptop"}'

# Via server-setup.sh
bash server-setup.sh --generate-key
```

### Use a Key (Client-Side)

1. Copy the key from the server output
2. In the desktop app: **Settings** → **API Key** → paste
3. Or via bootstrap: `--remote-backend http://server:8000` (key entered in Settings)

---

## Security Considerations

- **API keys** are required for all data endpoints when connecting remotely
- Keys are hashed (SHA-256) before storage — the raw key is shown only once
- Use HTTPS (via reverse proxy like nginx/Caddy) for production deployments
- The API binds to `0.0.0.0` by default — restrict with firewall rules if needed
- Consider a reverse proxy for TLS termination:

```nginx
# Example nginx config
server {
    listen 443 ssl;
    server_name rag.example.com;

    ssl_certificate /etc/letsencrypt/live/rag.example.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/rag.example.com/privkey.pem;

    location / {
        proxy_pass http://localhost:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
}
```

---

## Troubleshooting

### Server won't start
```bash
docker logs vector_rag_app    # Check app logs
docker logs vector_rag_db     # Check database logs
docker compose ps              # Check container status
```

### Client can't connect
1. Verify server URL is correct (include port, e.g., `http://192.168.1.100:8000`)
2. Check firewall allows the port
3. Test with: `curl http://server:8000/api`
4. Verify API key is correct

### WSL2: Port not accessible from network
```powershell
# In PowerShell as admin — allow port through Windows Firewall
netsh advfirewall firewall add rule name="PGVectorRAG" dir=in action=allow protocol=TCP localport=8000
```
