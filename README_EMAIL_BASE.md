# Email Indexing Base (Provider-Agnostic)

This branch contains reusable, provider-agnostic infrastructure for email indexing and search.

> This branch is infrastructure-only and is not exposed to users.

**Design principle:** Email is treated as a content source, not a mail client.

## What This Branch Contains

```
connectors/email/
├── __init__.py          # Exports: EmailProcessor, EmailSearchResult, search_emails
├── processor.py         # Thread cleaning, HTML-to-text, chunking
├── retriever.py         # EmailSearchResult dataclass + search_emails function
└── schema_email.sql     # Database schema (self-contained)
```

- `beautifulsoup4` dependency — For HTML parsing

## What This Branch Does NOT Contain

- ❌ Any provider-specific OAuth flows
- ❌ Any Microsoft/Outlook/MSAL implementation
- ❌ Any Gmail/Google implementation
- ❌ Any IMAP implementation
- ❌ Any UI or user-facing features

## Guarantees

- No dependency on Microsoft, Google, or any provider SDK
- No authentication logic
- No provider-specific configuration requirements
- Safe to merge into other feature branches

## Email Locator Format (source_uri)

Emails follow the same pattern as documents: `source_uri` is the locator string.

**The locator is built at index time by the ingestor**, not at search time.
This means search returns `source_uri` directly, just like document search.

**Format:**
```
<Provider>/<Folder-or-Label>/<Subject> (<From>, <YYYY-MM-DD>)
```

**Examples:**
- `Gmail/Inbox/Re: licensing question (Vitaly, 2026-01-02)`
- `Outlook/Inbox/Contract update (Legal Dept, 2025-11-18)`
- `IMAP/INBOX/Weekly report (System, 2026-01-01)`

**Why this design:**
- Consistent with documents (source_uri pattern)
- No provider-specific logic at search time
- Ingestor controls formatting
- UI can render emails and documents identically

## Building On This Branch

To add a new email provider (e.g., Gmail):

1. Branch from `feature/email-indexing-base`
2. Add provider-specific ingestor (OAuth, API calls)
3. Add provider-specific config fields to `EmailConfig`
4. Reuse `EmailProcessor` for text processing
5. Reuse `search_emails()` for search

## Related Branches

| Branch | Purpose |
|--------|---------|
| `main` | Production (no email features) |
| `feature/outlook-indexing` | Frozen Outlook/MSAL implementation |
| `feature/email-indexing-base` | This branch (provider-agnostic base) |
