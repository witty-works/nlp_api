import sentry_sdk
from sentry_sdk.integrations.aiohttp import AioHttpIntegration
from sentry_sdk.integrations.starlette import StarletteIntegration
from sentry_sdk.integrations.fastapi import FastApiIntegration
from sentry_sdk.scrubber import DEFAULT_DENYLIST, EventScrubber

from app.privacy_filter import get_privacy_filter
from app.privacy_filter import PrivacyFilter

from urllib.parse import urlparse

# Sentry's own scrubbing removes headers and fields with these names from every
# event. Its defaults cover Authorization and X-Api-Key, not the `x-key` header
# this API authenticates with.
SENTRY_DENYLIST = [*DEFAULT_DENYLIST, "x-key", "x_key"]


def _clean_request(event: dict, privacy_filter: PrivacyFilter) -> None:
    """No credential and no text in an event's request: the key header goes,
    the query string goes (the management routes take keys there), and the
    body goes whole. Filtering it was not enough: the privacy filter catches
    emails and numbers, not what people write about themselves, and every
    route but the management ones carries the user's text."""
    request = event.get("request")
    if not isinstance(request, dict):
        return
    headers = request.get("headers")
    if isinstance(headers, dict):
        for name in [n for n in headers if n.lower() in ("x-key", "x_key")]:
            del headers[name]
    request.pop("query_string", None)
    request.pop("data", None)


def _clean_messages(event: dict, privacy_filter: PrivacyFilter) -> None:
    """Log messages through the privacy filter: the event's own, which an
    ERROR log line becomes, and the breadcrumbs of the lines before it. The
    code does not log request text; this is for a line that does anyway."""
    if isinstance(event.get("message"), str):
        event["message"] = privacy_filter.clean(event["message"])
    logentry = event.get("logentry")
    if isinstance(logentry, dict):
        for key in ("message", "formatted", "params"):
            if key in logentry:
                logentry[key] = privacy_filter.clean_var(logentry[key])
    breadcrumbs = event.get("breadcrumbs")
    values = breadcrumbs.get("values") if isinstance(breadcrumbs, dict) else breadcrumbs
    for breadcrumb in values if isinstance(values, list) else []:
        if isinstance(breadcrumb, dict) and isinstance(breadcrumb.get("message"), str):
            breadcrumb["message"] = privacy_filter.clean(breadcrumb["message"])


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
    # Local variables hold the text being checked under many names (sentence,
    # suggestion, alternatives, *_form); none of them goes. Sentry is also
    # initialised without them; this is for an event that has them anyway.
    frame.pop("vars", None)
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

    # Clean exception frames, and the messages, which may quote input
    for exception in event.get("exception", {}).get("values", []):
        if isinstance(exception.get("value"), str):
            exception["value"] = privacy_filter.clean(exception["value"])
        for frame in exception.get("stacktrace", {}).get("frames", []):
            sentry_clean_sensitive_frame(frame, privacy_filter)

    # Clean thread frames
    for thread in event.get("threads", {}).get("values", []):
        for frame in thread.get("stacktrace", {}).get("frames", []):
            sentry_clean_sensitive_frame(frame, privacy_filter)

    _clean_request(event, privacy_filter)
    _clean_messages(event, privacy_filter)

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
    if not parsed_url.path.endswith("/check"):
        return None

    _clean_request(event, get_privacy_filter())
    return event


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
        environment=settings.environment,
        before_send=sentry_clean_event_data,
        # The user's text is in request bodies and local variables; neither
        # is collected (sentry_clean_event_data removes them again).
        include_local_variables=False,
        max_request_body_size="never",
        before_send_transaction=sentry_filter_transactions,
        event_scrubber=EventScrubber(denylist=SENTRY_DENYLIST, recursive=True),
    )

    return sentry_sdk
