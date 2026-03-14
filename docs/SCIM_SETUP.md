# SCIM 2.0 Provisioning Setup

PGVectorRAGIndexer includes a SCIM 2.0 server (RFC 7643/7644) for automated user
provisioning and deprovisioning from enterprise identity providers.

When enabled, your identity provider (Okta, Azure AD, OneLogin, etc.) can
automatically create, update, and deactivate user accounts in PGVectorRAGIndexer
whenever changes happen in your company directory.

## Quick Start

### 1. Enable SCIM on the server

Add these environment variables to your `.env` file or container configuration:

```bash
SCIM_ENABLED=true
SCIM_BEARER_TOKEN=<generate-a-strong-random-token>
SCIM_DEFAULT_ROLE=user          # optional, default: "user"
```

Generate a secure token:

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(48))"
```

Restart the server after changing these values.

### 2. Verify SCIM is active

```bash
curl -H "Authorization: Bearer <your-token>" \
     https://your-server/scim/v2/ServiceProviderConfig
```

You should get a JSON response with `patch.supported: true`, `filter.supported: true`, etc.

### 3. Configure your identity provider

See the provider-specific guides below.

---

## SCIM Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/scim/v2/ServiceProviderConfig` | Server capabilities |
| GET | `/scim/v2/Schemas` | User schema definition |
| GET | `/scim/v2/ResourceTypes` | Supported resource types |
| GET | `/scim/v2/Users` | List users (with filtering and pagination) |
| GET | `/scim/v2/Users/{id}` | Get single user |
| POST | `/scim/v2/Users` | Create (provision) user |
| PUT | `/scim/v2/Users/{id}` | Replace user |
| PATCH | `/scim/v2/Users/{id}` | Partial update |
| DELETE | `/scim/v2/Users/{id}` | Deactivate (soft-delete) user |

All endpoints require `Authorization: Bearer <SCIM_BEARER_TOKEN>`.

## Schema Mapping

| SCIM Attribute | PGVectorRAGIndexer Field | Notes |
|---------------|-------------------------|-------|
| `userName` | `email` | Primary identifier |
| `emails[0].value` | `email` | Takes priority over userName if present |
| `displayName` | `display_name` | |
| `active` | `is_active` | DELETE sets this to false |
| Custom extension: `role` | `role` | See custom schema below |

### Custom Role Extension

PGVectorRAGIndexer uses a custom SCIM schema extension for role assignment:

```
urn:ietf:params:scim:schemas:extension:pgvector:2.0:User
```

To set a user's role during provisioning, include:

```json
{
  "schemas": [
    "urn:ietf:params:scim:schemas:core:2.0:User",
    "urn:ietf:params:scim:schemas:extension:pgvector:2.0:User"
  ],
  "userName": "alice@example.com",
  "displayName": "Alice Smith",
  "active": true,
  "urn:ietf:params:scim:schemas:extension:pgvector:2.0:User": {
    "role": "admin"
  }
}
```

If no role extension is provided, the user gets `SCIM_DEFAULT_ROLE` (default: `"user"`).

---

## Okta Setup

### Prerequisites
- Okta admin account
- PGVectorRAGIndexer server accessible from Okta (public URL or VPN)

### Steps

1. **Okta Admin Console** > Applications > Create App Integration
2. Select **SCIM 2.0 Test App (Header Auth)** from the catalog
   - If not available: Create a **SWA** app, then enable SCIM provisioning in the Provisioning tab
3. **General Settings**:
   - App label: `PGVectorRAGIndexer`
4. **Provisioning** tab > Configure API Integration:
   - SCIM connector base URL: `https://your-server/scim/v2`
   - Unique identifier field: `userName`
   - Authentication Mode: HTTP Header
   - Authorization: `Bearer <your-SCIM_BEARER_TOKEN>`
5. Click **Test API Credentials** — should show "Verified"
6. **To App** settings — enable:
   - Create Users
   - Update User Attributes
   - Deactivate Users
7. **Attribute Mapping**:
   - `userName` → user email
   - `displayName` → user display name
   - For role mapping, add custom attribute:
     - SCIM attribute: `urn:ietf:params:scim:schemas:extension:pgvector:2.0:User.role`
     - Map to Okta profile attribute or set a default value
8. **Assignments** tab: Assign users or groups to the app

### Verification

After assigning a user in Okta:
1. Check PGVectorRAGIndexer's Users & Roles panel — user should appear
2. Check Activity log for `user.scim_provisioned` event
3. Unassign the user in Okta — user should show as inactive

---

## Azure AD (Microsoft Entra ID) Setup

### Prerequisites
- Azure AD admin account (P1 or P2 license for provisioning)
- PGVectorRAGIndexer server accessible from Azure

### Steps

1. **Azure Portal** > Microsoft Entra ID > Enterprise Applications > New application
2. Create your own application > name: `PGVectorRAGIndexer` > Non-gallery
3. **Provisioning** > Get started:
   - Provisioning Mode: **Automatic**
   - Tenant URL: `https://your-server/scim/v2`
   - Secret Token: `<your-SCIM_BEARER_TOKEN>`
4. Click **Test Connection** — should succeed
5. **Mappings** > Provision Azure Active Directory Users:
   - `userPrincipalName` → `userName`
   - `displayName` → `displayName`
   - `mail` → `emails[type eq "work"].value`
   - (Optional) Add custom mapping for role extension
6. **Settings**:
   - Scope: Sync assigned users and groups (or all users)
   - Provisioning Status: **On**
7. **Users and groups**: Assign users or groups

### Verification

Azure AD syncs every ~40 minutes by default. To test immediately:
1. Provisioning > Provision on demand > select a user > Provision
2. Check PGVectorRAGIndexer's Activity log for `user.scim_provisioned`

---

## OneLogin Setup

### Steps

1. **OneLogin Admin** > Applications > Add App
2. Search for **SCIM Provisioner with SAML (SCIM v2 - Header Auth)**
3. **Configuration** tab:
   - SCIM Base URL: `https://your-server/scim/v2`
   - SCIM Bearer Token: `<your-SCIM_BEARER_TOKEN>`
   - SCIM Username Mapping: Email
4. **Provisioning** tab:
   - Enable provisioning
   - When users are deleted: Suspend
   - When user accounts are suspended: Suspend
5. **Users** tab: Assign users

---

## Audit Trail

All SCIM operations are logged in PGVectorRAGIndexer's activity log:

| Event | Trigger |
|-------|---------|
| `user.scim_provisioned` | POST /scim/v2/Users (new user created) |
| `user.scim_updated` | PUT /scim/v2/Users/{id} (full replacement) |
| `user.scim_patched` | PATCH /scim/v2/Users/{id} (partial update) |
| `user.scim_deprovisioned` | DELETE /scim/v2/Users/{id} (user deactivated) |

View these events in:
- **Desktop app**: Organization tab > Activity sub-tab (filter by action)
- **API**: `GET /api/v1/activity?action=user.scim_provisioned`
- **CLI**: Query the activity_log table directly

---

## Security Considerations

- **Bearer token**: Treat `SCIM_BEARER_TOKEN` like a password. Store it in a secrets manager, not in version control.
- **HTTPS required**: Always use HTTPS in production. SCIM requests contain PII (emails, names).
- **Token rotation**: To rotate the bearer token:
  1. Generate a new token
  2. Update `SCIM_BEARER_TOKEN` in server env and restart
  3. Update the token in your IdP's SCIM configuration
  4. There is no grace period — the old token stops working immediately
- **Network access**: Restrict SCIM endpoint access to your IdP's IP ranges if possible (firewall/reverse proxy rules).
- **Soft delete**: `DELETE` deactivates users (sets `is_active=false`) rather than permanently removing them. This preserves audit history and document ownership.

---

## Troubleshooting

**SCIM endpoint returns 404**
- Check `SCIM_ENABLED=true` in server environment
- Restart the server after changing env vars
- Verify with: `curl https://your-server/scim/v2/ServiceProviderConfig`

**IdP says "authentication failed"**
- Verify `SCIM_BEARER_TOKEN` matches exactly (no trailing whitespace)
- Check that the IdP is sending `Authorization: Bearer <token>` (not Basic auth)

**Users created but no role assigned**
- The custom role extension must be explicitly mapped in your IdP
- Without it, users get `SCIM_DEFAULT_ROLE` (default: `"user"`)
- Check that the extension schema URI is exact: `urn:ietf:params:scim:schemas:extension:pgvector:2.0:User`

**IdP reports "filter not supported"**
- PGVectorRAGIndexer supports: `eq`, `ne`, `co` (contains), `sw` (starts with), `ew` (ends with)
- Supported filter attributes: `userName`, `displayName`, `emails.value`, `active`, `externalId`

**Azure AD sync is slow**
- Default Azure AD sync cycle is ~40 minutes
- Use "Provision on demand" for immediate testing
- Check Azure AD provisioning logs for errors

## Group Provisioning

PGVectorRAGIndexer supports SCIM 2.0 Group provisioning. Groups map to internal
roles — when a user is added to a SCIM group, their role changes to match.

### Group Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/scim/v2/Groups` | List groups |
| GET | `/scim/v2/Groups/{id}` | Get single group |
| POST | `/scim/v2/Groups` | Create group (maps to a role) |
| PUT | `/scim/v2/Groups/{id}` | Replace group |
| PATCH | `/scim/v2/Groups/{id}` | Update membership |
| DELETE | `/scim/v2/Groups/{id}` | Delete group mapping |

### How Group-to-Role Mapping Works

Each SCIM group maps to exactly one internal role. When the IdP pushes group
membership changes:

- **User added to group** → user's role is set to the group's mapped role
- **User removed from group** → user's role reverts to `SCIM_DEFAULT_ROLE`
- **User in multiple groups** → last write wins (single-role model)

### Specifying the Role Mapping

The role is determined in this order:

1. **Custom extension** (explicit): Include `roleName` in the group payload:
   ```json
   {
     "displayName": "Engineering Admins",
     "urn:ietf:params:scim:schemas:extension:pgvector:2.0:Group": {
       "roleName": "admin"
     }
   }
   ```

2. **Name matching**: If `displayName` matches an existing role name
   (case-insensitive), it auto-maps. E.g., group "Admin" → role "admin".

3. **Default**: Falls back to `SCIM_DEFAULT_ROLE`.

### IdP Group Configuration

**Okta**: Enable "Push Groups" in the app's Push Groups tab. Map Okta groups
to PGVectorRAGIndexer groups. Okta will POST to `/scim/v2/Groups` and PATCH
membership changes.

**Azure AD**: In the Provisioning mappings, enable "Provision Azure Active
Directory Groups". Azure AD will sync group objects and membership.

## Current Limitations

- **Single role per user**: Users have one role. If a user is in multiple SCIM groups, only the last membership change takes effect.
- **No bulk operations**: Large batch imports must be done one user at a time.
- **Bearer token only**: OAuth 2.0 client credentials flow is not supported.
