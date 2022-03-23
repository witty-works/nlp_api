from fastapi_microsoft_identity import initialize


def initialize_aadb2c(settings):
    initialize(
        settings.aadb2c_tenant_id,
        settings.aadb2c_client_id,
        settings.aadb2c_policy,
        settings.aadb2c_domain,
    )
