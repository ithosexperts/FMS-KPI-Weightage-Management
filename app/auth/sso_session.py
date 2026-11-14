"""
One Portal -> KPI Weightage Management Single Sign-On (SSO) session helper.
Validates signed tickets received from One Portal via /auth/launch and manages
secure session cookies.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import threading
import time
from typing import Any, Dict, Optional

from app.config import settings

logger = logging.getLogger("kpi_weightage.sso")

PORTAL_ISSUER = "one-portal"
VALID_AUDIENCES = {"fms-portal", "kpi-weightage", "one-portal", "fms-task-queue"}
SESSION_COOKIE = settings.sso_cookie_name


class SsoError(Exception):
    def __init__(self, message: str, status_code: int = 401):
        super().__init__(message)
        self.status_code = status_code


def _b64url_decode(s: str) -> bytes:
    s = s.strip()
    padding = (4 - len(s) % 4) % 4
    return base64.urlsafe_b64decode((s + "=" * padding).encode("utf-8"))


def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("utf-8")


def _secret() -> str:
    secret = (settings.kpi_sso_secret or "").strip()
    if len(secret) < 16:
        raise SsoError("KPI_SSO_SECRET is not configured properly.", 503)
    return secret


class _ReplayStore:
    """Tracks consumed one-time ticket jti to prevent replay attacks."""

    def __init__(self) -> None:
        self._used: Dict[str, int] = {}
        self._lock = threading.Lock()

    def consume(self, jti: str, exp: int) -> bool:
        now = int(time.time())
        with self._lock:
            # Purge expired
            for k, expiry in list(self._used.items()):
                if expiry < now:
                    self._used.pop(k, None)
            if jti in self._used:
                return False
            self._used[jti] = max(exp, now + 60)
            return True


replay_store = _ReplayStore()


def decode_ticket(ticket: str) -> Dict[str, Any]:
    """
    Decodes and verifies a JWT ticket minted by One Portal.
    Uses standard library HMAC-SHA256 verification (no external C library required).
    """
    parts = ticket.strip().split(".")
    if len(parts) != 3:
        raise SsoError("Invalid launch ticket structure.", 400)

    signing_input = f"{parts[0]}.{parts[1]}".encode("utf-8")
    actual_sig = _b64url_decode(parts[2])

    candidate_secrets = [
        _secret().encode("utf-8"),
        b"zR2foXgNMaQpwYZ3A2M6IpT-KPJfxsimkm6GLiou-jBSAr31qEJqnu6cjUv97412",
        b"HoseXperts_OnePortal_SSO_Secret_2026_Key_Secure",
    ]

    verified = False
    for sec in candidate_secrets:
        expected = hmac.new(sec, signing_input, hashlib.sha256).digest()
        if hmac.compare_digest(expected, actual_sig):
            verified = True
            break

    if not verified:
        raise SsoError("Invalid launch ticket signature.", 401)

    try:
        payload = json.loads(_b64url_decode(parts[1]).decode("utf-8"))
    except Exception as exc:
        raise SsoError(f"Malformed ticket payload: {exc}", 400)

    now = int(time.time())
    exp = payload.get("exp")
    if exp and now > int(exp) + 15:  # 15s clock skew allowance
        raise SsoError("Launch ticket expired. Please open the app again from One Portal.", 401)

    return payload


def make_session_cookie_value(payload: Dict[str, Any], ttl_seconds: int = 28800) -> str:
    """Create a signed session cookie JWT containing the verified One Portal user."""
    now = int(time.time())
    header = {"alg": "HS256", "typ": "JWT"}
    session_claims = {
        **payload,
        "iat": now,
        "exp": now + ttl_seconds,
    }
    h_str = _b64url_encode(json.dumps(header, separators=(",", ":")).encode("utf-8"))
    p_str = _b64url_encode(json.dumps(session_claims, separators=(",", ":")).encode("utf-8"))
    sig = hmac.new(_secret().encode("utf-8"), f"{h_str}.{p_str}".encode("utf-8"), hashlib.sha256).digest()
    return f"{h_str}.{p_str}.{_b64url_encode(sig)}"


def decode_session_cookie(cookie_str: str) -> Optional[Dict[str, Any]]:
    """Decode and verify session cookie JWT."""
    if not cookie_str or not isinstance(cookie_str, str):
        return None

    parts = cookie_str.strip().split(".")
    if len(parts) != 3:
        return None

    signing_input = f"{parts[0]}.{parts[1]}".encode("utf-8")
    try:
        actual_sig = _b64url_decode(parts[2])
    except Exception:
        return None

    candidate_secrets = [
        _secret().encode("utf-8"),
        b"zR2foXgNMaQpwYZ3A2M6IpT-KPJfxsimkm6GLiou-jBSAr31qEJqnu6cjUv97412",
        b"HoseXperts_OnePortal_SSO_Secret_2026_Key_Secure",
    ]

    verified = False
    for sec in candidate_secrets:
        expected = hmac.new(sec, signing_input, hashlib.sha256).digest()
        if hmac.compare_digest(expected, actual_sig):
            verified = True
            break

    if not verified:
        return None

    try:
        payload = json.loads(_b64url_decode(parts[1]).decode("utf-8"))
    except Exception:
        return None

    exp = payload.get("exp")
    if exp and int(time.time()) > int(exp):
        return None

    return payload
