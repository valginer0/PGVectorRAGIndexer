# Security & Network Configuration

PGVectorRAGIndexer is designed to be a local-first application. By default, it prioritizes ease of use and "headless" LAN accessibility.

## Default Configuration (0.0.0.0)

By default, the application binds to `0.0.0.0` (all network interfaces).

**Why?**
This allows you to run the application on a headless server (e.g., a Mac Mini in a closet, a Raspberry Pi, or a desktop PC) and access it from your laptop or phone on the same local network (LAN).

**The Risk**
Because it listens on all interfaces, if you connect to a **Public Wi-Fi** network (like a coffee shop or airport), other users on that same network could theoretically access the application if they know your IP address and port (default: 8000).

## How to Secure It

### 1. Use a Firewall (Recommended)
The best way to secure the application without breaking LAN functionality is to use your operating system's firewall.

-   **Windows**: Configure "Windows Defender Firewall" to allow the app on "Private" networks but block it on "Public" networks.
-   **macOS**: Use the built-in Firewall in System Settings.
-   **Linux**: Use `ufw` (Uncomplicated Firewall) to deny incoming traffic on port 8000 from public interfaces.

### 2. Lock to Localhost (Maximum Security)
If you **only** want to access the app from the same computer it is running on (no LAN access), you can force it to listen only on `127.0.0.1`.

**Docker Users:**
Edit `docker-compose.yml`:
```yaml
ports:
  - "127.0.0.1:8000:8000"  # Change from "8000:8000"
```

**Python / Manual Users:**
Edit `config.py` or set the environment variable:
```bash
export API_HOST=127.0.0.1
```

## Model Context Protocol (MCP)
If you use the MCP server (`mcp_server.py`) for AI agents, it uses `stdio` (standard input/output) communication. This is inherently secure and does not open any network ports, regardless of the API configuration.
