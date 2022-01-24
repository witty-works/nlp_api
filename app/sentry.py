import sentry_sdk
from sentry_sdk.integrations.aiohttp import AioHttpIntegration

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
    )

    return sentry_sdk
