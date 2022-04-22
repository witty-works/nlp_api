import sentry_sdk
from sentry_sdk.integrations.aiohttp import AioHttpIntegration
from app.privacy_filter import get_privacy_filter
from app.privacy_filter import PrivacyFilter


def sentry_clean_sensitive_frame(
    frame, privacy_filter: PrivacyFilter
):  # pragma: no cover
    for var_name in frame.get("vars", None):
        frame["vars"][var_name] = privacy_filter.clean_var(frame["vars"][var_name])

    return frame


def sentry_clean_event_data(event):  # pragma: no cover
    privacy_filter = get_privacy_filter()

    for exception in event.get("exception", {}).get("values", []):
        for frame in exception.get("stacktrace", {}).get("frames", []):
            frame = sentry_clean_sensitive_frame(frame, privacy_filter)

    for exception in event.get("threads", {}).get("values", []):
        for frame in exception.get("stacktrace", {}).get("frames", []):
            frame = sentry_clean_sensitive_frame(frame, privacy_filter)

    return event


# Sentry SDK set up
def set_up_sentry_sdk(version, settings):
    if not settings.sentry_dsn or settings.testing == True:
        return None

    integrations = [AioHttpIntegration()]

    sentry_sdk.init(
        dsn=settings.sentry_dsn,
        traces_sample_rate=settings.sentry_traces_sample_rate,
        sample_rate=settings.sentry_sample_rate,
        integrations=integrations,
        release=version,
        environment=settings.platform_environment,
        before_send=sentry_clean_event_data,
    )

    return sentry_sdk
