import posthog


def set_up_posthog(settings):
    if not settings.training_data_enabled:
        return

    posthog.api_key = settings.posthog_api_key
    posthog.host = settings.posthog_host

    if settings.logging_config_level == "DEBUG":
        posthog.debug = True

    if settings.testing:
        posthog.disabled = True

    return posthog
