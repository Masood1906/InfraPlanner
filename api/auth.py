# api/auth.py
# API key authentication.
# All protected routes depend on verify_api_key.
# Clients must send:  X-API-Key: <API_SECRET_KEY from .env>

import hmac
import logging
import os
from fastapi import Security, HTTPException, status
from fastapi.security import APIKeyHeader

logger = logging.getLogger(__name__)
_API_KEY_HEADER = APIKeyHeader(name="X-API-Key", auto_error=False)


def verify_api_key(api_key: str = Security(_API_KEY_HEADER)) -> str:
    secret = os.getenv("API_SECRET_KEY", "")

    if not secret:
        # No key configured — auth is disabled, allow all requests.
        # Log a warning so operators notice this in production.
        logger.warning("API_SECRET_KEY not set — admin endpoint is unprotected.")
        return "no-auth"

    # hmac.compare_digest prevents timing attacks on key comparison.
    if not api_key or not hmac.compare_digest(api_key, secret):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing X-API-Key header.",
        )
    return api_key
