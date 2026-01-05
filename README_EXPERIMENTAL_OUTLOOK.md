# ⚠️ Outlook Email Connector - EXPERIMENTAL

> **Status**: Not supported / Not shipped / For dev use only
>
> **Frozen**: This branch is not being maintained and may break at any time.
>
> This connector is intentionally excluded from the main product and documentation.

This branch contains an experimental Microsoft Outlook/Exchange email connector using the Graph API.

## Why Not Shipped

The Microsoft Azure App Registration system proved too complex for a simple desktop app:

1. **Permission Maze**: Delegated permissions for `Mail.Read` require specific consent flows that differ between personal accounts (MSA) and work/school accounts (Azure AD)

2. **MSA Limitations / Licensing Variability**: In our testing, personal Microsoft accounts (MSA) had access limitations and may require a Microsoft 365 subscription for mailbox API access

3. **Empty 401 Responses**: Graph API returns 401 with empty body even with valid tokens when permissions aren't properly configured

4. **Unpredictable Changes**: Microsoft frequently reorganizes Azure Portal, making setup instructions outdated

## If You Want to Try Anyway

### Azure App Registration Setup

1. Go to [Azure Portal](https://portal.azure.com) → **App Registrations** → **New Registration**
2. Name: `PGVectorRAGIndexer`
3. Supported account types: Choose based on your users
4. Redirect URI: Leave empty (device-code flow)

### Required Settings

1. **Authentication** → **Advanced Settings**:
   - Set "Allow public client flows" = **Yes**

2. **API Permissions** → **Add a permission**:
   - Microsoft Graph → Delegated permissions
   - Add: `Mail.Read`, `User.Read`
   - Grant admin consent (if organizational account)

3. **Certificates & secrets**:
   - NOT needed (device-code flow uses public client)

### Environment Variables

```bash
EMAIL_ENABLED=true
EMAIL_CLIENT_ID=<your-app-client-id>
EMAIL_TENANT_ID=<your-tenant-id-or-common>
```

### Known Issues

- Every request returns 401 with empty body → permissions not configured correctly
- Silent auth succeeds but token is rejected → consent not granted
- Works in browser auth but fails in API calls → scopes mismatch

## Alternative: Gmail

Consider `feature/email-indexing-base` with Gmail API instead - cleaner OAuth, free, better documentation.
