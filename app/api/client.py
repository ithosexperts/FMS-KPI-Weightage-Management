"""
API Client for HoseXperts Company Gateway.
Supports both OperationsDB (apiv3.php) and Test_OperationsDB (apiv2.php).
"""
import logging
from typing import Any, Dict, List, Optional
import httpx

from app.config import settings

logger = logging.getLogger(__name__)


class ApiError(Exception):
    def __init__(self, message: str, status_code: int | None = None, raw_response: Any = None):
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.raw_response = raw_response


def get_headers() -> Dict[str, str]:
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json; charset=utf-8",
    }
    if settings.api_auth_token:
        headers["API-Key"] = settings.api_auth_token
        headers["Authorization"] = f"Bearer {settings.api_auth_token}"
    return headers


async def query_gateway(
    table: str,
    action: str = "select",
    database: Optional[str] = None,
    columns: Optional[List[str]] = None,
    filters: Optional[Dict[str, Any]] = None,
    data: Optional[Dict[str, Any]] = None,
    where: Optional[Dict[str, Any]] = None,
    order_by: Optional[str] = None,
    limit: Optional[int] = None,
    page: Optional[int] = None,
    fetch_all: bool = True,
    additional_payload: Optional[Dict[str, Any]] = None,
    timeout: Optional[float] = None,
) -> Dict[str, Any]:
    """Execute a query against the HoseXperts API gateway."""
    target_db = database or settings.api_database
    url = settings.get_api_url_for_db(target_db)

    payload: Dict[str, Any] = {
        "action": action,
        "table": table,
        "database": target_db,
        "fetchAll": fetch_all,
    }

    if columns:
        payload["columns"] = columns
    if filters:
        payload["filters"] = filters
    if data:
        payload["data"] = data
    if where:
        payload["where"] = where
    if order_by:
        payload["orderBy"] = order_by
    if limit is not None:
        payload["limit"] = limit
    if page is not None:
        payload["page"] = page

    if additional_payload:
        payload.update(additional_payload)

    req_timeout = timeout or settings.api_timeout

    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(req_timeout, connect=10.0),
            verify=False,
        ) as client:
            resp = await client.post(url, json=payload, headers=get_headers())
            resp.raise_for_status()
            res_json = resp.json()
    except httpx.HTTPStatusError as exc:
        msg = f"HTTP {exc.response.status_code} from gateway: {exc.response.text[:500]}"
        logger.error(msg)
        raise ApiError(msg, status_code=exc.response.status_code) from exc
    except httpx.RequestError as exc:
        msg = f"Network failure connecting to gateway ({url}): {exc}"
        logger.error(msg)
        raise ApiError(msg) from exc
    except ValueError as exc:
        msg = f"Invalid JSON response from gateway: {exc}"
        logger.error(msg)
        raise ApiError(msg) from exc

    # Status check
    status = str(res_json.get("status") or "").lower()
    if status == "error" or "error" in res_json:
        err_msg = res_json.get("message") or res_json.get("error") or "Unknown gateway error"
        raise ApiError(str(err_msg), raw_response=res_json)

    return res_json
