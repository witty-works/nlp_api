import sentry_sdk
from sentry_sdk.integrations.aiohttp import AioHttpIntegration
from sentry_sdk.integrations.starlette import StarletteIntegration
from sentry_sdk.integrations.fastapi import FastApiIntegration

from app.privacy_filter import get_privacy_filter
from app.privacy_filter import PrivacyFilter

from urllib.parse import urlparse


def sentry_clean_sensitive_frame(
    frame: dict, privacy_filter: PrivacyFilter
) -> dict:  # pragma: no cover
    """Clean sensitive data from a Sentry stack frame.

    Args:
        frame: Stack frame dictionary from Sentry event
        privacy_filter: PrivacyFilter instance for cleaning data

    Returns:
        Cleaned frame dictionary
    """
    # List of variable names that don't need cleaning
    skip_vars = {"rule", "alternatives", "word_types", "word_type", "client"}

    for var_name in frame.get("vars", {}):
        if var_name in skip_vars or var_name.endswith(("_index", "_form")):
            continue

        frame["vars"][var_name] = privacy_filter.clean_var(frame["vars"][var_name])

    return frame


def sentry_clean_event_data(event: dict, hint: dict) -> dict:  # pragma: no cover
    """Clean sensitive data from Sentry events before sending.

    Args:
        event: Sentry event dictionary
        hint: Additional context hints from Sentry

    Returns:
        Cleaned event dictionary
    """
    privacy_filter = get_privacy_filter()

    # Clean exception frames
    for exception in event.get("exception", {}).get("values", []):
        for frame in exception.get("stacktrace", {}).get("frames", []):
            sentry_clean_sensitive_frame(frame, privacy_filter)

    # Clean thread frames
    for thread in event.get("threads", {}).get("values", []):
        for frame in thread.get("stacktrace", {}).get("frames", []):
            sentry_clean_sensitive_frame(frame, privacy_filter)

    # Clean request data
    if "text" in event.get("request", {}).get("data", {}):
        event["request"]["data"]["text"] = privacy_filter.clean_var(
            event["request"]["data"]["text"]
        )

    return event


def sentry_filter_transactions(event: dict, hint: dict) -> dict | None:
    """Filter Sentry transactions to only include /check endpoints.

    Args:
        event: Sentry transaction event
        hint: Additional context hints from Sentry

    Returns:
        Event if it's a /check endpoint, None otherwise
    """
    url_string = event["request"]["url"]
    parsed_url = urlparse(url_string)

    return event if parsed_url.path.endswith("/check") else None


def set_up_sentry_sdk(version: str, settings):
    """Initialize Sentry SDK with privacy filters and integrations.

    Args:
        version: Application version string for release tracking
        settings: Settings instance with Sentry configuration

    Returns:
        Initialized sentry_sdk module, or None if Sentry is disabled
    """
    if not settings.sentry_dsn or settings.testing:
        return None

    integrations = [
        AioHttpIntegration(),
        StarletteIntegration(transaction_style="endpoint"),
        FastApiIntegration(transaction_style="endpoint"),
    ]

    sentry_sdk.init(
        dsn=settings.sentry_dsn,
        sample_rate=settings.sentry_sample_rate,
        traces_sample_rate=settings.sentry_traces_sample_rate,
        profiles_sample_rate=settings.sentry_profiles_sample_rate,
        integrations=integrations,
        release=version,
        environment=settings.platform_environment,
        before_send=sentry_clean_event_data,
        before_send_transaction=sentry_filter_transactions,
    )

    return sentry_sdk
