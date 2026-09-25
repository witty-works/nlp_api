"""Validation functions for API versions and client versions.

Also exposes typed version constants.
"""

from fastapi import HTTPException, status
from packaging.version import InvalidVersion, Version
from typing import Final, Literal

from app.models import Client


# Typed API version constants
CHECK_API_VERSION: Final[Literal["2.4"]] = "2.4"
REPHRASE_API_VERSION: Final[Literal["1.0"]] = "1.0"


def rephrase_api_version(version: str) -> None:
    if version != REPHRASE_API_VERSION:  # pragma: no cover
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"API version '{version}' not supported, please use version '{REPHRASE_API_VERSION}'."
            ),
        )


def check_api_version(version: str) -> None:
    if version != CHECK_API_VERSION:  # pragma: no cover
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"API version '{version}' not supported, please use version '{CHECK_API_VERSION}'."
            ),
        )


def client_version(
    client: Client, minimum_versions: dict[str, str] | None = None
) -> None:
    """Reject a client below the minimum version set for its name.

    A request without a client string is never rejected: it is parsed as
    web-ext 0.0.0, which would fail any web-ext minimum. Clients read the 400
    as "this version is no longer supported" and show its detail.
    """
    if not minimum_versions or not client.given:
        return

    if client.name in minimum_versions and _below(
        client.version or "0.0.0", minimum_versions[client.name]
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Client version '{client.version}' not supported, please use at least '{minimum_versions[client.name]}'.",
        )


def _below(version: str, minimum: str) -> bool:
    """Semantic version order, pre-releases before their release (`2.4.0-beta`
    is below `2.4.0`). A version that does not parse counts as below: with a
    minimum set, "abc" is not a supported version."""
    try:
        return Version(version) < Version(minimum)
    except InvalidVersion:
        return True
