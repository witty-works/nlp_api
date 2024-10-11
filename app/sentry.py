import sentry_sdk
from sentry_sdk.integrations.aiohttp import AioHttpIntegration
from sentry_sdk.integrations.starlette import StarletteIntegration
from sentry_sdk.integrations.fastapi import FastApiIntegration

from app.privacy_filter import get_privacy_filter
from app.privacy_filter import PrivacyFilter

from urllib.parse import urlparse


def sentry_clean_sensitive_frame(
    frame, privacy_filter: PrivacyFilter
):  # pragma: no cover
    for var_name in frame.get("vars", None):
        if (
            var_name in ["rule", "alternatives", "word_types", "word_type", "client"]
            or var_name.endswith("_index")
            or var_name.endswith("_form")
        ):
            continue

        frame["vars"][var_name] = privacy_filter.clean_var(frame["vars"][var_name])

    return frame


def sentry_clean_event_data(event, hint):  # pragma: no cover
    privacy_filter = get_privacy_filter()

    for exception in event.get("exception", {}).get("values", []):
        for frame in exception.get("stacktrace", {}).get("frames", []):
            frame = sentry_clean_sensitive_frame(frame, privacy_filter)

    for exception in event.get("threads", {}).get("values", []):
        for frame in exception.get("stacktrace", {}).get("frames", []):
            frame = sentry_clean_sensitive_frame(frame, privacy_filter)

    if "text" in event["request"]["data"]:
        event["request"]["data"]["text"] = privacy_filter.clean_var(
            event["request"]["data"]["text"]
        )

    return event


def sentry_filter_transactions(event, hint):
    url_string = event["request"]["url"]
    parsed_url = urlparse(url_string)

    if parsed_url.path.endswith("/check"):
        return event

    return None


# Sentry SDK set up
def set_up_sentry_sdk(version, settings):
    if not settings.sentry_dsn or settings.testing is True:
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
