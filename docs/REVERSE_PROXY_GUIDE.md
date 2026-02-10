# Reverse Proxy & TLS Guide

How to put PGVectorRAGIndexer behind a reverse proxy with HTTPS for secure remote access.

---

## Why a Reverse Proxy?

When exposing the API beyond `localhost` (e.g., for Team edition multi-client setups), you need:

- **TLS encryption** — protect API keys and document content in transit
- **Domain name** — friendly URL instead of `http://192.168.1.50:8000`
- **Rate limiting / IP filtering** — additional security layer
- **Automatic certificate renewal** — via Let's Encrypt

The API itself runs plain HTTP on `localhost:8000`. The reverse proxy terminates TLS and forwards traffic.

---

## Option 1: Caddy (Recommended)

Caddy automatically provisions and renews Let's Encrypt certificates.

### Install

```bash
# Debian/Ubuntu
sudo apt install -y caddy

# Or via official repo: https://caddyserver.com/docs/install
```

### Caddyfile

Create `/etc/caddy/Caddyfile`:

```
ragvault.example.com {
    reverse_proxy localhost:8000

    # Optional: restrict to specific IPs
    # @blocked not remote_ip 10.0.0.0/8 192.168.0.0/16
    # respond @blocked 403

    # Optional: rate limiting (requires caddy-ratelimit plugin)
    # rate_limit {uri} 60r/m
}
```

### Start

```bash
sudo systemctl enable --now caddy
```

Caddy will automatically obtain a TLS certificate for `ragvault.example.com`.

### Self-Signed (LAN Only)

For internal networks without a public domain:

```
https://ragvault.local:443 {
    tls internal
    reverse_proxy localhost:8000
}
```

Add `ragvault.local` to `/etc/hosts` on each client machine, and trust the Caddy root CA.

---

## Option 2: Nginx

### Install

```bash
sudo apt install -y nginx certbot python3-certbot-nginx
```

### Configuration

Create `/etc/nginx/sites-available/pgvector`:

```nginx
server {
    listen 80;
    server_name ragvault.example.com;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;

        # Large file uploads (OCR PDFs can be big)
        client_max_body_size 500M;
        proxy_read_timeout 7200;
    }
}
```

### Enable & Get Certificate

```bash
sudo ln -s /etc/nginx/sites-available/pgvector /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl reload nginx

# Obtain Let's Encrypt certificate
sudo certbot --nginx -d ragvault.example.com
```

### Self-Signed (LAN Only)

```bash
sudo openssl req -x509 -nodes -days 365 -newkey rsa:2048 \
    -keyout /etc/ssl/private/pgvector.key \
    -out /etc/ssl/certs/pgvector.crt \
    -subj "/CN=ragvault.local"
```

Then update the Nginx config to use `ssl_certificate` and `ssl_certificate_key`.

---

## Enabling API Key Authentication

Once the proxy is set up, enable auth so that only clients with a valid API key can access the API:

```bash
# On the server
export API_REQUIRE_AUTH=true
```

Or in `docker-compose.yml`:

```yaml
services:
  api:
    environment:
      - API_REQUIRE_AUTH=true
```

### Create the First API Key

```bash
# Via the API (before auth is enforced, or from localhost)
curl -X POST "http://localhost:8000/api/keys?name=Admin" | jq
```

Save the returned key — it is shown **only once**.

### Desktop Client Configuration

In the desktop app Settings, enter:
- **Backend URL**: `https://ragvault.example.com`
- **API Key**: the key from the step above

---

## Security Checklist

- [ ] TLS enabled (Let's Encrypt or self-signed)
- [ ] `API_REQUIRE_AUTH=true` set in environment
- [ ] At least one API key created
- [ ] Firewall: only ports 80/443 open (not 8000)
- [ ] API keys distributed securely to team members (not via email/Slack)
- [ ] Consider IP allow-listing if all clients are on the same network

---

## Troubleshooting

| Symptom | Cause | Fix |
|---------|-------|-----|
| `502 Bad Gateway` | API not running | Check `docker compose ps` or `systemctl status pgvector` |
| `413 Request Entity Too Large` | Nginx body size limit | Increase `client_max_body_size` |
| `504 Gateway Timeout` | Large file indexing | Increase `proxy_read_timeout` |
| Certificate warnings | Self-signed cert | Trust the CA on client machines |
| `403 Forbidden` | Missing API key | Add `X-API-Key` header or configure in desktop app |
