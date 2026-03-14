"""
SCIM 2.0 provisioning routes for PGVectorRAGIndexer.
"""

import logging
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import JSONResponse, Response

logger = logging.getLogger(__name__)

scim_router = APIRouter(tags=["SCIM"])


def _scim_auth(request: Request):
    """Validate SCIM bearer token from Authorization header."""
    from scim import is_scim_available, validate_bearer_token, scim_error
    if not is_scim_available():
        raise HTTPException(status_code=404, detail="SCIM provisioning is not enabled")
    auth = request.headers.get("Authorization", "")
    if not validate_bearer_token(auth):
        raise HTTPException(status_code=401, detail=scim_error(401, "Invalid or missing bearer token"))


@scim_router.get("/ServiceProviderConfig")
async def scim_service_provider_config():
    """SCIM ServiceProviderConfig discovery endpoint."""
    from scim import is_scim_available, get_service_provider_config
    if not is_scim_available():
        raise HTTPException(status_code=404, detail="SCIM provisioning is not enabled")
    return JSONResponse(content=get_service_provider_config(), media_type="application/scim+json")


@scim_router.get("/Schemas")
async def scim_schemas():
    """SCIM Schemas discovery endpoint."""
    from scim import is_scim_available, get_schemas, SCIM_SCHEMA_LIST
    if not is_scim_available():
        raise HTTPException(status_code=404, detail="SCIM provisioning is not enabled")
    schemas = get_schemas()
    return JSONResponse(
        content={"schemas": [SCIM_SCHEMA_LIST], "totalResults": len(schemas), "Resources": schemas},
        media_type="application/scim+json",
    )


@scim_router.get("/ResourceTypes")
async def scim_resource_types():
    """SCIM ResourceTypes discovery endpoint."""
    from scim import is_scim_available, get_resource_types, SCIM_SCHEMA_LIST
    if not is_scim_available():
        raise HTTPException(status_code=404, detail="SCIM provisioning is not enabled")
    types = get_resource_types()
    return JSONResponse(
        content={"schemas": [SCIM_SCHEMA_LIST], "totalResults": len(types), "Resources": types},
        media_type="application/scim+json",
    )


@scim_router.get("/Users")
async def scim_list_users(
    request: Request,
    filter: Optional[str] = Query(default=None),
    startIndex: int = Query(default=1, ge=1),
    count: int = Query(default=100, ge=1, le=200),
):
    """List/search users via SCIM."""
    _scim_auth(request)
    from scim import list_scim_users
    base_url = str(request.base_url).rstrip("/")
    result = list_scim_users(filter_str=filter, start_index=startIndex, count=count, base_url=base_url)
    return JSONResponse(content=result, media_type="application/scim+json")


@scim_router.get("/Users/{user_id}")
async def scim_get_user(user_id: str, request: Request):
    """Get a single user via SCIM."""
    _scim_auth(request)
    from scim import user_to_scim, scim_error
    import users
    user = users.get_user(user_id)
    if not user:
        raise HTTPException(status_code=404, detail=scim_error(404, f"User {user_id} not found"))
    base_url = str(request.base_url).rstrip("/")
    return JSONResponse(content=user_to_scim(user, base_url), media_type="application/scim+json")


@scim_router.post("/Users", status_code=201)
async def scim_create_user(request: Request):
    """Create a user via SCIM provisioning."""
    _scim_auth(request)
    from scim import scim_to_user_params, user_to_scim, scim_error, SCIM_DEFAULT_ROLE
    import users
    try:
        body = await request.json()
        params = scim_to_user_params(body)
        if not params.get("email"):
            raise HTTPException(
                status_code=400,
                detail=scim_error(400, "userName or emails[0].value is required", "invalidValue"),
            )

        existing = users.get_user_by_email(params["email"])
        if existing:
            raise HTTPException(
                status_code=409,
                detail=scim_error(409, f"User with email {params['email']} already exists", "uniqueness"),
            )

        params.setdefault("role", SCIM_DEFAULT_ROLE)
        params["auth_provider"] = "saml"

        new_user = users.create_user(**params)
        if not new_user:
            raise HTTPException(status_code=500, detail=scim_error(500, "Failed to create user"))

        from activity_log import log_activity
        log_activity("user.scim_provisioned", details={"user_id": new_user["id"], "email": new_user.get("email")})

        base_url = str(request.base_url).rstrip("/")
        return JSONResponse(
            content=user_to_scim(new_user, base_url),
            status_code=201,
            media_type="application/scim+json",
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"SCIM create user failed: {e}")
        raise HTTPException(status_code=500, detail=scim_error(500, str(e)))


@scim_router.put("/Users/{user_id}")
async def scim_replace_user(user_id: str, request: Request):
    """Full replace of a user via SCIM."""
    _scim_auth(request)
    from scim import scim_to_user_params, user_to_scim, scim_error
    import users
    try:
        existing = users.get_user(user_id)
        if not existing:
            raise HTTPException(status_code=404, detail=scim_error(404, f"User {user_id} not found"))

        body = await request.json()
        params = scim_to_user_params(body)

        updated = users.update_user(user_id, **params)
        if not updated:
            raise HTTPException(status_code=500, detail=scim_error(500, "Failed to update user"))

        from activity_log import log_activity
        log_activity("user.scim_updated", details={"user_id": user_id, "fields": list(params.keys())})

        base_url = str(request.base_url).rstrip("/")
        return JSONResponse(content=user_to_scim(updated, base_url), media_type="application/scim+json")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"SCIM replace user failed: {e}")
        raise HTTPException(status_code=500, detail=scim_error(500, str(e)))


@scim_router.patch("/Users/{user_id}")
async def scim_patch_user(user_id: str, request: Request):
    """Partial update of a user via SCIM PATCH."""
    _scim_auth(request)
    from scim import apply_patch_operations, user_to_scim, scim_error, SCIM_SCHEMA_PATCH
    import users
    try:
        existing = users.get_user(user_id)
        if not existing:
            raise HTTPException(status_code=404, detail=scim_error(404, f"User {user_id} not found"))

        body = await request.json()
        schemas = body.get("schemas", [])
        if SCIM_SCHEMA_PATCH not in schemas:
            raise HTTPException(
                status_code=400,
                detail=scim_error(400, f"Request must include schema {SCIM_SCHEMA_PATCH}", "invalidValue"),
            )

        operations = body.get("Operations", [])
        if not operations:
            raise HTTPException(status_code=400, detail=scim_error(400, "No operations provided"))

        updated = apply_patch_operations(user_id, operations)
        if not updated:
            raise HTTPException(status_code=500, detail=scim_error(500, "Failed to apply patch"))

        from activity_log import log_activity
        log_activity("user.scim_patched", details={"user_id": user_id, "op_count": len(operations)})

        base_url = str(request.base_url).rstrip("/")
        return JSONResponse(content=user_to_scim(updated, base_url), media_type="application/scim+json")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"SCIM patch user failed: {e}")
        raise HTTPException(status_code=500, detail=scim_error(500, str(e)))


@scim_router.delete("/Users/{user_id}", status_code=204)
async def scim_delete_user(user_id: str, request: Request):
    """Deactivate (soft-delete) a user via SCIM."""
    _scim_auth(request)
    from scim import scim_error
    import users
    try:
        existing = users.get_user(user_id)
        if not existing:
            raise HTTPException(status_code=404, detail=scim_error(404, f"User {user_id} not found"))

        users.deactivate_user(user_id)

        from activity_log import log_activity
        log_activity("user.scim_deprovisioned", details={"user_id": user_id, "email": existing.get("email")})

        return Response(status_code=204)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"SCIM delete user failed: {e}")
        raise HTTPException(status_code=500, detail=scim_error(500, str(e)))


# ---------------------------------------------------------------------------
# SCIM Group endpoints
# ---------------------------------------------------------------------------


@scim_router.get("/Groups")
async def scim_list_groups(
    request: Request,
    filter: Optional[str] = Query(default=None),
    startIndex: int = Query(default=1, ge=1),
    count: int = Query(default=100, ge=1, le=200),
):
    """List/search groups via SCIM."""
    _scim_auth(request)
    from scim import list_scim_groups
    base_url = str(request.base_url).rstrip("/")
    result = list_scim_groups(filter_str=filter, start_index=startIndex, count=count, base_url=base_url)
    return JSONResponse(content=result, media_type="application/scim+json")


@scim_router.get("/Groups/{group_id}")
async def scim_get_group(group_id: str, request: Request):
    """Get a single group via SCIM."""
    _scim_auth(request)
    from scim import get_scim_group, group_to_scim, scim_error
    group = get_scim_group(group_id)
    if not group:
        raise HTTPException(status_code=404, detail=scim_error(404, f"Group {group_id} not found"))
    base_url = str(request.base_url).rstrip("/")
    return JSONResponse(content=group_to_scim(group, base_url), media_type="application/scim+json")


@scim_router.post("/Groups", status_code=201)
async def scim_create_group(request: Request):
    """Create a group via SCIM provisioning."""
    _scim_auth(request)
    from scim import (
        create_scim_group, group_to_scim, scim_error,
        _resolve_role_name, CUSTOM_SCHEMA_GROUP_ROLE,
    )
    try:
        body = await request.json()
        display_name = body.get("displayName")
        if not display_name:
            raise HTTPException(
                status_code=400,
                detail=scim_error(400, "displayName is required", "invalidValue"),
            )

        role_name = _resolve_role_name(body)
        external_id = body.get("externalId")

        group = create_scim_group(display_name, role_name, external_id)

        # Apply initial members if provided
        members = body.get("members", [])
        if members:
            import users
            for member in members:
                uid = member.get("value") if isinstance(member, dict) else member
                if uid:
                    users.change_role(uid, role_name)

        from activity_log import log_activity
        log_activity(
            "group.scim_created",
            details={"group_id": group["id"], "display_name": display_name, "role": role_name},
        )

        base_url = str(request.base_url).rstrip("/")
        return JSONResponse(
            content=group_to_scim(group, base_url),
            status_code=201,
            media_type="application/scim+json",
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=scim_error(400, str(e), "invalidValue"))
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"SCIM create group failed: {e}")
        raise HTTPException(status_code=500, detail=scim_error(500, str(e)))


@scim_router.put("/Groups/{group_id}")
async def scim_replace_group(group_id: str, request: Request):
    """Full replace of a group via SCIM."""
    _scim_auth(request)
    from scim import (
        get_scim_group, update_scim_group, group_to_scim, scim_error,
        _resolve_role_name, get_group_members, SCIM_DEFAULT_ROLE,
    )
    try:
        existing = get_scim_group(group_id)
        if not existing:
            raise HTTPException(status_code=404, detail=scim_error(404, f"Group {group_id} not found"))

        body = await request.json()
        display_name = body.get("displayName", existing["display_name"])
        role_name = _resolve_role_name(body)
        external_id = body.get("externalId", existing.get("external_id"))

        updated = update_scim_group(group_id, display_name=display_name, role_name=role_name, external_id=external_id)

        # Replace membership: new members get the role, old-only members revert
        new_member_ids = set()
        for member in body.get("members", []):
            uid = member.get("value") if isinstance(member, dict) else member
            if uid:
                new_member_ids.add(uid)

        import users as users_mod
        # Set new members' roles
        for uid in new_member_ids:
            users_mod.change_role(uid, role_name)

        # Revert old members not in new list
        old_members = get_group_members(existing["role_name"])
        for om in old_members:
            if om["value"] not in new_member_ids:
                users_mod.change_role(om["value"], SCIM_DEFAULT_ROLE)

        from activity_log import log_activity
        log_activity("group.scim_updated", details={"group_id": group_id, "display_name": display_name})

        base_url = str(request.base_url).rstrip("/")
        return JSONResponse(content=group_to_scim(updated, base_url), media_type="application/scim+json")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=scim_error(400, str(e), "invalidValue"))
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"SCIM replace group failed: {e}")
        raise HTTPException(status_code=500, detail=scim_error(500, str(e)))


@scim_router.patch("/Groups/{group_id}")
async def scim_patch_group(group_id: str, request: Request):
    """Partial update of a group via SCIM PATCH (membership changes)."""
    _scim_auth(request)
    from scim import (
        get_scim_group, apply_group_membership, group_to_scim, scim_error,
        SCIM_SCHEMA_PATCH,
    )
    try:
        existing = get_scim_group(group_id)
        if not existing:
            raise HTTPException(status_code=404, detail=scim_error(404, f"Group {group_id} not found"))

        body = await request.json()
        schemas = body.get("schemas", [])
        if SCIM_SCHEMA_PATCH not in schemas:
            raise HTTPException(
                status_code=400,
                detail=scim_error(400, f"Request must include schema {SCIM_SCHEMA_PATCH}", "invalidValue"),
            )

        operations = body.get("Operations", [])
        if not operations:
            raise HTTPException(status_code=400, detail=scim_error(400, "No operations provided"))

        updated = apply_group_membership(group_id, operations)
        if not updated:
            raise HTTPException(status_code=500, detail=scim_error(500, "Failed to apply patch"))

        from activity_log import log_activity
        log_activity(
            "group.scim_membership_changed",
            details={"group_id": group_id, "op_count": len(operations)},
        )

        base_url = str(request.base_url).rstrip("/")
        return JSONResponse(content=group_to_scim(updated, base_url), media_type="application/scim+json")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"SCIM patch group failed: {e}")
        raise HTTPException(status_code=500, detail=scim_error(500, str(e)))


@scim_router.delete("/Groups/{group_id}", status_code=204)
async def scim_delete_group(group_id: str, request: Request):
    """Delete a SCIM group mapping."""
    _scim_auth(request)
    from scim import get_scim_group, delete_scim_group, scim_error
    try:
        existing = get_scim_group(group_id)
        if not existing:
            raise HTTPException(status_code=404, detail=scim_error(404, f"Group {group_id} not found"))

        delete_scim_group(group_id)

        from activity_log import log_activity
        log_activity(
            "group.scim_deleted",
            details={"group_id": group_id, "display_name": existing["display_name"]},
        )

        return Response(status_code=204)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"SCIM delete group failed: {e}")
        raise HTTPException(status_code=500, detail=scim_error(500, str(e)))
