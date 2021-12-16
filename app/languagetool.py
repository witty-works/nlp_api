import json
import base64

# Languagetool URL
def get_languagetool_url(settings):
    if settings.languagetool_api:
        return settings.languagetool_api

    if settings.platform_relationships:
        relationships = json.loads(base64.b64decode(settings.platform_relationships))
        languagetool = relationships["languagetool"][0]
        return "%(scheme)s://%(host)s:%(port)d/v2" % languagetool

    return "https://lt.default.api.witty.works/v2"
