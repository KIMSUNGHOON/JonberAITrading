"""
Upbit API Authentication Module

Implements JWT token generation for Upbit EXCHANGE API authentication.
Based on Upbit API documentation:
- Uses HS256 algorithm
- Requires query_hash (SHA512) for requests with parameters
"""

import hashlib
import time
import uuid
from typing import Optional
from urllib.parse import urlencode

import jwt


def generate_jwt_token(
    access_key: str,
    secret_key: str,
    query: Optional[dict] = None,
) -> str:
    """
    Generate JWT token for Upbit API authentication.

    Args:
        access_key: Upbit API access key
        secret_key: Upbit API secret key
        query: Optional query parameters for the request

    Returns:
        JWT token string (without 'Bearer ' prefix)

    Example:
        >>> token = generate_jwt_token(access_key, secret_key)
        >>> headers = {"Authorization": f"Bearer {token}"}
    """
    payload = {
        "access_key": access_key,
        "nonce": str(uuid.uuid4()),
        "timestamp": round(time.time() * 1000),
    }

    # Add query hash if query parameters exist
    if query:
        # Sort query parameters for consistent hashing
        query_string = urlencode(query).encode("utf-8")

        # Generate SHA512 hash
        m = hashlib.sha512()
        m.update(query_string)

        payload["query_hash"] = m.hexdigest()
        payload["query_hash_alg"] = "SHA512"

    # Encode JWT with HS256
    return jwt.encode(payload, secret_key, algorithm="HS256")


def generate_authorization_header(
    access_key: str,
    secret_key: str,
    query: Optional[dict] = None,
) -> dict:
    """
    Generate complete Authorization header for Upbit API.

    Args:
        access_key: Upbit API access key
        secret_key: Upbit API secret key
        query: Optional query parameters

    Returns:
        Dictionary with Authorization header
    """
    token = generate_jwt_token(access_key, secret_key, query)
    return {"Authorization": f"Bearer {token}"}
