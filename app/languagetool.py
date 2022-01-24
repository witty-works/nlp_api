import json
import base64

# Languagetool URL
def get_languagetool_url(settings):
    if settings.languagetool_api:
        return settings.languagetool_api

    return "https://lt.default.api.witty.works/v2"
