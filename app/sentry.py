import sentry_sdk
from sentry_sdk.integrations.aiohttp import AioHttpIntegration
from app.persidio import Persidio


def sentry_clean_sensitive_frame(frame, persidio: Persidio):
    for var_name in frame.get("vars", None):
        frame["vars"][var_name] = persidio.clean_var(frame["vars"][var_name], persidio)

    return frame


def sentry_clean_event_data(event, hint):
    persidio = Persidio

    for exception in event.get("exception", {}).get("values", []):
        for frame in exception.get("stacktrace", {}).get("frames", []):
            frame = sentry_clean_sensitive_frame(frame, persidio)

    for exception in event.get("threads", {}).get("values", []):
        for frame in exception.get("stacktrace", {}).get("frames", []):
            frame = sentry_clean_sensitive_frame(frame, persidio)

    return event


# Sentry SDK set up
def set_up_sentry_sdk(version, settings):
    if not settings.sentry_dsn or settings.testing == True:
        return None

    sentry_sdk.init(
        dsn=settings.sentry_dsn,
        traces_sample_rate=settings.sentry_traces_sample_rate,
        sample_rate=settings.sentry_sample_rate,
        integrations=[AioHttpIntegration()],
        release=version,
        environment=settings.platform_environment,
        before_send=sentry_clean_event_data,
    )

    return sentry_sdk
