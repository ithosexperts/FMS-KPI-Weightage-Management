"""
FastAPI Router for KPI Weightage Management.
Includes both UI routes and JSON APIs.
Enforces WR16: Role-based access control (only approving role can access).
"""
import logging
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import HTMLResponse, JSONResponse

from app.api.client import ApiError
from app.auth.sso_session import SESSION_COOKIE, decode_session_cookie
from app.config import settings
from app.services.kpi_service import KpiService

logger = logging.getLogger(__name__)

router = APIRouter()


# ── Pydantic Request Models ───────────────────────────────────────────────────

class WeightItem(BaseModel):
    KPI: str = Field(..., description="KPICode from Z_KPI_Master")
    W: float = Field(..., description="Weightage value (e.g. 0.85)")


class SetWeightagePayload(BaseModel):
    DoerCode: str = Field(..., description="Employee Code of the doer")
    EffectiveFromDate: str = Field(..., description="Effective start date (YYYY-MM-DD), today or later")
    Weights: List[WeightItem] = Field(..., min_length=1, description="List of KPI weights adding to 1.00")
    ChangeReason: str = Field(..., min_length=1, max_length=250, description="Mandatory reason for change")
    UserCode: Optional[str] = Field(None, description="Logged in user code")
    Database: Optional[str] = Field(None, description="Target database (OperationsDB / Test_OperationsDB)")


class InactiveWeightagePayload(BaseModel):
    DoerCode: str = Field(..., description="Employee Code of the doer")
    InactiveFromDate: str = Field(..., description="Inactive start date (YYYY-MM-DD), today or later")
    ChangeReason: str = Field(..., min_length=1, max_length=250, description="Mandatory reason for inactive status")
    UserCode: Optional[str] = Field(None, description="Logged in user code")
    Database: Optional[str] = Field(None, description="Target database (OperationsDB / Test_OperationsDB)")


# ── Role-based Access Guard (WR16) & One Portal SSO ───────────────────────────

def get_current_user_and_role(request: Request) -> Dict[str, Any]:
    """
    Extract session identity and role.
    1. Check verified SSO session cookie (minted upon One Portal SSO launch).
    2. Check headers or query params (forwarded proxy / test parameters).
    3. Fallback to default Guest (unauthorized / read-only).
    """
    # 1. SSO Session Cookie (One Portal)
    cookie_token = request.cookies.get(SESSION_COOKIE)
    if cookie_token:
        sso_data = decode_session_cookie(cookie_token)
        if sso_data:
            role_id = int(sso_data.get("role_id", 99))
            user_code = str(sso_data.get("employee_code") or settings.default_user_code).strip()
            user_name = str(sso_data.get("full_name") or settings.default_user_name).strip()
            role_name = str(sso_data.get("role_name") or ("Super Admin" if role_id == 1 else f"Role {role_id}")).strip()
            return {
                "role_id": role_id,
                "role_name": role_name,
                "user_code": user_code,
                "user_name": user_name,
                "is_approver": role_id in settings.allowed_approver_role_ids,
                "is_sso": True,
                "target_database": sso_data.get("target_database"),
            }

    # 2. Explicit headers or query parameters (for direct API testing / gateway forwarding)
    role_id_raw = request.headers.get("X-Role-ID") or request.query_params.get("role_id")
    user_code = request.headers.get("X-User-Code") or request.query_params.get("user_code")
    user_name = request.headers.get("X-User-Name")

    if role_id_raw or user_code:
        try:
            role_id = int(role_id_raw) if role_id_raw else settings.default_role_id
        except (ValueError, TypeError):
            role_id = 99
        return {
            "role_id": role_id,
            "role_name": "Approver" if role_id in settings.allowed_approver_role_ids else "Guest",
            "user_code": user_code or settings.default_user_code,
            "user_name": user_name or settings.default_user_name,
            "is_approver": role_id in settings.allowed_approver_role_ids,
            "is_sso": False,
            "target_database": None,
        }

    # 3. Default Guest (Read-Only)
    return {
        "role_id": settings.default_role_id,  # 99
        "role_name": settings.default_user_name,  # Guest
        "user_code": settings.default_user_code,  # GUEST
        "user_name": settings.default_user_name,  # Guest
        "is_approver": settings.default_role_id in settings.allowed_approver_role_ids,  # False
        "is_sso": False,
        "target_database": None,
    }


def enforce_sso_session(request: Request) -> Dict[str, Any]:
    """
    Ensures request originates from an authenticated One Portal SSO session.
    Direct access without portal authentication is denied.
    """
    user = get_current_user_and_role(request)
    if not user.get("is_sso"):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Access Denied: Please launch KPI Weightage Management from One Portal.",
        )
    return user


def enforce_approver_role(request: Request) -> Dict[str, Any]:
    """Rule WR16: Only an authorized approver role can submit or modify weightages."""
    user = enforce_sso_session(request)
    if not user["is_approver"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Access Denied (WR16): Role ID {user['role_id']} ({user.get('role_name', '')}) is not authorized to approve KPI weightages.",
        )
    return user


# ── Web UI Routes ────────────────────────────────────────────────────────────

@router.get("/", response_class=HTMLResponse)
async def weightage_screen(request: Request):
    """
    Renders the KPI Weightage Management Screen.
    If not accessed via One Portal SSO, renders the access restricted screen.
    """
    user = get_current_user_and_role(request)
    if not user.get("is_sso"):
        template_env = request.app.state.templates
        return template_env.TemplateResponse(
            request=request,
            name="sso_required.html",
            context={
                "portal_url": settings.one_portal_url,
            },
            status_code=status.HTTP_401_UNAUTHORIZED,
        )

    active_db = user.get("target_database") or settings.api_database
    template_env = request.app.state.templates
    return template_env.TemplateResponse(
        request=request,
        name="weightage.html",
        context={
            "user": user,
            "app_name": settings.app_name,
            "database": active_db,
            "is_production": settings.is_production,
            "allowed_roles": settings.allowed_approver_role_ids,
            "current_page": "weightage",
        },
    )


@router.get("/documentation", response_class=HTMLResponse)
@router.get("/docs", response_class=HTMLResponse)
async def documentation_screen(request: Request):
    """
    Renders the complete 10-page official System Design Documentation.
    If not accessed via One Portal SSO, renders the access restricted screen.
    """
    user = get_current_user_and_role(request)
    if not user.get("is_sso"):
        template_env = request.app.state.templates
        return template_env.TemplateResponse(
            request=request,
            name="sso_required.html",
            context={
                "portal_url": settings.one_portal_url,
            },
            status_code=status.HTTP_401_UNAUTHORIZED,
        )

    active_db = user.get("target_database") or settings.api_database
    template_env = request.app.state.templates
    return template_env.TemplateResponse(
        request=request,
        name="documentation.html",
        context={
            "user": user,
            "app_name": settings.app_name,
            "database": active_db,
            "is_production": settings.is_production,
            "allowed_roles": settings.allowed_approver_role_ids,
            "current_page": "documentation",
        },
    )


# ── JSON APIs ────────────────────────────────────────────────────────────────

@router.get("/api/doers")
async def api_get_doers(
    database: Optional[str] = Query(None),
    user: Dict[str, Any] = Depends(enforce_sso_session),
):
    """
    Section 5.1 & Rule WR2:
    Lists active, employed, non-management employees eligible for KPI scoring.
    """
    try:
        doers = await KpiService.get_eligible_doers(database=database)
        return {"status": "success", "count": len(doers), "data": doers}
    except Exception as exc:
        logger.exception("Failed to get eligible doers: %s", exc)
        return JSONResponse(status_code=500, content={"status": "error", "message": str(exc)})


@router.get("/api/kpi-master")
async def api_get_kpi_master(
    database: Optional[str] = Query(None),
    user: Dict[str, Any] = Depends(enforce_sso_session),
):
    """
    Section 3.2:
    Lists active KPIs from Z_KPI_Master for the KPI dropdown.
    """
    try:
        kpis = await KpiService.get_kpi_master(database=database)
        return {"status": "success", "count": len(kpis), "data": kpis}
    except Exception as exc:
        logger.exception("Failed to get KPI master: %s", exc)
        return JSONResponse(status_code=500, content={"status": "error", "message": str(exc)})


@router.get("/api/weightage/current/{doer_code}")
async def api_get_current_weightage(
    doer_code: str,
    database: Optional[str] = Query(None),
    user: Dict[str, Any] = Depends(enforce_sso_session),
):
    """
    Section 5.2 & Rule WR3:
    Returns the doer's version in effect and any version waiting to start (read-only).
    Also checks if the doer is on active FMS_Config (for Section 5.6 button state).
    """
    try:
        weightage_data = await KpiService.get_current_weightage(doer_code, database=database)
        is_on_fms, fms_stages = await KpiService.check_doer_active_in_fms_config(doer_code, database=database)

        return {
            "status": "success",
            "data": weightage_data,
            "fms_config_status": {
                "is_on_fms_config": is_on_fms,
                "stages": fms_stages,
                "can_mark_inactive": not is_on_fms,
                "inactive_blocked_message": "Remove this doer from FMS_Config first" if is_on_fms else None,
            },
        }
    except Exception as exc:
        logger.exception("Failed to get current weightage for %s: %s", doer_code, exc)
        return JSONResponse(status_code=500, content={"status": "error", "message": str(exc)})


@router.get("/api/weightage/history/{doer_code}")
async def api_get_weightage_history(
    doer_code: str,
    database: Optional[str] = Query(None),
    user: Dict[str, Any] = Depends(enforce_sso_session),
):
    """
    Section 5.7:
    Returns every row for the doer, newest first, voided rows included and marked.
    """
    try:
        history = await KpiService.get_weightage_history(doer_code, database=database)
        return {"status": "success", "count": len(history), "data": history}
    except Exception as exc:
        logger.exception("Failed to get weightage history for %s: %s", doer_code, exc)
        return JSONResponse(status_code=500, content={"status": "error", "message": str(exc)})


@router.post("/api/weightage/set")
async def api_set_weightage(
    payload: SetWeightagePayload,
    user: Dict[str, Any] = Depends(enforce_approver_role),
):
    """
    Section 5.5 & Section 6.1:
    Submits a complete new weightage set via SP_KPI_Weightage_Set.
    """
    user_code = payload.UserCode or user["user_code"]
    try:
        weights_dict = [{"KPI": w.KPI, "W": w.W} for w in payload.Weights]
        result = await KpiService.set_kpi_weightage(
            doer_code=payload.DoerCode,
            effective_from_str=payload.EffectiveFromDate,
            weights=weights_dict,
            change_reason=payload.ChangeReason,
            user_code=user_code,
            database=payload.Database,
        )
        return result
    except ApiError as exc:
        # Show the procedure error message unchanged as required by Section 6.3
        logger.warning("Procedure error setting weightage: %s", exc.message)
        return JSONResponse(status_code=400, content={"status": "error", "message": exc.message})
    except Exception as exc:
        logger.exception("Unexpected error setting weightage: %s", exc)
        return JSONResponse(status_code=500, content={"status": "error", "message": str(exc)})


@router.post("/api/weightage/inactive")
async def api_inactive_weightage(
    payload: InactiveWeightagePayload,
    user: Dict[str, Any] = Depends(enforce_approver_role),
):
    """
    Section 5.6 & Section 6.2:
    Marks doer inactive via SP_KPI_Weightage_Inactive.
    """
    user_code = payload.UserCode or user["user_code"]
    try:
        result = await KpiService.inactive_kpi_weightage(
            doer_code=payload.DoerCode,
            inactive_from_str=payload.InactiveFromDate,
            change_reason=payload.ChangeReason,
            user_code=user_code,
            database=payload.Database,
        )
        return result
    except ApiError as exc:
        logger.warning("Procedure error marking inactive: %s", exc.message)
        return JSONResponse(status_code=400, content={"status": "error", "message": exc.message})
    except Exception as exc:
        logger.exception("Unexpected error marking inactive: %s", exc)
        return JSONResponse(status_code=500, content={"status": "error", "message": str(exc)})


@router.get("/api/fms-config/doers")
async def api_get_fms_config_doers(
    database: Optional[str] = Query(None),
):
    """
    Section 7.1 & Deliverable 5:
    The Doer, Backup Doer and Temp Doer dropdowns for FMS_Config and the doer reallocation app.
    List only employees with a weightage in effect today.
    """
    try:
        doers = await KpiService.get_measured_doers_for_fms_config(database=database)
        return {"status": "success", "count": len(doers), "data": doers}
    except Exception as exc:
        logger.exception("Failed to get FMS_Config measured doers: %s", exc)
        return JSONResponse(status_code=500, content={"status": "error", "message": str(exc)})


@router.get("/health")
async def health_check():
    return {
        "status": "healthy",
        "app_name": settings.app_name,
        "environment": settings.environment,
        "database": settings.api_database,
    }
