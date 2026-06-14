# JWT Expiry Runbook

JWT expiry errors usually mean the access token is older than the configured
session lifetime. The application should reject expired tokens, request a fresh
token, and avoid silently extending access without validation.

Operators should check clock skew between the API server and identity provider
before changing token lifetime settings. A sudden spike in JWT expiry failures
can also indicate stale desktop clients or a failed refresh-token exchange.

Do not disable token expiration to work around login problems.
