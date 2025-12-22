# Windows Native Setup Guide

This guide is for Windows users who want to run PGVectorRAGIndexer **without WSL**, using Docker Desktop for Windows directly.

## Prerequisites

1. **Windows 10/11** (64-bit)
2. **Container Runtime** (choose one):
   - **Docker Desktop for Windows**: https://www.docker.com/products/docker-desktop
   - **Rancher Desktop**: https://rancherdesktop.io/ (free, open-source alternative)
   - Install and start your chosen runtime
   - Ensure it's running (check system tray icon)
   - Both work identically with this project

## Quick Start

### Option 1: One-Liner Bootstrap (Recommended)

Open **PowerShell** (admin not required) and run:

```powershell
irm https://raw.githubusercontent.com/valginer0/PGVectorRAGIndexer/main/bootstrap_desktop_app.ps1 | iex
```

The bootstrap script:
- Clones/updates `%USERPROFILE%\PGVectorRAGIndexer`
- Installs desktop dependencies
- Refreshes containers using the latest production image
- Launches the desktop app once setup completes

Afterwards, use the unified wrapper for daily tasks:

```powershell
cd %USERPROFILE%\PGVectorRAGIndexer
./manage.ps1 -Action update      # refresh containers (prod by default)
./manage.ps1 -Action run         # relaunch desktop app anytime
./manage.ps1 -Action update -Channel dev  # optional dev build testing
```

More examples live in [WORKFLOW_GUIDE.md](WORKFLOW_GUIDE.md#windows-clients--testers).

### Option 2: Manual Setup

1. **Create deployment directory:**
```powershell
mkdir $env:USERPROFILE\pgvector-rag
cd $env:USERPROFILE\pgvector-rag
```

2. **Create `.env` file:**
```powershell
@"
POSTGRES_USER=rag_user
POSTGRES_PASSWORD=rag_password
POSTGRES_DB=rag_vector_db
DB_HOST=db
DB_PORT=5432
EMBEDDING_MODEL_NAME=all-MiniLM-L6-v2
EMBEDDING_DIMENSION=384
API_HOST=0.0.0.0
API_PORT=8000
"@ | Out-File -FilePath .env -Encoding UTF8
```

3. **Create `docker-compose.yml`:**
```powershell
Invoke-WebRequest -Uri "https://raw.githubusercontent.com/valginer0/PGVectorRAGIndexer/main/docker-compose.yml" -OutFile docker-compose.yml
```

4. **Download database initialization:**
```powershell
Invoke-WebRequest -Uri "https://raw.githubusercontent.com/valginer0/PGVectorRAGIndexer/main/init-db.sql" -OutFile init-db.sql
```

5. **Create documents directory:**
```powershell
mkdir documents
```

6. **Start services:**
```powershell
docker compose up -d
```

7. **Initialize database:**
```powershell
Start-Sleep -Seconds 5
Get-Content init-db.sql | docker exec -i vector_rag_db psql -U rag_user -d rag_vector_db
```

## Usage

### Access the API

- **API Endpoint:** http://localhost:8000
- **Interactive Docs:** http://localhost:8000/docs
- **Health Check:** http://localhost:8000/health

### Index Files from ANY Windows Location

**The best feature:** You can index files from anywhere on your Windows system!

```powershell
# From your Documents folder
curl -X POST "http://localhost:8000/upload-and-index" `
  -F "file=@C:\Users\YourName\Documents\report.pdf"

# From Desktop
curl -X POST "http://localhost:8000/upload-and-index" `
  -F "file=@C:\Users\YourName\Desktop\presentation.pptx"

# From D: drive
curl -X POST "http://localhost:8000/upload-and-index" `
  -F "file=@D:\Projects\data.xlsx"

# From network drive
curl -X POST "http://localhost:8000/upload-and-index" `
  -F "file=@\\server\share\document.docx"
```

### Or Place Files in Documents Folder

```powershell
# Copy file to documents folder
Copy-Item "C:\path\to\file.pdf" "$env:USERPROFILE\pgvector-rag\documents\"

# Index it
curl -X POST "http://localhost:8000/index" `
  -H "Content-Type: application/json" `
  -d '{"source_uri": "/app/documents/file.pdf"}'
```

### Search Documents

```powershell
curl -X POST "http://localhost:8000/search" `
  -H "Content-Type: application/json" `
  -d '{\"query\": \"What is machine learning?\", \"top_k\": 5}'
```

### List Indexed Documents

```powershell
curl http://localhost:8000/documents
```

### Get Statistics

```powershell
curl http://localhost:8000/stats
```

## Management Commands

### View Logs
```powershell
cd $env:USERPROFILE\pgvector-rag
docker compose logs -f
```

### Stop Services
```powershell
docker compose down
```

### Restart Services
```powershell
docker compose restart
```

### Update to Latest Version
```powershell
docker compose pull
docker compose up -d
```

### Remove Everything (including data)
```powershell
docker compose down -v
Remove-Item -Recurse -Force $env:USERPROFILE\pgvector-rag
```

## Troubleshooting

### Container Runtime Not Running
**Error:** `Cannot connect to the Docker daemon`

**Solution:** 
- **Docker Desktop**: Start from the Start menu and wait for it to fully start
- **Rancher Desktop**: Start from the Start menu, ensure "dockerd (moby)" is selected in Settings → Container Engine

### Port Already in Use
**Error:** `port is already allocated`

**Solution:** Change the port in `.env` file:
```
API_PORT=8001
```
Then restart: `docker compose up -d`

### Permission Denied
**Error:** `Access is denied`

**Solution:** Run PowerShell as Administrator:
1. Right-click PowerShell
2. Select "Run as Administrator"

### curl Not Found
**Error:** `curl : The term 'curl' is not recognized`

**Solution:** Use PowerShell's `Invoke-WebRequest` or install curl:
```powershell
# Alternative to curl
Invoke-RestMethod -Uri "http://localhost:8000/health" -Method Get
```

Or install curl via Windows Package Manager:
```powershell
winget install curl
```

## Supported File Types

- `.txt` - Plain text
- `.pdf` - PDF documents
- `.docx` - Word documents
- `.xlsx`, `.csv` - Spreadsheets
- `.html` - HTML files
- `.pptx` - PowerPoint presentations

## Directory Structure

```
%USERPROFILE%\pgvector-rag\
├── .env                    # Environment variables
├── docker-compose.yml      # Docker configuration
├── init-db.sql            # Database schema
└── documents\             # Optional: Place files here
```

## Next Steps

- See [USAGE_GUIDE.md](USAGE_GUIDE.md) for advanced features
- See [README.md](README.md) for architecture details
- Visit http://localhost:8000/docs for interactive API documentation

## Troubleshooting Resources

If something goes wrong, check logs and documentation first:

- **Logs**: `docker compose logs -f`
- **Documentation**: [README.md](README.md) and [USAGE_GUIDE.md](USAGE_GUIDE.md)
- **GitHub Issues**: https://github.com/valginer0/PGVectorRAGIndexer/issues
