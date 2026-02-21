"""
API Key, Client, and User management routes for PGVectorRAGIndexer.
"""

import logging
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from auth import require_api_key, require_admin, require_permission

logger = logging.getLogger(__name__)

identity_router = APIRouter(tags=["Identity & Auth"])


# ---------------------------------------------------------------------------
# API Key Management
# ---------------------------------------------------------------------------

@identity_router.post("/api/keys", dependencies=[Depends(require_permission("keys.manage"))])
async def create_key(name: str = Query(..., description="Human-readable name for the key")):
    """Create a new API key."""
    from auth import create_api_key_record
    try:
        result = create_api_key_record(name)
        return {
            "key": result["key"],
            "id": result["id"],
            "name": result["name"],
            "prefix": result["prefix"],
            "created_at": result["created_at"],
            "message": "Store this key securely. It will not be shown again.",
        }
    except Exception as e:
        logger.error(f"Failed to create API key: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create API key: {str(e)}",
        )


@identity_router.get("/api/keys", dependencies=[Depends(require_permission("keys.manage"))])
async def list_keys():
    """List all API keys (active and revoked)."""
    from auth import list_api_keys
    try:
        return {"keys": list_api_keys()}
    except Exception as e:
        logger.error(f"Failed to list API keys: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to list API keys: {str(e)}",
        )


@identity_router.delete("/api/keys/{key_id}", dependencies=[Depends(require_permission("keys.manage"))])
async def delete_key(key_id: int):
    """Revoke an API key immediately."""
    from auth import revoke_api_key
    try:
        revoked = revoke_api_key(key_id)
        if not revoked:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Key not found or already revoked",
            )
        return {"revoked": True, "id": key_id}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to revoke API key: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to revoke API key: {str(e)}",
        )


@identity_router.post("/api/keys/{key_id}/rotate", dependencies=[Depends(require_permission("keys.manage"))])
async def rotate_key(key_id: int):
    """Rotate an API key."""
    from auth import rotate_api_key
    try:
        result = rotate_api_key(key_id)
        if not result:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Key not found or already revoked",
            )
        return {
            "key": result["key"],
            "id": result["id"],
            "name": result["name"],
            "prefix": result["prefix"],
            "created_at": result["created_at"],
            "old_key_id": result["old_key_id"],
            "grace_period_hours": result["grace_period_hours"],
            "message": f"Old key remains valid for {result['grace_period_hours']} hours. Store new key securely.",
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to rotate API key: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to rotate API key: {str(e)}",
        )


# ---------------------------------------------------------------------------
# Client Identity
# ---------------------------------------------------------------------------

@identity_router.post("/clients/register", dependencies=[Depends(require_api_key)])
async def register_client_endpoint(request: Request):
    """Register or update a client identity."""
    from client_identity import register_client
    try:
        body = await request.json()
        client_id = body.get("client_id")
        display_name = body.get("display_name", "Unknown")
        os_type = body.get("os_type", "unknown")
        app_version = body.get("app_version")

        if not client_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="client_id is required",
            )

        result = register_client(
            client_id=client_id,
            display_name=display_name,
            os_type=os_type,
            app_version=app_version,
        )
        if result:
            return result
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to register client",
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to register client: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to register client: {str(e)}",
        )


@identity_router.post("/clients/heartbeat", dependencies=[Depends(require_api_key)])
async def client_heartbeat_endpoint(request: Request):
    """Update last_seen_at for a client."""
    from client_identity import heartbeat
    try:
        body = await request.json()
        client_id = body.get("client_id")
        if not client_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="client_id is required",
            )
        app_version = body.get("app_version")
        success = heartbeat(client_id, app_version=app_version)
        return {"ok": success}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to heartbeat client: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to heartbeat: {str(e)}",
        )


@identity_router.get("/clients", dependencies=[Depends(require_api_key)])
async def list_clients_endpoint():
    """List all registered clients."""
    from client_identity import list_clients
    try:
        clients = list_clients()
        return {"clients": clients, "count": len(clients)}
    except Exception as e:
        logger.error(f"Failed to list clients: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to list clients: {str(e)}",
        )


# ---------------------------------------------------------------------------
# User Management
# ---------------------------------------------------------------------------

@identity_router.get("/users", dependencies=[Depends(require_api_key)])
async def list_users_endpoint(
    role: Optional[str] = Query(default=None),
    active_only: bool = Query(default=True),
):
    """List all users."""
    from users import list_users
    try:
        users = list_users(role=role, active_only=active_only)
        return {"users": users, "count": len(users)}
    except Exception as e:
        logger.error(f"Failed to list users: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to list users: {str(e)}",
        )


@identity_router.get("/users/{user_id}", dependencies=[Depends(require_api_key)])
async def get_user_endpoint(user_id: str):
    """Get a user by ID."""
    from users import get_user
    try:
        user = get_user(user_id)
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        return user
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get user: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get user: {str(e)}",
        )


@identity_router.post("/users", dependencies=[Depends(require_admin)])
async def create_user_endpoint(request: Request):
    """Create a new user (admin only)."""
    from users import create_user
    try:
        body = await request.json()
        user = create_user(
            email=body.get("email"),
            display_name=body.get("display_name"),
            role=body.get("role", "user"),
            auth_provider=body.get("auth_provider", "api_key"),
            api_key_id=body.get("api_key_id"),
            client_id=body.get("client_id"),
        )
        if not user:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Failed to create user. Check role and email uniqueness.",
            )
        from activity_log import log_activity
        log_activity(
            "user.created",
            details={"user_id": user["id"], "email": user.get("email"), "role": user["role"]},
        )
        return user
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to create user: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create user: {str(e)}",
        )


@identity_router.put("/users/{user_id}", dependencies=[Depends(require_admin)])
async def update_user_endpoint(user_id: str, request: Request):
    """Update a user (admin only)."""
    from users import update_user
    try:
        body = await request.json()
        user = update_user(
            user_id,
            email=body.get("email"),
            display_name=body.get("display_name"),
            role=body.get("role"),
            is_active=body.get("is_active"),
        )
        if not user:
            raise HTTPException(status_code=404, detail="User not found or invalid data")
        from activity_log import log_activity
        log_activity(
            "user.updated",
            details={"user_id": user_id, "changes": body},
        )
        return user
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to update user: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to update user: {str(e)}",
        )


@identity_router.delete("/users/{user_id}", dependencies=[Depends(require_admin)])
async def delete_user_endpoint(user_id: str):
    """Delete a user (admin only)."""
    from users import delete_user, count_admins, get_user, ROLE_ADMIN
    try:
        user = get_user(user_id)
        if user and user.get("role") == ROLE_ADMIN and count_admins() <= 1:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot delete the last admin user.",
            )
        deleted = delete_user(user_id)
        if not deleted:
            raise HTTPException(status_code=404, detail="User not found")
        from activity_log import log_activity
        log_activity("user.deleted", details={"user_id": user_id})
        return {"ok": True, "deleted": user_id}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to delete user: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to delete user: {str(e)}",
        )


@identity_router.post("/users/{user_id}/role", dependencies=[Depends(require_admin)])
async def change_user_role_endpoint(user_id: str, request: Request):
    """Change a user's role (admin only)."""
    from users import change_role, count_admins, get_user, ROLE_ADMIN
    try:
        body = await request.json()
        new_role = body.get("role")
        if not new_role:
            raise HTTPException(status_code=400, detail="'role' is required")

        user = get_user(user_id)
        if (
            user
            and user.get("role") == ROLE_ADMIN
            and new_role != ROLE_ADMIN
            and count_admins() <= 1
        ):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot demote the last admin user.",
            )

        updated = change_role(user_id, new_role)
        if not updated:
            raise HTTPException(status_code=404, detail="User not found")
        from activity_log import log_activity
        log_activity(
            "user.role_changed",
            details={
                "user_id": user_id, 
                "old_role": user.get("role") if user else None, 
                "new_role": new_role
            },
        )
        return {"ok": True, "user_id": user_id, "new_role": new_role}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to change user role: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to change role: {str(e)}",
        )


# ---------------------------------------------------------------------------
# Roles & Permissions
# ---------------------------------------------------------------------------

@identity_router.get("/roles", dependencies=[Depends(require_api_key)])
async def list_roles_endpoint():
    """List all available roles with their permissions."""
    from role_permissions import list_roles
    return {"roles": list_roles()}


@identity_router.get("/roles/{role_name}", dependencies=[Depends(require_api_key)])
async def get_role_endpoint(role_name: str):
    """Get a specific role's definition and permissions."""
    from role_permissions import get_role_info
    info = get_role_info(role_name)
    if not info:
        raise HTTPException(status_code=404, detail=f"Role '{role_name}' not found")
    return info


@identity_router.get("/permissions", dependencies=[Depends(require_api_key)])
async def list_permissions_endpoint():
    """List all available granular permissions."""
    from role_permissions import list_permissions
    return {"permissions": list_permissions()}


@identity_router.get("/roles/{role_name}/check/{permission}", dependencies=[Depends(require_api_key)])
async def check_role_permission_endpoint(role_name: str, permission: str):
    """Check if a role has a specific permission."""
    from role_permissions import has_permission, is_valid_role
    if not is_valid_role(role_name):
        raise HTTPException(status_code=404, detail=f"Role '{role_name}' not found")
    return {"role": role_name, "permission": permission, "granted": has_permission(role_name, permission)}


@identity_router.post("/roles", dependencies=[Depends(require_admin)])
async def create_role_endpoint(request: Request):
    """Create a new custom role (admin only)."""
    from role_permissions import create_role
    try:
        body = await request.json()
        result = create_role(
            name=body.get("name"),
            description=body.get("description"),
            permissions=body.get("permissions"),
        )
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Failed to create role: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to create role: {str(e)}")


@identity_router.put("/roles/{role_name}", dependencies=[Depends(require_admin)])
async def update_role_endpoint(role_name: str, request: Request):
    """Update an existing role (admin only)."""
    from role_permissions import update_role
    try:
        body = await request.json()
        result = update_role(
            name=role_name,
            description=body.get("description"),
            permissions=body.get("permissions"),
        )
        if not result:
            raise HTTPException(status_code=404, detail=f"Role '{role_name}' not found")
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to update role: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to update role: {str(e)}")


@identity_router.delete("/roles/{role_name}", dependencies=[Depends(require_admin)])
async def delete_role_endpoint(role_name: str):
    """Delete a custom role (admin only)."""
    from role_permissions import delete_role
    try:
        deleted = delete_role(role_name)
        if not deleted:
            raise HTTPException(status_code=404, detail=f"Role '{role_name}' not found")
        return {"deleted": True, "role": role_name}
    except ValueError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to delete role: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to delete role: {str(e)}")


# ---------------------------------------------------------------------------
# SAML/SSO
# ---------------------------------------------------------------------------

@identity_router.get("/saml/metadata")
async def saml_metadata():
    """Return SP metadata XML."""
    from saml_auth import is_saml_available, get_sp_metadata
    if not is_saml_available():
        raise HTTPException(status_code=404, detail="SAML/SSO is not enabled")
    try:
        metadata = get_sp_metadata()
        from fastapi.responses import Response
        return Response(content=metadata, media_type="application/xml")
    except Exception as e:
        logger.error(f"Failed to generate SP metadata: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to generate SP metadata: {str(e)}",
        )


@identity_router.get("/saml/login")
async def saml_login(request: Request, return_to: Optional[str] = Query(default=None)):
    """Initiate SAML login."""
    from saml_auth import is_saml_available, prepare_request_from_fastapi, initiate_login
    if not is_saml_available():
        raise HTTPException(status_code=404, detail="SAML/SSO is not enabled")
    try:
        req = prepare_request_from_fastapi(request)
        redirect_url = initiate_login(req, return_to=return_to)
        from fastapi.responses import RedirectResponse
        return RedirectResponse(url=redirect_url)
    except Exception as e:
        logger.error(f"Failed to initiate SAML login: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to initiate SAML login: {str(e)}",
        )


@identity_router.post("/saml/acs")
async def saml_acs(request: Request):
    """Assertion Consumer Service."""
    from saml_auth import (
        is_saml_available, prepare_request_from_fastapi, process_acs,
        provision_or_get_user, create_session, SAML_IDP_ENTITY_ID,
    )
    if not is_saml_available():
        raise HTTPException(status_code=404, detail="SAML/SSO is not enabled")
    try:
        form_data = await request.form()
        post_data = dict(form_data)
        req = prepare_request_from_fastapi(request)
        result = process_acs(req, post_data)

        if not result.get("success"):
            logger.error("SAML ACS failed: %s", result.get("errors"))
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=f"SAML authentication failed: {result.get('error_reason', 'Unknown error')}",
            )

        email = result.get("email")
        if not email:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No email address in SAML response",
            )

        user = provision_or_get_user(email, display_name=result.get("display_name"))
        if not user:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="User provisioning failed or disabled",
            )

        session = create_session(
            user_id=user["id"],
            name_id=result.get("name_id", email),
            name_id_format=result.get("name_id_format"),
            session_index=result.get("session_index"),
            idp_entity_id=SAML_IDP_ENTITY_ID,
        )

        from activity_log import log_activity
        log_activity(
            "user.saml_login",
            user_id=user["id"],
            details={"email": email, "idp": SAML_IDP_ENTITY_ID},
        )

        return {
            "ok": True,
            "user": user,
            "session_id": session["id"] if session else None,
            "expires_at": session["expires_at"] if session else None,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to process SAML ACS: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to process SAML response: {str(e)}",
        )


@identity_router.get("/saml/logout", dependencies=[Depends(require_api_key)])
async def saml_logout(
    request: Request,
    session_id: str = Query(..., description="SAML session ID to terminate"),
):
    """Initiate SAML Single Logout (SLO)."""
    from saml_auth import (
        is_saml_available, prepare_request_from_fastapi,
        get_session, expire_session, initiate_logout,
    )
    if not is_saml_available():
        raise HTTPException(status_code=404, detail="SAML/SSO is not enabled")
    try:
        session = get_session(session_id)
        if not session:
            raise HTTPException(status_code=404, detail="Session not found or expired")

        expire_session(session_id)

        from activity_log import log_activity
        log_activity(
            "user.saml_logout",
            user_id=session.get("user_id"),
            details={"session_id": session_id},
        )

        try:
            req = prepare_request_from_fastapi(request)
            redirect_url = initiate_logout(
                req,
                name_id=session.get("name_id"),
                session_index=session.get("session_index"),
            )
            return {"ok": True, "redirect_url": redirect_url}
        except Exception:
            return {"ok": True, "redirect_url": None, "note": "Local session expired; IdP SLO unavailable"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to process SAML logout: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to process SAML logout: {str(e)}",
        )


@identity_router.get("/saml/status")
async def saml_status():
    """Check if SAML/SSO is enabled."""
    from saml_auth import is_saml_available, SAML_IDP_ENTITY_ID, SAML_SP_ENTITY_ID
    return {
        "enabled": is_saml_available(),
        "idp_entity_id": SAML_IDP_ENTITY_ID if is_saml_available() else None,
        "sp_entity_id": SAML_SP_ENTITY_ID if is_saml_available() else None,
    }


@identity_router.post("/saml/sessions/cleanup", dependencies=[Depends(require_admin)])
async def saml_cleanup_sessions():
    """Remove expired SAML sessions (admin only)."""
    from saml_auth import cleanup_expired_sessions
    try:
        deleted = cleanup_expired_sessions()
        return {"deleted": deleted, "ok": True}
    except Exception as e:
        logger.error(f"Failed to cleanup SAML sessions: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to cleanup sessions: {str(e)}",
        )
