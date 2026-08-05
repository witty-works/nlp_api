# https://github.com/425show/fastapi_microsoft_identity/blob/e98f1ff4a86e436b2d6d874738ff655fe1a63e54/LICENSE
"""The MIT License (MIT)

Copyright (c) 2021 Christos Matskas

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
"""

from fastapi import Request
import jwt
import base64
import logging
import uuid
import re
import asyncio
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import (
    Request,
    HTTPException,
    status,
)
from app.settings import Settings
from app.redis import Redis
from app.http import Http


class AuthError(Exception):
    def __init__(self, error_msg: str, status_code: int):
        super().__init__(error_msg)

        self.error_msg = error_msg
        self.status_code = status_code


def get_token_auth_header(request: Request):
    auth = request.headers.get("Authorization", None)
    return get_token_(auth)


def get_unverified_token_claims(request: Request):
    token = get_token_auth_header(request)
    return get_unverified_token_claims_(token)


async def get_rsa_key(redis: Redis, session, token, url):
    unverified_header = jwt.get_unverified_header(token)
    key = "rsa_pem:" + unverified_header["kid"]
    rsa_key = redis.db.get(key)
    if rsa_key:
        return rsa_key

    rsa_key, ttl = await get_rsa_key_(session, unverified_header["kid"], url)

    # Set cached RSA PEM with TTL to handle JWKS rotation. Default to 1 hour.
    try:
        if ttl and isinstance(ttl, int) and ttl > 0:
            redis.db.set(key, rsa_key, ex=ttl)
        else:
            redis.db.set(key, rsa_key, ex=3600)
    except Exception:
        # If Redis set fails, return the key without caching (don't expose internal errors here).
        pass

    return rsa_key


async def decode_b2c_jwt(
    redis: Redis,
    session,
    request: Request,
    tenant_id: str,
    client_id: str,
    scope: str,
    b2c_domain_name: str,
    b2c_policy_name: str,
):
    token = get_token_auth_header(request)
    issuer = f"https://{b2c_domain_name}.b2clogin.com/{tenant_id}/v2.0/".lower()
    audience = client_id

    key_url = f"https://{b2c_domain_name}.b2clogin.com/{b2c_domain_name}.onmicrosoft.com/{b2c_policy_name}/discovery/v2.0/keys"
    rsa_key = await get_rsa_key(redis, session, token, key_url)

    return decode_jwt_(token, rsa_key, issuer, audience, scope)


async def decode_jwt(
    redis: Redis, session, request: Request, tenant_id: str, client_id: str, scope: str
):
    # https://learn.microsoft.com/en-us/entra/identity-platform/access-tokens#multi-tenant-applications

    try:
        uuid.UUID(tenant_id)
    except ValueError:
        raise AuthError(
            "Token error: The 'tid' in the access token is not a valid GUID", 401
        )

    token = get_token_auth_header(request)
    key_url = f"https://login.microsoftonline.com/common/discovery/v2.0/keys"
    rsa_key = await get_rsa_key(redis, session, token, key_url)

    issuer = f"https://login.microsoftonline.com/{tenant_id}/v2.0"
    audience = f"{client_id}"

    return decode_jwt_(token, rsa_key, issuer, audience, scope)


async def decode_jwks_jwt(
    redis: Redis,
    session,
    request: Request,
    jwks_url: str,
    client_id: str,
    issuer: str | None = None,
    scope: str | None = None,
):
    """Verify a token against a plain JWKS document, looked up by `kid`.

    Used for the tokens the dashboard issues via Laravel Passport, which carry
    neither the tenant id of an Entra token nor a B2C policy — only a `kid` in
    the header pointing at the issuer's JWKS. The key is fetched and cached by
    the same path as the Microsoft ones, so a key rotation needs no redeploy.
    """
    token = get_token_auth_header(request)
    rsa_key = await get_rsa_key(redis, session, token, jwks_url)

    return decode_jwt_(token, rsa_key, issuer, client_id, scope)


def decode_jwt_(
    token: str,
    rsa_key: dict,
    issuer: str | None,
    audience: str,
    scope: str | None,
):
    try:
        # `exp` and `nbf` are verified by PyJWT itself. `issuer=None` skips the
        # issuer check, which is what a Passport token needs — it has no `iss`.
        claims = jwt.decode(
            token, rsa_key, algorithms=["RS256"], audience=audience, issuer=issuer
        )
    except jwt.MissingRequiredClaimError as error:
        # Raised when the token omits a claim we asked to be verified, e.g. an
        # `iss` for an issuer that was configured to emit one.
        raise AuthError(f"Token error: The {error.claim} claim is missing", 401)
    except jwt.ExpiredSignatureError:
        raise AuthError("Token error: The token has expired", 401)
    except jwt.InvalidIssuerError:
        raise AuthError("Token error: Please check the issuer", 401)
    except jwt.InvalidAudienceError:
        raise AuthError("Token error: Please check the audience", 401)
    except jwt.InvalidIssuedAtError:
        raise AuthError("Token error: iat claim is not a number", 401)
    except Exception:
        raise AuthError("Token error: Unable to parse authentication", 401)

    # An explicit None means the issuer defines no scopes to check against —
    # Passport's `scopes` claim is a JSON array and empty for our client. An
    # empty string still fails validation, so a misconfigured Microsoft issuer
    # keeps being rejected rather than silently accepting every scope.
    if scope is not None:
        validate_scope_(scope, claims)

    return claims


def validate_scope_(required_scope: str, claims: dict):
    ## check to ensure that either a valid scope is present in the token
    if claims.get("scp") is None:
        raise AuthError(
            "IDW10201: No scope was found in the bearer token",
            403,
        )

    if not claims.get("scp"):
        raise AuthError("IDW10201: No scope claim was found in the bearer token", 403)

    # the scp claim is a space delimited string
    token_scopes = claims["scp"].split()
    for token_scope in token_scopes:
        if token_scope.lower() == required_scope.lower():
            return True

    raise AuthError(
        f'IDW10203: The "scope" or "scp" claim does not contain scopes {required_scope} or was not found',
        403,
    )


def get_token_(auth: str):
    if not auth:
        raise AuthError("Authentication error: Authorization header is missing", 401)

    parts = auth.split()

    if parts[0].lower() != "bearer":
        raise AuthError(
            "Authentication error: Authorization header must start with ' Bearer'", 401
        )
    elif len(parts) == 1:
        raise AuthError("Authentication error: Token not found", 401)
    elif len(parts) > 2:
        raise AuthError(
            "Authentication error: Authorization header must be 'Bearer <token>'", 401
        )

    token = parts[1]
    return token


def get_unverified_token_claims_(token: str):
    return jwt.decode(token, options={"verify_signature": False})


def base64_to_long(data):
    if isinstance(data, str):
        data = data.encode("ascii")

    # urlsafe_b64decode will happily convert b64encoded data. JWKS values carry
    # no padding, and the extra "==" is ignored when none is needed.
    return int.from_bytes(base64.urlsafe_b64decode(bytes(data) + b"=="), "big")


def convert_to_pem(n, e):
    """Turn a JWKS RSA entry into a PEM that PyJWT and Redis can both hold."""
    public_key = rsa.RSAPublicNumbers(
        e=base64_to_long(e), n=base64_to_long(n)
    ).public_key()

    return public_key.public_bytes(
        serialization.Encoding.PEM,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    )


async def get_rsa_key_(session, kid, url):
    # Robust fetching with retries, timeouts and exponential backoff.
    retries = 3
    timeout_secs = 5
    backoff_base = 0.5

    for attempt in range(retries):
        try:
            resp = await asyncio.wait_for(session.get(url), timeout=timeout_secs)
            async with resp as r:
                if r.status != 200:  # pragma: no cover
                    # Don't reflect remote response body to clients; return a sanitized error.
                    raise AuthError(
                        f"Fetching RSA key resulted in HTTP status {r.status}", 400
                    )

                jwks = await r.json()
                for key in jwks.get("keys", []):
                    if key.get("kid") == kid:
                        pem = convert_to_pem(key["n"], key["e"])

                        # Try to parse Cache-Control header for max-age to set TTL on cached key
                        cache_control = r.headers.get("Cache-Control", "") or ""
                        ttl = None
                        m = re.search(r"max-age=(\d+)", cache_control)
                        if m:
                            try:
                                ttl = int(m.group(1))
                            except Exception:
                                ttl = None

                        return pem, ttl

                # If we reached here, no matching kid was found in the JWKS
                raise AuthError("Unable to fetch RSA key", 400)

        except AuthError:
            # Don't retry on deterministic auth errors (4xx), re-raise immediately.
            raise
        except asyncio.TimeoutError:
            if attempt < retries - 1:
                await asyncio.sleep(backoff_base * (2**attempt))
                continue
            raise AuthError("Timeout while fetching RSA keys from issuer", 400)
        except Exception as error:
            # For transient network errors, retry a few times.
            if attempt < retries - 1:
                await asyncio.sleep(backoff_base * (2**attempt))
                continue

            # The client only ever sees the sanitized message, which makes a
            # misconfiguration hard to place — a self-signed issuer certificate
            # reads exactly like the issuer being down. Log the real cause.
            logging.getLogger("nlp_api").error(
                "Fetching RSA keys from %s failed: %s: %s",
                url,
                type(error).__name__,
                error,
            )

            raise AuthError("Failed to fetch RSA keys from issuer", 400)


def fetch_email_from_claims(claims: dict) -> str:
    try:  # pragma: no cover
        if "email" in claims:
            return claims["email"]

        if "emails" in claims and len(claims["emails"]) > 0:
            return claims["emails"][0]

        # Office SSO
        if "preferred_username" in claims:
            return claims["preferred_username"]
    except KeyError:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="access token does not map to email",
        )

    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="no email found in claim",
    )


async def fetch_user(
    request: Request, settings: Settings, redis: Redis, http: Http
) -> str | None:
    if "authorization" in request.headers and request.headers[
        "authorization"
    ].lower().startswith("bearer"):
        try:
            unverified_claims = get_unverified_token_claims(request)
            for key in settings.sso_configs:
                config = settings.sso_configs[key]
                # An unconfigured issuer has an empty client_id, which would
                # otherwise match any token whose `aud` is missing or empty.
                if not config.get("client_id"):
                    continue

                if (
                    "aud" not in unverified_claims
                    or unverified_claims["aud"] != config["client_id"]
                ):
                    continue

                if "domain" in config:
                    claims = await decode_b2c_jwt(
                        redis,
                        http.ssl_session,
                        request,
                        config["tenant_id"],
                        config["client_id"],
                        config["expected_scope"],
                        config["domain"],
                        config["policy"],
                    )
                elif "jwks_url" in config:
                    claims = await decode_jwks_jwt(
                        redis,
                        http.ssl_session,
                        request,
                        config["jwks_url"],
                        config["client_id"],
                        config["issuer"],
                        config["expected_scope"],
                    )
                elif "tid" in unverified_claims:
                    claims = await decode_jwt(
                        redis,
                        http.ssl_session,
                        request,
                        unverified_claims["tid"],
                        config["client_id"],
                        config["expected_scope"],
                    )
                else:
                    # The client id matched but the token carries nothing this
                    # issuer knows how to verify with.
                    continue

                return fetch_email_from_claims(claims)
        except Exception as e:
            # Sanitize error messages returned to clients. If it's an AuthError,
            # surface the sanitized message; otherwise return a generic forbidden.
            if isinstance(e, AuthError):
                detail = getattr(e, "error_msg", "Forbidden")
            else:
                detail = "Forbidden"

            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=detail)

        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Token provided did not map to a valid client ID",
        )

    elif "x-key" in request.headers:
        return redis.get_api_key_email(request.headers["x-key"])

    if settings.testing:
        # Only use test credentials when the explicit testing header is present
        # or when an explicit allow flag is enabled in settings.
        testing_header = request.headers.get("x-testing-auth")
        if testing_header:
            return testing_header

    return None
