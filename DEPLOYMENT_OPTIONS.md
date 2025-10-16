# Deployment Options

PGVectorRAGIndexer supports multiple deployment methods to fit different environments and preferences.

## Quick Comparison

| Feature | Windows Native | WSL/Linux | macOS |
|---------|---------------|-----------|-------|
| **Container Runtime** | Docker Desktop or Rancher Desktop | Docker or Rancher Desktop | Docker Desktop or Rancher Desktop |
| **Setup Script** | `docker-run.ps1` (PowerShell) | `docker-run.sh` (Bash) | `docker-run.sh` (Bash) |
| **Deployment Location** | `%USERPROFILE%\pgvector-rag\` | `~/pgvector-rag/` | `~/pgvector-rag/` |
| **File Upload** | ✅ From ANY Windows path | ✅ From ANY Linux path | ✅ From ANY macOS path |
| **WSL Required** | ❌ No | N/A | N/A |
| **Performance** | Native | Native | Native |

## Supported Container Runtimes

Both of these work identically with PGVectorRAGIndexer:

### Docker Desktop
- **Website**: https://www.docker.com/products/docker-desktop
- **License**: Free for personal use, paid for enterprise
- **Platforms**: Windows, macOS, Linux
- **Features**: Full Docker ecosystem, Kubernetes support, GUI

### Rancher Desktop
- **Website**: https://rancherdesktop.io/
- **License**: Free and open-source (Apache 2.0)
- **Platforms**: Windows, macOS, Linux
- **Features**: Lightweight, Kubernetes support, choice of container runtime
- **Note**: Select "dockerd (moby)" in Settings → Container Engine for Docker compatibility

## Installation Methods

### 1. Windows Native (Recommended for Windows Users)

**Advantages:**
- ✅ No WSL required
- ✅ Native Windows performance
- ✅ Direct access to all Windows drives
- ✅ Simpler setup

**Setup:**
```powershell
# PowerShell
Invoke-WebRequest -Uri "https://raw.githubusercontent.com/valginer0/PGVectorRAGIndexer/main/docker-run.ps1" -OutFile "$env:TEMP\docker-run.ps1"
PowerShell -ExecutionPolicy Bypass -File "$env:TEMP\docker-run.ps1"
```

📖 **See [WINDOWS_SETUP.md](WINDOWS_SETUP.md)**

### 2. WSL/Linux

**Advantages:**
- ✅ Linux-native tools
- ✅ Better for development
- ✅ Consistent with Linux servers

**Setup:**
```bash
curl -fsSL https://raw.githubusercontent.com/valginer0/PGVectorRAGIndexer/main/docker-run.sh | bash
```

📖 **See [QUICK_START.md](QUICK_START.md)**

### 3. macOS

**Advantages:**
- ✅ Native macOS performance
- ✅ Unix-like environment

**Setup:**
```bash
curl -fsSL https://raw.githubusercontent.com/valginer0/PGVectorRAGIndexer/main/docker-run.sh | bash
```

📖 **See [QUICK_START.md](QUICK_START.md)**

## File Indexing Options

Regardless of deployment method, you have two ways to index files:

### Option 1: Upload from ANY Location (Recommended)

Works from **any directory** on your system:

**Windows:**
```powershell
curl -X POST "http://localhost:8000/upload-and-index" `
  -F "file=@C:\Users\YourName\Documents\file.pdf"
```

**Linux/macOS:**
```bash
curl -X POST "http://localhost:8000/upload-and-index" \
  -F "file=@/home/user/documents/file.pdf"
```

### Option 2: Place in Documents Folder

Copy files to the deployment directory:

**Windows:** `%USERPROFILE%\pgvector-rag\documents\`
**Linux/macOS:** `~/pgvector-rag/documents/`

Then index via API:
```bash
curl -X POST "http://localhost:8000/index" \
  -H "Content-Type: application/json" \
  -d '{"source_uri": "/app/documents/file.pdf"}'
```

## Which Should You Choose?

### Choose Windows Native If:
- ✅ You primarily use Windows
- ✅ You don't need WSL for other tasks
- ✅ You want the simplest setup
- ✅ You want to index files from Windows Explorer

### Choose WSL/Linux If:
- ✅ You're developing or modifying the code
- ✅ You prefer Linux tools
- ✅ You need to match production Linux environment
- ✅ You already use WSL for other projects

### Choose Docker Desktop If:
- ✅ You need official Docker support
- ✅ You want GUI management
- ✅ You need Kubernetes integration

### Choose Rancher Desktop If:
- ✅ You prefer open-source software
- ✅ You want a lighter-weight solution
- ✅ You need more control over container runtime
- ✅ You're cost-conscious (free for all use cases)

## Switching Between Methods

You can run multiple deployments simultaneously on different ports:

**Windows Native on port 8000:**
```powershell
# In PowerShell
cd $env:USERPROFILE\pgvector-rag
docker compose up -d
```

**WSL on port 8001:**
```bash
# In WSL
cd ~/pgvector-rag
# Edit .env to set API_PORT=8001
docker compose up -d
```

## Need Help?

- **Windows Setup**: [WINDOWS_SETUP.md](WINDOWS_SETUP.md)
- **Linux/WSL Setup**: [QUICK_START.md](QUICK_START.md)
- **Usage Guide**: [USAGE_GUIDE.md](USAGE_GUIDE.md)
- **GitHub Issues**: https://github.com/valginer0/PGVectorRAGIndexer/issues
