# Frequently Asked Questions

## General

### Does PGVectorRAGIndexer include installation or support services?

No. PGVectorRAGIndexer is designed as a self-service product. The focus is on clear documentation and reliable local operation rather than ongoing services.

This approach keeps the project sustainable, allows faster feature development, and ensures the software remains affordable and private by design.

### What platforms are supported?

- **macOS** (including Catalina 10.15+)
- **Windows** (10/11)
- **Linux/Unix** (Ubuntu, Debian, and other distributions)

### What file types are supported?

- **PDFs** (native text and scanned via OCR)
- **Text files** (.txt)
- **Markdown** (.md)
- **Code files** (.py, .js, .go, etc.)
- **Other text-based formats**

OCR is used automatically when required for scanned documents.

### Does my data leave my machine?

No. All indexing and search runs locally. Your documents are processed on your machine and stored in a local PostgreSQL database.

---

## Technical

### What container runtimes are supported?

PGVectorRAGIndexer works with any Docker-compatible container runtime:

- **Docker Desktop** (most common)
- **Rancher Desktop** (free alternative)
- **Podman Desktop** (another free option)
- **Docker Engine** (Linux native)
- **Docker in WSL** (Windows Subsystem for Linux)

### What embedding model is used?

The default configuration uses local embedding models. No external API calls are required for document indexing.

### Can I use this for commercial purposes?

Yes. Commercial licensing is available for teams and organizations. See [DEPLOYMENT.md](DEPLOYMENT.md) for team deployment options.

---

## Troubleshooting

### The desktop app won't start

1. Ensure Docker (or compatible runtime) is running
2. Check that Python 3.10+ is installed
3. Try reinitializing: `./manage.sh update` (Linux/macOS) or `./manage.ps1 -Action update` (Windows)

### Files aren't being indexed

1. Check the file format is supported
2. For PDFs, ensure they're not password-protected (encrypted PDFs are detected and listed separately)
3. Check the upload log for specific errors

For more help, see:
- [INSTALL_DESKTOP_APP.md](INSTALL_DESKTOP_APP.md) - Installation guide
- [USAGE_GUIDE.md](USAGE_GUIDE.md) - Detailed usage instructions
