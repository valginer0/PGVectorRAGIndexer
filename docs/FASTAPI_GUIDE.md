# FastAPI Usage Guide

`PGVectorRAGIndexer` uses **FastAPI** as its core web framework. The project makes extensive use of both its **Dependency Injection** and **Middleware** systems. Here is a breakdown of how they are currently used in the project:

## 1. Dependency Injection (`Depends`)

Dependency Injection is heavily used in the route definitions (e.g., `routers/search_api.py`, `routers/indexing_api.py`, etc.) primarily for **authentication and authorization**.

Common dependencies injected into routes include:

*   `Depends(require_api_key)`: Ensures the request has a valid API key.
*   `Depends(require_team_edition)`: Restricts specific endpoints to the Team Edition.
*   `Depends(require_admin)`: Ensures the user has administrative privileges.
*   `Depends(require_permission("..."))`: Finer-grained role-based access control (e.g., used in `identity_api.py`).

## 2. Middleware

Middleware is used in `api.py` (and specifically defined in places like `license_overage.py`) for global, cross-cutting concerns that need to intercept every request/response:

*   **`CORSMiddleware`**: Handles Cross-Origin Resource Sharing.
*   **`TrustedHostMiddleware`**: Restricts allowed `Host` headers for security.
*   **`RateLimitMiddleware`**: Enforces the configured per-minute API rate limit and adds `X-RateLimit-*` and `Retry-After` headers. Trusted bulk indexing/probe/scan calls bypass this generic limiter so large imports are not throttled; the Desktop App also retries residual 429 responses for those bulk operations. Server-side scheduled scans run inside the backend scheduler rather than through the HTTP limiter.
*   **`LicenseOverageMiddleware`**: A custom seat-overage warning middleware that injects specific headers if a large organization exceeds their allowed seat count.
*   **`DemoModeMiddleware`**: Intercepts and blocks write operations when the application is running in a read-only demo mode (`DEMO_MODE=1`).

## When to use which:

*   Use **Dependency Injection** when you need to validate something specific to a route, extract data (like the current user or database session) to pass into the endpoint function, or when only *certain* routes need the logic.
*   Use **Middleware** when you need to run logic globally across *all* requests (like logging, setting global security headers, or the global read-only demo mode).
