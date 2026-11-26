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
import json
import logging
import uuid
import re
import hashlib
from redis.exceptions import RedisError
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
from app import managed_keys
from app.request_team import key_team


class AuthError(Exception):
    def __init__(self, error_msg: str, status_code: int):
        super().__init__(error_msg)

        self.error_msg = error_msg
        self.status_code = status_code


class UnknownKid(AuthError):
    """The issuer's JWKS has no key by the token's `kid`."""


def get_token_auth_header(request: Request):
    auth = request.headers.get("Authorization", None)
    return get_token_(auth)


def get_unverified_token_claims(request: Request):
    token = get_token_auth_header(request)
    return get_unverified_token_claims_(token)


# How long a `kid` the issuer's JWKS did not have is answered from the cache,
# so that tokens with made-up ones do not each send a request to the issuer.
# Short, as a key the issuer has just published is refused meanwhile.
UNKNOWN_KID_TTL = 60
# A `kid` is a short name; a longer one is no key of any issuer here.
KID_MAX_LENGTH = 256


def rsa_key_name(url: str, kid: str) -> str:
    """The cache entry of one issuer's key: by its JWKS address as well as its
    `kid`, which issuers choose themselves, so one cannot shadow another's."""
    return f"rsa_pem:{hashlib.sha256(url.encode()).hexdigest()}:{kid}"


async def get_rsa_key(redis: Redis, session, token, url):
    unverified_header = jwt.get_unverified_header(token)
    kid = unverified_header.get("kid")
    if not isinstance(kid, str) or not kid or len(kid) > KID_MAX_LENGTH:
        raise AuthError("Unable to fetch RSA key", 401)

    key = rsa_key_name(url, kid)
    rsa_key = redis.db.get(key)
    if rsa_key:
        return rsa_key

    unknown = "unknown_kid:" + key.removeprefix("rsa_pem:")
    if redis.db.get(unknown):
        raise UnknownKid("Unable to fetch RSA key", 401)

    try:
        rsa_key, ttl = await get_rsa_key_(session, kid, url)
    except UnknownKid:
        try:
            redis.db.set(unknown, "1", ex=UNKNOWN_KID_TTL)
        except Exception:
            pass
        raise

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
        # `exp` and `nbf` are verified by PyJWT itself, and `exp` is required:
        # a token without one would be valid for ever. `issuer=None` skips the
        # issuer check.
        claims = jwt.decode(
            token,
            rsa_key,
            algorithms=["RS256"],
            audience=audience,
            issuer=issuer,
            options={"require": ["exp"]},
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
                        f"Fetching RSA key resulted in HTTP status {r.status}", 503
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
                raise UnknownKid("Unable to fetch RSA key", 401)

        except AuthError:
            # Don't retry on deterministic auth errors (4xx), re-raise immediately.
            raise
        except asyncio.TimeoutError:
            if attempt < retries - 1:
                await asyncio.sleep(backoff_base * (2**attempt))
                continue
            raise AuthError("Timeout while fetching RSA keys from issuer", 503)
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

            raise AuthError("Failed to fetch RSA keys from issuer", 503)


def token_refused(detail: str) -> HTTPException:
    """A 401 for a token that is missing, malformed, expired, for another
    audience or not signed by its issuer (RFC 6750, 3.1): a client may get a
    new one and try again."""
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detail,
        headers={"WWW-Authenticate": 'Bearer error="invalid_token"'},
    )


# Seconds a client waits before trying again when a token could not be
# verified for a reason on our side.
AUTH_RETRY_AFTER = 10


def auth_unavailable(detail: str) -> HTTPException:
    """A 503: the token could not be verified, which says nothing about the
    token, so the client keeps it and tries again later."""
    return HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail=detail,
        headers={"Retry-After": str(AUTH_RETRY_AFTER)},
    )


def auth_http_error(error: AuthError) -> HTTPException:
    """The answer to an AuthError: 503 when the issuer's keys could not be
    fetched, which says nothing about the token; 403 for a valid token whose
    user is not let in (a scope, an unverified email); 401 otherwise."""
    if error.status_code == 503:
        return auth_unavailable(error.error_msg)
    if error.status_code == 403:
        return HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail=error.error_msg
        )

    return token_refused(error.error_msg)


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


def _synced_teams(redis: Redis, email: str) -> list[str] | None:
    """The teams the dashboard last synced for an email, None without any."""
    stored = redis.db.get(redis.get_user_id(email))
    if stored is None:
        return None
    teams = json.loads(stored).get("teams")
    return teams if isinstance(teams, list) else None


def resolve_key(request: Request, redis: Redis, api_key: str) -> str | None:
    """The email an x-key resolves to. A managed key for a team only resolves
    while the person's synced user config lists that team, and then makes it
    the request's team (key_team); without a synced list it is refused."""
    managed = managed_keys.lookup(redis, api_key)
    if managed is None:
        request.state.key_team = None
        key_team.set(None)
        return redis.get_api_key_email(api_key)

    if managed.team_id is not None:
        teams = _synced_teams(redis, managed.email)
        if teams is None or managed.team_id not in teams:
            return None

    request.state.key_team = managed.team_id
    key_team.set(managed.team_id)
    return managed.email


async def fetch_user(
    request: Request, settings: Settings, redis: Redis, http: Http
) -> str | None:
    # Already resolved for this request by the key gate (require_api_key).
    resolved = getattr(request.state, "resolved_user", None)
    if resolved is not None:
        key_team.set(getattr(request.state, "key_team", None))
        return resolved

    # An x-key decides when there is one, before any Bearer token: gateways
    # such as agentgateway forward the client's own Authorization header (its
    # LLM key) next to the x-key they add for this API. A wrong x-key is not a
    # reason to try the token instead. The browser extension orders its own
    # headers the same way.
    if "x-key" in request.headers:
        # Several would leave it to header order which configuration applies,
        # and behind a gateway that forwards its client's headers the client's
        # own may come first.
        if len(request.headers.getlist("x-key")) > 1:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Send one x-key header, not several.",
            )
        return resolve_key(request, redis, request.headers["x-key"])

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
                    # The dashboard's tokens name the user by email, so the
                    # email has to be one its owner confirmed: anyone can sign
                    # up with someone else's address.
                    if claims.get("email_verified") is not True:
                        raise AuthError("Token error: The email is not verified", 403)
                elif "tid" in unverified_claims:
                    claims = await decode_jwt(
                        redis,
                        http.ssl_session,
                        request,
                        unverified_claims["tid"],
                        config["client_id"],
                        config["expected_scope"],
                    )
                    # Office SSO accepts tokens from any Entra tenant, and a
                    # tenant's admin can put any address into a user's email
                    # ("nOAuth"). Only an email whose domain the tenant
                    # verified (`xms_edov`, an optional claim the app
                    # registration has to issue) names the user; never
                    # preferred_username, which Microsoft calls a display hint.
                    if claims.get("xms_edov") is not True or not claims.get("email"):
                        raise AuthError(
                            "Token error: The email domain is not verified", 403
                        )
                    return claims["email"]
                else:
                    # The client id matched but the token carries nothing this
                    # issuer knows how to verify with.
                    continue

                return fetch_email_from_claims(claims)
        except HTTPException:
            raise
        except AuthError as error:
            # Only the sanitized message, never what the issuer answered.
            raise auth_http_error(error) from None
        except RedisError:
            raise auth_unavailable("Token error: Verification unavailable") from None
        except Exception:
            raise token_refused("Token error: Unable to parse authentication")

        raise token_refused("Token provided did not map to a valid client ID")

    if settings.testing:
        # Only use test credentials when the explicit testing header is present
        # or when an explicit allow flag is enabled in settings.
        testing_header = request.headers.get("x-testing-auth")
        if testing_header:
            return testing_header

    return None
