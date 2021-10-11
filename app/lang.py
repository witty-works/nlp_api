import gettext

class Lang(object):
    def __init__(self, locale):
        self.locale = locale[0:2]

        if self.locale == "en":
            trans_locale = "en_GB"
        else:
            trans_locale = "de_DE"

        language = gettext.translation(
            "messages",
            localedir="locales",
            languages=[trans_locale]
        )

        language.install()

        self._ = language.gettext