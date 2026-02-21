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
