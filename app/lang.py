import gettext

class Lang(object):
    def __init__(self, locale):
        self.locale = locale[0:2]

        language = gettext.translation(
            "messages",
            localedir="locales",
            languages=[locale.replace("-", "_")]
        )

        language.install()

        self._ = language.gettext