"""Dashboard authentication for API clients and the operator's browser."""

from __future__ import annotations

import base64
import binascii
import os
import secrets

from fastapi import HTTPException, Request

HEALTH_PATHS = frozenset({"/health", "/healthz", "/readyz"})


def require_dashboard_auth(request: Request) -> None:
    """Accept X-API-Key or browser Basic auth; fail closed in production.

    Browser username: operator. Password: DASHBOARD_API_KEY. Credentials are
    never accepted in query strings or stored in browser local storage.
    """
    expected = os.environ.get("DASHBOARD_API_KEY", "")
    production = os.environ.get("ENVIRONMENT", "development").lower() in {"production", "staging"}
    if not expected:
        if production:
            raise HTTPException(503, "Dashboard authentication is not configured")
        return
    if production and len(expected) < 32:
        raise HTTPException(503, "Dashboard credentials must contain at least 32 characters")
    supplied = request.headers.get("x-api-key", "")
    if supplied and secrets.compare_digest(supplied.encode(), expected.encode()):
        return
    scheme, _, credentials = request.headers.get("authorization", "").partition(" ")
    if scheme.lower() == "basic":
        try:
            decoded = base64.b64decode(credentials, validate=True).decode("utf-8")
            username, _, password = decoded.partition(":")
        except (ValueError, binascii.Error, UnicodeError):
            username, password = "", ""
        if username == "operator" and secrets.compare_digest(password.encode(), expected.encode()):
            if request.method not in {"GET", "HEAD", "OPTIONS"}:
                scheme = "https" if production else request.url.scheme
                expected_origin = f"{scheme}://{request.headers.get('host', '')}"
                if request.headers.get("origin", "") != expected_origin:
                    raise HTTPException(403, "A same-origin request is required")
            return
    raise HTTPException(
        401,
        "Invalid or missing dashboard credentials",
        headers={"WWW-Authenticate": 'Basic realm="Trading Bot", charset="UTF-8"'},
    )
