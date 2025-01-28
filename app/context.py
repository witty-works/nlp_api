import os
import json
import fasttext
import logging
from app.models import (
    LangWithAutoType,
    Language,
    WordType,
)
from app.db import Db
from app.emoji_check import EmojiCheck
from app.rule_check import RuleCheck
from app.regex_check import RegexCheck
from app.nouns import Nouns
from app.verbs import Verbs
from app.adjectives import Adjectives
from app.model import Model
from app.translations import translations
from app.llm_alternatives import LlmAlternatives
from app.lang_detection import LangDetection
from app.categories import get_categories
from app.alternatives import Alternatives
from app.llm_alternatives import LlmAlternatives
from app.prompt import Prompt
from app.languagetool import LanguageTool
from app.db import Db
from app.settings import Settings
from app.logger import Logger
from app.redis import Redis
from app.rules import fetch_static_rules
from app.sentry import set_up_sentry_sdk
from app.query_definitions import (
    declensions_config,
    verb_form_map,
)
from app.http import Http


class AppContext:
    version = "2.4.6"
    translations: dict[str, dict[str, str]]
    declensions_config: dict
    verb_form_map: dict
    categories: dict
    settings: Settings
    logger: logging.Logger
    model: Model
    db: Db
    http: Http
    nouns: Nouns
    verbs: Verbs
    adjectives: Adjectives
    alternatives: Alternatives
    languagetool: LanguageTool
    prompt: Prompt
    llm_alternatives: LlmAlternatives
    rule_check: RuleCheck
    regex_check: RegexCheck
    emoji_check: EmojiCheck
    prompt: Prompt
    langs: list = []

    def __init__(self):
        self.translations = translations
        self.declensions_config = declensions_config
        self.verb_form_map = verb_form_map
        self.categories = get_categories()
        self.settings = Settings.factory()
        self.logger = Logger.factory(self.settings)
        self.logger.debug("app started with settings: %s", self.settings)

        self.sentry_sdk = set_up_sentry_sdk(self.version, self.settings)

        self.supported_word_types = list(WordType._member_map_.values())

        self.term_replacement_langs = []
        for model_name in self.settings.models:
            lang = model_name[0:2]

            self.langs.append(lang)
            self.term_replacement_langs.append("|" + lang)

        self.static_rules = fetch_static_rules(self.langs)

        with open("./training_data/lemma_plural_lookup.json", "r") as fp:
            self.lemma_plural_lookup = json.load(fp)
            for lang in self.lemma_plural_lookup:
                self.lemma_plural_lookup[lang] = set(self.lemma_plural_lookup[lang])

        self.model = Model(
            self.settings, self.logger, self.static_rules, self.lemma_plural_lookup
        )

        self.languages = {}
        for locale in LangWithAutoType._member_map_.values():
            if locale == LangWithAutoType.AUTO:
                continue

            self.languages[locale] = Language(locale, translations)

        pretrained_lang_model = os.getcwd() + "/training_data/lid.176.bin"
        fasttext_model = fasttext.load_model(pretrained_lang_model)

        self.lang_detection = LangDetection(fasttext_model)
        self.redis = Redis.factory(self.settings)
